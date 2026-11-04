import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
import { inspect, prepare } from "./caf-comparison-fixture";
export { python, inspect, prepare };
export const ref = "8-1/536_4",
  prototype = ref + ".560_10",
  mixedRef = "8-1/575_1",
  mixedEnum = mixedRef + ".560_80",
  mixedFloat = mixedRef + ".560_60";
export function source(kind = "enum") {
  return python(
    "from tests.test_caf_enum_comparison_copy import example,mixed_example;import sys;kind=sys.argv[1];sys.stdout.buffer.write(mixed_example() if kind=='mixed' else example(states=4 if kind=='four' else 6,encoding='matching' if kind=='matching' else 647,omitted=kind=='omitted',zero=True))",
    kind,
  );
}
export async function enter(page: Page, kind = "enum") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "comparison.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("comparison.caf");
  await logic(page);
  if (kind === "mixed") {
    await page
      .getByLabel("Recorded block type", { exact: true })
      .selectOption("comparison");
    const editor = await inspect(page);
    await editor
      .getByLabel("Block prototype", { exact: true })
      .selectOption(mixedEnum);
  }
  return inspect(page);
}
const fixtures: Record<string, any> = {};
export function contract(kind = "enum") {
  fixtures[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_enum_comparison_copy import example,REF,PROTOTYPE,packed
from bms_tool.caf import CafArchive
from bms_tool.caf_comparison_service import CafComparisonService
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1];original=example(states=4 if kind in ('four','max') else 6,encoding='matching' if kind=='matching' else 647,omitted=kind=='omitted',values=('4294967295','0') if kind=='max' else None);ref=REF;proto=PROTOTYPE
if kind=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
a=CafArchive(original);c=CafComparisonService(a);s=c.inspect(ref,proto);request={'source_sha256':a.hash,'diagram_ref':ref,'prototype_ref':proto}
proposal={**request,'selection_sha256':s['selection_sha256'],'x':'81.000','y':'42.000'};ConstantSource.model_validate(request);ConstantPreview.model_validate(proposal)
output,creation=c.compile(**{k:v for k,v in proposal.items() if k!='source_sha256'})
review={'request':proposal,'creation':creation,'controller_write':False,'field_transfer_enabled':False}
print(json.dumps({'source':s,'request':request,'proposal':proposal,'diagram':CafGraph(a).diagram(ref),'review':{**review,'review_sha256':seal(review)}}))
`,
      kind,
    ).toString(),
  );
  return structuredClone(fixtures[kind]);
}
