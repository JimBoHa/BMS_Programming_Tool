import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { enter, inspect, prepare, python, ref } from "./caf-math-fixture";
import { logic } from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const kind of ["small", "extra", "output-second"])
  test(`${kind} Math export preserves exact review, child order, output and recorded defaults`, async ({
    page,
    request,
  }) => {
    const editor = await enter(page, kind);
    await expect(editor).toContainText("Recorded setup code 17");
    await editor.getByText("Recorded math inputs", { exact: true }).click();
    await expect(editor).toContainText("recorded default 0.002000");
    await expect(editor).toContainText(
      "Port 7000: default omitted in source; exposed",
    );
    if (kind !== "small")
      await expect(editor).toContainText("Recorded input standard-name code 0");
    let exact = Buffer.alloc(0);
    await page.route("**/math-copy/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    });
    const review = await prepare(page);
    await expect(review).toContainText(
      `One graph member and ${kind === "small" ? "four" : "five"} objects added`,
    );
    let downloading = page.waitForEvent("download");
    await review
      .getByRole("button", { name: "Save exact block review", exact: true })
      .click();
    expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
    downloading = page.waitForEvent("download");
    await review
      .getByRole("button", { name: "Save block CAF copy", exact: true })
      .click();
    const file = (await (await downloading).path())!;
    expect(createHash("sha256").update(readFileSync(file)).digest("hex")).toBe(
      JSON.parse(exact.toString()).creation.output_sha256,
    );
    const result = JSON.parse(
      python(
        "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph;a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2]);base=sys.argv[2]+'.561_31';print(json.dumps({'objects':len(a.objects),'last':g['blocks'][-1]['ref'],'order':g['execution_order'],'external_attr':a.info.external_attr,'child_refs':[r for r in a.objects if r.startswith(base+'.')],'input_default':next(p['scalar']['text'] for p in a.properties(base+'.2_'+('34' if sys.argv[3]=='small' else '35')) if p['id']=='3113')}))",
        file,
        ref,
        kind,
      ).toString(),
    );
    expect(result).toEqual({
      objects: kind === "small" ? 11 : 13,
      last: ref + ".561_31",
      order: [0, 3, 1, 2],
      external_attr: 0,
      child_refs: Array.from(
        { length: kind === "small" ? 3 : 4 },
        (_, i) => ref + `.561_31.2_${32 + i}`,
      ),
      input_default: "0.002000",
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
test("math and constant drafts survive task and block-kind ABA", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New block X", { exact: true }).fill("120");
  await prepare(page);
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("comparison");
  const previous = await inspect(page);
  await previous.getByLabel("New block X", { exact: true }).fill("220");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("float");
  const constant = page.getByRole("region", {
    name: "CAF constant creation",
    exact: true,
  });
  const details = page.locator(".caf-constant-copy:visible");
  if ((await details.getAttribute("open")) === null)
    await details.locator("summary").first().click();
  await constant
    .getByRole("button", { name: "Inspect constant prototype", exact: true })
    .click();
  await constant.getByLabel("New constant X", { exact: true }).fill("-");
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("math");
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "120",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("comparison");
  const previousAgain = await inspect(page);
  await expect(
    previousAgain.getByLabel("New block X", { exact: true }),
  ).toHaveValue("220");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("float");
  await expect(
    constant.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".react-flow__node"),
  ).toHaveCount(7);
});
test("late math export retires across block-kind ABA", async ({ page }) => {
  let editor = await enter(page, "mixed");
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/math-copy/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await held;
    await route.fulfill({ response });
    completed();
  });
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  await editor
    .getByRole("button", { name: "Save block CAF copy", exact: true })
    .click();
  await entered;
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("boolean");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("math");
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/math-copy/export");
  await prepare(page);
  expect(downloads).toEqual([]);
});
test("compact block creation keeps one primary action and readable coordinates", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const editor = await enter(page, "mixed");
  await prepare(page);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect(
    (await editor.getByLabel("New block X", { exact: true }).boundingBox())!
      .height,
  ).toBeGreaterThanOrEqual(36);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
});
