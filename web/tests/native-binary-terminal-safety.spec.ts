import { test, expect } from "./nativeScheduleWriteFixture";
import {
  seedBinary,
  openBinary,
  binaryDraft,
} from "./native-binary-terminal-fixture";
for (const fault of ["source", "review", "export"] as const)
  test(`malformed binary ${fault} cannot enable an unsafe action`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedBinary(nativeScheduleWriteServer.directory);
    if (fault === "source")
      await page.route("**/input/binary-terminal/source", async (route) => {
        const response = await route.fetch(),
          v = await response.json();
        v.inputs[0].configuration_sha256 = "bad";
        await route.fulfill({ response, json: v });
      });
    if (fault === "source") {
      await page.goto("/");
      await page
        .getByRole("button", { name: "New application", exact: true })
        .click();
      const { chooseWorkspaceTask } = await import("./workspace-navigation");
      await chooseWorkspaceTask(page, "Points & I/O");
      await page
        .getByLabel("Retained native input source", { exact: true })
        .selectOption(f.id);
      const binary = page.getByLabel("Binary input terminal movement", {
        exact: true,
      });
      await binary.locator(":scope > summary").click();
      await expect(binary.getByRole("alert")).toContainText(
        "differs from this retained capture",
      );
      await expect(binary.getByLabel("Configured binary input")).toHaveCount(0);
      return;
    }
    const { binary } = await openBinary(page, f.id);
    await binaryDraft(binary);
    if (fault === "review")
      await page.route("**/input/copy/preview", async (route) => {
        const response = await route.fetch(),
          v = await response.json();
        v.compilation.stored_configuration.polarity = 0;
        await route.fulfill({ response, json: v });
      });
    await binary
      .getByRole("button", {
        name: "Review local binary terminal copy",
        exact: true,
      })
      .click();
    if (fault === "review") {
      await expect(binary.getByRole("alert")).toContainText("proof differs");
      await expect(
        binary.getByRole("button", {
          name: "Save native binary terminal copy",
          exact: true,
        }),
      ).toHaveCount(0);
      return;
    }
    await expect(
      binary.getByRole("region", {
        name: "Binary terminal review",
        exact: true,
      }),
    ).toBeVisible();
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/input/copy/export", async (route) => {
      const response = await route.fetch(),
        body = await response.body();
      await route.fulfill({
        response,
        body: Buffer.concat([body, Buffer.from([0])]),
      });
    });
    await binary
      .getByRole("button", {
        name: "Save native binary terminal copy",
        exact: true,
      })
      .click();
    await expect(binary.getByRole("alert")).toContainText(
      "differs from its reviewed bytes",
    );
    expect(downloads).toBe(0);
  });
test("a delayed binary proof digest cannot revive a review after page hide", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedBinary(nativeScheduleWriteServer.directory),
    { binary } = await openBinary(page, f.id);
  await binaryDraft(binary);
  await page.evaluate(() => {
    const w = window as any,
      original = crypto.subtle.digest.bind(crypto.subtle);
    w.binaryWaiting = [];
    w.binaryDelay = true;
    w.binaryDone = 0;
    crypto.subtle.digest = async (a: any, v: any) => {
      const tracked = new TextDecoder()
        .decode(v)
        .includes("tagged-moi-local-terminal-copy/3");
      if (tracked && w.binaryDelay)
        await new Promise<void>((r) => w.binaryWaiting.push(r));
      const result = await original(a, v);
      if (tracked) w.binaryDone++;
      return result;
    };
  });
  await binary
    .getByRole("button", {
      name: "Review local binary terminal copy",
      exact: true,
    })
    .click();
  await page.waitForFunction(() => (window as any).binaryWaiting.length > 0);
  await page.evaluate(() => {
    const w = window as any;
    window.dispatchEvent(new Event("pagehide"));
    w.binaryDelay = false;
    w.binaryWaiting.splice(0).forEach((r: any) => r());
  });
  await page.waitForFunction(() => (window as any).binaryDone >= 2);
  await binary.locator(":scope > summary").click();
  await expect(
    binary.getByRole("button", {
      name: "Review local binary terminal copy",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    binary.getByRole("region", { name: "Binary terminal review", exact: true }),
  ).toHaveCount(0);
});
