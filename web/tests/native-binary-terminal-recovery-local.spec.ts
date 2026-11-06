import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  offline,
  prepare,
} from "./native-binary-terminal-recovery-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const caf of [false, true])
  for (const width of [1440, 390])
    test(`${caf ? "CAF" : "graph"} ${width}px previous binary terminal stages explicitly and preserves ordinary drafts`, async ({
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
        "**/input/binary-terminal/recovery/prepare",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          original = await response.body();
          await route.fulfill({ response });
        },
      );
      await page.setViewportSize({ width, height: 1000 });
      const { inputs, binary } = await offline(page, f, caf),
        recovery = await prepare(binary, f.parent.id);
      await expect(
        recovery.getByRole("button", {
          name: "Stage previous binary terminal",
          exact: true,
        }),
      ).toBeVisible();
      const saved = page.waitForEvent("download");
      await recovery
        .getByRole("button", {
          name: "Save previous binary recovery evidence",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await saved).path())!)).toEqual(original);
      await recovery
        .getByRole("button", {
          name: "Stage previous binary terminal",
          exact: true,
        })
        .click();
      await expect(
        binary.getByLabel("Binary terminal destination", { exact: true }),
      ).toHaveValue("1");
      await expect(
        binary.getByRole("region", {
          name: "Staged previous binary terminal",
          exact: true,
        }),
      ).toContainText(f.parent.id);
      await binary.screenshot({
        path: testInfo.outputPath("staged-binary-recovery.png"),
      });
      await binary
        .getByRole("button", {
          name: "Review local binary terminal copy",
          exact: true,
        })
        .click();
      const review = binary.getByRole("region", {
        name: "Binary terminal review",
        exact: true,
      });
      await expect(review).toBeVisible();
      const copy = page.waitForEvent("download");
      await review
        .getByRole("button", {
          name: "Save native binary terminal copy",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await copy).path())!)).toEqual(
        Buffer.from(f.output, "base64"),
      );
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Points & I/O");
      if (
        (await binary
          .getByLabel("Configured binary input", { exact: true })
          .count()) === 0
      )
        await binary.locator(":scope > summary").click();
      await expect(
        binary.getByLabel("Binary terminal destination", { exact: true }),
      ).toHaveValue("1");
      await binary
        .getByRole("button", {
          name: "Restore ordinary binary draft",
          exact: true,
        })
        .click();
      await expect(
        binary.getByLabel("Binary terminal destination", { exact: true }),
      ).toHaveValue("2");
      await binary.locator(":scope > summary").click();
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
            "/input/binary-terminal/source",
            "/input/binary-terminal/recovery/prepare",
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
      { binary, inputs } = await offline(page, f, caf),
      recovery = await prepare(binary, f.parent.id);
    await recovery
      .getByRole("button", {
        name: "Stage previous binary terminal",
        exact: true,
      })
      .click();
    await expect(
      binary.getByRole("button", {
        name: "Restore ordinary binary draft",
        exact: true,
      }),
    ).toBeVisible();
    await binary
      .getByRole("button", { name: "Discard local binary draft", exact: true })
      .click();
    for (const navigate of [false, true]) {
      if (navigate) {
        await chooseWorkspaceTask(page, "Program");
        await chooseWorkspaceTask(page, "Points & I/O");
        if ((await binary.getAttribute("open")) === null)
          await binary.locator(":scope > summary").click();
      }
      await expect(
        binary.getByRole("button", {
          name: "Restore ordinary binary draft",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        binary.getByRole("region", {
          name: "Staged previous binary terminal",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        binary.getByLabel("Configured binary input", { exact: true }),
      ).toHaveValue("");
      await expect(
        binary.getByLabel("Binary terminal destination", { exact: true }),
      ).toHaveValue("");
      await expect(
        binary.getByLabel("Previous configured binary transfer receipt", {
          exact: true,
        }),
      ).toHaveValue("");
    }
    await binary.locator(":scope > summary").click();
    await expect(
      inputs.getByLabel("Engineering range high", { exact: true }),
    ).toHaveValue("9.");
  });

for (const fault of ["source", "lineage", "payload"] as const)
  test(`damaged prepared binary ${fault} cannot stage`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory);
    await page.route(
      "**/input/binary-terminal/recovery/prepare",
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
    const { binary } = await offline(page, f),
      recovery = await prepare(binary, f.parent.id);
    await expect(recovery.getByRole("alert")).toContainText(
      "differs from this exact source and receipt",
    );
    await expect(
      recovery.getByRole("button", {
        name: "Stage previous binary terminal",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      binary.getByLabel("Binary terminal destination", { exact: true }),
    ).toHaveValue("2");
  });

for (const change of ["task", "source", "draft", "lifecycle"] as const)
  test(`a delayed binary preparation cannot return after ${change} changes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      other =
        change === "source" ? seed(nativeScheduleWriteServer.directory) : null,
      { binary, inputs } = await offline(page, f);
    let seen!: () => void, release!: () => void;
    const arrived = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r));
    await page.route(
      "**/input/binary-terminal/recovery/prepare",
      async (route) => {
        const response = await route.fetch();
        seen();
        await gate;
        await route.fulfill({ response });
      },
    );
    await prepare(binary, f.parent.id);
    await arrived;
    if (change === "task") await chooseWorkspaceTask(page, "Program");
    if (change === "source")
      await inputs
        .getByLabel("Retained native input source", { exact: true })
        .selectOption(other.id);
    if (change === "draft")
      await binary
        .getByLabel("Binary terminal destination", { exact: true })
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
    if ((await binary.getAttribute("open")) === null)
      await binary.locator(":scope > summary").click();
    const recovery = binary.getByLabel("Previous configured binary terminal", {
      exact: true,
    });
    if ((await recovery.getAttribute("open")) === null)
      await recovery.locator(":scope > summary").click();
    await expect(
      recovery.getByRole("button", {
        name: "Prepare previous binary terminal",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      recovery.getByRole("button", {
        name: "Stage previous binary terminal",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      binary.getByLabel("Binary terminal destination", { exact: true }),
    ).toHaveValue(change === "draft" ? "1" : "2");
  });

test("manual terminal editing retires staged lineage and keeps the saved ordinary draft recoverable", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { binary } = await offline(page, f),
    recovery = await prepare(binary, f.parent.id);
  await recovery
    .getByRole("button", {
      name: "Stage previous binary terminal",
      exact: true,
    })
    .click();
  await expect(
    binary.getByRole("region", {
      name: "Staged previous binary terminal",
      exact: true,
    }),
  ).toContainText(f.parent.id);
  await binary
    .getByLabel("Binary terminal destination", { exact: true })
    .selectOption("2");
  const ordinary = binary.getByRole("region", {
    name: "Staged previous binary terminal",
    exact: true,
  });
  await expect(ordinary).toContainText(
    "The saved ordinary binary draft is retained. This edited proposal needs its own review.",
  );
  await expect(ordinary).not.toContainText(f.parent.id);
  await expect(
    ordinary.getByRole("button", {
      name: "Save staged binary recovery evidence",
      exact: true,
    }),
  ).toHaveCount(0);
  await binary
    .getByRole("button", { name: "Restore ordinary binary draft", exact: true })
    .click();
  await expect(
    binary.getByLabel("Binary terminal destination", { exact: true }),
  ).toHaveValue("2");
  await expect(
    binary.getByRole("region", {
      name: "Staged previous binary terminal",
      exact: true,
    }),
  ).toHaveCount(0);
});
