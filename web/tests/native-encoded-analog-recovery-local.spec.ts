import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  offline,
  prepare,
} from "./native-encoded-analog-recovery-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const caf of [false, true])
  for (const width of [1440, 390])
    test(`${caf ? "CAF" : "graph"} ${width}px previous analog terminal stages explicitly and preserves ordinary drafts`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, testInfo) => {
      const f = seed(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      let original = Buffer.alloc(0);
      await page.route(
        "**/input/encoded-terminal/recovery/prepare",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          original = await response.body();
          await route.fulfill({ response });
        },
      );
      await page.setViewportSize({ width, height: 1000 });
      const { inputs, analog } = await offline(page, f, caf),
        recovery = await prepare(analog, f.parent.id);
      await expect(
        recovery.getByRole("button", {
          name: "Stage previous analog terminal",
          exact: true,
        }),
      ).toBeVisible();
      const saved = page.waitForEvent("download");
      await recovery
        .getByRole("button", {
          name: "Save previous analog recovery evidence",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await saved).path())!)).toEqual(original);
      await recovery
        .getByRole("button", {
          name: "Stage previous analog terminal",
          exact: true,
        })
        .click();
      await expect(
        analog.getByLabel("Analog terminal destination", { exact: true }),
      ).toHaveValue("1");
      await expect(
        analog.getByRole("region", {
          name: "Staged previous analog terminal",
          exact: true,
        }),
      ).toContainText(f.parent.id);
      await analog.screenshot({
        path: testInfo.outputPath("staged-analog-recovery.png"),
      });
      await analog
        .getByRole("button", {
          name: "Review local analog terminal copy",
          exact: true,
        })
        .click();
      const review = analog.getByRole("region", {
        name: "Analog terminal review",
        exact: true,
      });
      await expect(review).toBeVisible();
      const copy = page.waitForEvent("download");
      await review
        .getByRole("button", {
          name: "Save native analog terminal copy",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await copy).path())!)).toEqual(
        Buffer.from(f.output, "base64"),
      );
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Points & I/O");
      if (
        (await analog
          .getByLabel("Configured analog input", { exact: true })
          .count()) === 0
      )
        await analog.locator(":scope > summary").click();
      await expect(
        analog.getByLabel("Analog terminal destination", { exact: true }),
      ).toHaveValue("1");
      await analog
        .getByRole("button", {
          name: "Restore ordinary analog draft",
          exact: true,
        })
        .click();
      await expect(
        analog.getByLabel("Analog terminal destination", { exact: true }),
      ).toHaveValue("2");
      await analog.locator(":scope > summary").click();
      await expect(
        inputs.getByLabel("Engineering range high", { exact: true }),
      ).toHaveValue("9.");
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      expect(
        calls.every((p) =>
          [
            "/input/source",
            "/input/encoded-terminal/source",
            "/input/encoded-terminal/recovery/prepare",
            "/input/copy/preview",
            "/input/copy/export",
          ].some((s) => p.endsWith(s)),
        ),
      ).toBe(true);
    });

for (const caf of [false, true])
  test(`${caf ? "CAF" : "graph"} discard clears staged recovery and cannot resurrect its saved ordinary draft`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { analog, inputs } = await offline(page, f, caf),
      recovery = await prepare(analog, f.parent.id);
    await recovery
      .getByRole("button", {
        name: "Stage previous analog terminal",
        exact: true,
      })
      .click();
    await expect(
      analog.getByRole("button", {
        name: "Restore ordinary analog draft",
        exact: true,
      }),
    ).toBeVisible();
    await analog
      .getByRole("button", { name: "Discard local analog draft", exact: true })
      .click();
    for (const navigate of [false, true]) {
      if (navigate) {
        await chooseWorkspaceTask(page, "Program");
        await chooseWorkspaceTask(page, "Points & I/O");
        if ((await analog.getAttribute("open")) === null)
          await analog.locator(":scope > summary").click();
      }
      await expect(
        analog.getByRole("button", {
          name: "Restore ordinary analog draft",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        analog.getByRole("region", {
          name: "Staged previous analog terminal",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        analog.getByLabel("Configured analog input", { exact: true }),
      ).toHaveValue("");
      await expect(
        analog.getByLabel("Analog terminal destination", { exact: true }),
      ).toHaveValue("");
      await expect(
        analog.getByLabel("Previous configured analog transfer receipt", {
          exact: true,
        }),
      ).toHaveValue("");
    }
    await analog.locator(":scope > summary").click();
    await expect(
      inputs.getByLabel("Engineering range high", { exact: true }),
    ).toHaveValue("9.");
  });

for (const fault of ["source", "lineage", "payload"] as const)
  test(`damaged prepared analog ${fault} cannot stage`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory);
    await page.route(
      "**/input/encoded-terminal/recovery/prepare",
      async (route) => {
        const response = await route.fetch(),
          v = await response.json();
        if (fault === "source") v.source.capture_id = "0".repeat(32);
        if (fault === "lineage") v.origin.parent_receipt_id = "0".repeat(32);
        if (fault === "payload")
          v.inverse_compilation.terminal_compilation.payloads[0].after = "02";
        await route.fulfill({ response, json: v });
      },
    );
    const { analog } = await offline(page, f),
      recovery = await prepare(analog, f.parent.id);
    await expect(recovery.getByRole("alert")).toContainText(
      "differs from this exact source and receipt",
    );
    await expect(
      recovery.getByRole("button", {
        name: "Stage previous analog terminal",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      analog.getByLabel("Analog terminal destination", { exact: true }),
    ).toHaveValue("2");
  });

for (const change of ["task", "source", "draft", "lifecycle"] as const)
  test(`a delayed analog preparation cannot return after ${change} changes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      other =
        change === "source" ? seed(nativeScheduleWriteServer.directory) : null,
      { analog, inputs } = await offline(page, f);
    let seen!: () => void, release!: () => void;
    const arrived = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r));
    await page.route(
      "**/input/encoded-terminal/recovery/prepare",
      async (route) => {
        const response = await route.fetch();
        seen();
        await gate;
        await route.fulfill({ response });
      },
    );
    await prepare(analog, f.parent.id);
    await arrived;
    if (change === "task") await chooseWorkspaceTask(page, "Program");
    if (change === "source")
      await inputs
        .getByLabel("Retained native input source", { exact: true })
        .selectOption(other.id);
    if (change === "draft")
      await analog
        .getByLabel("Analog terminal destination", { exact: true })
        .selectOption("1");
    if (change === "lifecycle")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    const done = page.waitForResponse((r) =>
      r.url().endsWith("/recovery/prepare"),
    );
    release();
    await done;
    if (change === "task") await chooseWorkspaceTask(page, "Points & I/O");
    if (change === "source")
      await inputs
        .getByLabel("Retained native input source", { exact: true })
        .selectOption(f.id);
    if ((await analog.getAttribute("open")) === null)
      await analog.locator(":scope > summary").click();
    const recovery = analog.getByLabel("Previous configured analog terminal", {
      exact: true,
    });
    if ((await recovery.getAttribute("open")) === null)
      await recovery.locator(":scope > summary").click();
    await expect(
      recovery.getByRole("button", {
        name: "Prepare previous analog terminal",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      recovery.getByRole("button", {
        name: "Stage previous analog terminal",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      analog.getByLabel("Analog terminal destination", { exact: true }),
    ).toHaveValue(change === "draft" ? "1" : "2");
  });
