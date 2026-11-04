import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  enter,
  inspect,
  prepare,
  python,
  ref,
  mixedEnum,
  mixedFloat,
} from "./caf-enum-comparison-fixture";
import { logic } from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const kind of ["four", "enum", "matching", "omitted"])
  test(`${kind} Enumeration comparison export preserves namespaces, omissions, hidden input and exact review`, async ({
    page,
    request,
  }) => {
    const editor = await enter(page, kind);
    await expect(editor).toContainText("Recorded setup code 5");
    await expect(editor).toContainText("Enum meanings remain unverified");
    await editor
      .getByText("Recorded comparison inputs", { exact: true })
      .click();
    await expect(editor).toContainText(
      "Port 637: default omitted in source; not exposed",
    );
    await expect(editor).toContainText(
      `Number Of States: ${kind === "four" ? 4 : 6}`,
    );
    let exact = Buffer.alloc(0);
    await page.route("**/comparison-copy/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    });
    const review = await prepare(page);
    await expect(review).toContainText(
      "One graph member and five objects added",
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
        "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph;a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2]);base=sys.argv[2]+'.560_31';print(json.dumps({'objects':len(a.objects),'last':g['blocks'][-1]['ref'],'order':g['execution_order'],'external_attr':a.info.external_attr,'child_refs':[r for r in a.objects if r.startswith(base+'.')],'exposed':[p['id'] for p in g['blocks'][-1]['exposed_ports']],'defaults':[next((p['scalar'] for p in a.properties(base+'.19_'+str(i)) if p['id']=='3113'),None) for i in (34,35)]}))",
        file,
        ref,
      ).toString(),
    );
    const scalar = (text: string) => ({
      type: "enum",
      text,
      attributes: { set: kind === "matching" ? "387" : "647" },
    });
    expect(result).toEqual({
      objects: 13,
      last: ref + ".560_31",
      order: [0, 3, 1, 2],
      external_attr: 0,
      child_refs: [
        ref + ".560_31.5_32",
        ref + ".560_31.2_33",
        ref + ".560_31.19_34",
        ref + ".560_31.19_35",
      ],
      exposed: [50083, 50084, 85],
      defaults:
        kind === "omitted"
          ? [null, null]
          : kind === "four"
            ? [null, scalar("1")]
            : [scalar("3"), scalar("5")],
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
test("Enum/Float comparison and constant drafts survive prototype and task ABA", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New block X", { exact: true }).fill("120");
  await prepare(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption(mixedFloat);
  const previous = await inspect(page);
  await previous.getByLabel("New block X", { exact: true }).fill("220");
  await prepare(page);
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
    .selectOption("comparison");
  editor = await inspect(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption(mixedEnum);
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
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption(mixedFloat);
  const restored = await inspect(page);
  await expect(restored.getByLabel("New block X", { exact: true })).toHaveValue(
    "220",
  );
  await expect(
    restored.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
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
  ).toHaveCount(8);
});
test("late Enumeration comparison export retires across navigation and prototype ABA", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/comparison-copy/export", async (route) => {
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
  await expect(
    editor.getByLabel("Block prototype", { exact: true }),
  ).toBeDisabled();
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption(mixedFloat);
  editor = await inspect(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption(mixedEnum);
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/comparison-copy/export");
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
