import { expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { openNativeCompiler } from "./workspace-navigation";

const root = path.resolve("..");
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
import base64,json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_enum_compiler import EffectiveEnumService
from tests.test_moi_effective_enum import enum_files
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]));a=retained(s,enum_files())
b=retained(s,enum_files(cid=529,compressed=False,saved=7),target={'address':'10','router':'127.0.0.1:47919','dnet':200},connector_config={'transport':'mstp','serial_port':'/dev/authored-only'})
unverified=retained(s,enum_files(),source_identity_matches=False,source_identity_error='Authored incomplete identity')
files=enum_files();files[11]=b'Unknown directory';files[12]=b'Opaque saved values';unknown=retained(s,files)
service=EffectiveEnumService(NativeBackupRecords(s));source=service.source({'capture_id':a['id'],'snapshot_sha256':a['evidence_sha256']});field=source['fields'][0]
body={'capture_id':a['id'],'snapshot_sha256':a['evidence_sha256'],'source_sha256':source['source_sha256'],'record_ref':field['ref'],'encoded_sha256':field['encoded_sha256'],'value':65535}
_,review=service.preview(body)
print(json.dumps({'a':a['id'],'b':b['id'],'unverified':unverified['id'],'unknown':unknown['id'],'caf':base64.b64encode(caf_source().original).decode(),'source':source,'review':review,'request':body}))
`,
      directory,
    ),
  );
}
export async function inspect(compiler: Locator) {
  await compiler
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  const records = compiler.getByLabel("Captured native record explorer", {
    exact: true,
  });
  await records.locator(":scope > summary").click();
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({ hasText: "controller/enum-1" })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  return records;
}
export async function effective(compiler: Locator) {
  await compiler
    .getByLabel("Enum default source", { exact: true })
    .selectOption("effective");
  return compiler.getByRole("region", {
    name: "Effective native Enum compiler",
    exact: true,
  });
}
export async function enter(page: Page, ids: any, variant = "a", caf = false) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "enum-compiler.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(ids.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("enum-compiler.caf");
  } else
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
    .selectOption(ids[variant]);
  const records = await inspect(compiler),
    panel = await effective(compiler);
  return { compiler, records, panel };
}
export async function load(panel: Locator, value = "513") {
  await panel
    .getByRole("button", { name: "Open saved Enum defaults", exact: true })
    .click();
  await expect(
    panel.getByLabel("Proposed effective Enum code", { exact: true }),
  ).toHaveValue(value);
}
export async function prepare(panel: Locator, value = "65535") {
  await panel
    .getByLabel("Proposed effective Enum code", { exact: true })
    .fill(value);
  await panel
    .getByRole("button", { name: "Review effective Enum copy", exact: true })
    .click();
  const reviewed = panel.getByRole("region", {
    name: "Reviewed effective Enum copy",
    exact: true,
  });
  await expect(reviewed).toContainText(`copy code ${Number(value)}`);
  return reviewed;
}
