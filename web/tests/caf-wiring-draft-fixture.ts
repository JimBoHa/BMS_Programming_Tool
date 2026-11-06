import { python } from "./caf-simulation-fixture";
import { expect, type Page } from "@playwright/test";
import { logic } from "./caf-constant-fixture";
import { openDraftCaf } from "./caf-scalar-draft-recovery-fixture";
export function wiringFixture(kind = "rewire", keep = false, directory = "") {
  return JSON.parse(
    python(
      `
import base64,json,sys,tempfile
from tests.test_caf_graph import make_graph,REF
from tests.test_caf_wiring_drafts import selection,match
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_wiring_drafts import CafWiringDrafts
from bms_tool.storage import Store
kind=sys.argv[1];keep=sys.argv[2]=='yes';temp=tempfile.TemporaryDirectory()
directory=sys.argv[3] or temp.name
a=CafArchive(make_graph(wires=[(0,663,2,513)]) if kind=='partial' else make_graph())
row=selection(connection_count=1) if kind=='partial' else selection(rewire_source_ref=REF+'.2_11',connection_source_ref='')
service=CafWiringDrafts(Store(directory))
with service.store.connect() as db:db.execute('DELETE FROM caf_wiring_drafts')
saved=service.save(a,{'selection':row,'expected':None});checkpoint=saved['checkpoint'];status=service.status(a.hash,REF);restored=service.restore(a,match(checkpoint))
if not keep:service.remove(a.hash,match(checkpoint))
print(json.dumps({'caf':base64.b64encode(a.original).decode(),'hash':a.hash,'graph':CafGraph(a).diagram(REF),'selection':row,'saved':saved,'checkpoint':checkpoint,'status':status,'restored':restored,'token':match(checkpoint)['expected']}))
`,
      kind,
      keep ? "yes" : "no",
      directory,
    ).toString(),
  );
}
export const checkpoint = (page: Page) =>
  page.getByRole("region", { name: "Saved CAF wiring draft", exact: true });
export async function savedWiring(page: Page) {
  await logic(page);
  const tools = page.locator("details.caf-logic-export-tools");
  if ((await tools.getAttribute("open")) === null)
    await tools.locator(":scope > summary").click();
  if (!(await checkpoint(page).isVisible()))
    await page.getByText("Saved wiring draft", { exact: true }).click();
  await expect(
    checkpoint(page).getByRole("button", {
      name: "Refresh saved wiring draft",
      exact: true,
    }),
  ).toBeEnabled();
  return checkpoint(page);
}
export async function openWiring(page: Page, kind = "rewire", keep = false) {
  const f = wiringFixture(kind, keep, process.env.BMS_TEST_COMPILER_STATE!);
  await openDraftCaf(page, f.caf, "wiring-original.caf");
  await savedWiring(page);
  await expect(checkpoint(page)).toContainText(
    keep ? "Saved checkpoint revision 1" : "No wiring checkpoint is saved",
  );
  return f;
}
