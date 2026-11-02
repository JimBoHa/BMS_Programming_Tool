import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { calendarControllerPeer } from "./calendar-controller-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { readFileSync } from "node:fs";

const base = "/api/bacnet/calendars/writes";
async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
test.afterEach(async ({ request }) => {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await auth(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
});
async function select(page: Page, target: any, initial = true) {
  if (initial) {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  } else
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [name, value] of [
    ["Known controller address", target.address],
    ["Known Device object", target.device],
    ["Known router", target.router || ""],
    ["Known network", target.dnet == null ? "" : String(target.dnet)],
  ])
    await page.getByLabel(name, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Native " + target.device);
  await chooseWorkspaceTask(page, "Schedules");
}
async function setup(page: Page, request: APIRequestContext, routed = false) {
  const peer = await calendarControllerPeer(routed),
    headers = await auth(request);
  try {
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers,
          data: { local_address: peer.local },
        })
      ).ok(),
    ).toBe(true);
    const response = await request.post("/api/bacnet/schedules/read", {
      headers,
      data: {
        ...peer.target,
        object_ids: ["calendar,1"],
        operation_id:
          "calendar_capture_" + crypto.randomUUID().replaceAll("-", ""),
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    const report = await response.json();
    expect(report.complete).toBe(true);
    const saved = await request.post("/api/bacnet/schedules/library/save", {
      headers,
      data: { id: report.id },
    });
    expect(saved.ok()).toBe(true);
    const capture = await saved.json();
    await select(page, peer.target);
    const library = page.getByRole("region", {
      name: "Native Schedule capture library",
      exact: true,
    });
    await library
      .getByRole("button", {
        name: "Open capture " + capture.id.slice(0, 12),
        exact: true,
      })
      .click();
    await library
      .getByLabel("Captured Calendar dates", { exact: true })
      .getByText("Calendar dates", { exact: true })
      .click();
    const editor = page.getByRole("region", {
      name: "Captured Calendar date editor",
      exact: true,
    });
    await expect(
      editor.getByLabel("Captured Calendar for date draft", { exact: true }),
    ).toHaveValue("calendar,1");
    while (
      await editor
        .getByRole("button", { name: /^Remove Calendar entry/ })
        .count()
    )
      await editor
        .getByRole("button", { name: /^Remove Calendar entry/ })
        .first()
        .click();
    await editor
      .getByRole("button", { name: "Add Calendar entry", exact: true })
      .click();
    await editor
      .getByLabel("Calendar entry 1 year", { exact: true })
      .fill("2026");
    await editor
      .getByLabel("Calendar entry 1 month", { exact: true })
      .selectOption("11");
    await editor
      .getByLabel("Calendar entry 1 day", { exact: true })
      .selectOption("2");
    await editor
      .getByLabel("Calendar entry 1 weekday", { exact: true })
      .selectOption("*");
    await editor
      .getByRole("button", { name: "Review Calendar dates", exact: true })
      .click();
    await expect(
      editor.getByLabel("Calendar date draft review", { exact: true }),
    ).toBeVisible();
    const panel = editor.getByRole("region", {
      name: "Calendar controller deployment",
      exact: true,
    });
    await panel
      .getByRole("button", {
        name: "Open Calendar deployment and receipts",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("table", {
        name: "Calendar transfer journal",
        exact: true,
      }),
    ).toBeVisible();
    await panel
      .getByLabel("Declared Calendar operator", { exact: true })
      .fill("Authored operator");
    await panel
      .getByLabel("Calendar change rationale", { exact: true })
      .fill("Authored Calendar replacement");
    return { peer, capture, editor, panel, headers };
  } catch (e) {
    await peer.close();
    throw e;
  }
}
async function preview(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", {
      name: "Review Calendar controller change",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
  ).toBeEnabled();
}
for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} Calendar replacement sends exact dates once and keeps immutable receipts`, async ({
    page,
    request,
  }, info) => {
    const { peer, panel, editor, capture } = await setup(page, request, routed);
    try {
      await preview(panel);
      await panel
        .getByRole("button", { name: "Apply Calendar dates", exact: true })
        .click();
      const receipt = panel.getByRole("region", {
        name: "Calendar transfer receipt",
        exact: true,
      });
      await expect(receipt).toContainText(
        "Reviewed dates and other static Calendar fields matched at readback",
      );
      const id = (await receipt.textContent())!.match(
        /Receipt ([a-f0-9]{32})/,
      )![1];
      const original = await (
        await request.get(base + "/receipts/" + id)
      ).body();
      expect((await peer.stats()).values).toEqual(["0c7e0b02ff"]);
      await receipt
        .getByRole("button", {
          name: "Read back Calendar receipt",
          exact: true,
        })
        .click();
      await expect(
        panel.getByRole("region", {
          name: "Calendar receipt readback",
          exact: true,
        }),
      ).toContainText("Writes sent: 0.");
      const download = page.waitForEvent("download");
      await receipt
        .getByRole("button", { name: "Save Calendar receipt", exact: true })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(original);
      expect(
        await (await request.get(base + "/receipts/" + id)).body(),
      ).toEqual(original);
      expect((await peer.stats()).writes).toBe(1);
      await page.setViewportSize({ width: routed ? 390 : 1440, height: 1000 });
      await panel.scrollIntoViewIfNeeded();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("calendar-deployment.png"),
        fullPage: true,
      });
      // Local source and unfinished text remain useful after a completed field action.
      await editor
        .getByLabel("Calendar entry 1 year", { exact: true })
        .fill("20");
      await chooseWorkspaceTask(page, "Overview");
      await chooseWorkspaceTask(page, "Schedules");
      await page
        .getByRole("region", {
          name: "Native Schedule capture library",
          exact: true,
        })
        .getByRole("button", {
          name: "Open capture " + capture.id.slice(0, 12),
          exact: true,
        })
        .click();
      await expect(
        editor.getByLabel("Calendar entry 1 year", { exact: true }),
      ).toHaveValue("20");
      await expect(
        editor.getByRole("button", {
          name: "Apply Calendar dates",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      await peer.close();
    }
  });

for (const mode of ["drop", "error", "reject"])
  test(`Calendar ${mode} keeps protocol outcome separate from observed dates without retry`, async ({
    page,
    request,
  }) => {
    const { peer, panel } = await setup(page, request);
    try {
      await preview(panel);
      await peer.mode(mode);
      await panel
        .getByRole("button", { name: "Apply Calendar dates", exact: true })
        .click();
      const receipt = panel.getByRole("region", {
        name: "Calendar transfer receipt",
        exact: true,
      });
      await expect(receipt).toBeVisible();
      await expect(receipt.locator("dd")).toHaveText([
        "One dispatch admitted",
        mode === "drop" ? "Unknown" : "Rejected",
        mode === "reject" ? "mismatch" : "match",
      ]);
      const id = (await receipt.textContent())!.match(
        /Receipt ([a-f0-9]{32})/,
      )![1];
      const original = await (
        await request.get(base + "/receipts/" + id)
      ).body();
      const data = JSON.parse(original.toString());
      expect(data.protocol_accepted).toBe(mode === "drop" ? null : false);
      await receipt
        .getByRole("button", {
          name: "Read back Calendar receipt",
          exact: true,
        })
        .click();
      await expect(
        panel.getByRole("region", {
          name: "Calendar receipt readback",
          exact: true,
        }),
      ).toContainText("Writes sent: 0.");
      expect((await peer.stats()).writes).toBe(1);
      expect(
        await (await request.get(base + "/receipts/" + id)).body(),
      ).toEqual(original);
    } finally {
      await peer.close();
    }
  });

for (const changed of ["operation", "rules", "target", "request"])
  test(`a substituted Calendar preview ${changed} cannot authorize Apply`, async ({
    page,
    request,
  }) => {
    const { peer, panel } = await setup(page, request);
    try {
      await page.route("**/calendars/writes/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        expect(data.can_apply).toBe(true);
        if (changed === "operation")
          data.operation_id = "another_calendar_preview";
        if (changed === "rules") data.rules_sha256 = "0".repeat(64);
        if (changed === "target") data.target.address = "127.0.0.1:1";
        if (changed === "request")
          data.request_service_body_hex = data.request_service_body_hex.replace(
            "7e0b02ff",
            "7e0b03ff",
          );
        await route.fulfill({ response, json: data });
      });
      await panel
        .getByRole("button", {
          name: "Review Calendar controller change",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText("Calendar review");
      await expect(
        panel.getByRole("button", {
          name: "Apply Calendar dates",
          exact: true,
        }),
      ).toHaveCount(0);
      expect((await peer.stats()).writes).toBe(0);
    } finally {
      await peer.close();
    }
  });

test("a substituted Calendar Apply operation keeps local dates and the real journal receipt", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  try {
    let original: any;
    await page.route("**/calendars/writes/apply", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      original = await response.json();
      expect(original.readback.status).toBe("match");
      await route.fulfill({
        response,
        json: { ...original, operation_id: "another_calendar_apply" },
      });
    });
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Calendar dates", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "Apply outcome is unconfirmed",
    );
    await expect(
      panel.getByRole("region", {
        name: "Calendar transfer receipt",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      editor.getByLabel("Calendar entry 1 year", { exact: true }),
    ).toHaveValue("2026");
    await panel
      .getByRole("button", {
        name: "Open Calendar receipt " + original.id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Calendar transfer receipt",
        exact: true,
      }),
    ).toContainText("matched at readback");
    expect((await peer.stats()).writes).toBe(1);
  } finally {
    await peer.close();
  }
});

test("Calendar target changes preserve the local draft while blocking foreign deployment and receipt readback", async ({
  page,
  request,
}) => {
  const { peer, panel, editor, capture } = await setup(page, request),
    other = await calendarControllerPeer();
  try {
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Calendar dates", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "Calendar transfer receipt",
      exact: true,
    });
    await expect(receipt).toContainText("matched at readback");
    const id = (await receipt.textContent())!.match(
      /Receipt ([a-f0-9]{32})/,
    )![1];
    await select(page, other.target, false);
    await page
      .getByRole("region", {
        name: "Native Schedule capture library",
        exact: true,
      })
      .getByRole("button", {
        name: "Open capture " + capture.id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      editor.getByLabel("Calendar entry 1 year", { exact: true }),
    ).toHaveValue("2026");
    await editor
      .getByRole("button", { name: "Review Calendar dates", exact: true })
      .click();
    await panel
      .getByRole("button", {
        name: "Open Calendar deployment and receipts",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("table", {
        name: "Calendar transfer journal",
        exact: true,
      }),
    ).toBeVisible();
    await panel
      .getByLabel("Declared Calendar operator", { exact: true })
      .fill("Authored operator");
    await panel
      .getByLabel("Calendar change rationale", { exact: true })
      .fill("Foreign source qualification");
    await expect(
      panel.getByRole("button", {
        name: "Review Calendar controller change",
        exact: true,
      }),
    ).toBeDisabled();
    await panel
      .getByRole("button", {
        name: "Open Calendar receipt " + id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("button", {
        name: "Read back Calendar receipt",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("button", { name: "Save Calendar receipt", exact: true }),
    ).toBeEnabled();
    expect((await peer.stats()).writes).toBe(1);
    expect((await other.stats()).writes).toBe(0);
  } finally {
    await peer.close();
    await other.close();
  }
});

test("a held Calendar preview cannot revive after local date A to B to A", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  let release = () => {};
  try {
    let arrived!: () => void, finished!: () => void;
    const held = new Promise<void>((resolve) => {
        arrived = resolve;
      }),
      gate = new Promise<void>((resolve) => {
        release = resolve;
      }),
      delivered = new Promise<void>((resolve) => {
        finished = resolve;
      });
    await page.route(
      "**/calendars/writes/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        expect((await response.json()).can_apply).toBe(true);
        arrived();
        await gate;
        await route.fulfill({ response });
        finished();
      },
      { times: 1 },
    );
    await panel
      .getByRole("button", {
        name: "Review Calendar controller change",
        exact: true,
      })
      .click();
    await held;
    for (const year of ["2027", "2026"]) {
      await editor
        .getByLabel("Calendar entry 1 year", { exact: true })
        .fill(year);
      await editor
        .getByRole("button", { name: "Review Calendar dates", exact: true })
        .click();
      await expect(
        editor.getByLabel("Calendar date draft review", { exact: true }),
      ).toBeVisible();
    }
    release();
    await delivered;
    await expect(
      panel.getByRole("button", {
        name: "Review Calendar controller change",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
    ).toHaveCount(0);
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    release();
    await peer.close();
  }
});

test("Calendar visibility retirement keeps local date text and requires a new field review", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  try {
    await preview(panel);
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await expect(
      panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
    ).toHaveCount(0);
    await editor
      .getByRole("button", { name: "Refresh captured Calendars", exact: true })
      .click();
    await expect(
      editor.getByLabel("Calendar entry 1 year", { exact: true }),
    ).toHaveValue("2026");
    await expect(
      panel.getByRole("button", {
        name: "Review Calendar controller change",
        exact: true,
      }),
    ).toBeDisabled();
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    await peer.close();
  }
});

test("Calendar review expiry stays retired after a client clock rewind", async ({
  page,
  request,
}) => {
  const initial = Date.now();
  await page.clock.install({ time: initial });
  const { peer, panel } = await setup(page, request);
  try {
    await preview(panel);
    await page.clock.runFor(60000);
    await expect(
      panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
    ).toBeDisabled();
    await page.clock.setSystemTime(initial);
    await expect(
      panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
    ).toBeDisabled();
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    await peer.close();
  }
});

test("an interrupted Calendar intent remains unknown and supports separate explicit readback", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const { peer, panel } = await setup(page, request);
  try {
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Calendar dates", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "Calendar transfer receipt",
      exact: true,
    });
    await expect(receipt).toContainText("matched at readback");
    const id = (await receipt.textContent())!.match(
      /Receipt ([a-f0-9]{32})/,
    )![1];
    const { execFileSync } = await import("node:child_process"),
      { default: path } = await import("node:path");
    execFileSync(path.join(path.resolve(".."), ".venv/bin/python"), [
      "-c",
      "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]+'/studio.sqlite3'); db.execute('UPDATE native_calendar_writes SET result=NULL WHERE id=?',(sys.argv[2],)); db.commit(); db.close()",
      nativeScheduleWriteServer.directory,
      id,
    ]);
    await panel
      .getByRole("button", { name: "Refresh Calendar receipts", exact: true })
      .click();
    await panel
      .getByRole("button", {
        name: "Open Calendar receipt " + id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(receipt).toContainText("Unresolved durable Calendar intent");
    await expect(receipt.locator("dd")).toHaveText([
      "Unknown after interrupted intent",
      "Unknown",
      "unknown",
    ]);
    const original = await (await request.get(base + "/receipts/" + id)).body();
    await receipt
      .getByRole("button", { name: "Read back Calendar receipt", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Calendar receipt readback",
        exact: true,
      }),
    ).toContainText("Writes sent: 0.");
    expect(await (await request.get(base + "/receipts/" + id)).body()).toEqual(
      original,
    );
    expect((await peer.stats()).writes).toBe(1);
  } finally {
    await peer.close();
  }
});

for (const revision of [18, 17])
  test(`mixed Calendar choices require actual protocol revision ${revision}`, async ({
    page,
    request,
  }) => {
    const { peer, panel, editor } = await setup(page, request);
    try {
      await editor
        .getByRole("button", { name: "Add Calendar entry", exact: true })
        .click();
      await editor
        .getByLabel("Calendar entry 2 type", { exact: true })
        .selectOption("dateRange");
      for (const [side, day] of [
        ["start", "2"],
        ["end", "4"],
      ]) {
        await editor
          .getByLabel(`Calendar entry 2 ${side} year`, { exact: true })
          .fill("2026");
        for (const [part, value] of [
          ["month", "11"],
          ["day", day],
          ["weekday", side === "start" ? "1" : "3"],
        ])
          await editor
            .getByLabel(`Calendar entry 2 ${side} ${part}`, { exact: true })
            .selectOption(value);
      }
      await editor
        .getByRole("button", { name: "Add Calendar entry", exact: true })
        .click();
      await editor
        .getByLabel("Calendar entry 3 type", { exact: true })
        .selectOption("weekNDay");
      for (const [part, value] of [
        ["month", "*"],
        ["week", "7"],
        ["weekday", "1"],
      ])
        await editor
          .getByLabel(`Calendar entry 3 ${part}`, { exact: true })
          .selectOption(value);
      await editor
        .getByRole("button", { name: "Review Calendar dates", exact: true })
        .click();
      await expect(
        editor.getByLabel("Calendar date draft review", { exact: true }),
      ).toBeVisible();
      await peer.revision(revision);
      await panel
        .getByRole("button", {
          name: "Review Calendar controller change",
          exact: true,
        })
        .click();
      if (revision === 17) {
        await expect(panel).toContainText(
          "requires verified protocol revision 18 or later",
        );
        await expect(
          panel.getByRole("button", {
            name: "Apply Calendar dates",
            exact: true,
          }),
        ).toHaveCount(0);
        expect((await peer.stats()).writes).toBe(0);
      } else {
        await panel
          .getByRole("button", { name: "Apply Calendar dates", exact: true })
          .click();
        await expect(
          panel.getByRole("region", {
            name: "Calendar transfer receipt",
            exact: true,
          }),
        ).toContainText("matched at readback");
        expect((await peer.stats()).values).toEqual([
          "0c7e0b02ff1ea47e0b0201a47e0b04031f2bff0701",
        ]);
      }
    } finally {
      await peer.close();
    }
  });

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} Calendar range refusal preserves local work, then a corrected range deploys once`, async ({
    page,
    request,
  }, info) => {
    const { peer, panel, editor } = await setup(page, request, routed);
    try {
      await editor
        .getByLabel("Calendar entry 1 type", { exact: true })
        .selectOption("dateRange");
      for (const [side, year, month, day, weekday] of [
        ["start", "*", "1", "1", "*"],
        ["end", "2026", "11", "4", "3"],
      ]) {
        await editor
          .getByLabel(`Calendar entry 1 ${side} year`, { exact: true })
          .fill(year);
        for (const [part, value] of [
          ["month", month],
          ["day", day],
          ["weekday", weekday],
        ])
          await editor
            .getByLabel(`Calendar entry 1 ${side} ${part}`, { exact: true })
            .selectOption(value);
      }
      await expect(editor).toContainText(
        "fully specify each endpoint and its matching weekday",
      );
      await editor
        .getByRole("button", { name: "Review Calendar dates", exact: true })
        .click();
      await expect(
        editor.getByLabel("Calendar date draft review", { exact: true }),
      ).toBeVisible();
      const saving = page.waitForEvent("download");
      await editor
        .getByRole("button", {
          name: "Export reviewed Calendar draft",
          exact: true,
        })
        .click();
      const saved = JSON.parse(
        readFileSync((await (await saving).path())!).toString(),
      );
      expect(saved.request.entries).toEqual([
        { kind: "dateRange", start: [255, 1, 1, 255], end: [126, 11, 4, 3] },
      ]);
      const before = await peer.stats(),
        journal = (await (await request.get(base + "/profile")).json()).journal;
      const rejected = page.waitForResponse((r) =>
        r.url().endsWith(base + "/preview"),
      );
      await panel
        .getByRole("button", {
          name: "Review Calendar controller change",
          exact: true,
        })
        .click();
      expect((await rejected).status()).toBe(422);
      await expect(panel).toContainText(
        "entry 1 start requires a fully specified date",
      );
      await expect(
        panel.getByRole("button", {
          name: "Apply Calendar dates",
          exact: true,
        }),
      ).toHaveCount(0);
      const refused = await peer.stats();
      expect(refused.reads).toBe(before.reads);
      expect(refused.writes).toBe(0);
      expect(
        (await (await request.get(base + "/profile")).json()).journal,
      ).toEqual(journal);
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Schedules");
      await expect(
        editor.getByLabel("Calendar entry 1 start year", { exact: true }),
      ).toHaveValue("*");
      await editor
        .getByLabel("Calendar entry 1 start year", { exact: true })
        .fill("2026");
      for (const [part, value] of [
        ["month", "11"],
        ["day", "2"],
        ["weekday", "1"],
      ])
        await editor
          .getByLabel(`Calendar entry 1 start ${part}`, { exact: true })
          .selectOption(value);
      await editor
        .getByRole("button", { name: "Review Calendar dates", exact: true })
        .click();
      await expect(
        editor.getByLabel("Calendar date draft review", { exact: true }),
      ).toBeVisible();
      await panel
        .getByRole("button", {
          name: "Open Calendar deployment and receipts",
          exact: true,
        })
        .click();
      await panel
        .getByLabel("Declared Calendar operator", { exact: true })
        .fill("Authored operator");
      await panel
        .getByLabel("Calendar change rationale", { exact: true })
        .fill("Corrected range qualification");
      await preview(panel);
      await panel
        .getByRole("button", { name: "Apply Calendar dates", exact: true })
        .click();
      await expect(
        panel.getByRole("region", {
          name: "Calendar transfer receipt",
          exact: true,
        }),
      ).toContainText("matched at readback");
      expect((await peer.stats()).values).toEqual(["1ea47e0b0201a47e0b04031f"]);
      await page.setViewportSize({ width: 390, height: 1100 });
      const caption = editor
        .locator("caption")
        .filter({ hasText: "Local Calendar entries" });
      await caption.scrollIntoViewIfNeeded();
      const captionBox = await caption.boundingBox();
      expect(captionBox!.width).toBeGreaterThan(200);
      expect(captionBox!.height).toBeLessThan(60);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("qualified-calendar-range-phone.png"),
        fullPage: true,
      });
    } finally {
      await peer.close();
    }
  });

