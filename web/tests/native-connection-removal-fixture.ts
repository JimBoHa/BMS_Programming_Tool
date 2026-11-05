import type { Page, Locator } from "@playwright/test";
import { expect } from "@playwright/test";
import { python, ref } from "./native-connection-fixture";
import { inspect } from "./native-boolean-fixture";
import { openNativeCompiler } from "./workspace-navigation";

export { python, ref };
export function seed(directory: string) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from pathlib import Path
from tests.test_native_connection_removal import setup,proposal,removal_files,WIRES
from bms_tool.native_connection_removal import NativeConnectionRemovals,EffectiveConnectionRemovals
p=Path(sys.argv[1]);storage,service,files,q=setup(p)
def bundle(effective):
 s=(EffectiveConnectionRemovals if effective else NativeConnectionRemovals)(service.records)
 source=s.source(q);body=proposal(s,q);output,review=s.preview(body)
 return {'source':source,'request':q,'proposal':body,'review':review,'output':base64.b64encode(output).decode(),'archive':{k:source[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}}
archive,effective=bundle(False),bundle(True)
_,_,_,other=setup(p,files=removal_files(compressed=False))
_,_,_,empty=setup(p,files=removal_files(wires=[]))
_,_,_,last=setup(p,files=removal_files(wires=WIRES[:1],metadata=False))
unknown_files=removal_files();unknown_files[11]=b'Unknown saved directory';unknown_files[12]=b'Opaque saved values'
_,_,_,unknown=setup(p,effective=False,files=unknown_files)
print(json.dumps({'id':q['capture_id'],'other':other['capture_id'],'empty':empty['capture_id'],'last':last['capture_id'],'unknown':unknown['capture_id'],'archive':archive,'effective':effective}))
`,
      directory,
    ),
  );
}
export async function openRecord(
  page: Page,
  compiler: Locator,
  effective = false,
  inspectFirst = true,
) {
  const records = inspectFirst
    ? (await inspect(compiler, 9)).records
    : compiler.getByLabel("Captured native record explorer", { exact: true });
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", { name: ref + " engineering", exact: true }),
    })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const operations = records.getByRole("region", {
    name: "Native diagram edits",
    exact: true,
  });
  await operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("remove");
  const editor = operations.getByLabel("Native connection removal", {
    exact: true,
  });
  if ((await editor.getAttribute("open")) === null)
    await editor.locator(":scope > summary").click();
  await editor
    .getByLabel("Connection removal basis", { exact: true })
    .selectOption(effective ? "effective" : "archive");
  await editor
    .getByRole("button", { name: "Open connections for removal", exact: true })
    .click();
  return { operations, editor };
}
export async function enter(page: Page, id: string, effective = false) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  return { compiler, ...(await openRecord(page, compiler, effective)) };
}
export async function prepare(editor: Locator) {
  await editor
    .getByRole("button", { name: "Review connection removal", exact: true })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed connection removal",
    exact: true,
  });
  await expect(review).toBeVisible();
  return review;
}
