import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
import { inspect, prepare } from "./caf-comparison-fixture";
export { python, inspect, prepare };
export const ref = "8-1/536_4",
  prototype = ref + ".562_10";
export function source(kind = "float") {
  return python(
    "from tests.test_caf_enum_selector_multiplexer_copy import example,mixed_example;import sys;sys.stdout.buffer.write(mixed_example() if sys.argv[1]=='mixed' else example(zero=True,spelling='100' if sys.argv[1]=='short' else '+2.50' if sys.argv[1]=='finite' else '100.000000'))",
    kind,
  );
}
export async function enter(page: Page, kind = "float") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "enum-selector.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-selector.caf");
  await logic(page);
  if (kind === "mixed") {
    await page
      .getByLabel("Recorded block type", { exact: true })
      .selectOption("multiplexer");
    const editor = await inspect(page);
    await editor
      .getByLabel("Block prototype", { exact: true })
      .selectOption("8-1/575_1.562_140");
  }
  return inspect(page);
}
const fixtures: Record<string, any> = {};
export function contract(kind = "float") {
  fixtures[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_enum_selector_multiplexer_copy import example,REF,PROTOTYPE,packed
from bms_tool.caf import CafArchive
from bms_tool.caf_enum_selector_multiplexer_copy import CafEnumSelectorMultiplexerCopies
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1]
original=example(zero=True,spelling='100' if kind=='short' else '+2.50' if kind=='finite' else '100.000000');ref=REF;proto=PROTOTYPE
if kind=='last':
 original=packed(CafArchive(original).xml.replace(b'<string>Unrelated graph metadata</string>',b'<BACoid id="2">4194295</BACoid>'))
if kind=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
c=CafEnumSelectorMultiplexerCopies(original);s=c.inspect(ref,proto);request={'source_sha256':c.archive.hash,'diagram_ref':ref,'prototype_ref':proto}
proposal={**request,'selection_sha256':s['selection_sha256'],'x':'81.000','y':'42.000'};ConstantSource.model_validate(request);ConstantPreview.model_validate(proposal)
output,creation=c.compile(**{k:v for k,v in proposal.items() if k!='source_sha256'})
review={'request':proposal,'creation':creation,'controller_write':False,'field_transfer_enabled':False}
print(json.dumps({'source':s,'request':request,'proposal':proposal,'diagram':c.graph.diagram(ref),'review':{**review,'review_sha256':seal(review)}}))
`,
      kind,
    ).toString(),
  );
  return structuredClone(fixtures[kind]);
}
