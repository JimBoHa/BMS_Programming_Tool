import { test, expect } from "./nativeScheduleWriteFixture";
import { enter, inspect, python, ref } from "./caf-boolean-fixture";
import { logic, prepare } from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
test("Boolean-only CAF entry exports both exact identities and keeps recorded truth spelling", async ({
  page,
  request,
}) => {
  const editor = await enter(page);
  await expect(editor).toContainText("standard-name code 13; output true");
  await expect(page.getByLabel("Constant type", { exact: true })).toHaveCount(
    0,
  );
  await prepare(page);
  const downloading = page.waitForEvent("download");
  await editor
    .getByRole("button", { name: "Save constant CAF copy", exact: true })
    .click();
  const file = (await (await downloading).path())!;
  const output = JSON.parse(
    python(
      "from pathlib import Path;import json,sys;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph;a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2]);print(json.dumps({'objects':len(a.objects),'last':g['blocks'][-1]['ref'],'order':g['execution_order'],'external_attr':a.info.external_attr,'output':[p['scalar'] for p in a.properties(sys.argv[2]+'.552_31.5_32') if p['id']=='3113']}))",
      file,
      ref,
    ).toString(),
  );
  expect(output).toEqual({
    objects: 7,
    last: ref + ".552_31",
    order: [0, 3, 1, 2],
    external_attr: 0,
    output: [{ type: "boolean", text: "true", attributes: {} }],
  });
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
test("mixed actual-data kind selection retains both unfinished drafts without restoring reviews", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New constant X", { exact: true }).fill("-");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("boolean");
  editor = await inspect(page);
  await expect(editor).toContainText("output true");
  await editor.getByLabel("New constant X", { exact: true }).fill("120");
  await prepare(page);
  await page.getByLabel("Constant type", { exact: true }).selectOption("float");
  editor = await inspect(page);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF constant copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("boolean");
  editor = await inspect(page);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("120");
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".react-flow__node"),
  ).toHaveCount(4);
});
test("type ABA retires a late Boolean export while preserving its own proposal", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("boolean");
  editor = await inspect(page);
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/boolean-constant-copy/export", async (route) => {
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
  await page.getByLabel("Constant type", { exact: true }).selectOption("float");
  await page
    .getByLabel("Constant type", { exact: true })
    .selectOption("boolean");
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/boolean-constant-copy/export");
  await prepare(page);
  expect(downloads).toEqual([]);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("81.000");
});
test("compact mixed-kind controls keep one visible primary action and a usable selector", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let editor = await enter(page, "mixed");
  const kind = page.getByLabel("Constant type", { exact: true });
  expect((await kind.boundingBox())!.height).toBeGreaterThanOrEqual(36);
  await kind.selectOption("boolean");
  editor = await inspect(page);
  await prepare(page);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  await kind.selectOption("float");
  editor = await inspect(page);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
});
