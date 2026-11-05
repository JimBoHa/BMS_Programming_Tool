import { python } from "./native-connection-fixture";
import { expect, type Page } from "@playwright/test";
import { chooseWorkspaceTask } from "./workspace-navigation";
export function seedReanalysis(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from bms_tool.app import create_app
from tests.test_hardware_reanalysis import seed
from bms_tool.hardware_reanalysis import reanalyze_archive
w,raw,parent=seed(create_app(Path(sys.argv[1])))
child=reanalyze_archive(w,parent['id'],parent['source']['sha256'])
print(json.dumps({'parent':parent,'child':child}))
`,
      directory,
    ),
  );
}
export async function openSavedArchive(page: Page, id: string, caf = false) {
  await page.goto("/");
  if (caf) {
    const buffer = Buffer.from(
      python(
        "from tests.test_caf_graph import make_graph; import base64; print(base64.b64encode(make_graph()).decode())",
      ),
      "base64",
    );
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "reanalysis.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceTask(page, "Points & I/O");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  await expect(tools).toBeVisible();
  const select = tools.getByRole("combobox");
  if (await select.isVisible())
    await select.selectOption({ label: "Hardware survey" });
  else
    await tools
      .getByRole("button", { name: "Hardware survey", exact: true })
      .click();
  const panel = page.getByRole("region", {
    name: "Controller hardware and input survey",
    exact: true,
  });
  await panel
    .getByLabel("Configured hardware archive", { exact: true })
    .selectOption(id);
  await panel
    .getByText("Archive provenance and configured hardware", { exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Reanalyze saved archive", exact: true }),
  ).toBeEnabled();
  return panel;
}
