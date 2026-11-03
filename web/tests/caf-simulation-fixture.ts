import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, type Page } from "@playwright/test";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
export const root = path.resolve("..");
export function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [
          process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
          root,
        ].join(path.delimiter),
      },
    },
  );
}
export function synthetic(cid = "528", cdata = false) {
  return python(
    "from tests.test_caf_enum_simulation import source;import sys;sys.stdout.buffer.write(source(cid=int(sys.argv[1]),cdata=sys.argv[2]=='yes'))",
    cid,
    cdata ? "yes" : "no",
  );
}
export const value = (page: Page, cid = "528") =>
  page.getByLabel(`Simulation value 8-1/528_4`, { exact: true });
export async function simulation(page: Page) {
  await chooseWorkspaceTask(page, "Program");
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await chooseWorkspaceTool(page, "CAF simulation inputs");
}
export async function openSimulation(
  page: Page,
  options: { cafEntry?: boolean; cid?: string; cdata?: boolean } = {},
) {
  await page.goto("/");
  const file = {
    name: "authored.caf",
    mimeType: "application/octet-stream",
    buffer: synthetic(options.cid, options.cdata),
  };
  if (options.cafEntry) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles(file);
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await simulation(page);
  if (!options.cafEntry)
    await page
      .getByLabel("Simulation CAF file", { exact: true })
      .setInputFiles(file);
  await expect(
    page.getByRole("region", { name: "Simulation file summary", exact: true }),
  ).toContainText("4 editable");
}
