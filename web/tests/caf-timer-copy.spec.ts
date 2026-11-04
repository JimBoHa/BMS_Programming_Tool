import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { enter, inspect, prepare, python, ref } from "./caf-timer-fixture";
import { logic } from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const kind of ["timer", "off", "matching"])
  test(`${kind} Timer export retains seven ports, both outputs, exact defaults and review`, async ({
    page,
    request,
  }) => {
    const editor = await enter(page, kind);
    await expect(editor).toContainText("Recorded standard-name code 62");
    await expect(editor).not.toContainText("Recorded setup code");
    await editor.getByText("Recorded Timer ports", { exact: true }).click();
    await expect(editor).toContainText(
      "output port 85: default omitted in source; exposed",
    );
    await expect(editor).toContainText(
      "output port 1081: default omitted in source; not exposed",
    );
    await expect(editor).toContainText(
      "input port 1082: default omitted in source; not exposed",
    );
    await expect(editor).toContainText(
      `recorded default ${kind === "timer" ? "2" : "4"}`,
    );
    await expect(editor).toContainText("Recorded units code 73");
    await expect(
      editor.getByRole("option", {
        name: "558_10 · Timer (reference)",
        exact: true,
      }),
    ).toHaveCount(1);
    let exact = Buffer.alloc(0);
    await page.route("**/timer-copy/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    });
    const review = await prepare(page);
    await expect(review).toContainText(
      "One graph member and eight objects added",
    );
    await expect(review).toContainText("Primary output");
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
        "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph;a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2]);base=sys.argv[2]+'.558_31';print(json.dumps({'objects':len(a.objects),'last':g['blocks'][-1]['ref'],'order':g['execution_order'],'external_attr':a.info.external_attr,'child_refs':[r for r in a.objects if r.startswith(base+'.')],'exposed':[p['id'] for p in g['blocks'][-1]['exposed_ports']],'mode':next(p['scalar'] for p in a.properties(base+'.19_35') if p['id']=='3113'),'duration':next(p['scalar']['text'] for p in a.properties(base+'.2_36') if p['id']=='3113'),'output_default':next((p['scalar'] for p in a.properties(base+'.2_38') if p['id']=='3113'),None)}))",
        file,
        ref,
      ).toString(),
    );
    expect(result).toEqual({
      objects: 19,
      last: ref + ".558_31",
      order: [0, 3, 1, 2],
      external_attr: 0,
      child_refs: [
        ref + ".558_31.5_32",
        ref + ".558_31.5_33",
        ref + ".558_31.5_34",
        ref + ".558_31.19_35",
        ref + ".558_31.2_36",
        ref + ".558_31.19_37",
        ref + ".558_31.2_38",
      ],
      exposed: [513, 1080, 85],
      mode: {
        type: "enum",
        text: kind === "timer" ? "2" : "4",
        attributes: { set: kind === "matching" ? "21" : "647" },
      },
      duration: kind === "matching" ? "5" : "5.000000",
      output_default: null,
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
test("Timer and constant drafts survive task and block-kind ABA", async ({
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
    .selectOption("timer");
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
  ).toHaveCount(9);
});
test("late Timer export retires across block-kind ABA", async ({ page }) => {
  let editor = await enter(page, "mixed");
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/timer-copy/export", async (route) => {
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
    .selectOption("timer");
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/timer-copy/export");
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
