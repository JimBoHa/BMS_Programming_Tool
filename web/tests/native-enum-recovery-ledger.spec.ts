import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { python } from "./native-effective-enum-fixture";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";
const records = (page: Page) =>
  page.getByRole("region", { name: "Recorded changes", exact: true });
const evidence = (page: Page) =>
  page.getByRole("region", { name: "Change evidence", exact: true });
const lineage = (page: Page) =>
  page.getByRole("region", {
    name: "Recorded native recovery lineage",
    exact: true,
  });
const details = (page: Page, id: string) =>
  records(page).getByRole("button", {
    name: "Details for native " + id,
    exact: true,
  });
function seed(directory: string, mode = "actual", routed = false) {
  return JSON.parse(
    python(
      `
import sys,json,asyncio,base64,pytest
from pathlib import Path
from bms_tool.app import create_app
from bms_tool.native_enum_recovery_ledger import enum_recovery_lineage
from tests.test_native_applications import native_link
from tests.test_native_enum_recovery_transfer import recovery_review
from tests.test_native_default_transfer import NativeRouter,apply_request
from tests.test_native_enum_recovery_ledger import recorded_child,malformed
from tests.test_caf_graph import make_graph
async def actual():
 patch=pytest.MonkeyPatch();generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator);transport=None
 try:
  _,_,_,service,target=link
  if sys.argv[3]=='routed':
   host,port=target['address'].split(':');transport,proxy=await asyncio.get_running_loop().create_datagram_endpoint(lambda:NativeRouter((host,int(port))),local_addr=('127.0.0.1',0))
   target=target|dict(address='3001:7',router=proxy.endpoint,dnet=3001)
  _,_,_,_,plan=await recovery_review(link,target=target,previous=0)
  result=await service.apply_enum_default(**apply_request(plan));assert result['result']['status']=='verified',result
  return result['intent']
 finally:
  if transport:transport.close();await asyncio.sleep(.02)
  await generator.aclose();patch.undo()
mode=sys.argv[2];app=create_app(sys.argv[1]);storage=app.state.native_applications.storage
if mode=='unavailable':body,_=recorded_child(app,lambda b:malformed(b,'extra-origin'))
else:body=asyncio.run(actual())
if mode=='missing':
 with storage.store.connect() as db:db.execute('DELETE FROM application_transfers WHERE id=?',(body['recovery_origin']['parent_receipt_id'],))
 for k in ('original_backup_id','current_capture_id'):
  p=storage.directory/body['recovery_origin'][k];p.rename(p.with_name(p.name+'-unavailable'))
record=storage.receipt(body['id']);meta=enum_recovery_lineage(body,dict(object=body['default_edit']['record_ref']))
print(json.dumps(dict(id=body['id'],parent=body['recovery_origin']['parent_receipt_id'],record=record,meta=meta,target=body['target'],caf=base64.b64encode(make_graph()).decode())))
`,
      directory,
      mode,
      routed ? "routed" : "direct",
    ),
  );
}
async function open(page: Page, data: any, caf = false, history = false) {
  await page.goto("/");
  if (caf) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "recorded-enum-recovery.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(data.caf, "base64"),
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("recorded-enum-recovery.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  if (history) {
    await chooseWorkspaceSurface(page, "History");
    const tools = page.getByRole("navigation", {
        name: "history tools",
        exact: true,
      }),
      select = tools.getByRole("combobox");
    if (await select.isVisible())
      await select.selectOption({ label: "Recorded changes" });
    else
      await tools
        .getByRole("button", { name: "Recorded changes", exact: true })
        .click();
  } else await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  await expect(details(page, data.id)).toBeVisible();
}
function traffic(page: Page) {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname.startsWith("/api/bacnet/")
    )
      calls.push(r.url());
  });
  return calls;
}
for (const variant of ["Changes", "CAF-phone", "History"]) {
  test(`recorded Enum recovery through ${variant} keeps exact historical codes, encodings and original JSON`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const data = seed(
        nativeScheduleWriteServer.directory,
        "actual",
        variant === "CAF-phone",
      ),
      calls = traffic(page);
    if (variant === "CAF-phone")
      await page.setViewportSize({ width: 390, height: 1000 });
    await open(page, data, variant === "CAF-phone", variant === "History");
    await expect(records(page)).toContainText("Previous Enum code recovery");
    await details(page, data.id).click();
    await expect(lineage(page)).toContainText("Recorded Enum code proposal");
    await expect(lineage(page)).toContainText("65535 to 0");
    await expect(lineage(page)).toContainText("9200002f");
    await expect(lineage(page)).toContainText("91002f");
    await expect(lineage(page)).toContainText("does not revalidate");
    await expect(lineage(page)).toContainText("Code meanings");
    await expect(evidence(page)).toContainText(data.target.address);
    if (variant === "CAF-phone")
      await expect(evidence(page)).toContainText(data.target.router);
    const original = await request.get(
      "/api/bacnet/controller/native-application/receipts/" + data.id,
    );
    const download = page.waitForEvent("download");
    await evidence(page)
      .getByRole("button", { name: "Download evidence JSON", exact: true })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(
      await original.body(),
    );
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(calls).toEqual([]);
    await lineage(page).scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("recorded-enum-recovery.png"),
      fullPage: true,
    });
    await lineage(page)
      .getByRole("button", {
        name: "Search recorded parent receipt",
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Search recorded changes", { exact: true }),
    ).toHaveValue(data.parent);
    await expect(details(page, data.parent)).toBeVisible();
    await details(page, data.parent).click();
    await expect(lineage(page)).toHaveCount(0);
    expect(calls).toEqual([]);
  });
}
test("missing parent and source files do not turn recorded references into availability or field authority", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, "missing"),
    calls = traffic(page);
  await open(page, data);
  await details(page, data.id).click();
  await expect(lineage(page)).toContainText(data.parent);
  await expect(lineage(page)).toContainText("does not revalidate");
  await lineage(page)
    .getByRole("button", {
      name: "Search recorded parent receipt",
      exact: true,
    })
    .click();
  await expect(details(page, data.id)).toBeVisible();
  await expect(details(page, data.parent)).toHaveCount(0);
  expect(calls).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
