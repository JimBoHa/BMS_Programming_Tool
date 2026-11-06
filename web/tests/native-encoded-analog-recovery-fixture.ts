import { python } from "./native-connection-fixture";
import { expect, type Page, type Locator } from "@playwright/test";
import { chooseWorkspaceTask } from "./workspace-navigation";

export function seed(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_encoded_analog_recovery import setup
from bms_tool.app import create_app
storage,recovery,query,before,files,_=setup(Path(sys.argv[1]))
app=create_app(Path(sys.argv[1]));service=app.state.native_applications
source=service.encoded_analog_input_source(capture_id=query['capture_id'],snapshot_sha256=query['snapshot_sha256'])
report=recovery.prepare(query)
parent=storage.receipt(query['receipt_id'])['intent']
output,local=service.input_copy(**report['proposal'])
from bms_tool.native_encoded_analog_recovery_transfer import EncodedAnalogRecoveryPreview,recovery_origin
options=EncodedAnalogRecoveryPreview(**report['source']['target'],**report['proposal'],operation_id='authored-recovery-contract',encoded_analog_recovery_parent_receipt=parent['id'],encoded_analog_recovery_origin_sha256=report['origin_sha256'])
lineage=recovery_origin(service,options,local['compilation'])
import base64
print(json.dumps({'id':query['capture_id'],'parent':parent,'report':report,'source':source,'text':json.dumps(report,ensure_ascii=False),'lineage':lineage,'output':base64.b64encode(output).decode()}))`,
      directory,
    ),
  );
}
export async function offline(page: Page, f: any, caf = false) {
  await page.goto("/");
  if (caf)
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "analog-recovery.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(
          python(
            "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
          ),
          "base64",
        ),
      });
  else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceTask(page, "Points & I/O");
  const inputs = page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
  await inputs
    .getByLabel("Retained native input source", { exact: true })
    .selectOption(f.id);
  await inputs.getByLabel("Engineering range high", { exact: true }).fill("9.");
  const analog = inputs.getByLabel("Analog input terminal movement", {
    exact: true,
  });
  await analog.locator(":scope > summary").click();
  await expect(
    analog.getByLabel("Configured analog input", { exact: true }),
  ).toBeVisible();
  await analog
    .getByLabel("Configured analog input", { exact: true })
    .selectOption("analog-input,101");
  await analog
    .getByLabel("Analog terminal destination", { exact: true })
    .selectOption("2");
  return { inputs, analog };
}
export async function prepare(analog: Locator, parentId: string) {
  const recovery = analog.getByLabel("Previous configured analog terminal", {
    exact: true,
  });
  if ((await recovery.getAttribute("open")) === null)
    await recovery.locator(":scope > summary").click();
  await recovery
    .getByLabel("Previous configured analog transfer receipt", { exact: true })
    .selectOption(parentId);
  await recovery
    .getByRole("button", {
      name: "Prepare previous analog terminal",
      exact: true,
    })
    .click();
  return recovery;
}
