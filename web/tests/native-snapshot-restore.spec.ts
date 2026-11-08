import { readFile } from "node:fs/promises";
import { gunzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { expect } from "./nativeScheduleWriteFixture";
import {
  snapshotFixture,
  openSnapshot,
  reviewSnapshot,
  nativeBase,
  restoreBase,
} from "./native-snapshot-restore-browser-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";
import { connectionSeal } from "../src/nativeConnectionContract";
const restores = (events: any[]) =>
  events.filter((row) => row[0] === "state" && row[1] === "start-restore");
const verified = (panel: any) =>
  panel.getByRole("region", {
    name: "Recorded retained application restore",
    exact: true,
  });

snapshotFixture()(
  "selecting an original recorded restore retires the current Apply before loading its exact receipt",
  async ({ page, request, snapshot }) => {
    const { peer, seeded } = snapshot;
    const preview = await request.post(restoreBase + "/preview", {
      headers: seeded.headers,
      data: {
        ...seeded.target,
        restore_capture_id: seeded.original.id,
        restore_snapshot_sha256: seeded.original.snapshot_evidence_sha256,
        operation_id: "seed-recorded-restore-review",
      },
    });
    expect(preview.ok()).toBe(true);
    const plan = await preview.json();
    const applied = await request.post(restoreBase + "/apply", {
      headers: seeded.headers,
      data: {
        operation_id: "seed-recorded-restore-apply",
        token: plan.token,
        review_sha256: plan.review_sha256,
        historical_application_confirmed: true,
        application_transfer_confirmed: true,
      },
    });
    expect(applied.ok()).toBe(true);
    const receipt = await applied.json();
    expect(receipt.result.status).toBe("verified");
    await peer.command("snapshot-current");
    const { panel } = await openSnapshot(page, seeded),
      { apply } = await reviewSnapshot(page, panel);
    let dispatched = 0;
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        r.url().endsWith("/application-restore/apply")
      )
        dispatched++;
    });
    const old = await apply.elementHandle();
    await panel
      .getByRole("combobox", { name: /Recorded application restores/ })
      .evaluate(
        (select, args) => {
          (select as HTMLSelectElement).value = args.id;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          (args.old as HTMLButtonElement).click();
        },
        { id: receipt.intent.id, old },
      );
    await panel
      .getByRole("button", {
        name: "Load recorded application restore",
        exact: true,
      })
      .click();
    await expect(verified(panel)).toContainText(receipt.intent.id);
    await expect(
      panel.getByRole("region", {
        name: "Reviewed retained application restore",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(dispatched).toBe(0);
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  },
);

for (const caf of [false, true])
  snapshotFixture()(
    `${caf ? "CAF" : "graph"} controller route changes retire restore authority and preserve local drafts`,
    async ({ page, snapshot }) => {
      const { peer, seeded } = snapshot,
        { panel } = await openSnapshot(page, seeded, caf);
      const { apply } = await reviewSnapshot(page, panel);
      await apply.evaluate(
        (button) => ((window as any).__oldRouteRestore = button),
      );
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Known controller address", exact: true })
        .click();
      await page
        .getByLabel("Known controller address", { exact: true })
        .fill("3001:7");
      await page
        .getByLabel("Known Device object", { exact: true })
        .fill("device,5136");
      await page.getByLabel("Known router", { exact: true }).fill(peer.router);
      await page.getByLabel("Known network", { exact: true }).fill("3001");
      await page
        .getByRole("region", {
          name: "Known controller connection",
          exact: true,
        })
        .getByRole("button", { name: "Open controller", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      await page.evaluate(() =>
        ((window as any).__oldRouteRestore as HTMLButtonElement).click(),
      );
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTool(page, "Local graph editor");
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue("Preserved retained-restore local graph");
      if (caf)
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("retained-restore-local.caf");
      expect(restores((await peer.command("stats")).events)).toHaveLength(0);
      expect((await peer.command("stats")).router_errors).toEqual([]);
    },
  );
for (const routed of [false, true])
  for (const caf of [false, true])
    for (const width of [1440, 390])
      snapshotFixture(routed)(
        `${routed ? "routed" : "direct"} ${caf ? "CAF" : "graph"} retained application restores exact historical image at ${width}px`,
        async ({ page, request, snapshot }, info) => {
          await page.setViewportSize({ width, height: 1000 });
          const { peer, seeded } = snapshot;
          const opened = await openSnapshot(page, seeded, caf),
            { panel } = opened;
          const stats = await peer.command("stats");
          expect(stats.native_record_count).toBe(6);
          const download = page.waitForEvent("download");
          await panel
            .getByRole("button", {
              name: "Save saved-application copy",
              exact: true,
            })
            .click();
          const artifact = await download;
          expect(artifact.suggestedFilename()).toBe(
            "retained-saved-application.moz",
          );
          const bytes = await readFile((await artifact.path())!);
          expect(
            createHash("sha256").update(gunzipSync(bytes)).digest("hex"),
          ).toBe(stats.expected_native_sha256);
          expect(restores((await peer.command("stats")).events)).toHaveLength(
            0,
          );
          const { apply } = await reviewSnapshot(
            page,
            panel,
            caf && width === 390,
          );
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= window.innerWidth,
            ),
          ).toBe(true);
          await expect(
            panel.getByRole("table", {
              name: "Retained restore record changes",
              exact: true,
            }),
          ).toContainText("6");
          await expect(
            panel.getByRole("table", {
              name: "Retained restore record changes",
              exact: true,
            }),
          ).toContainText("3");
          if (!routed && !caf)
            await page.screenshot({
              path: info.outputPath(`retained-restore-review-${width}.png`),
              fullPage: true,
            });
          let actual: any, exact: Buffer | undefined;
          await page.route("**/application-restore/apply", async (route) => {
            const response = await route.fetch({ maxRetries: 0 });
            exact = await response.body();
            actual = JSON.parse(exact.toString());
            await route.fulfill({ response, body: exact });
          });
          const applied = page.waitForResponse(
            (r) =>
              r.url().endsWith("/application-restore/apply") &&
              r.request().method() === "POST",
          );
          await apply.click();
          await expectWorkspaceNavigationLocked(page);
          expect((await applied).ok()).toBe(true);
          expect(actual.result.status).toBe("verified");
          expect(actual.pending).toBe(false);
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= window.innerWidth,
            ),
          ).toBe(true);
          await expect(verified(panel)).toContainText(actual.intent.id);
          await expect(verified(panel)).toContainText(
            "Retained application and saved values verified",
          );
          const after = await peer.command("stats");
          expect(after.native_sha256).toBe(after.expected_native_sha256);
          expect(after.native_record_count).toBe(3);
          expect(restores(after.events)).toHaveLength(1);
          expect(after.router_errors).toEqual([]);
          const receiptDownload = page.waitForEvent("download");
          await verified(panel)
            .getByRole("button", {
              name: "Save exact retained-restore receipt",
              exact: true,
            })
            .click();
          expect(
            await readFile((await (await receiptDownload).path())!),
          ).toEqual(exact);
          const old = await request.post(nativeBase + "/inspection/source", {
            headers: seeded.headers,
            data: {
              capture_id: seeded.original.id,
              snapshot_sha256: seeded.original.snapshot_evidence_sha256,
            },
          });
          expect(old.ok()).toBe(true);
          expect((await old.json()).files).toEqual(seeded.original.files);
          await chooseWorkspaceTask(page, "Changes");
          const records = page.getByRole("region", {
            name: "Recorded changes",
            exact: true,
          });
          await expect(records).toContainText(
            "Retained native application restore",
          );
          await records
            .getByRole("button", {
              name: `Details for native ${actual.intent.id}`,
              exact: true,
            })
            .click();
          const provenance = page.getByRole("region", {
            name: "Recorded retained application restore provenance",
            exact: true,
          });
          await expect(provenance).toContainText(seeded.original.id);
          await expect(provenance).toContainText(actual.intent.backup_id);
          await page
            .getByRole("region", { name: "Change evidence", exact: true })
            .getByRole("button", {
              name: "Open native program tools",
              exact: true,
            })
            .click();
          await expect(
            page.getByRole("region", {
              name: "Native backup default compiler",
              exact: true,
            }),
          ).toBeVisible();
          await chooseWorkspaceTool(page, "Local graph editor");
          await expect(
            page.getByLabel("Program name", { exact: true }),
          ).toHaveValue("Preserved retained-restore local graph");
          if (caf)
            await expect(
              page.getByLabel("Current CAF archive", { exact: true }),
            ).toHaveText("retained-restore-local.caf");
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= window.innerWidth,
            ),
          ).toBe(true);
        },
      );

