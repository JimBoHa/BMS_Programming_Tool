import { expect, type Locator, type Page } from "@playwright/test";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

export function seedTerminals(directory: string) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from pathlib import Path
from tests.test_native_terminal_copies import setup,proposal
from tests.test_moi_terminal_copies import authored
from bms_tool.native_terminal_copies import NativeTerminalCopies,EffectiveNativeTerminalCopies
p=Path(sys.argv[1]);storage,service,files,q=setup(p)
def bundle(effective):
 s=(EffectiveNativeTerminalCopies if effective else NativeTerminalCopies)(service.records)
 source=s.source(q);body=proposal(s,q);output,review=s.preview(body)
 return {'source':source,'query':q,'proposal':body,'review':review,'output':base64.b64encode(output).decode(),'archive':{k:source[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}}
archive,effective=bundle(False),bundle(True)
_,_,_,binary=setup(p,files=authored(binary=True))
unknown_files=authored();unknown_files[11]=b'Unknown directory';unknown_files[12]=b'Opaque values'
_,_,_,unknown=setup(p,files=unknown_files)
print(json.dumps({'id':q['capture_id'],'binary':binary['capture_id'],'unknown':unknown['capture_id'],'archive':archive,'effective':effective}))
`,
      directory,
    ),
  );
}

export async function enterTerminals(
  page: Page,
  id: string,
  effective = false,
) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await chooseWorkspaceTask(page, "Points & I/O");
  const editor = page.getByLabel("Local native terminal reassignment", {
    exact: true,
  });
  await editor.locator(":scope > summary").click();
  await editor
    .getByLabel("Captured terminal source", { exact: true })
    .selectOption(id);
  if (effective)
    await editor
      .getByLabel("Terminal copy basis", { exact: true })
      .selectOption("effective");
  await expect(
    editor.getByLabel("Input to reassign", { exact: true }),
  ).toBeVisible();
  return editor;
}
export async function draftTerminal(editor: Locator) {
  await editor
    .getByLabel("Input to reassign", { exact: true })
    .selectOption("controller/0_101");
  await editor
    .getByLabel("Destination universal terminal", { exact: true })
    .selectOption("3");
}
export async function reviewTerminal(editor: Locator) {
  await editor
    .getByRole("button", { name: "Review local terminal copy", exact: true })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed local terminal copy",
    exact: true,
  });
  await expect(review).toBeVisible();
  return review;
}
