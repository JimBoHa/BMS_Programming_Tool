import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve("..");
const inspector = (page: Page) => page.locator(".inspector");
const value = (page: Page) =>
  inspector(page)
    .locator("label")
    .filter({ hasText: /^\s*value/ })
    .locator("input");
const calendar = (page: Page) =>
  inspector(page).getByLabel("Calendar exception JSON", { exact: true });
const applyCalendar = (page: Page) =>
  inspector(page).getByRole("button", {
    name: "Apply calendar exceptions",
    exact: true,
  });
async function importSource(page: Page, kind = "Constant", source = "one") {
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `
import sys
from bms_tool.models import Program,Node
kind=sys.argv[1]
params={'exceptions':[],'days':[0,1,2,3,4],'opaque':{'gain':1.0,'min':-0.0}} if kind=='Schedule' else {'value':0}
p=Program(id='draft_source_'+sys.argv[2],name='Draft ownership '+sys.argv[2],nodes=[Node(id='draft_a',kind=kind,label='Draft A',params=params,x=0,y=0,value_type='boolean' if kind=='Schedule' else 'number'),Node(id='draft_b',kind=kind,label='Draft B',params=params,x=320,y=0,value_type='boolean' if kind=='Schedule' else 'number')])
print(p.model_dump_json())
`,
      kind,
      source,
    ],
    { cwd: root },
  );
  const imported = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/import") &&
      response.request().method() === "POST",
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "owned-drafts.bms.json",
      mimeType: "application/json",
      buffer,
    });
  expect((await imported).ok()).toBe(true);
  await expect(
    page.getByRole("textbox", { name: "Program name", exact: true }),
  ).toHaveValue("Draft ownership " + source);
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Imported as a new local project." }),
  ).toBeVisible();
}
async function open(page: Page, kind = "Constant", source = "one") {
  await page.goto("/");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await importSource(page, kind, source);
}
async function select(page: Page, id: string) {
  await page.locator(`.react-flow__node[data-id="${id}"]`).click();
  await expect(
    inspector(page).getByLabel("Identifier", { exact: true }),
  ).toHaveValue(id);
}
async function exportText(page: Page) {
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await download;
  return readFile((await file.path())!, "utf8");
}
async function exported(page: Page) {
  return JSON.parse(await exportText(page));
}

test("unfinished numeric text stays with its original block and never changes the other block", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  await expect(inspector(page)).toContainText("Edit not applied");
  await select(page, "draft_b");
  await expect(value(page)).toHaveValue("0");
  await expect(inspector(page)).not.toContainText("Edit not applied");
  await value(page).fill("7");
  await select(page, "draft_a");
  await expect(value(page)).toHaveValue("-");
  await expect(inspector(page)).toContainText("Edit not applied");
  const graph = await exported(page);
  expect(
    graph.nodes.find((node: any) => node.id === "draft_a").params.value,
  ).toBe(0);
  expect(
    graph.nodes.find((node: any) => node.id === "draft_b").params.value,
  ).toBe(7);
});

test("valid unapplied JSON survives task navigation without entering the program or field network", async ({
  page,
}) => {
  const fieldCalls: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/bacnet\//.test(request.url()) && request.method() === "POST")
      fieldCalls.push(request.url());
  });
  await open(page, "Schedule");
  await select(page, "draft_a");
  const pending = '[{"date":"2026-12-25","enabled":false}]';
  await calendar(page).fill(pending);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Help", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await expect(calendar(page)).toHaveValue(pending);
  await select(page, "draft_b");
  await expect(calendar(page)).toHaveValue("[]");
  const before = await exported(page);
  expect(before.nodes.map((node: any) => node.params.exceptions)).toEqual([
    [],
    [],
  ]);
  await select(page, "draft_a");
  await expect(calendar(page)).toHaveValue(pending);
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/projects") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  expect((await saved).ok()).toBe(true);
  await expect(page.locator(".validation-bar")).toContainText("r1");
  const stored = await (
    await page.request.get("/api/projects/" + before.id)
  ).json();
  expect(stored.nodes[0].params.exceptions).toEqual([]);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          JSON.parse(localStorage.getItem("bms-studio-draft-v1")!).nodes[0]
            .params.exceptions,
      ),
    )
    .toEqual([]);
  await expect(calendar(page)).toHaveValue(pending);
  await applyCalendar(page).click();
  const after = await exported(page);
  expect(after.nodes[0].params.exceptions).toEqual([
    { date: "2026-12-25", enabled: false },
  ]);
  expect(after.nodes[1].params.exceptions).toEqual([]);
  expect(fieldCalls).toEqual([]);
});

