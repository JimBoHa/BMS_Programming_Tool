import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seed, offline, prepare } from "./native-terminal-recovery-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const { width, caf } of [
  { width: 1440, caf: false },
  { width: 390, caf: true },
])
  test(`${caf ? "CAF" : "graph"} previous-terminal draft retains ordinary text and exports a separate offline copy at ${width}px`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const f = seed(nativeScheduleWriteServer.directory),
      posts: string[] = [];
    await page.setViewportSize({ width, height: 1000 });
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/api/bacnet/"))
        posts.push(new URL(r.url()).pathname);
    });
    const inputs = await offline(page, f, caf),
      recovery = inputs.getByLabel("Previous analog input terminal", {
        exact: true,
      });
    if (!caf) {
      await inputs
        .getByLabel("Input operation", { exact: true })
        .selectOption("mode");
      await inputs
        .getByLabel("Engineering range high", { exact: true })
        .fill("9.");
    }
    await prepare(inputs, f.parent.id);
    await expect(
      recovery.getByRole("button", {
        name: "Use previous input terminal",
        exact: true,
      }),
    ).toBeEnabled();
    let download = page.waitForEvent("download");
    await recovery
      .getByRole("button", {
        name: "Save previous-terminal evidence",
        exact: true,
      })
      .click();
    const saved = JSON.parse(
      readFileSync((await (await download).path())!).toString(),
    );
    expect(saved.origin.parent_receipt_id).toBe(f.parent.id);
    await recovery
      .getByRole("button", { name: "Use previous input terminal", exact: true })
      .click();
    await expect(
      inputs.getByLabel("Field terminal destination", { exact: true }),
    ).toHaveValue("1");
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    await expect(
      inputs.getByLabel("Field terminal destination", { exact: true }),
    ).toHaveValue("1");
    await expect(
      inputs.getByRole("region", {
        name: "Staged previous-terminal draft",
        exact: true,
      }),
    ).toContainText("UI IN3 to UI IN1");
    await inputs
      .getByRole("button", { name: "Review local input copy", exact: true })
      .click();
    await expect(inputs).toContainText("Local copy reviewed.");
    download = page.waitForEvent("download");
    await inputs
      .getByRole("button", { name: "Save native copy", exact: true })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(
      Buffer.from(f.output, "base64"),
    );
    await inputs
      .getByRole("button", { name: "Return to saved input draft", exact: true })
      .click();
    if (caf)
      await expect(
        inputs.getByLabel("Field terminal destination", { exact: true }),
      ).toHaveValue("2");
    else {
      await expect(
        inputs.getByLabel("Input operation", { exact: true }),
      ).toHaveValue("mode");
      await expect(
        inputs.getByLabel("Engineering range high", { exact: true }),
      ).toHaveValue("9.");
    }
    await expect(
      inputs.getByRole("region", {
        name: "Staged previous-terminal draft",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(
      posts.every((p) =>
        [
          "/input/source",
          "/input/terminal-recovery/prepare",
          "/input/copy/preview",
          "/input/copy/export",
        ].some((s) => p.endsWith(s)),
      ),
    ).toBe(true);
    if (caf)
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("terminal-recovery.caf");
    await recovery.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("terminal-recovery-local.png"),
    });
  });
test("malformed preparation withholds staging and its evidence download", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.route("**/input/terminal-recovery/prepare", async (route) => {
    const response = await route.fetch(),
      v = await response.json();
    v.origin.previous_slot = 2;
    await route.fulfill({ response, json: v });
  });
  const inputs = await offline(page, f),
    recovery = await prepare(inputs, f.parent.id);
  await expect(recovery.getByRole("alert")).toContainText(
    "differs from this exact source",
  );
  await expect(
    recovery.getByRole("button", {
      name: "Use previous input terminal",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    recovery.getByRole("button", {
      name: "Save previous-terminal evidence",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    inputs.getByLabel("Field terminal destination", { exact: true }),
  ).toHaveValue("2");
});
test("late preparation cannot overwrite an edited ordinary input draft", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    arrived = new Promise<void>((r) => (seen = r));
  await page.route("**/input/terminal-recovery/prepare", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
  });
  const inputs = await offline(page, f),
    recovery = await prepare(inputs, f.parent.id);
  await arrived;
  await inputs
    .getByLabel("Field terminal destination", { exact: true })
    .selectOption("1");
  release();
  await expect(
    recovery.getByRole("button", {
      name: "Prepare previous input terminal",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    recovery.getByRole("button", {
      name: "Use previous input terminal",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    inputs.getByRole("region", {
      name: "Staged previous-terminal draft",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("a delayed preparation digest cannot restore evidence after page hide", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    inputs = await offline(page, f);
  await page.evaluate(() => {
    const w = window as any,
      original = crypto.subtle.digest.bind(crypto.subtle);
    w.recoveryDigestWait = [];
    w.recoveryDigestDelay = true;
    w.recoveryDigestDone = 0;
    crypto.subtle.digest = async (algorithm: any, value: any) => {
      const tracked = new TextDecoder()
        .decode(value)
        .includes("tagged-moi-local-terminal-copy/2");
      if (tracked && w.recoveryDigestDelay)
        await new Promise<void>((r) => w.recoveryDigestWait.push(r));
      const answer = await original(algorithm, value);
      if (tracked) w.recoveryDigestDone++;
      return answer;
    };
  });
  const recovery = await prepare(inputs, f.parent.id);
  await page.waitForFunction(
    () => (window as any).recoveryDigestWait.length > 0,
  );
  await page.evaluate(() => {
    const w = window as any;
    window.dispatchEvent(new Event("pagehide"));
    w.recoveryDigestDelay = false;
    w.recoveryDigestWait.splice(0).forEach((r: any) => r());
  });
  await page.waitForFunction(() => (window as any).recoveryDigestDone >= 2);
  await expect(
    recovery.getByRole("button", {
      name: "Prepare previous input terminal",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    recovery.getByRole("button", {
      name: "Use previous input terminal",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    recovery.getByRole("button", {
      name: "Save previous-terminal evidence",
      exact: true,
    }),
  ).toHaveCount(0);
});
