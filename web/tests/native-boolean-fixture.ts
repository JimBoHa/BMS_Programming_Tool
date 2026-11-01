import { expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../..", import.meta.url));
export function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      encoding: "utf8",
    },
  );
}
export function seed() {
  const state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state) throw new Error("An isolated native backup state is required.");
  return JSON.parse(
    python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_boolean_copies import boolean_files
from tests.test_native_signal_compiler import retained
s=ApplicationStore(Store(sys.argv[1]));files=boolean_files()
a=retained(s,files);b=retained(s,files,target={'address':'10','router':'127.0.0.1:47919','dnet':200})
files[11]=b'Unknown saved directory';files[12]=b'Opaque saved values'
unknown=retained(s,files,source_identity_matches=False,source_identity_error='Authored identity mismatch')
print(json.dumps({'a':a['id'],'b':b['id'],'unknown':unknown['id']}))
`,
      state,
    ),
  );
}
export async function inspect(compiler: Locator, expectedRows = 12) {
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
  const records = inspection.getByLabel("Captured native record explorer", {
    exact: true,
  });
  await records.locator(":scope > summary").click();
  await expect(
    records
      .getByRole("table", { name: "Captured native records", exact: true })
      .getByRole("row"),
  ).toHaveCount(expectedRows);
  return { inspection, records };
}
export async function record(records: Locator, ref = "controller/boolean-20") {
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({ hasText: ref })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const copy = records.getByLabel("Native Boolean archive copy", {
    exact: true,
  });
  await copy.locator(":scope > summary").click();
  return copy;
}
export async function enter(page: Page, id: string, expectedRows = 12) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  const { inspection, records } = await inspect(compiler, expectedRows);
  return { compiler, inspection, records, copy: await record(records) };
}
export async function review(copy: Locator) {
  await copy
    .getByLabel("Proposed Boolean archive default", { exact: true })
    .check();
  await copy
    .getByRole("button", { name: "Review Boolean archive copy", exact: true })
    .click();
  const reviewed = copy.getByRole("region", {
    name: "Reviewed Boolean archive copy",
    exact: true,
  });
  await expect(reviewed).toContainText(
    "Original archive default false · proposed true",
  );
  return reviewed;
}