for (const mode of ["unavailable", "substituted-width", "substituted-type"]) {
  test(`${mode} Enum lineage is unavailable while original child JSON remains readable`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(
        nativeScheduleWriteServer.directory,
        mode === "unavailable" ? mode : "actual",
      ),
      calls = traffic(page);
    if (mode !== "unavailable")
      await page.route("**/api/changes/query", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          body = await response.json();
        for (const row of body.rows)
          if (row.id === data.id) {
            if (mode === "substituted-width")
              row.native_recovery.after_encoding_hex = "91002f";
            else row.native_recovery.after_value = false;
          }
        await route.fulfill({ response, json: body });
      });
    await open(page, data);
    await details(page, data.id).click();
    await expect(lineage(page)).toContainText(
      "Recorded Enum recovery metadata is incomplete or inconsistent",
    );
    await expect(
      lineage(page).getByRole("button", {
        name: "Search recorded parent receipt",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      await (
        await request.get(
          "/api/bacnet/controller/native-application/receipts/" + data.id,
        )
      ).json(),
    ).toEqual(data.record);
    expect(calls).toEqual([]);
  });
}
test("late recorded Enum parent query cannot revive retired selection after navigation", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory),
    calls = traffic(page);
  await open(page, data);
  await details(page, data.id).click();
  let release = () => {},
    entered = () => {};
  const gate = new Promise<void>((r) => (release = r)),
    seen = new Promise<void>((r) => (entered = r));
  await page.route("**/api/changes/query", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    entered();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await lineage(page)
      .getByRole("button", {
        name: "Search recorded parent receipt",
        exact: true,
      })
      .click();
    await seen;
    await chooseWorkspaceTask(page, "Program");
    const response = page.waitForResponse((r) =>
      r.url().endsWith("/api/changes/query"),
    );
    release();
    await (await response).finished();
    await page.unroute("**/api/changes/query");
    await chooseWorkspaceTask(page, "Changes");
    await expect(lineage(page)).toHaveCount(0);
    expect(calls).toEqual([]);
  } finally {
    release();
  }
});
