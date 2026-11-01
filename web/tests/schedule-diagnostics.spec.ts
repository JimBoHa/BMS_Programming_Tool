import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  scheduleTracePeer,
  openScheduleController,
} from "./schedule-trace-peer";

async function finishPeer(
  peer: Awaited<ReturnType<typeof scheduleTracePeer>>,
  primary: unknown,
) {
  let cleanup: unknown;
  try {
    const audit = await peer.stop();
    await test.info().attach("authored-schedule-peer-audit", {
      body: Buffer.from(JSON.stringify(audit)),
      contentType: "application/json",
    });
  } catch (failure) {
    cleanup = failure;
  }
  if (primary && cleanup)
    throw new AggregateError(
      [primary, cleanup],
      "Schedule case and cleanup both failed",
    );
  if (primary) throw primary;
  if (cleanup) throw cleanup;
}

test.afterEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBeTruthy();
});
async function includeTrace(panel: Locator) {
  await panel.getByText("Read diagnostics", { exact: true }).click();
  await panel
    .getByLabel("Include one-property Schedule trace", { exact: true })
    .check();
  await panel
    .getByLabel("Trace Calendar/Schedule object", { exact: true })
    .fill("schedule,1");
}
async function read(panel: Locator) {
  await panel
    .getByRole("button", { name: "Read native schedules", exact: true })
    .click();
  await expect(
    panel.getByLabel("Schedule evidence report", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Cancel schedule read", exact: true }),
  ).toBeDisabled();
}
async function download(page: Page, button: Locator) {
  const pending = page.waitForEvent("download");
  await button.click();
  return readFileSync((await (await pending).path())!);
}

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} focused property trace preserves actual core and original diagnostic download`, async ({
    page,
    request,
  }, info) => {
    const peer = await scheduleTracePeer(routed);
    let primary: unknown;
    try {
      const panel = await openScheduleController(page, request, peer, routed);
      await includeTrace(panel);
      const before = peer.reads();
      await read(panel);
      const trace = panel.getByRole("region", {
        name: "Schedule property diagnostic trace",
        exact: true,
      });
      await expect(trace).toContainText(
        "list-of-object-property-references · complete",
      );
      await expect(trace).toContainText("1 observed reads");
      expect(peer.reads() - before).toBe(28);
      const raw = await download(
        page,
        trace.getByRole("button", {
          name: "Download original Schedule diagnostic bundle",
          exact: true,
        }),
      );
      const envelope = JSON.parse(raw.toString()),
        core = Buffer.from(envelope.core_report_json, "utf8");
      expect(createHash("sha256").update(core).digest("hex")).toBe(
        envelope.core_report_sha256,
      );
      expect(core.toString()).toContain('"value":-0.0');
      expect(core.toString()).toContain('"value":2.0');
      const report = JSON.parse(core.toString());
      expect(report.complete).toBe(true);
      expect(report.target).toEqual({
        address: routed ? "3001:7" : peer.endpoint,
        device: "device,42",
        router: routed ? peer.endpoint : null,
        dnet: routed ? 3001 : null,
      });
      expect(envelope.trace_focus).toEqual({
        object_id: "schedule,1",
        property: "list-of-object-property-references",
        array_index: null,
      });
      expect(
        envelope.trace.events.filter(
          (row: any) => row.event === "read_started",
        ),
      ).toHaveLength(1);
      const exact = await download(
        page,
        panel.getByRole("button", {
          name: "Export exact schedule evidence",
          exact: true,
        }),
      );
      expect(exact.equals(core)).toBe(true);
      expect(peer.reads() - before).toBe(28);
      await panel
        .getByRole("button", {
          name: "Refresh retained schedule reports",
          exact: true,
        })
        .click();
      await panel
        .getByText("Retained reports and limits", { exact: true })
        .click();
      await panel
        .getByRole("button", {
          name: new RegExp(`^Open schedule report ${report.id.slice(0, 8)}`),
        })
        .click();
      await expect(trace).toHaveCount(0);
      expect(
        (
          await download(
            page,
            panel.getByRole("button", {
              name: "Export exact schedule evidence",
              exact: true,
            }),
          )
        ).equals(core),
      ).toBe(true);
      expect(peer.reads() - before).toBe(28);
      // The retained report cannot pretend its transient trace was persisted.
      await panel
        .getByLabel("Trace native property", { exact: true })
        .selectOption("exception-schedule");
      await panel
        .getByLabel("Schedule trace array index", { exact: true })
        .fill("2");
      await read(panel);
      await expect(trace).toContainText("exception-schedule [2] · complete");
      await expect(trace).toContainText("1 observed reads");
      await page.screenshot({
        path: info.outputPath("schedule-trace.png"),
        fullPage: true,
      });
      await panel
        .getByLabel("Trace native property", { exact: true })
        .selectOption("weekly-schedule");
      await expect(trace).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: "Export exact schedule evidence",
          exact: true,
        }),
      ).toBeDisabled();
    } catch (failure) {
      primary = failure;
    } finally {
      await finishPeer(peer, primary);
    }
  });

test("default-off inventory remains ordinary read and supports offline exact report reopen", async ({
  page,
  request,
}) => {
  const peer = await scheduleTracePeer();
  let primary: unknown;
  try {
    const panel = await openScheduleController(page, request, peer);
    const calls: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/bacnet/schedules/read"))
        calls.push(request.url().split("/").pop()!);
    });
    await read(panel);
    expect(calls).toEqual(["read"]);
    await expect(
      panel.getByRole("region", { name: "Schedule property diagnostic trace" }),
    ).toHaveCount(0);
    const raw = await download(
      page,
      panel.getByRole("button", {
        name: "Export exact schedule evidence",
        exact: true,
      }),
    );
    const id = JSON.parse(raw.toString()).id;
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(
      page.getByText("No BACnet interface open", { exact: true }),
    ).toBeVisible();
    const count = peer.reads();
    await panel
      .getByRole("button", {
        name: "Refresh retained schedule reports",
        exact: true,
      })
      .click();
    await panel
      .getByText("Retained reports and limits", { exact: true })
      .click();
    await panel
      .getByRole("button", {
        name: new RegExp(`^Open schedule report ${id.slice(0, 8)}`),
      })
      .click();
    expect(
      (
        await download(
          page,
          panel.getByRole("button", {
            name: "Export exact schedule evidence",
            exact: true,
          }),
        )
      ).equals(raw),
    ).toBe(true);
    expect(peer.reads()).toBe(count);
  } catch (failure) {
    primary = failure;
  } finally {
    await finishPeer(peer, primary);
  }
});

test("missing reference retains focused timeout and refuses native editing", async ({
  page,
  request,
}) => {
  const peer = await scheduleTracePeer(true, "dropped");
  let primary: unknown;
  try {
    const panel = await openScheduleController(page, request, peer, true);
    await includeTrace(panel);
    const before = peer.reads();
    await read(panel);
    const trace = panel.getByRole("region", {
      name: "Schedule property diagnostic trace",
      exact: true,
    });
    await expect(trace).toContainText("1 observed reads");
    const raw = await download(
      page,
      trace.getByRole("button", {
        name: "Download original Schedule diagnostic bundle",
        exact: true,
      }),
    );
    const envelope = JSON.parse(raw.toString()),
      report = JSON.parse(envelope.core_report_json);
    expect(report.complete).toBe(false);
    expect(
      report.objects[1].properties["list-of-object-property-references"].status,
    ).toBe("timeout");
    expect(
      envelope.trace.events.some(
        (row: any) => row.reason === "retained_matching_candidate",
      ),
    ).toBe(false);
    expect(
      envelope.trace.events.some(
        (row: any) => row.event === "native_apdu_handoff",
      ),
    ).toBe(true);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const saved = await request.post("/api/bacnet/schedules/library/save", {
      headers,
      data: { id: report.id },
    });
    expect(saved.ok()).toBe(true);
    expect((await saved.json()).objects[0].eligible).toBe(false);
    expect(peer.reads() - before).toBe(28);
  } catch (failure) {
    primary = failure;
  } finally {
    await finishPeer(peer, primary);
  }
});

test("cancelled property read exposes original partial evidence and no automatic replay", async ({
  page,
  request,
}) => {
  const peer = await scheduleTracePeer(false, "hold");
  let primary: unknown;
  try {
    const panel = await openScheduleController(page, request, peer);
    await includeTrace(panel);
    const before = peer.reads();
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    await expect.poll(peer.reads).toBe(before + 14);
    await panel
      .getByRole("button", { name: "Cancel schedule read", exact: true })
      .click();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toContainText("cancelled");
    const trace = panel.getByRole("region", {
      name: "Schedule property diagnostic trace",
      exact: true,
    });
    await expect(trace).toContainText("1 observed reads");
    const envelope = JSON.parse(
      (
        await download(
          page,
          trace.getByRole("button", {
            name: "Download original Schedule diagnostic bundle",
            exact: true,
          }),
        )
      ).toString(),
    );
    expect(
      envelope.trace.events.some((row: any) => row.event === "read_retired"),
    ).toBe(true);
    expect(JSON.parse(envelope.core_report_json).complete).toBe(false);
    expect(peer.reads()).toBe(before + 14);
  } catch (failure) {
    primary = failure;
  } finally {
    await finishPeer(peer, primary);
  }
});

for (const corruption of ["hash", "focus", "target", "operation"])
  test(`altered ${corruption} cannot authorize Schedule trace or downloads`, async ({
    page,
    request,
  }) => {
    const peer = await scheduleTracePeer();
    let primary: unknown;
    try {
      const panel = await openScheduleController(page, request, peer);
      await includeTrace(panel);
      await page.route(
        "**/api/bacnet/schedules/read-diagnostics",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            data = await response.json();
          if (corruption === "hash") data.core_report_sha256 = "0".repeat(64);
          else if (corruption === "focus")
            data.trace_focus.property = "present-value";
          else {
            const core = JSON.parse(data.core_report_json);
            if (corruption === "target")
              core.target.address = "127.0.0.2:47808";
            else core.operation_id = "some_other_operation";
            data.core_report_json = JSON.stringify(core);
            data.core_report_sha256 = createHash("sha256")
              .update(data.core_report_json)
              .digest("hex");
          }
          await route.fulfill({ response, json: data });
        },
      );
      const before = peer.reads();
      await panel
        .getByRole("button", { name: "Read native schedules", exact: true })
        .click();
      await expect(panel.getByRole("alert")).toContainText(
        ["target", "operation"].includes(corruption)
          ? "does not match"
          : "invalid",
      );
      await expect(
        panel.getByLabel("Schedule evidence report", { exact: true }),
      ).toHaveCount(0);
      await expect(
        panel.getByRole("region", {
          name: "Schedule property diagnostic trace",
        }),
      ).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: "Export exact schedule evidence",
          exact: true,
        }),
      ).toBeDisabled();
      expect(peer.reads() - before).toBe(28);
    } catch (failure) {
      primary = failure;
    } finally {
      await finishPeer(peer, primary);
    }
  });

test("late diagnostic response cannot return after a controller change and same-target reopen", async ({
  page,
  request,
}) => {
  const peer = await scheduleTracePeer();
  let primary: unknown;
  let release!: () => void, enter!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    entered = new Promise<void>((resolve) => {
      enter = resolve;
    });
  try {
    const panel = await openScheduleController(page, request, peer);
    await includeTrace(panel);
    await page.route(
      "**/api/bacnet/schedules/read-diagnostics",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        enter();
        await gate;
        await route.fulfill({ response });
      },
    );
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    await entered;
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Schedules", exact: true })
      .click();
    release();
    await expect(
      panel.getByRole("button", { name: "Read native schedules", exact: true }),
    ).toBeEnabled();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("region", { name: "Schedule property diagnostic trace" }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Export exact schedule evidence",
        exact: true,
      }),
    ).toBeDisabled();
  } catch (failure) {
    primary = failure;
  } finally {
    release();
    await finishPeer(peer, primary);
  }
});

for (const declared of [false, true])
  test(`plain Schedule fallback ${declared ? "with" : "without"} explicit unavailable header preserves its qualification`, async ({
    page,
    request,
  }) => {
    const peer = await scheduleTracePeer();
    let primary: unknown,
      original: Buffer | null = null;
    try {
      const panel = await openScheduleController(page, request, peer);
      await includeTrace(panel);
      await page.route(
        "**/api/bacnet/schedules/read-diagnostics",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            envelope = await response.json();
          original = Buffer.from(envelope.core_report_json, "utf8");
          const headers = {
            ...response.headers(),
            ...(declared ? { "x-studio-diagnostics": "unavailable" } : {}),
          };
          delete headers["content-length"];
          await route.fulfill({
            status: response.status(),
            headers,
            body: original,
          });
        },
      );
      const before = peer.reads();
      await panel
        .getByRole("button", { name: "Read native schedules", exact: true })
        .click();
      if (declared) {
        await expect(
          panel.getByLabel("Schedule evidence report", { exact: true }),
        ).toBeVisible();
        const trace = panel.getByRole("region", {
          name: "Schedule property diagnostic trace",
          exact: true,
        });
        await expect(trace).toContainText("unavailable");
        await expect(
          trace.getByRole("button", {
            name: "Download original Schedule diagnostic bundle",
            exact: true,
          }),
        ).toHaveCount(0);
        expect(
          (
            await download(
              page,
              panel.getByRole("button", {
                name: "Export exact schedule evidence",
                exact: true,
              }),
            )
          ).equals(original!),
        ).toBe(true);
      } else {
        await expect(panel.getByRole("alert")).toContainText(
          "lacks its explicit server state",
        );
        await expect(
          panel.getByLabel("Schedule evidence report", { exact: true }),
        ).toHaveCount(0);
        await expect(
          panel.getByRole("button", {
            name: "Export exact schedule evidence",
            exact: true,
          }),
        ).toBeDisabled();
      }
      expect(peer.reads() - before).toBe(28);
    } catch (failure) {
      primary = failure;
    } finally {
      await finishPeer(peer, primary);
    }
  });

for (const width of [1440, 820])
  test(`Schedule trace controls stay readable and keyboard reachable at ${width}px`, async ({
    page,
    request,
  }, info) => {
    const peer = await scheduleTracePeer();
    let primary: unknown;
    try {
      await page.setViewportSize({ width, height: 1000 });
      const panel = await openScheduleController(page, request, peer);
      await includeTrace(panel);
      const checkbox = panel.getByLabel("Include one-property Schedule trace", {
        exact: true,
      });
      await expect(checkbox.locator("..")).toHaveCSS("flex-direction", "row");
      await checkbox.uncheck();
      await checkbox.focus();
      await page.keyboard.press("Space");
      await expect(checkbox).toBeChecked();
      const select = panel.getByLabel("Trace native property", { exact: true });
      await expect(select).toHaveCSS("font-size", "14px");
      expect((await select.boundingBox())!.height).toBeGreaterThanOrEqual(36);
      expect(
        await select.evaluate((node) => {
          const field = node.getBoundingClientRect(),
            parent = node.parentElement!.getBoundingClientRect();
          return field.left >= parent.left && field.right <= parent.right + 1;
        }),
      ).toBe(true);
      const readButton = panel.getByRole("button", {
        name: "Read native schedules",
        exact: true,
      });
      await readButton.focus();
      await page.keyboard.press("Enter");
      const trace = panel.getByRole("region", {
        name: "Schedule property diagnostic trace",
        exact: true,
      });
      await expect(trace).toContainText("1 observed reads");
      await expect(trace).toHaveCSS("font-size", "14px");
      await trace.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`schedule-layout-${width}.png`),
      });
    } catch (failure) {
      primary = failure;
    } finally {
      await finishPeer(peer, primary);
    }
  });
