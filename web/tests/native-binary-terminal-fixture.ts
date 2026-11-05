import { expect, type Page } from "@playwright/test";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
export function seedBinary(directory: string) {
  return JSON.parse(
    python(
      `
import json,base64,sys
from pathlib import Path
from bms_tool.app import create_app
from tests.test_native_terminal_copies import setup
from tests.test_native_terminal_labels import observed_shape
from tests.test_native_binary_terminal import compiler,edit
_,_,files,q=setup(Path(sys.argv[1]),files=observed_shape(compressed=True))
s=create_app(Path(sys.argv[1])).state.native_applications;args={k:q[k] for k in ('capture_id','snapshot_sha256')};source=s.binary_input_source(**args);body=edit(compiler(files));output,review=s.input_copy(**args,edit=body)
print(json.dumps({'id':q['capture_id'],'source':source,'parent':s.input_source(**args),'edit':review['edit'],'text':json.dumps(review),'output':base64.b64encode(output).decode()}))
`,
      directory,
    ),
  );
}
export async function openBinary(page: Page, id: string, caf = false) {
  await page.goto("/");
  if (caf) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "binary-work.caf",
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
    ).toContainText("binary-work.caf");
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
    .selectOption(id);
  await expect(
    inputs.getByLabel("Input operation", { exact: true }),
  ).toBeVisible();
  await inputs
    .getByLabel("Input operation", { exact: true })
    .selectOption("mode");
  await inputs.getByLabel("Engineering range high", { exact: true }).fill("9.");
  const binary = inputs.getByLabel("Binary input terminal movement", {
    exact: true,
  });
  await binary.locator(":scope > summary").click();
  await expect(
    binary.getByLabel("Configured binary input", { exact: true }),
  ).toBeVisible();
  return { inputs, binary };
}
export async function binaryDraft(binary: ReturnType<Page["getByLabel"]>) {
  await binary
    .getByLabel("Configured binary input", { exact: true })
    .selectOption("binary-input,101");
  await binary
    .getByLabel("Binary terminal destination", { exact: true })
    .selectOption("3");
}

export function binaryDocuments(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys
from pathlib import Path
from contextlib import aclosing
import pytest
from tests.test_native_applications import native_link
from tests.test_native_binary_terminal_transfer import binary_peer
from tests.test_native_binary_terminal import compiler,edit
from tests.test_native_input_transfer import preview,apply
async def main():
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1]),patch)) as generator:
   link=await anext(generator);peer,service=binary_peer(link);capture,plan=await preview(link,edit(compiler(peer.files)),'binary-client-document')
   args={'capture_id':capture['id'],'snapshot_sha256':capture['snapshot_evidence_sha256']};source=service.binary_input_source(**args);parent=service.input_source(**args)
   result=await service.apply_input(**apply(plan,'binary-client-document'))
   assert result['result']['status']=='verified',result
   print(json.dumps({'source':source,'parent':parent,'edit':plan['input_edit'],'text':json.dumps(plan),'receipt':result}))
asyncio.run(main())
`,
      directory,
    ),
  );
}
