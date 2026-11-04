import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  enter,
  inspect,
  prepare,
  python,
  ref,
} from "./caf-enum-selector-multiplexer-fixture";
import { logic } from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const kind of ["float", "short"])
  test(`${kind} Enum-selector Multiplexer exact export preserves six ports, stored Float spelling and Enum metadata`, async ({
    page,
    request,
  }) => {
    const editor = await enter(page, kind);
    await expect(editor).toContainText("Recorded standard-name code 15");
    await expect(editor).not.toContainText("Recorded setup code");
    await expect(editor).toContainText("Six port objects are copied");
    await editor
      .getByText("Recorded multiplexer ports", { exact: true })
      .click();
    await expect(editor).toContainText(
      "input port 961: default omitted in source; exposed",
    );
    await expect(editor).toContainText("States Text code: 900");
    await expect(editor).toContainText(
      `recorded default ${kind === "short" ? "100" : "100.000000"}`,
    );
    await expect(editor).toContainText("Recorded input standard-name code 0");
    await expect(
      editor.getByRole("option", {
        name: "562_10 · MUX (Float IO, Enum Mode) (reference)",
        exact: true,
      }),
    ).toHaveCount(1);
    let exact = Buffer.alloc(0);
    await page.route("**/float-multiplexer-copy/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    });
    const review = await prepare(page);
    await expect(review).toContainText(
      "One graph member and seven objects added",
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
        "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph,_properties,_collection;a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2]);base=sys.argv[2]+'.562_31';children=[r for r in a.objects if r.startswith(base+'.')];p=_properties(a.objects[base]);print(json.dumps({'objects':len(a.objects),'last':g['blocks'][-1]['ref'],'order':g['execution_order'],'external_attr':a.info.external_attr,'child_refs':children,'defaults':[next((p['scalar']['text'] for p in a.properties(r) if p['id']=='3113'),None) for r in children],'bookkeeping':[x.text for x in _collection(p,'2381','listof')],'selector_states':next(p['scalar'] for p in a.properties(base+'.19_37') if p['id']=='931')}))",
        file,
        ref,
      ).toString(),
    );
    expect(result).toEqual({
      objects: 17,
      last: ref + ".562_31",
      order: [0, 3, 1, 2],
      external_attr: 0,
      child_refs: [
        ref + ".562_31.2_32",
        ref + ".562_31.2_33",
        ref + ".562_31.2_34",
        ref + ".562_31.2_35",
        ref + ".562_31.2_36",
        ref + ".562_31.19_37",
      ],
      defaults: [
        null,
        null,
        null,
        null,
        kind === "short" ? "100" : "100.000000",
        null,
      ],
      bookkeeping: ["0", "2", "0", "0", "3", "4"],
      selector_states: {
        type: "enum",
        text: "900",
        attributes: { set: "802" },
      },
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
test("Enum-selector Float Multiplexer, Timer and Boolean constant drafts survive task and block-kind ABA", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New block X", { exact: true }).fill("120");
  await prepare(page);
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("timer");
  const previous = await inspect(page);
  await previous.getByLabel("New block X", { exact: true }).fill("220");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("boolean");
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
    .selectOption("multiplexer");
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
    .selectOption("timer");
  const previousAgain = await inspect(page);
  await expect(
    previousAgain.getByLabel("New block X", { exact: true }),
  ).toHaveValue("220");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("boolean");
  await expect(
    constant.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".react-flow__node"),
  ).toHaveCount(14);
});
test("late float-multiplexer export retires across block-kind ABA", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/float-multiplexer-copy/export", async (route) => {
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
    .selectOption("multiplexer");
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/float-multiplexer-copy/export");
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

test("Enum-selector Float Multiplexer page lifecycle retires review while retaining local coordinates", async ({
  page,
}) => {
  let editor = await enter(page);
  await editor.getByLabel("New block X", { exact: true }).fill("130");
  await prepare(page);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "130",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await prepare(page);
});

test("Enum-selector Float Multiplexer rejects a mismatched source proof in the task", async ({
  page,
}) => {
  await page.route("**/float-multiplexer-copy/source", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    const data = await response.json();
    data.children[0].recorded_default = "false";
    await route.fulfill({ response, json: data });
  });
  await page.goto("/");
  const { source } = await import("./caf-enum-selector-multiplexer-fixture");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "enum-selector.caf",
      mimeType: "application/octet-stream",
      buffer: source(),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-selector.caf");
  await logic(page);
  const details = page.locator(".caf-constant-copy:visible");
  await details.locator("summary").first().click();
  const editor = page.getByRole("region", {
    name: "CAF block creation",
    exact: true,
  });
  await editor
    .getByRole("button", { name: "Inspect block prototype", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "source proof does not match",
  );
  await expect(
    editor.getByRole("button", { name: "Review block CAF copy", exact: true }),
  ).toHaveCount(0);
});

test("Boolean and Enum selector prototype ABA retains separate drafts and retires reviews", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New block X", { exact: true }).fill("140");
  await prepare(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_130");
  editor = await inspect(page);
  await expect(editor).toContainText("Recorded standard-name code 14");
  await editor.getByLabel("New block X", { exact: true }).fill("240");
  await prepare(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_140");
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "140",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(editor).toContainText("Six port objects");
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_130");
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "240",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(editor).toContainText("Four port objects");
});
