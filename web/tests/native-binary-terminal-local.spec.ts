import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seedBinary,
  openBinary,
  binaryDraft,
} from "./native-binary-terminal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const width of [1440, 390])
  test(`${width}px binary local copy uses selected capture and retains analog raw draft`, async ({
    page,
    nativeScheduleWriteServer,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const f = seedBinary(nativeScheduleWriteServer.directory),
      { inputs, binary } = await openBinary(page, f.id, width === 390);
    await binaryDraft(binary);
    await expect(
      inputs.getByLabel("Engineering range high", { exact: true }),
    ).toHaveCount(0);
    let raw = Buffer.alloc(0);
    await page.route("**/input/copy/preview", async (route) => {
      const response = await route.fetch();
      raw = await response.body();
      await route.fulfill({ response, body: raw });
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
    let wait = page.waitForEvent("download");
    await review
      .getByRole("button", { name: "Save binary terminal review", exact: true })
      .click();
    expect(readFileSync((await (await wait).path())!)).toEqual(raw);
    wait = page.waitForEvent("download");
    await review
      .getByRole("button", {
        name: "Save native binary terminal copy",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await wait).path())!)).toEqual(
      Buffer.from(f.output, "base64"),
    );
    expect(
      await binary
        .getByRole("button", {
          name: "Apply binary terminal change to controller",
          exact: true,
        })
        .count(),
    ).toBe(0);
    await binary.locator(":scope > summary").click();
    await expect(
      inputs.getByLabel("Engineering range high", { exact: true }),
    ).toHaveValue("9.");
    await binary.locator(":scope > summary").click();
    await expect(
      binary.getByLabel("Configured binary input", { exact: true }),
    ).toHaveValue("binary-input,101");
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    await binary.locator(":scope > summary").click();
    await expect(
      binary.getByLabel("Binary terminal destination", { exact: true }),
    ).toHaveValue("3");
    await expect(
      binary.getByRole("region", {
        name: "Binary terminal review",
        exact: true,
      }),
    ).toHaveCount(0);
    await binary.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: info.outputPath("binary-terminal.png") });
  });
test("late local binary preview cannot return after leaving its task", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedBinary(nativeScheduleWriteServer.directory),
    { binary } = await openBinary(page, f.id);
  await binaryDraft(binary);
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    arrived = new Promise<void>((r) => (seen = r));
  await page.route("**/input/copy/preview", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
  });
  await binary
    .getByRole("button", {
      name: "Review local binary terminal copy",
      exact: true,
    })
    .click();
  await arrived;
  await chooseWorkspaceTask(page, "Overview");
  release();
  await chooseWorkspaceTask(page, "Points & I/O");
  await binary.locator(":scope > summary").click();
  await expect(
    binary.getByRole("region", { name: "Binary terminal review", exact: true }),
  ).toHaveCount(0);
});
