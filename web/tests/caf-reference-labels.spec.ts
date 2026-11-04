import { test, expect } from "./nativeScheduleWriteFixture";
import { enter, inspect, prepare } from "./caf-math-fixture";
import {
  enter as enumEntry,
  inspect as comparisonInspect,
  mixedEnum,
} from "./caf-enum-comparison-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { logic } from "./caf-constant-fixture";

test("actual prototype references gain reference names and versioned provenance", async ({
  page,
}) => {
  const editor = await enter(page);
  await expect(
    editor.getByRole("option", {
      name: "561_10 · MAX (reference)",
      exact: true,
    }),
  ).toHaveCount(1);
  await editor
    .getByText("Reference names and provenance", { exact: true })
    .click();
  await expect(editor).toContainText("Reference standard name: MAX");
  await expect(editor).toContainText("FDB Control 10.8 / Firmware 12.0");
  await expect(editor).toContainText(
    "Compatibility with this archive and runtime meaning remain unverified",
  );
  await prepare(page);
});
test("reference labels arriving after a valid review do not retire it or consume a draft", async ({
  page,
}) => {
  let release!: () => void, started!: () => void, finished!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    done = new Promise<void>((r) => (finished = r));
  await page.route("**/reference-labels?*", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await held;
    await route.fulfill({ response });
    finished();
  });
  const editor = await enter(page);
  await entered;
  await editor.getByLabel("New block X", { exact: true }).fill("+120.000");
  const review = await prepare(page);
  release();
  await done;
  await expect(
    editor.getByRole("option", {
      name: "561_10 · MAX (reference)",
      exact: true,
    }),
  ).toHaveCount(1);
  await expect(review).toBeVisible();
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "+120.000",
  );
  const download = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save block CAF copy", exact: true })
    .click();
  await download;
});
test("unavailable reference metadata keeps raw selection and existing copy workflow usable", async ({
  page,
}) => {
  await page.route("**/reference-labels?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: "metadata unavailable" }),
    }),
  );
  const editor = await enter(page);
  await expect(
    editor.getByRole("note", {
      name: "Reference-name availability",
      exact: true,
    }),
  ).toContainText("Raw references and existing CAF tools remain available");
  await expect(
    editor.getByRole("option", { name: "561_10", exact: true }),
  ).toHaveCount(1);
  const review = await prepare(page);
  const downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save block CAF copy", exact: true })
    .click();
  await downloading;
  await expect(editor.getByRole("status")).toContainText(
    "No controller write was sent",
  );
});
test("late reference failure for a retired task cannot replace its fresh metadata", async ({
  page,
}) => {
  let release!: () => void,
    started!: () => void,
    finished!: () => void,
    seen = false;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    done = new Promise<void>((r) => (finished = r));
  await page.route("**/reference-labels?*", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    if (!seen) {
      seen = true;
      started();
      await held;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "retired metadata failure" }),
      });
      finished();
    } else await route.fulfill({ response });
  });
  let editor = await enter(page);
  await entered;
  await editor.getByLabel("New block X", { exact: true }).fill("120");
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(
    editor.getByRole("option", {
      name: "561_10 · MAX (reference)",
      exact: true,
    }),
  ).toHaveCount(1);
  release();
  await done;
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "120",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await prepare(page);
  await expect(
    editor.getByRole("option", {
      name: "561_10 · MAX (reference)",
      exact: true,
    }),
  ).toHaveCount(1);
  await expect(
    editor.getByRole("note", {
      name: "Reference-name availability",
      exact: true,
    }),
  ).toHaveCount(0);
});
test("Enum prototype names stay reference-only while raw source codes and mixed drafts remain", async ({
  page,
}) => {
  const editor = await enumEntry(page, "mixed");
  await expect(
    editor.getByRole("option", {
      name: "560_80 · Equal (Enum) (reference)",
      exact: true,
    }),
  ).toHaveCount(1);
  await editor.getByLabel("New block X", { exact: true }).fill("120");
  await editor
    .getByText("Reference names and provenance", { exact: true })
    .click();
  await expect(editor).toContainText("Reference setup: =");
  await expect(editor).toContainText("Recorded setup code 5");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("math");
  await inspect(page);
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("comparison");
  const restored = await comparisonInspect(page);
  await expect(
    restored.getByLabel("Block prototype", { exact: true }),
  ).toHaveValue(mixedEnum);
  await expect(restored.getByLabel("New block X", { exact: true })).toHaveValue(
    "120",
  );
});
test("compact reference names retain one primary action and the original readable controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const editor = await enter(page);
  await expect(
    editor.getByRole("option", {
      name: "561_10 · MAX (reference)",
      exact: true,
    }),
  ).toHaveCount(1);
  await prepare(page);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect(
    (await editor.getByLabel("Block prototype", { exact: true }).boundingBox())!
      .height,
  ).toBeGreaterThanOrEqual(36);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
});