test("ordinary JSON fields retain exact tokens and owned parse errors through selection", async ({
  page,
}) => {
  await open(page, "Schedule");
  await select(page, "draft_a");
  const json = () =>
    inspector(page).getByLabel("opaque parameter JSON", { exact: true });
  const apply = () =>
    inspector(page).getByRole("button", {
      name: "Apply parameter JSON",
      exact: true,
    });
  await json().fill('{"gain":9007199254740993,"min":-0.0}');
  await select(page, "draft_b");
  await expect(json()).toContainText("1.0");
  await select(page, "draft_a");
  await expect(json()).toHaveValue('{"gain":9007199254740993,"min":-0.0}');
  await apply().click();
  const accepted = await exportText(page);
  expect(accepted).toMatch(/"gain"\s*:\s*9007199254740993/);
  expect(accepted).toMatch(/"min"\s*:\s*-0\.0/);
  await json().fill('{"gain":1,"gain":2}');
  await apply().click();
  await expect(inspector(page).locator(".inline-error")).toContainText(
    "Duplicate",
  );
  await select(page, "draft_b");
  await expect(inspector(page).locator(".inline-error")).toHaveCount(0);
  await select(page, "draft_a");
  await expect(json()).toHaveValue('{"gain":1,"gain":2}');
  await expect(inspector(page).locator(".inline-error")).toContainText(
    "Duplicate",
  );
  expect(await exportText(page)).toBe(accepted);
});

test("an unfinished number survives group selection and task navigation with its own error", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  await page
    .locator('.react-flow__node[data-id="draft_b"]')
    .click({ modifiers: ["Shift"] });
  await expect(page.locator(".react-flow__node.selected")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Draft A Constant", exact: true })
    .click();
  await expect(
    inspector(page).getByLabel("Identifier", { exact: true }),
  ).toHaveValue("draft_a");
  await expect(value(page)).toHaveValue("-");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Help", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await expect(value(page)).toHaveValue("-");
  await expect(inspector(page)).toContainText("Edit not applied");
  expect((await exported(page)).nodes[0].params.value).toBe(0);
});

test("accepted exact numeric edits retire an earlier unfinished token through undo and redo", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  await value(page).fill("-0.0");
  await expect(value(page)).toHaveValue("-0.0");
  expect(await exportText(page)).toMatch(/"value"\s*:\s*-0\.0/);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(value(page)).toHaveValue("0");
  await expect(inspector(page)).not.toContainText("Edit not applied");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(value(page)).toHaveValue("-0.0");
  await value(page).fill("1e0");
  expect(await exportText(page)).toMatch(/"value"\s*:\s*1(?:\.0|e0)/);
  await select(page, "draft_b");
  await expect(value(page)).toHaveValue("0");
  await select(page, "draft_a");
  await expect(value(page)).toHaveValue("1e0");
});

test("numeric array drafts and calendar JSON stay in separate fields and blocks", async ({
  page,
}) => {
  await open(page, "Schedule");
  await select(page, "draft_a");
  const days = () =>
    inspector(page)
      .locator("label")
      .filter({ hasText: /^\s*days/ })
      .locator("input");
  await days().fill("0,-");
  await calendar(page).fill("[");
  await applyCalendar(page).click();
  await select(page, "draft_b");
  await expect(days()).toHaveValue("0,1,2,3,4");
  await expect(calendar(page)).toHaveValue("[]");
  await select(page, "draft_a");
  await expect(days()).toHaveValue("0,-");
  await expect(calendar(page)).toHaveValue("[");
  const graph = await exported(page);
  expect(graph.nodes[0].params.days).toEqual([0, 1, 2, 3, 4]);
  expect(graph.nodes[0].params.exceptions).toEqual([]);
});

