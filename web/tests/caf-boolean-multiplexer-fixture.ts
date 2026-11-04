import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
import { inspect, prepare } from "./caf-comparison-fixture";
export { python, logic, inspect, prepare };
export const ref = "8-1/536_4",
  prototype = ref + ".562_10";
export const sourceForms = [
  "boolean",
  ...["enum-two", "enum-five-a", "enum-five-b"].flatMap((k) =>
    ["1", "true", "0", "false"].map((v) => `${k}:${v}`),
  ),
];
export function source(kind = "boolean") {
  return python(
    "from tests.test_caf_boolean_multiplexer_copy import example,mixed_example;import sys;k,*v=sys.argv[1].split(':');sys.stdout.buffer.write(mixed_example() if k=='mixed' else example(k,value=v[0] if v else '1',zero=True))",
    kind,
  );
}
export async function enter(page: Page, kind = "boolean") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "boolean-multiplexer.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("boolean-multiplexer.caf");
  await logic(page);
  if (kind === "mixed") {
    await page
      .getByLabel("Recorded block type", { exact: true })
      .selectOption("multiplexer");
    const editor = await inspect(page);
    await editor
      .getByLabel("Block prototype", { exact: true })
      .selectOption("8-1/575_1.562_180");
  }
  return inspect(page);
}
const cache: Record<string, any> = {};
export function contract(kind = "boolean") {
  cache[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_boolean_multiplexer_copy import example,REF,PROTOTYPE,packed,compiler
from bms_tool.caf import CafArchive
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1];key,*value=kind.split(':');source_kind='enum-two' if key in ('last','unicode') else key
original=example(source_kind,value=value[0] if value else '1',zero=True);ref=REF;proto=PROTOTYPE
if key=='last':original=packed(CafArchive(original).xml.replace(b'<string>Unrelated graph metadata</string>',b'<BACoid id="2">4194297</BACoid>'))
if key=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
c=compiler(source_kind,original);s=c.inspect(ref,proto);request={'source_sha256':c.archive.hash,'diagram_ref':ref,'prototype_ref':proto}
proposal={**request,'selection_sha256':s['selection_sha256'],'x':'81.000','y':'42.000'};ConstantSource.model_validate(request);ConstantPreview.model_validate(proposal)
output,creation=c.compile(**{k:v for k,v in proposal.items() if k!='source_sha256'})
review={'request':proposal,'creation':creation,'controller_write':False,'field_transfer_enabled':False}
print(json.dumps({'source':s,'request':request,'proposal':proposal,'diagram':c.graph.diagram(ref),'review':{**review,'review_sha256':seal(review)}}))
`,
      kind,
    ).toString(),
  );
  return structuredClone(cache[kind]);
}
