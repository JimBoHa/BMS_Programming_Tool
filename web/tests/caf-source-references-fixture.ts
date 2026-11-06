import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Locator, Page } from "@playwright/test";
export { chooseFile } from "./caf-native-fixture";
import { panel } from "./caf-native-fixture";
const root = fileURLToPath(new URL("../..", import.meta.url));

export async function compatibility(page: Page) {
  await page
    .getByRole("navigation", { name: "CAF application tasks", exact: true })
    .waitFor({ state: "visible" });
  const compact = page.getByRole("combobox", {
    name: "CAF application tasks",
    exact: true,
  });
  if (await compact.count())
    await compact.selectOption({ label: "Compatibility" });
  else
    await page
      .getByRole("navigation", { name: "CAF application tasks", exact: true })
      .getByRole("button", { name: "Compatibility", exact: true })
      .click();
  const result = panel(page),
    disclosure = result.locator(":scope > details");
  if ((await disclosure.getAttribute("open")) === null)
    await disclosure.locator(":scope > summary").click();
  return result;
}
export async function enterCafComparison(page: Page, encoded: string) {
  await page.goto("/");
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name: "authored.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(encoded, "base64"),
  });
  return compatibility(page);
}

export function pythonReference(code: string, ...args: string[]) {
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
export function seedReferences(
  directory = process.env.BMS_TEST_COMPILER_STATE!,
  router = "127.0.0.1:47919",
) {
  return JSON.parse(
    pythonReference(
      `
import base64,json,sys
from bms_tool.storage import Store
from bms_tool.bacnet_files import BacnetFiles
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.caf_native_file_correlation import NativeFileCorrelation,file_source
from bms_tool.caf_source_references import CafSourceReferences
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source,ROWS
from tests.test_caf_native_file_correlation import retained_file
store=Store(sys.argv[1]);files=BacnetFiles(None,store);applications=ApplicationStore(store)
native=retained(applications)
receipt=retained_file(files,target={'address':'3001:7'},config={'router':sys.argv[2],'dnet':3001},reuse=True)
service=CafSourceReferences(store,NativeBackupRecords(applications),NativeFileCorrelation(files))
with store.connect() as db: db.execute('DELETE FROM caf_source_references')
caf=caf_source();source=file_source(receipt)
bodies={'backup':{'source_kind':'backup','source_sha256':caf.hash,'capture_id':native['id'],'snapshot_sha256':native['evidence_sha256']},'file':{'source_kind':'file','source_sha256':caf.hash,'capture_id':receipt['id'],'receipt_sha256':source['receipt_sha256'],'file_sha256':source['sha256']}}
samples={}
for kind,body in bodies.items():
 result=service.save(caf,body);row=result['reference'];raw=service.report(caf.hash,row['id'])
 samples[kind]={'save':result,'list':service.list(caf.hash),'raw':raw.decode(),'row':row}
 service.remove(caf.hash,row['id'])
print(json.dumps({'caf':base64.b64encode(caf.original).decode(),'hash':caf.hash,'other':base64.b64encode(caf_source(model='Another model').original).decode(),'large':base64.b64encode(caf_source(rows=ROWS+[(f'controller/extra-{i}',526,100+i) for i in range(150)]).original).decode(),'backup':native['id'],'file':receipt['id'],'bodies':bodies,'samples':samples}))
`,
      directory,
      router,
    ),
  );
}
export const references = (page: Page) =>
  page.getByRole("region", {
    name: "Saved CAF/source references",
    exact: true,
  });
export async function selectReferenceSource(
  panel: Locator,
  kind: "backup" | "file",
  id: string,
) {
  await panel
    .getByLabel("Comparison source type", { exact: true })
    .selectOption(kind);
  await panel
    .getByLabel(
      kind === "backup"
        ? "Native backup for CAF comparison"
        : "Captured File for CAF comparison",
      { exact: true },
    )
    .selectOption(id);
}
export async function saveReference(page: Page) {
  await references(page)
    .getByRole("button", {
      name: "Save selected source reference",
      exact: true,
    })
    .click();
}
export function alterStoredReference(
  id: string,
  mode: "missing-source" | "corrupt-report",
) {
  return pythonReference(
    `
import sys
from bms_tool.storage import Store
from bms_tool.bacnet_files import BacnetFiles
store=Store(sys.argv[1])
if sys.argv[3]=='corrupt-report':
 with store.connect() as db: db.execute("UPDATE caf_source_references SET report=? WHERE id=?",(b'broken evidence',sys.argv[2]))
else:
 files=BacnetFiles(None,store)
 for p in files.directory.glob(sys.argv[2]+'*'): p.unlink()
`,
    process.env.BMS_TEST_COMPILER_STATE!,
    id,
    mode,
  );
}
