import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { logic } from "./caf-constant-fixture";
export { logic };
const root = fileURLToPath(new URL("../..", import.meta.url));
export function removalPython(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [
          process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
          root,
        ].join(path.delimiter),
      },
      encoding: "utf8",
    },
  );
}
export function removalFixture(kind = "normal", index = 0) {
  return JSON.parse(
    removalPython(
      `
import base64,json,sys
from tests.test_caf_connection_removal import removal_caf,removal_request,REF,authored_rows
from tests.test_caf_graph import pack
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_connection_removal import CafConnectionRemoval,FLAGS
from bms_tool.moi_identity import seal
kind=sys.argv[1];index=int(sys.argv[2])
wires=[] if kind=='empty' else [(0,663,2,513)] if kind=='last' else [(0,663,2,513),(0,663,2,513)] if kind=='duplicate' else [(0,663,2,513),(1,663,3,513)]
raw=removal_caf(wires=wires,version='9.0' if kind=='unsupported' else '1.0') if kind in ('empty','unsupported') else authored_rows(wires)[0]
ref=REF
if kind=='long':
 ref='8-1/575_1234567.575_2345678.575_3456789.575_1234567.575_1'
 raw=pack(CafArchive(raw).xml.replace(REF.encode(),ref.encode()))
a=CafArchive(raw);g=CafGraph(a).diagram(ref)
result={'caf':base64.b64encode(raw).decode(),'hash':a.hash,'diagram':g,'objects':len(a.objects)}
if kind not in ('empty','unsupported'):
 e=CafConnectionRemoval(raw);s=e.inspect(ref,index);r=removal_request(e,index,ref);output,removal=e.compile(**r)
 review={'profile':'caf-connection-removal-review/1','request':r,'removal':removal,**FLAGS};review['review_sha256']=seal(review)
 result.update(source=s,request=r,review=review,output=base64.b64encode(output).decode(),headers={'X-Studio-Artifact-Sha256':removal['output_sha256'],'X-Studio-Source-Sha256':a.hash,'X-Studio-Review-Sha256':review['review_sha256'],'X-Studio-Removal-Sha256':removal['removal_sha256'],'X-Studio-Request-Sha256':seal(r)})
print(json.dumps(result))
`,
      kind,
      String(index),
    ),
  );
}
export const removalPanel = (page: Page) =>
  page.getByRole("region", { name: "CAF connection removal", exact: true });
export const removalReview = (page: Page) =>
  page.getByRole("region", {
    name: "Reviewed CAF connection removal",
    exact: true,
  });
export async function showRemoval(page: Page, index?: number) {
  await logic(page);
  const graph = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  const details = graph.locator("details.caf-logic-export-tools");
  if ((await details.getAttribute("open")) === null)
    await details.locator(":scope > summary").click();
  if (index !== undefined)
    await graph
      .getByRole("button", {
        name: `Select native connection ${index}`,
        exact: true,
      })
      .click();
  const disclosure = details.locator("details").filter({
    has: page.getByRole("region", {
      name: "CAF connection removal",
      exact: true,
      includeHidden: true,
    }),
  });
  if ((await disclosure.getAttribute("open")) === null)
    await disclosure.locator(":scope > summary").click();
  await expect(removalPanel(page)).toBeVisible();
  return removalPanel(page);
}
export async function enterRemoval(
  page: Page,
  fixture = removalFixture(),
  index = 0,
) {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "authored-removal.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(fixture.caf, "base64"),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-removal.caf");
  return showRemoval(
    page,
    fixture.diagram.connections.length ? index : undefined,
  );
}
export async function reviewRemoval(page: Page) {
  await removalPanel(page)
    .getByRole("button", { name: "Review connection removal", exact: true })
    .click();
  await expect(removalReview(page)).toBeVisible();
  return removalReview(page);
}
export async function saveRemoval(page: Page) {
  const pending = page.waitForEvent("download");
  await removalReview(page)
    .getByRole("button", {
      name: "Save connection removal CAF copy",
      exact: true,
    })
    .click();
  const downloaded = await pending;
  await expect(
    removalReview(page).getByRole("button", {
      name: "Open CAF copy",
      exact: true,
    }),
  ).toBeVisible();
  return downloaded;
}
export function inspectRemoval(file: string) {
  return JSON.parse(
    removalPython(
      `from pathlib import Path
import sys,json,base64
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from tests.test_caf_connection_removal import REF
a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(REF)
print(json.dumps({'hash':a.hash,'xml':base64.b64encode(a.xml).decode(),'objects':list(a.objects),'graph':g,'comment':a.comment.decode(),'metadata':[a.info.filename,a.info.date_time,a.info.compress_type,a.info.comment.decode(),a.info.external_attr]}))`,
      file,
    ),
  );
}