test("renaming preserves an unfinished field while changing its units retires it", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  await inspector(page)
    .getByLabel("Label", { exact: true })
    .fill("Renamed Draft A");
  await expect(value(page)).toHaveValue("-");
  await inspector(page)
    .getByLabel("Engineering units", { exact: true })
    .fill("degF");
  await expect(value(page)).toHaveValue("0");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(value(page)).toHaveValue("0");
  await expect(inspector(page)).not.toContainText("Edit not applied");
});

test("a changed graph target retires drafts even when the inspector is hidden", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  await page.getByTitle("Program settings", { exact: true }).click();
  await page
    .getByRole("combobox", { name: "Target family", exact: true })
    .selectOption("johnson-fx");
  await page.getByLabel("Close settings", { exact: true }).click();
  await expect(value(page)).toHaveValue("0");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(value(page)).toHaveValue("0");
  await expect(inspector(page)).not.toContainText("Edit not applied");
});

test("a changed accepted value retires hidden text before undo returns to its old value", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("7");
  await value(page).fill("-");
  await select(page, "draft_b");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await select(page, "draft_a");
  await expect(value(page)).toHaveValue("7");
  await expect(inspector(page)).not.toContainText("Edit not applied");
});

test("changing a parameter type retires its numeric text when the old type returns", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  await inspector(page)
    .getByRole("combobox", { name: "Value type", exact: true })
    .selectOption("boolean");
  await expect(
    inspector(page)
      .locator("label")
      .filter({ hasText: /^\s*value/ })
      .locator("input"),
  ).toHaveAttribute("type", "checkbox");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(value(page)).toHaveValue("0");
  await expect(inspector(page)).not.toContainText("Edit not applied");
});

test("importing another graph with identical node IDs never inherits its unfinished edits", async ({
  page,
}) => {
  await open(page);
  await select(page, "draft_a");
  await value(page).fill("-");
  const first = (await exported(page)).id;
  await importSource(page, "Constant", "two");
  await select(page, "draft_a");
  await expect(value(page)).toHaveValue("0");
  await expect(inspector(page)).not.toContainText("Edit not applied");
  expect((await exported(page)).id).not.toBe(first);
});

test("unapplied calendar JSON belongs to one block, including its parse error", async ({
  page,
}) => {
  await open(page, "Schedule");
  await select(page, "draft_a");
  const json = () =>
    inspector(page).getByLabel("Calendar exception JSON", { exact: true });
  await json().fill("[");
  await inspector(page)
    .getByRole("button", { name: "Apply calendar exceptions", exact: true })
    .click();
  await expect(inspector(page).locator(".inline-error")).toBeVisible();
  await select(page, "draft_b");
  await expect(json()).toHaveValue("[]");
  await expect(inspector(page).locator(".inline-error")).toHaveCount(0);
  await select(page, "draft_a");
  await expect(json()).toHaveValue("[");
  await expect(inspector(page).locator(".inline-error")).toBeVisible();
  await json().fill('[{"date":"2026-01-05","enabled":false}]');
  await inspector(page)
    .getByRole("button", { name: "Apply calendar exceptions", exact: true })
    .click();
  await expect(inspector(page).locator(".inline-error")).toHaveCount(0);
  const graph = await exported(page);
  expect(
    graph.nodes.find((node: any) => node.id === "draft_a").params.exceptions,
  ).toEqual([{ date: "2026-01-05", enabled: false }]);
  expect(
    graph.nodes.find((node: any) => node.id === "draft_b").params.exceptions,
  ).toEqual([]);
});
