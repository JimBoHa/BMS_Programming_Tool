import { python } from "./native-connection-fixture";
import { expect, type Page, type Locator } from "@playwright/test";
import { chooseWorkspaceTask } from "./workspace-navigation";

export function seed(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_terminal_recovery import setup
from bms_tool.app import create_app
storage,recovery,query,before,files,_=setup(Path(sys.argv[1]))
app=create_app(Path(sys.argv[1]));service=app.state.native_applications
source=service.input_source(capture_id=query['capture_id'],snapshot_sha256=query['snapshot_sha256'])
report=recovery.prepare(query)
parent=storage.receipt(query['receipt_id'])['intent']
output,local=service.input_copy(**report['proposal'])
import base64
print(json.dumps({'id':query['capture_id'],'parent':parent,'report':report,'source':source,'text':json.dumps(report,ensure_ascii=False),'output':base64.b64encode(output).decode()}))`,
      directory,
    ),
  );
}
export async function offline(page: Page, f: any, caf = false) {
  await page.goto("/");
  if (caf) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "terminal-recovery.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(
          python(
            "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
          ),
          "base64",
        ),
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("terminal-recovery.caf");
  } else
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
  await inputs
    .getByLabel("Input operation", { exact: true })
    .selectOption("terminal");
  await inputs
    .getByLabel("Configured native input", { exact: true })
    .selectOption("analog-input,101");
  await inputs
    .getByLabel("Field terminal destination", { exact: true })
    .selectOption("2");
  return inputs;
}
export async function prepare(inputs: Locator, parentId: string) {
  const recovery = inputs.getByLabel("Previous analog input terminal", {
    exact: true,
  });
  if ((await recovery.getAttribute("open")) === null)
    await recovery.locator(":scope > summary").click();
  await recovery
    .getByLabel("Previous-terminal transfer receipt", { exact: true })
    .selectOption(parentId);
  await recovery
    .getByRole("button", {
      name: "Prepare previous input terminal",
      exact: true,
    })
    .click();
  return recovery;
}
export async function confirm(review: Locator) {
  for (const label of [
    "Wiring, sensor mode, common and any required jumpers match this terminal.",
    "I confirm this input terminal move with unchanged mode and scaling.",
    "I confirm the application transfer and possible control restart.",
  ])
    await review.getByLabel(label, { exact: true }).check();
}
export async function apply(page: Page, inputs: Locator) {
  const review = inputs.getByRole("region", {
    name: "Input change review",
    exact: true,
  });
  await confirm(review);
  const done = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/input/apply"),
  );
  await review
    .getByRole("button", {
      name: "Apply input change to controller",
      exact: true,
    })
    .click();
  await (await done).finished();
}
