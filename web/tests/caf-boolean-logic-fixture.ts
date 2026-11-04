import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
import { inspect, prepare } from "./caf-comparison-fixture";
export { python, inspect, prepare };
export const ref = "8-1/536_4",
  prototype = ref + ".559_10";
export function source(kind = "small") {
  return python(
    "from tests.test_caf_boolean_logic_copy import example,mixed_example,ORDERS;import sys;kind=sys.argv[1];sys.stdout.buffer.write(mixed_example() if kind=='mixed' else example(setup=2 if kind=='or' else 3 if kind=='xor' else 1,standard=25 if kind=='or' else 26 if kind=='xor' else 24,order=ORDERS[1] if kind=='output-second' else ORDERS[2] if kind=='extra' else ORDERS[0],zero=True))",
    kind,
  );
}
export async function enter(page: Page, kind = "small") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "boolean-logic.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("boolean-logic.caf");
  await logic(page);
  if (kind === "mixed")
    await page
      .getByLabel("Recorded block type", { exact: true })
      .selectOption("booleanLogic");
  return inspect(page);
}
const fixtures: Record<string, any> = {};
export function contract(kind = "small") {
  fixtures[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_boolean_logic_copy import example,ORDERS,REF,PROTOTYPE,packed
from bms_tool.caf import CafArchive
from bms_tool.caf_boolean_logic_copy import CafBooleanLogicCopies
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1];order=ORDERS[1] if kind in ('output-second','unicode') else ORDERS[2] if kind=='extra' else ORDERS[0]
original=example(setup=2 if kind=='or' else 3 if kind=='xor' else 1,standard=25 if kind=='or' else 26 if kind=='xor' else 24,order=order);ref=REF;proto=PROTOTYPE
if kind=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
c=CafBooleanLogicCopies(original);s=c.inspect(ref,proto);request={'source_sha256':c.archive.hash,'diagram_ref':ref,'prototype_ref':proto}
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