test("a Calendar native no-op grants no Apply authority", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  try {
    await editor
      .getByRole("button", { name: "Discard Calendar edits", exact: true })
      .click();
    await editor
      .getByRole("button", { name: "Review Calendar dates", exact: true })
      .click();
    await expect(
      editor.getByLabel("Calendar date draft review", { exact: true }),
    ).toContainText("Exact native Calendar no-op");
    await panel
      .getByRole("button", {
        name: "Review Calendar controller change",
        exact: true,
      })
      .click();
    await expect(panel).toContainText("No Apply authority: no_change");
    await expect(
      panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
    ).toHaveCount(0);
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    await peer.close();
  }
});

test("an owned Calendar cancellation prevents a held undispatched Apply without replay", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  let release = () => {};
  try {
    await preview(panel);
    let arrived!: () => void,
      delivered!: () => void,
      operation = "";
    const held = new Promise<void>((resolve) => {
        arrived = resolve;
      }),
      gate = new Promise<void>((resolve) => {
        release = resolve;
      }),
      finished = new Promise<void>((resolve) => {
        delivered = resolve;
      });
    await page.route(
      "**/calendars/writes/apply",
      async (route) => {
        operation = route.request().postDataJSON().operation_id;
        arrived();
        await gate;
        await route.continue();
        delivered();
      },
      { times: 1 },
    );
    const applied = page.waitForResponse((r) =>
      r.url().endsWith("/calendars/writes/apply"),
    );
    await panel
      .getByRole("button", { name: "Apply Calendar dates", exact: true })
      .click();
    await held;
    const cancelled = page.waitForResponse(
      (r) =>
        r.url().endsWith("/calendars/writes/cancel") &&
        r.request().postDataJSON().operation_id === operation,
    );
    await panel
      .getByRole("button", {
        name: "Cancel active Calendar operation",
        exact: true,
      })
      .click();
    expect((await (await cancelled).json()).operation_id).toBe(operation);
    release();
    await finished;
    await applied;
    await expect(
      panel.getByRole("button", {
        name: "Review Calendar controller change",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      panel.getByRole("button", { name: "Apply Calendar dates", exact: true }),
    ).toHaveCount(0);
    await expect(
      editor.getByLabel("Calendar entry 1 year", { exact: true }),
    ).toHaveValue("2026");
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    release();
    await peer.close();
  }
});
