import { python } from "./caf-simulation-fixture";
import { expect, type Page } from "@playwright/test";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
export { python };
export const ref = "8-1/575_1",
  prototype = ref + ".551_10";
export function source(standard = 11) {
  return python(
    "from tests.test_caf_constant_copy import example;import sys;sys.stdout.buffer.write(example(standard=int(sys.argv[1]),zero=True))",
    String(standard),
  );
}
export async function logic(page: Page) {
  await chooseWorkspaceTask(page, "Program");
  const tools = page.getByRole("navigation", {
    name: "Current task tools",
    exact: true,
  });
  const connected =
    (await tools
      .getByRole("button", { name: "Local CAF file", exact: true })
      .count()) ||
    (await tools
      .getByRole("option", { name: "Local CAF file", exact: true })
      .count());
  await chooseWorkspaceTool(page, connected ? "Local CAF file" : "CAF file");
  const nav = page.getByRole("navigation", {
    name: "CAF application tasks",
    exact: true,
  });
  const compact = nav.getByRole("combobox", {
    name: "CAF application tasks",
    exact: true,
  });
  if (await compact.isVisible()) await compact.selectOption({ label: "Logic" });
  else await nav.getByRole("button", { name: "Logic", exact: true }).click();
}
export async function enter(page: Page, standard = 11) {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "constant.caf",
      mimeType: "application/octet-stream",
      buffer: source(standard),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("constant.caf");
  await logic(page);
  return await inspect(page);
}
export async function inspect(page: Page) {
  const details = page.locator(".caf-constant-copy");
  if (!(await details.getAttribute("open").then((x) => x !== null)))
    await details.locator("summary").click();
  const editor = page.getByRole("region", {
    name: "CAF constant creation",
    exact: true,
  });
  await editor
    .getByRole("button", { name: "Inspect constant prototype", exact: true })
    .click();
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toBeVisible();
  return editor;
}
export async function prepare(page: Page) {
  const editor = page.getByRole("region", {
    name: "CAF constant creation",
    exact: true,
  });
  await editor
    .getByRole("button", { name: "Review constant CAF copy", exact: true })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed CAF constant copy",
    exact: true,
  });
  await expect(review).toBeVisible();
  return review;
}
export function inspectFile(file: string) {
  return JSON.parse(
    python(
      "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph;a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2]);print(json.dumps({'objects':len(a.objects),'order':g['execution_order'],'blocks':len(g['blocks']),'wires':[w['raw'] for w in g['connections']],'external_attr':a.info.external_attr,'last':g['blocks'][-1]}))",
      file,
      ref,
    ).toString(),
  );
}
