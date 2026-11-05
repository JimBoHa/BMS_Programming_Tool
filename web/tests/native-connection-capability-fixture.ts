import { expect, type Page, type Locator } from "@playwright/test";
import { python } from "./native-connection-fixture";
import { openNativeCompiler } from "./workspace-navigation";

export function seed(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_connection_capabilities import source,LEGACY
from tests.test_native_connection_compiler import connection_files
from tests.test_native_wire_compiler import wire_files
from tests.test_native_signal_compiler import retained
s,records,files,query=source(Path(sys.argv[1]));report=records.capabilities(query)
legacy=records.capabilities({**query,'capability_profile':LEGACY})
unknown_files=connection_files();unknown_files[11]=b'Unknown saved directory';unknown_files[12]=b'Opaque values'
unknown=retained(s,unknown_files,identity=report['identity'])
unverified=retained(s,connection_files(),identity=report['identity'],source_identity_matches=False)
full=retained(s,wire_files(),identity=report['identity'])
print(json.dumps({'id':query['capture_id'],'unknown':unknown['id'],'unverified':unverified['id'],'full':full['id'],'report':report,'legacy':legacy,'request':query,'archive':{k:report[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}}))
`,
      directory,
    ),
  );
}
export async function inspect(compiler: Locator) {
  const inspection = compiler.getByRole("region", {
    name: "Retained native backup inspection",
    exact: true,
  });
  await inspection
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  const support = inspection.getByLabel("Native backup operation support", {
    exact: true,
  });
  await expect(support).toBeVisible();
  return support;
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
  return { compiler, support: await inspect(compiler) };
}
export async function analyze(support: Locator) {
  if ((await support.getAttribute("open")) === null)
    await support.locator(":scope > summary").click();
  const table = support.getByRole("table", {
    name: "Native backup operations",
    exact: true,
  });
  await expect(table.getByRole("row")).toHaveCount(28);
  return table;
}
