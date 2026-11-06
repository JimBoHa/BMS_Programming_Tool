import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
export { chooseFile } from "./caf-native-fixture";
const root = fileURLToPath(new URL("../..", import.meta.url));
export function pythonDraft(code: string, ...args: string[]) {
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
export function seedDraft(
  directory = process.env.BMS_TEST_COMPILER_STATE!,
  keep = false,
  classless = false,
) {
  return JSON.parse(
    pythonDraft(
      `
import base64,json,sys,io,zipfile
from bms_tool.caf import CafArchive
from bms_tool.storage import Store
from bms_tool.caf_scalar_drafts import CafScalarDrafts
from tests.test_caf_scalar_drafts import source,proposals,expected
from tests.test_caf_enum_defaults import enum_caf
caf=source()
if sys.argv[3]=='classless':
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('authored.xml',caf.xml.replace(b"classid='526' ",b''))
 caf=CafArchive(output.getvalue())
store=Store(sys.argv[1]);service=CafScalarDrafts(store)
with store.connect() as db:db.execute('DELETE FROM caf_scalar_drafts')
changes=proposals();saved=service.save(caf,{'changes':changes,'expected':None})
checkpoint=saved['checkpoint'];token=expected(checkpoint)
status=service.status(caf.hash);restored=service.restore(caf,{'expected':token})
if sys.argv[2]!='keep':service.remove(caf.hash,{'expected':token})
print(json.dumps({'caf':base64.b64encode(caf.original).decode(),'hash':caf.hash,'other':base64.b64encode(enum_caf(cid='529')[0]).decode(),'changes':changes,'save':saved,'checkpoint':checkpoint,'status':status,'restored':restored,'token':token}))
`,
      directory,
      keep ? "keep" : "empty",
      classless ? "classless" : "normal",
    ),
  );
}
export const recovery = (page: Page) =>
  page.getByRole("region", { name: "Saved scalar CAF draft", exact: true });
export const review = (page: Page) =>
  page.getByRole("region", { name: "Local CAF change review", exact: true });
export async function cafObjects(page: Page) {
  await chooseWorkspaceTask(page, "Program");
  const tools = page.getByRole("navigation", {
    name: "Current task tools",
    exact: true,
  });
  const local =
    (await tools
      .getByRole("button", { name: "Local CAF file", exact: true })
      .count()) ||
    (await tools
      .getByRole("option", { name: "Local CAF file", exact: true })
      .count());
  await chooseWorkspaceTool(page, local ? "Local CAF file" : "CAF file");
  const nav = page.getByRole("navigation", {
    name: "CAF application tasks",
    exact: true,
  });
  await nav.waitFor({ state: "visible" });
  const compact = nav.getByRole("combobox");
  if (await compact.isVisible())
    await compact.selectOption({ label: "Objects & parameters" });
  else
    await nav
      .getByRole("button", { name: "Objects & parameters", exact: true })
      .click();
}
export async function editScalar(
  page: Page,
  name: string,
  property: string,
  value: string,
) {
  await cafObjects(page);
  await page
    .getByRole("button", { name: `Inspect CAF object ${name}`, exact: true })
    .click();
  await page
    .getByLabel(`CAF property ${property}`, { exact: true })
    .fill(value);
  await closeProperties(page);
}
export async function closeProperties(page: Page) {
  const close = page.getByRole("button", {
    name: "Close CAF properties",
    exact: true,
  });
  if (await close.isVisible()) await close.click();
}
export async function cafChanges(page: Page) {
  await closeProperties(page);
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "CAF changes");
  await expect(recovery(page)).toBeVisible();
  await expect(
    recovery(page).getByRole("button", {
      name: "Refresh saved scalar draft",
      exact: true,
    }),
  ).toBeEnabled();
  return recovery(page);
}
export async function openDraftCaf(
  page: Page,
  encoded: string,
  name = "unfinished.caf",
) {
  await page.goto("/");
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name,
    mimeType: "application/octet-stream",
    buffer: Buffer.from(encoded, "base64"),
  });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText(name);
}
export async function discardScalars(page: Page) {
  await cafChanges(page);
  page.once("dialog", (d) => d.accept());
  await page
    .locator(".export-strip:visible")
    .getByRole("button", { name: "Discard edits", exact: true })
    .click();
}
export function corruptDraft(hash: string) {
  pythonDraft(
    `
import sys
from bms_tool.storage import Store
with Store(sys.argv[1]).connect() as db:db.execute('UPDATE caf_scalar_drafts SET content=? WHERE caf_sha256=?',(b'altered',sys.argv[2]))
`,
    process.env.BMS_TEST_COMPILER_STATE!,
    hash,
  );
}
