import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openNativeCompiler } from "./workspace-navigation";
import { expect, type Locator, type Page } from "@playwright/test";
import { inspect } from "./native-boolean-fixture";

const root = fileURLToPath(new URL("../..", import.meta.url));
export const ref = "controller/575_1",
  a = ref + ".2_10",
  b = ref + ".2_11",
  d = ref + ".2_13";
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
      encoding: "utf8",
    },
  );
}
export function seed(directory: string) {
  return JSON.parse(
    python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_connection_copies import NativeConnectionCopies
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_identity import sha
from tests.test_moi_connection_copies import authored
from tests.test_moi_wire_sources import REF,A,D
from tests.test_native_signal_compiler import retained
from tests.test_controller_application import encoded
from bacpypes3.primitivedata import Boolean,CharacterString
s=ApplicationStore(Store(sys.argv[1]))
def capture(**kwargs):
 data=authored(**kwargs)
 snap=retained(s,{3:data,11:b'Unknown saved selectors',12:b'Opaque saved values'},identity={'object-name':'Authored native connection controller','model-name':'UNLISTED-MODEL','vendor-identifier':5})
 return snap,data
snap,data=capture(metadata=b'\\x3e'+encoded(Boolean(True))+encoded(CharacterString('Authored continuation'))+b'\\x3f')
other,_=capture(compressed=False);empty,_=capture(empty=True)
full,_=capture(wires=[(0,85,2,7000),(1,85,3,7000)])
multi,_=capture(wires=[(0,85,2,7000),(1,85,2,7001)])
service=NativeConnectionCopies(NativeBackupRecords(s));record=MoiConnectionCopies(data).wire.reader.records[REF]
req={'capture_id':snap['id'],'snapshot_sha256':snap['evidence_sha256'],'source_sha256':sha(data),'diagram_ref':REF,'record_sha256':record['sha256'],'prototype_index':0,'source_ref':None}
src=service.source(req);sel=src['selection']
proposal={**req,'source_ref':A,'target_ref':D,'property_sha256':sel['property_sha256'],'metadata_property_sha256':sel['metadata_property_sha256'],'prototype_old':sel['prototype']['old'],'connection_count':sel['connection_count']}
out,review=service.preview(proposal)
print(json.dumps({'a':snap['id'],'other':other['id'],'empty':empty['id'],'full':full['id'],'multi':multi['id'],'source':src,'request':req,'proposal':proposal,'review':review,'archive':{k:src[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}}))
`,
      directory,
    ),
  );
}
export async function openRecord(
  page: Page,
  compiler: Locator,
  inspectFirst = true,
) {
  const records = inspectFirst
    ? (await inspect(compiler, 8)).records
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
    .selectOption("add");
  const editor = operations.getByLabel("Native matching connection copy", {
    exact: true,
  });
  if ((await editor.getAttribute("open")) === null)
    await editor.locator(":scope > summary").click();
  await editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  return { operations, editor };
}
export async function enter(page: Page, id: string) {
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
  return { compiler, ...(await openRecord(page, compiler)) };
}
export async function prepare(editor: Locator) {
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await editor
    .getByRole("button", { name: "Review native connection copy", exact: true })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed native connection copy",
    exact: true,
  });
  await expect(review).toContainText("New connection: 0, 85, 3, 7000");
  return review;
}
