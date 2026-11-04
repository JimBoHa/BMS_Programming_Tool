import { expect, type Page, type Locator } from "@playwright/test";
import { python, ref, d } from "./native-connection-fixture";
import { openNativeCompiler } from "./workspace-navigation";
import { inspect } from "./native-boolean-fixture";

export function seed(directory: string) {
  return JSON.parse(
    python(
      `
import json,sys,struct
from pathlib import Path
from tests.test_native_connection_compiler import setup,proposal,connection_files
from tests.test_native_signal_compiler import retained
from bms_tool.mstp import header_crc
s,service,files,q=setup(Path(sys.argv[1]));source=service.source(q);p=proposal(service,q);out,review=service.preview(p)
other=retained(s,connection_files(compressed=False),identity=source['identity'])
unknown_files=connection_files();unknown_files[11]=b'Unknown saved directory';unknown_files[12]=b'Opaque values'
unknown=retained(s,unknown_files,identity=source['identity'])
changed_files=connection_files();value=struct.pack('>f',43.5)
changed_files[12]=value+bytes([header_crc(value)^255])+changed_files[12][5:]
changed=retained(s,changed_files,identity=source['identity'])
print(json.dumps({'id':q['capture_id'],'other':other['id'],'unknown':unknown['id'],'changed':changed['id'],'source':source,'request':q,'proposal':p,'review':review,'archive':{k:source[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}}))
`,
      directory,
    ),
  );
}
export async function openRecord(page: Page, compiler: Locator, saved = true) {
  const { records } = await inspect(compiler, 9);
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
    .getByLabel("Native connection basis", { exact: true })
    .selectOption(saved ? "effective" : "archive");
  await editor
    .getByRole("button", {
      name: saved
        ? "Open saved connection candidates"
        : "Open native connection candidates",
      exact: true,
    })
    .click();
  return { operations, editor };
}
export async function enter(page: Page, id: string, saved = true) {
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
  return { compiler, ...(await openRecord(page, compiler, saved)) };
}
export async function prepare(editor: Locator) {
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await editor
    .getByRole("button", {
      name: "Review saved connection compilation",
      exact: true,
    })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed saved connection compilation",
    exact: true,
  });
  await expect(review).toContainText("New connection: 0, 85, 3, 7000");
  return review;
}