snapshotFixture(true)(
  "uncertain retained restore loads exact original receipt and resolves by readback without replay",
  async ({ page, snapshot }) => {
    const { peer, seeded } = snapshot,
      { panel } = await openSnapshot(page, seeded);
    const { apply } = await reviewSnapshot(page, panel);
    let actual: any;
    await page.route("**/application-restore/apply", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      const bytes = await response.body();
      actual = JSON.parse(bytes.toString());
      await route.fulfill({ response, body: bytes });
    });
    await peer.command("mode drop-end");
    const done = page.waitForResponse(
      (r) =>
        r.url().endsWith("/application-restore/apply") &&
        r.request().method() === "POST",
    );
    await apply.click();
    expect((await done).ok()).toBe(true);
    expect(actual.pending).toBe(true);
    await expect(verified(panel)).toContainText(actual.intent.id);
    await expect(verified(panel)).toContainText(
      "Restore outcome requires attention",
    );
    await peer.command("mode normal");
    await panel
      .getByRole("combobox", { name: /Recorded application restores/ })
      .selectOption(actual.intent.id);
    await panel
      .getByRole("button", {
        name: "Load recorded application restore",
        exact: true,
      })
      .click();
    await expect(verified(panel)).toContainText(actual.intent.id);
    await verified(panel)
      .getByRole("button", {
        name: "Read back original retained-application restore",
        exact: true,
      })
      .click();
    await expect(verified(panel)).toContainText(
      "Retained application and saved values verified",
    );
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  },
);

