import { createHash } from "node:crypto";
import { python } from "./native-connection-fixture";
import type { Page } from "@playwright/test";
import { chooseWorkspaceSurface } from "./workspace-navigation";
export const digest = (raw: Uint8Array | string) =>
  createHash("sha256").update(raw).digest("hex");
export function engineeringSource(kind = "caf") {
  const value = python(
    "from tests.jci_engineering_fixtures import caf_source,native_source,program_source;import sys,base64;k=sys.argv[1];raw=caf_source() if k=='caf' else native_source(compressed=k=='moz',partial=k=='partial') if k in ('moi','moz','partial') else program_source();print(base64.b64encode(raw).decode())",
    kind,
  );
  return Buffer.from(value.trim(), "base64");
}
export function reportFor(name = "authored.caf", kind = "caf") {
  return Buffer.from(
    python(
      "from tests.jci_engineering_fixtures import caf_source,native_source,program_source;from bms_tool.jci_source_inspection import inspect_source,encoded;import sys;k=sys.argv[2];raw=caf_source() if k=='caf' else native_source(compressed=k=='moz',partial=k=='partial') if k in ('moi','moz','partial') else program_source();sys.stdout.buffer.write(encoded(inspect_source(raw,sys.argv[1])))",
      name,
      kind,
    ),
    "utf8",
  );
}
export async function openEngineering(page: Page, visit = true) {
  if (visit) await page.goto("/");
  await chooseWorkspaceSurface(page, "Help");
  await page
    .getByText("SCT/JCT engineering sources and parity inventory", {
      exact: true,
    })
    .click();
  return page.getByRole("region", {
    name: "SCT/JCT engineering sources",
    exact: true,
  });
}
