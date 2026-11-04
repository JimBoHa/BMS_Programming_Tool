import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
import { inspect, prepare } from "./caf-comparison-fixture";
export { python, logic, inspect, prepare };
export const ref = "8-1/536_4",
  prototype = ref + ".562_10";
export const kinds = [
  "two-generic",
  "two-native",
  "two-no-text",
  "four-generic",
  "four-native",
  "four-omitted",
] as const;
export function source(kind = "two-generic") {
  return python(
    "from tests.test_caf_enum_multiplexer_copy import example,mixed_example;import sys;sys.stdout.buffer.write(mixed_example() if sys.argv[1]=='mixed' else example(sys.argv[1],zero=True))",
    kind,
  );
}
export async function enter(page: Page, kind = "two-generic") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "enum-multiplexer.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-multiplexer.caf");
  await logic(page);
  if (kind === "mixed") {
    await page
      .getByLabel("Recorded block type", { exact: true })
      .selectOption("multiplexer");
    const editor = await inspect(page);
    await editor
      .getByLabel("Block prototype", { exact: true })
      .selectOption("8-1/575_1.562_150");
  }
  return inspect(page);
}
const cache: Record<string, any> = {};
export function contract(kind = "two-generic") {
  cache[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_enum_multiplexer_copy import example,REF,PROTOTYPE,packed
from bms_tool.caf import CafArchive
from bms_tool.caf_enum_multiplexer_copy import CafEnumMultiplexerCopies
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1];original=example('two-generic' if kind in ('last','unicode','wide') else kind,zero=True,second_value='4294967295' if kind=='wide' else None);ref=REF;proto=PROTOTYPE
if kind=='last':original=packed(CafArchive(original).xml.replace(b'<string>Unrelated graph metadata</string>',b'<BACoid id="2">4194297</BACoid>'))
if kind=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
c=CafEnumMultiplexerCopies(original);s=c.inspect(ref,proto);request={'source_sha256':c.archive.hash,'diagram_ref':ref,'prototype_ref':proto}
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