for (const caf of [false, true])
  snapshotFixture()(
    `${caf ? "CAF" : "graph"} source reconstruction stays offline and local download grants no controller review`,
    async ({ page, request, snapshot }) => {
      const { peer, seeded } = snapshot;
      expect(
        (
          await request.post("/api/bacnet/disconnect", {
            headers: seeded.headers,
            data: {},
          })
        ).ok(),
      ).toBe(true);
      const { panel } = await openSnapshot(page, seeded, caf, false);
      await expect(
        panel.getByRole("button", {
          name: "Review retained application restore",
          exact: true,
        }),
      ).toBeDisabled();
      const download = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Save saved-application copy",
          exact: true,
        })
        .click();
      expect((await download).suggestedFilename()).toBe(
        "retained-saved-application.moz",
      );
      expect(restores((await peer.command("stats")).events)).toHaveLength(0);
    },
  );

for (const fault of [
  "source-authority",
  "current-capture",
  "counter-guard",
  "interface",
])
  snapshotFixture()(
    `a resealed ${fault} restore response grants no browser Apply authority`,
    async ({ page, snapshot }) => {
      const { peer, seeded } = snapshot,
        { panel } = await openSnapshot(page, seeded);
      await page.route("**/application-restore/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          body = await response.json();
        if (fault === "source-authority") body.restore_source.can_apply = true;
        else if (fault === "current-capture")
          body.capture_id = seeded.original.id;
        else if (fault === "counter-guard")
          body.compilation.prewrite_guard.counter_count = true;
        else body.connector_config.local_address = "127.0.0.1:47899";
        body.restore_source.evidence_sha256 = await connectionSeal(
          Object.fromEntries(
            Object.entries(body.restore_source).filter(
              ([k]) => k !== "evidence_sha256",
            ),
          ),
        );
        body.compilation.restore_source_evidence_sha256 =
          body.restore_source.evidence_sha256;
        body.compilation.compilation_sha256 = await connectionSeal(
          Object.fromEntries(
            Object.entries(body.compilation).filter(
              ([k]) => k !== "compilation_sha256",
            ),
          ),
        );
        body.review_sha256 = await connectionSeal(
          Object.fromEntries(
            Object.entries(body).filter(
              ([k]) => !["token", "review_sha256"].includes(k),
            ),
          ),
        );
        await route.fulfill({ response, json: body });
      });
      await panel
        .getByRole("button", {
          name: "Review retained application restore",
          exact: true,
        })
        .click();
      await expect(
        panel.getByRole("region", {
          name: "Reviewed retained application restore",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(panel).toContainText("The restore review does not match");
      expect(restores((await peer.command("stats")).events)).toHaveLength(0);
    },
  );

snapshotFixture()(
  "a late retained restore preview cannot return after page retirement",
  async ({ page, snapshot }) => {
    const { peer, seeded } = snapshot,
      { panel } = await openSnapshot(page, seeded);
    let release = () => {},
      finish = () => {},
      arrived = false;
    const gate = new Promise<void>((resolve) => (release = resolve)),
      done = new Promise<void>((resolve) => (finish = resolve));
    try {
      await page.route("**/application-restore/preview", async (route) => {
        try {
          const response = await route.fetch({ maxRetries: 0 });
          arrived = true;
          await gate;
          await route.fulfill({ response });
        } finally {
          finish();
        }
      });
      await panel
        .getByRole("button", {
          name: "Review retained application restore",
          exact: true,
        })
        .click();
      await expect.poll(() => arrived).toBe(true);
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      release();
      await done;
      await expect(
        panel.getByRole("region", {
          name: "Reviewed retained application restore",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: "Review retained application restore",
          exact: true,
        }),
      ).toBeEnabled();
      expect(restores((await peer.command("stats")).events)).toHaveLength(0);
    } finally {
      release();
    }
  },
);

snapshotFixture(true)(
  "an active retained restore keeps its exact late receipt after page retirement",
  async ({ page, snapshot }) => {
    const { peer, seeded } = snapshot,
      { panel } = await openSnapshot(page, seeded, true);
    const { apply } = await reviewSnapshot(page, panel);
    let release = () => {},
      arrived = false,
      exact: Buffer | undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    try {
      await page.route("**/application-restore/apply", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        exact = await response.body();
        arrived = true;
        await gate;
        await route.fulfill({ response, body: exact });
      });
      const completed = page.waitForResponse(
        (r) =>
          r.url().endsWith("/application-restore/apply") &&
          r.request().method() === "POST",
      );
      await apply.click();
      // The ordinary preparation and native readback run; no test-owned delay replaces them.
      await expect.poll(() => arrived, { timeout: 15000 }).toBe(true);
      await expectWorkspaceNavigationLocked(page);
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      release();
      expect((await completed).ok()).toBe(true);
      const receipt = JSON.parse(exact!.toString());
      await expect(verified(panel)).toContainText(receipt.intent.id);
      await expect(verified(panel)).toContainText(
        "Retained application and saved values verified",
      );
      const download = page.waitForEvent("download");
      await verified(panel)
        .getByRole("button", {
          name: "Save exact retained-restore receipt",
          exact: true,
        })
        .click();
      expect(await readFile((await (await download).path())!)).toEqual(exact);
      expect(restores((await peer.command("stats")).events)).toHaveLength(1);
      await chooseWorkspaceTool(page, "Local graph editor");
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue("Preserved retained-restore local graph");
    } finally {
      release();
    }
  },
);

snapshotFixture()(
  "unknown retained restore service profiles keep source inspection offline",
  async ({ page, snapshot }) => {
    const { peer, seeded } = snapshot;
    await page.route("**/native-application/status", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        body = await response.json();
      body.retained_application_restore_profile += "future";
      await route.fulfill({ response, json: body });
    });
    const { panel } = await openSnapshot(page, seeded);
    await expect(
      panel.getByRole("button", {
        name: "Review retained application restore",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("button", {
        name: "Save saved-application copy",
        exact: true,
      }),
    ).toBeEnabled();
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  },
);

snapshotFixture()(
  "a changed current saved setting refuses restore before any native mutation",
  async ({ page, snapshot }) => {
    const { peer, seeded } = snapshot,
      { panel } = await openSnapshot(page, seeded);
    const { apply } = await reviewSnapshot(page, panel);
    await peer.command("snapshot-setting-changed");
    await apply.click();
    await expect(verified(panel)).toContainText("Restore not sent");
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  },
);

for (const boundary of ["summary", "pagehide", "visibility", "task", "source"])
  snapshotFixture()(
    `retained restore ${boundary} retires the cached Apply callback in the same turn`,
    async ({ page, snapshot }) => {
      const { peer, seeded } = snapshot,
        { panel } = await openSnapshot(page, seeded);
      const { apply } = await reviewSnapshot(page, panel),
        posts: string[] = [];
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          /\/application-restore\/(preview|apply)$/.test(
            new URL(r.url()).pathname,
          )
        )
          posts.push(r.url());
      });
      await apply.evaluate((element, kind) => {
        (window as any).__retiredRestoreApply = element;
        if (kind === "summary")
          element
            .closest("details")!
            .querySelector(":scope > summary")!
            .dispatchEvent(new MouseEvent("click", { bubbles: true }));
        else if (kind === "pagehide")
          window.dispatchEvent(new Event("pagehide"));
        else if (kind === "visibility") {
          Object.defineProperty(document, "visibilityState", {
            configurable: true,
            value: "hidden",
          });
          document.dispatchEvent(new Event("visibilitychange"));
        } else if (kind === "source") {
          const select = document.querySelector(
            'select[aria-label="Retained native backup"]',
          ) as HTMLSelectElement;
          if (!select)
            throw new Error("The retained source selector is missing.");
          select.value = "";
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        if (kind !== "task") (element as HTMLButtonElement).click();
      }, boundary);
      if (boundary === "task") {
        await chooseWorkspaceTask(page, "Overview");
        await page.evaluate(() =>
          ((window as any).__retiredRestoreApply as HTMLButtonElement).click(),
        );
      }
      if (boundary === "visibility")
        await page.evaluate(() => {
          Object.defineProperty(document, "visibilityState", {
            configurable: true,
            value: "visible",
          });
          document.dispatchEvent(new Event("visibilitychange"));
        });
      await page.waitForLoadState("networkidle");
      expect(posts).toEqual([]);
      expect(restores((await peer.command("stats")).events)).toHaveLength(0);
    },
  );
