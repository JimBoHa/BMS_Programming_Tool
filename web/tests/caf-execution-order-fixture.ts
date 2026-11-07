import { expect, type Page } from "@playwright/test";
import { removalPython } from "./caf-connection-removal-fixture";
import { logic } from "./caf-constant-fixture";
export { logic };
export function orderFixture(kind = "normal") {
  return JSON.parse(
    removalPython(
      `
import base64,json,sys
from tests.test_caf_graph import make_graph,pack,REF
from tests.test_caf_execution_order import order_request
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_execution_order import CafExecutionOrder,FLAGS
from bms_tool.moi_identity import seal
kind=sys.argv[1]
raw=make_graph(wires=[] if kind=='empty' else [(2,663,0,513)] if kind=='backward' else None,version='9.0' if kind=='unsupported' else '1.0')
if kind=='activity':raw=pack(CafArchive(raw).xml.replace(b'classid="575"',b'classid="536"',1))
a=CafArchive(raw);g=CafGraph(a).diagram(REF)
result=dict(caf=base64.b64encode(raw).decode(),hash=a.hash,diagram=g,objects=len(a.objects))
if kind!='unsupported':
 e=CafExecutionOrder(raw);s=e.inspect(REF);request=order_request(e);output,r=e.compile(**request)
 body=dict(profile='caf-execution-order-review/1',request=request,result=r,**FLAGS);review={**body,'review_sha256':seal(body)}
 result.update(source=s,request=request,review=review,output=base64.b64encode(output).decode(),headers={'Content-Type':'application/octet-stream','X-Studio-Artifact-Sha256':r['output_sha256'],'X-Studio-Source-Sha256':a.hash,'X-Studio-Review-Sha256':review['review_sha256'],'X-Studio-Order-Sha256':r['order_sha256'],'X-Studio-Request-Sha256':seal(request)})
print(json.dumps(result))
`,
      kind,
    ),
  );
}
export const orderPanel = (page: Page) =>
  page.getByRole("region", { name: "CAF execution order", exact: true });
export const reviewedOrder = (page: Page) =>
  page.getByRole("region", {
    name: "Reviewed CAF execution order",
    exact: true,
  });
export async function showOrder(page: Page) {
  await logic(page);
  const advanced = page.locator("details.caf-logic-export-tools");
  if ((await advanced.getAttribute("open")) === null)
    await advanced.locator(":scope > summary").click();
  const disclosure = advanced.locator("details.caf-connection-create").filter({
    has: page.getByRole("region", {
      name: "CAF execution order",
      exact: true,
      includeHidden: true,
    }),
  });
  if ((await disclosure.getAttribute("open")) === null)
    await disclosure.locator(":scope > summary").click();
  await expect(orderPanel(page)).toBeVisible();
  return orderPanel(page);
}
export async function enterOrder(
  page: Page,
  fixture = orderFixture(),
  workspace = false,
) {
  await page.goto("/");
  if (workspace)
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "authored-order.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(fixture.caf, "base64"),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-order.caf");
  return showOrder(page);
}
export async function stageOrder(page: Page) {
  await orderPanel(page)
    .getByRole("button", { name: "Move block later", exact: true })
    .click();
  await expect(orderPanel(page)).toContainText(
    "proposal has not been exported",
  );
}
export async function reviewOrder(page: Page) {
  await orderPanel(page)
    .getByRole("button", { name: "Review execution order", exact: true })
    .click();
  await expect(reviewedOrder(page)).toBeVisible();
  return reviewedOrder(page);
}
