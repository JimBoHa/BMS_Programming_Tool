import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
import { inspect, prepare } from "./caf-comparison-fixture";
export { python, inspect, prepare };
export const ref = "8-1/536_4",
  prototype = ref + ".558_10";
export function source(kind = "timer") {
  return python(
    "from tests.test_caf_timer_copy import example,mixed_example;import sys;kind=sys.argv[1];sys.stdout.buffer.write(mixed_example() if kind=='mixed' else example(encoding=21 if kind=='matching' else 647,mode='4' if kind in ('off','matching') else '2',duration='5' if kind=='matching' else '5.000000',zero=True))",
    kind,
  );
}
export async function enter(page: Page, kind = "timer") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "timer.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("timer.caf");
  await logic(page);
  if (kind === "mixed")
    await page
      .getByLabel("Recorded block type", { exact: true })
      .selectOption("timer");
  return inspect(page);
}
const fixtures: Record<string, any> = {};
export function contract(kind = "timer") {
  fixtures[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_timer_copy import example,REF,PROTOTYPE,packed
from bms_tool.caf import CafArchive
from bms_tool.caf_timer_copy import CafTimerCopies
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1];original=example(encoding=21 if kind=='matching' else 647,mode='4294967295' if kind=='maxmode' else '4' if kind in ('off','matching') else '2',duration='5' if kind=='matching' else '5.000000');ref=REF;proto=PROTOTYPE
if kind=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
c=CafTimerCopies(original);s=c.inspect(ref,proto);request={'source_sha256':c.archive.hash,'diagram_ref':ref,'prototype_ref':proto}
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
