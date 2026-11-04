import { expect, type Page } from "@playwright/test";
import { python, logic } from "./caf-constant-fixture";
export { python };
export const ref = "8-1/536_4",
  prototype = ref + ".560_10";
export function source(kind = "comparison") {
  return python(
    "from tests.test_caf_comparison_copy import example,mixed_example;import sys;sys.stdout.buffer.write(mixed_example() if sys.argv[1]=='mixed' else example(expose=sys.argv[1]!='hidden',zero=True))",
    kind,
  );
}
export async function inspect(page: Page) {
  const details = page.locator(".caf-constant-copy:visible");
  if ((await details.getAttribute("open")) === null)
    await details.locator("summary").first().click();
  const editor = page.getByRole("region", {
    name: "CAF block creation",
    exact: true,
  });
  await editor
    .getByRole("button", { name: "Inspect block prototype", exact: true })
    .click();
  await expect(editor.getByLabel("New block X", { exact: true })).toBeVisible();
  return editor;
}
export async function enter(page: Page, kind = "comparison") {
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
  }
  return await inspect(page);
}
export async function prepare(page: Page) {
  const editor = page.getByRole("region", {
    name: "CAF block creation",
    exact: true,
  });
  await editor
    .getByRole("button", { name: "Review block CAF copy", exact: true })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed CAF block copy",
    exact: true,
  });
  await expect(review).toBeVisible();
  return review;
}
const fixtures: Record<string, any> = {};
export function contract(kind = "comparison") {
  fixtures[kind] ??= JSON.parse(
    python(
      `
import json,sys,html
from tests.test_caf_comparison_copy import example,REF,PROTOTYPE,packed
from bms_tool.caf import CafArchive
from bms_tool.caf_comparison_copy import CafComparisonCopies
from bms_tool.caf_constant_api import ConstantSource,ConstantPreview
from bms_tool.moi_identity import seal
kind=sys.argv[1];original=example(expose=kind!='hidden');ref=REF;proto=PROTOTYPE
if kind=='unicode':
 new='source/'+(chr(0x1F600)*400)+'/536_4';original=packed(CafArchive(original).xml.decode().replace(ref,html.escape(new,quote=True)));proto=new+proto[len(ref):];ref=new
c=CafComparisonCopies(original);s=c.inspect(ref,proto);request={'source_sha256':c.archive.hash,'diagram_ref':ref,'prototype_ref':proto}
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
