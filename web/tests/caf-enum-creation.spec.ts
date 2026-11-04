import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { enter, inspect, python, ref } from "./caf-enum-creation-fixture";
import { prepare, logic } from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
test("enum local artifact and exact review preserve recorded namespaces and native code", async ({
  page,
  request,
}) => {
  const editor = await enter(page);
  await expect(editor).toContainText("standard-name code 12; output 10");
  await editor
    .getByText("Recorded enumeration metadata", { exact: true })
    .click();
  await expect(editor).toContainText("States Text code: 351");
  await expect(editor).toContainText("encoding set: 647");
  await expect(editor).toContainText("Enum meanings are unverified");
  let exact = Buffer.alloc(0);
  await page.route("**/enum-constant-copy/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    exact = await response.body();
    await route.fulfill({ response });
  });
  const review = await prepare(page);
  let downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save exact constant review", exact: true })
    .click();
  expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
  downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save constant CAF copy", exact: true })
    .click();
  const file = (await (await downloading).path())!;
  const result = JSON.parse(
    python(
      "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;a=CafArchive(Path(sys.argv[1]).read_bytes());print(json.dumps({'objects':len(a.objects),'external_attr':a.info.external_attr,'properties':{p['id']:p['scalar'] for p in a.properties(sys.argv[2]+'.568_31.19_32')}}))",
      file,
      ref,
    ).toString(),
  );
  expect(result.objects).toBe(7);
  expect(result.external_attr).toBe(0);
  expect(result.properties["3113"]).toEqual({
    type: "enum",
    text: "10",
    attributes: { set: "647" },
  });
  expect(result.properties["931"]).toEqual({
    type: "enum",
    text: "351",
    attributes: { set: "802" },
  });
  expect(result.properties["74"]).toEqual({
    type: "unsignedShort",
    text: "7",
    attributes: {},
  });
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
test("omitted enum defaults stay omitted instead of receiving a guessed value", async ({
  page,
}) => {
  const editor = await enter(page, "omitted");
  await expect(editor).toContainText("value omitted in source");
  await prepare(page);
  const downloading = page.waitForEvent("download");
  await editor
    .getByRole("button", { name: "Save constant CAF copy", exact: true })
    .click();
  const file = (await (await downloading).path())!;
  expect(
    python(
      "from pathlib import Path;import sys;from bms_tool.caf import CafArchive;a=CafArchive(Path(sys.argv[1]).read_bytes());assert all(p['id']!='3113' for p in a.properties(sys.argv[2]+'.568_31.19_32'));print('omitted')",
      file,
      ref,
    )
      .toString()
      .trim(),
  ).toBe("omitted");
});
test("three actual kinds retain separate unfinished drafts through task and kind changes", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New constant X", { exact: true }).fill("-");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("boolean");
  editor = await inspect(page);
  await editor.getByLabel("New constant X", { exact: true }).fill(" ");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("enumeration");
  editor = await inspect(page);
  await editor.getByLabel("New constant X", { exact: true }).fill("120");
  await prepare(page);
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("120");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF constant copy",
      exact: true,
    }),
  ).toHaveCount(0);
  for (const [kind, text] of [
    ["float", "-"],
    ["boolean", " "],
    ["enumeration", "120"],
  ]) {
    await page.getByLabel("Constant type", { exact: true }).selectOption(kind);
    editor = await inspect(page);
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue(text);
  }
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".react-flow__node"),
  ).toHaveCount(5);
});
test("late enum artifact cannot return after kind ABA", async ({ page }) => {
  let editor = await enter(page, "mixed");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("enumeration");
  editor = await inspect(page);
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/enum-constant-copy/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await held;
    await route.fulfill({ response });
    completed();
  });
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  await editor
    .getByRole("button", { name: "Save constant CAF copy", exact: true })
    .click();
  await entered;
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("boolean");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("enumeration");
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/enum-constant-copy/export");
  await prepare(page);
  expect(downloads).toEqual([]);
});
test("compact three-kind workflow has one focused primary action", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let editor = await enter(page, "mixed");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("enumeration");
  editor = await inspect(page);
  await prepare(page);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
});
