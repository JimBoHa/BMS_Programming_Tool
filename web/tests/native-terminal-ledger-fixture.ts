import { python } from "./native-connection-fixture";
import { expect, type Page } from "@playwright/test";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";

export function seedTerminalLedger(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys
from pathlib import Path
from tests.test_native_terminal_ledger import seed_terminal_records,terminal_body
from tests.test_native_input_ledger import authored_body
from tests.test_change_ledger import native
from bms_tool.app import create_app
from bms_tool.native_terminal_ledger import terminal_reference
from bms_tool.native_input_ledger import input_reference
p=Path(sys.argv[1]);receipt=asyncio.run(seed_terminal_records(p));app=create_app(p)
bad=terminal_body();bad['compilation']['terminal_compilation']['profile']='unsupported/2';invalid=native(app,number=201,**bad)
future=terminal_body();future['operation_profile']='native-local-universal-input-transfer/3';unknown=native(app,number=202,**future)
print(json.dumps({'id':receipt['intent']['id'],'metadata':terminal_reference(receipt['intent'])['native_terminal'],'invalid':invalid['id'],'unknown':unknown['id'],'legacy':input_reference(authored_body())['native_input']}))
`,
      directory,
    ),
  );
}
export async function openTerminalLedger(page: Page, history = false) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  if (history) {
    await chooseWorkspaceSurface(page, "History");
    const tools = page.getByRole("navigation", {
        name: "history tools",
        exact: true,
      }),
      select = tools.getByRole("combobox");
    if (await select.isVisible())
      await select.selectOption({ label: "Recorded changes" });
    else
      await tools
        .getByRole("button", { name: "Recorded changes", exact: true })
        .click();
  } else await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
}
export async function openTerminalEvidence(page: Page, id: string) {
  const records = page.getByRole("region", {
    name: "Recorded changes",
    exact: true,
  });
  await records
    .getByRole("button", { name: "Details for native " + id, exact: true })
    .click();
  const evidence = page.getByRole("region", {
    name: "Change evidence",
    exact: true,
  });
  await expect(evidence).toBeVisible();
  return evidence;
}
