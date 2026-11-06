import { python } from "./caf-simulation-fixture";
import { expect, type Page } from "@playwright/test";
import { logic } from "./caf-constant-fixture";
import { openDraftCaf, editScalar } from "./caf-scalar-draft-recovery-fixture";
export { logic, editScalar };
export function combinedFixture(
  kind = "rewire",
  enumValue = false,
  noop = false,
) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from tests.test_caf_combined_copy import combined_fixture
from tests.test_caf_graph import make_graph
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_combined_copy import CafCombinedCopy,FLAGS
from bms_tool.moi_identity import seal
raw,r=combined_fixture('rewire' if sys.argv[1]=='both' else sys.argv[1],enum=sys.argv[2]=='yes')
if sys.argv[1]=='both':
 raw=make_graph(wires=[(0,663,2,513),(1,663,2,513)]);r['source_sha256']=CafArchive(raw).hash
if sys.argv[3]=='noop':
 for row in r['changes']:row['value']=row['old']
 r['wiring']['source_ref']=r['changes'][0]['ref']
a=CafArchive(raw);e=CafCombinedCopy(a);s=e.inspect(**r);request={**r,'selection_sha256':s['selection_sha256']}
out,result=e.compile(**request)
review={'profile':'caf-combined-copy-review/1','request':request,'result':result,**FLAGS};review['review_sha256']=seal(review)
headers={'X-CAF-Source-SHA256':a.hash,'X-CAF-Request-SHA256':s['request_sha256'],'X-CAF-Selection-SHA256':s['selection_sha256'],'X-CAF-Review-SHA256':review['review_sha256'],'X-CAF-Combined-SHA256':result['combined_sha256'],'X-CAF-Output-SHA256':result['output_sha256']}
print(json.dumps({'caf':base64.b64encode(raw).decode(),'hash':a.hash,'diagram':CafGraph(a).diagram(r['wiring']['diagram_ref']),'request':r,'source':s,'previewRequest':request,'review':review,'output':base64.b64encode(out).decode(),'headers':headers}))
`,
      kind,
      enumValue ? "yes" : "no",
      noop ? "noop" : "edit",
    ).toString(),
  );
}
export const panel = (page: Page) =>
  page.getByRole("region", { name: "Combined CAF copy", exact: true });
export async function openCombined(
  page: Page,
  kind = "rewire",
  enumValue = false,
  value = enumValue ? "0002" : "12.5000",
) {
  const f = combinedFixture(kind, enumValue);
  await openDraftCaf(page, f.caf, "combined-example.caf");
  await editScalar(page, "Block 10", "3113", value);
  await showCombined(page, kind);
  return f;
}
export async function showCombined(
  page: Page,
  kind = "rewire",
  configure = true,
) {
  await logic(page);
  const graph = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  const tools = graph.locator("details.caf-logic-export-tools");
  if ((await tools.getAttribute("open")) === null)
    await tools.locator(":scope > summary").click();
  if (configure && (kind === "rewire" || kind === "both"))
    await graph
      .getByLabel("Native replacement source", { exact: true })
      .selectOption("8-1/575_1.2_11");
  if (configure && (kind === "connect" || kind === "both")) {
    const add = graph.locator("details").filter({
      has: page.locator(":scope > summary", {
        hasText: "Add native connection between existing blocks",
      }),
    });
    const summary = graph.getByText(
      "Add native connection between existing blocks",
      { exact: true },
    );
    if (
      !(await graph
        .getByLabel("Native new connection destination", { exact: true })
        .isVisible())
    )
      await summary.click();
    await graph
      .getByLabel("Native new connection source", { exact: true })
      .selectOption("8-1/575_1.2_11");
    await graph
      .getByLabel("Native new connection destination", { exact: true })
      .selectOption("8-1/575_1.2_13");
  }
  const combined = graph.getByText("Scalar + wiring CAF copy", { exact: true });
  if (!(await panel(page).isVisible())) await combined.click();
  await expect(panel(page)).toBeVisible();
  return panel(page);
}
