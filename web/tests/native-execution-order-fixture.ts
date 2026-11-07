import { expect, type Page, type Locator } from "@playwright/test";
import { python } from "./native-connection-fixture";
import { inspect } from "./native-boolean-fixture";
import { openNativeCompiler } from "./workspace-navigation";
export { python };
const immutableFixtures = new Map<string, any>();
export function orderFixture(directory: string, kind = "normal") {
  const key = JSON.stringify([directory, kind]);
  if (immutableFixtures.has(key))
    return structuredClone(immutableFixtures.get(key));
  const fixture = JSON.parse(
    python(
      `
from pathlib import Path
import base64,json,sys
from tests.test_native_execution_order import setup,proposal
from tests.test_native_wire_compiler import wire_files
from tests.test_native_signal_compiler import retained
from tests.test_caf_graph import make_graph
kind=sys.argv[2];files=wire_files(compressed=kind!='raw',diagram_class=536 if kind=='activity' else 575,wires=[] if kind=='empty' else [(2,85,0,7000)] if kind=='backward' else None)
metadata=dict(connector_config={'transport':'mstp','serial_port':'/dev/authored'},target={'address':'7','router':None,'dnet':None}) if kind=='serial' else {}
storage,service,snapshot,q=setup(Path(sys.argv[1]),files,**metadata)
report=service.source(q);request=proposal(service,q,[0,1,2,3] if kind=='noop' else [1,0,2,3]);output,review=service.preview(request)
other=retained(storage,files,identity=report['identity'])
unknown=dict(files);unknown[11]=b'Unknown saved directory';unknown[12]=b'Opaque saved bytes';bad=retained(storage,unknown,identity=report['identity'])
result=dict(id=snapshot['id'],other=other['id'],unknown=bad['id'],query=q,source=report,request=request,review=review,archive={k:report[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')},record=dict(ref=q['diagram_ref'],record_sha256=q['record_sha256'],class_id=536 if kind=='activity' else 575),output=base64.b64encode(output).decode(),caf=base64.b64encode(make_graph()).decode(),headers={'Content-Type':'application/octet-stream','X-Studio-Artifact-Sha256':review['output_sha256'],'X-Studio-Review-Sha256':review['review_sha256'],'X-Studio-Source-Sha256':q['source_sha256'],'X-Studio-Snapshot-Sha256':q['snapshot_sha256'],'X-Studio-Compilation-Sha256':review['compilation']['compilation_sha256']})
print(json.dumps(result))
`,
      directory,
      kind,
    ),
  );
  immutableFixtures.set(key, fixture);
  return structuredClone(fixture);
}
export const nativeOrderPanel = (page: Page) =>
  page.getByLabel("Native execution-order compilation", { exact: true });
export const nativeOrderReview = (page: Page) =>
  page.getByRole("region", {
    name: "Reviewed native execution-order compilation",
    exact: true,
  });
export async function openOrder(page: Page, compiler: Locator) {
  const { records } = await inspect(compiler, 9);
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", {
        name: "controller/575_1 engineering",
        exact: true,
      }),
    })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const operations = records.getByRole("region", {
    name: "Native diagram edits",
    exact: true,
  });
  await operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("order");
  const panel = nativeOrderPanel(page);
  if ((await panel.getAttribute("open")) === null)
    await panel.locator(":scope > summary").click();
  await panel
    .getByRole("button", {
      name: "Inspect effective execution order",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("table", {
      name: "Proposed native execution order",
      exact: true,
    }),
  ).toBeVisible();
  return { compiler, records, operations, panel };
}
export async function enterOrder(page: Page, f: any, caf = false) {
  await page.goto("/");
  if (caf)
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "authored-native-order.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(f.caf, "base64"),
      });
  else
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
    .selectOption(f.id);
  return openOrder(page, compiler);
}
export async function stageOrder(page: Page) {
  await nativeOrderPanel(page)
    .getByRole("button", { name: "Move native block later", exact: true })
    .click();
  await expect(nativeOrderPanel(page)).toContainText(
    "proposal has not been exported",
  );
}
export async function reviewOrder(page: Page) {
  await nativeOrderPanel(page)
    .getByRole("button", {
      name: "Review native execution-order compilation",
      exact: true,
    })
    .click();
  await expect(nativeOrderReview(page)).toBeVisible();
  return nativeOrderReview(page);
}
