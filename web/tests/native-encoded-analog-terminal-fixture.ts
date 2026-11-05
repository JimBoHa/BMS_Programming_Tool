import { expect, type Page } from "@playwright/test";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
export function seedEncodedAnalog(directory: string) {
  return JSON.parse(
    python(
      `
import json,base64,sys
from pathlib import Path
from bms_tool.app import create_app
from tests.test_native_terminal_copies import setup
from tests.test_native_terminal_labels import observed_shape
from bms_tool.native_inputs import NativeInputCompiler
from tests.test_native_encoded_terminal_input import edit,nonlinear
compiler=NativeInputCompiler
_,_,files,q=setup(Path(sys.argv[1]),files=nonlinear(observed_shape(binary=False,compressed=True)))
s=create_app(Path(sys.argv[1])).state.native_applications;args={k:q[k] for k in ('capture_id','snapshot_sha256')};source=s.encoded_analog_input_source(**args);body=edit(compiler(files));output,review=s.input_copy(**args,edit=body)
print(json.dumps({'id':q['capture_id'],'source':source,'parent':s.input_source(**args),'edit':review['edit'],'text':json.dumps(review),'output':base64.b64encode(output).decode()}))
`,
      directory,
    ),
  );
}
export async function openEncodedAnalog(page: Page, id: string, caf = false) {
  await page.goto("/");
  if (caf) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "analog-work.caf",
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
    ).toContainText("analog-work.caf");
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
  const analog = inputs.getByLabel("Analog input terminal movement", {
    exact: true,
  });
  await analog.locator(":scope > summary").click();
  await expect(
    analog.getByLabel("Configured analog input", { exact: true }),
  ).toBeVisible();
  return { inputs, analog };
}
export async function encodedAnalogDraft(
  analog: ReturnType<Page["getByLabel"]>,
) {
  await analog
    .getByLabel("Configured analog input", { exact: true })
    .selectOption("analog-input,101");
  await analog
    .getByLabel("Analog terminal destination", { exact: true })
    .selectOption("3");
}

export function encodedAnalogDocuments(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys
from pathlib import Path
from contextlib import aclosing
import pytest
from tests.test_native_applications import native_link
from tests.test_native_encoded_terminal_transfer import peer_for as analog_peer
from bms_tool.native_inputs import NativeInputCompiler
from tests.test_native_encoded_terminal_input import edit,nonlinear
compiler=NativeInputCompiler
from tests.test_native_input_transfer import preview,apply
async def main():
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1]),patch)) as generator:
   link=await anext(generator);peer,service=analog_peer(link,True);capture,plan=await preview(link,edit(compiler(peer.files)),'analog-client-document')
   args={'capture_id':capture['id'],'snapshot_sha256':capture['snapshot_evidence_sha256']};source=service.encoded_analog_input_source(**args);parent=service.input_source(**args)
   result=await service.apply_input(**apply(plan,'analog-client-document'))
   assert result['result']['status']=='verified',result
   print(json.dumps({'source':source,'parent':parent,'edit':plan['input_edit'],'text':json.dumps(plan),'receipt':result}))
asyncio.run(main())
`,
      directory,
    ),
  );
}
