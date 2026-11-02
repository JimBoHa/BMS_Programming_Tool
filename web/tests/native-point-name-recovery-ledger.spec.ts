import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { python } from "./caf-native-fixture";
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
    name: "Recorded point name recovery lineage",
    exact: true,
  });
const details = (page: Page, id: string) =>
  records(page).getByRole("button", {
    name: "Details for native " + id,
    exact: true,
  });
function seed(directory: string, mode = "actual") {
  return JSON.parse(
    python(
      `
import sys,json,asyncio,base64
from pathlib import Path
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_point_name_ledger import point_name_reference
from bms_tool.native_point_name_recovery_ledger import point_name_recovery_reference
from tests.test_native_point_name_recovery_ledger import seed_recovery_record,authored_body
from tests.test_change_ledger import native
from tests.test_caf_graph import make_graph
directory=Path(sys.argv[1]);mode=sys.argv[2]
if mode=='actual':record=asyncio.run(seed_recovery_record(directory));body=record['intent']
else:
 body=authored_body(directory/'authoring')
 if mode=='unavailable':body['recovery_origin']['profile']='future/2';body['recovery_origin_sha256']=seal(body['recovery_origin'])
 app=create_app(directory);body=native(app,**body);record=app.state.native_applications.storage.receipt(body['id'])
meta=point_name_recovery_reference(body,point_name_reference(body).get('native_point_name'))['native_point_name_recovery']
print(json.dumps({'id':body['id'],'parent':body['recovery_origin']['parent_receipt_id'],'record':record,'meta':meta,'caf':base64.b64encode(make_graph()).decode()}))
`,
      directory,
      mode,
    ),
  );
}
async function open(page: Page, data: any, caf = false, history = false) {
  await page.goto("/");
  if (caf) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "recorded-recovery.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(data.caf, "base64"),
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("recorded-recovery.caf");
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

for (const [caf, history] of [
  [false, false],
  [true, false],
  [false, true],
])
  test(`recorded recovery stays local through ${caf ? "CAF" : "graph"} ${history ? "History" : "Changes"}`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const data = seed(nativeScheduleWriteServer.directory),
      calls = traffic(page);
    await open(page, data, caf, history);
    await details(page, data.id).click();
    await expect(lineage(page)).toContainText(
      "Recorded previous point-name proposal",
    );
    await expect(lineage(page)).toContainText('"Changed input"');
    await expect(lineage(page)).toContainText('"Authored input"');
    await expect(lineage(page)).toContainText(data.parent);
    await expect(lineage(page)).toContainText(
      "availability, current point names and transfer authority are not established",
    );
    const original = await request.get(
      "/api/bacnet/controller/native-application/receipts/" + data.id,
    );
    const downloading = page.waitForEvent("download");
    await evidence(page)
      .getByRole("button", { name: "Download evidence JSON", exact: true })
      .click();
    expect(readFileSync((await (await downloading).path())!)).toEqual(
      await original.body(),
    );
    await page.setViewportSize({ width: 390, height: 1000 });
    await lineage(page).scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("recorded-point-recovery-phone.png"),
      fullPage: true,
    });
    await lineage(page)
      .getByRole("button", {
        name: "Search recorded point-name parent receipt",
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Search recorded changes", { exact: true }),
    ).toHaveValue(data.parent);
    await expect(details(page, data.parent)).toBeVisible();
    await details(page, data.parent).click();
    await expect(lineage(page)).toHaveCount(0);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(calls).toEqual([]);
  });

test("recorded references do not assert parent or original-backup availability", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, "recorded-only"),
    calls = traffic(page);
  await open(page, data);
  await details(page, data.id).click();
  await expect(lineage(page)).toContainText("not established");
  await lineage(page)
    .getByRole("button", {
      name: "Search recorded point-name parent receipt",
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

test("unknown origin metadata stays unavailable while original JSON remains readable", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, "unavailable");
  await open(page, data);
  await details(page, data.id).click();
  await expect(lineage(page)).toContainText(
    "Point-name recovery metadata unavailable",
  );
  await expect(
    lineage(page).getByRole("button", {
      name: "Search recorded point-name parent receipt",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(
    (
      await (
        await request.get(
          "/api/bacnet/controller/native-application/receipts/" + data.id,
        )
      ).json()
    ).intent.recovery_origin.profile,
  ).toBe("future/2");
});

test("browser independently rejects substituted recorded name bindings", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory);
  await page.route("**/api/changes/query", async (route) => {
    const response = await route.fetch(),
      body = await response.json();
    for (const row of body.rows)
      if (row.id === data.id)
        row.native_point_name_recovery.after = "Substituted name";
    await route.fulfill({ response, json: body });
  });
  await open(page, data);
  await details(page, data.id).click();
  await expect(lineage(page)).toContainText(
    "Point-name recovery metadata unavailable",
  );
  await expect(
    lineage(page).getByRole("button", {
      name: "Search recorded point-name parent receipt",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("late parent search cannot revive a retired selected recovery", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory);
  await open(page, data);
  await details(page, data.id).click();
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (seen = r));
  await page.route("**/api/changes/query", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
  });
  await lineage(page)
    .getByRole("button", {
      name: "Search recorded point-name parent receipt",
      exact: true,
    })
    .click();
  await entered;
  await chooseWorkspaceTask(page, "Program");
  const settled = page.waitForResponse((r) =>
    r.url().endsWith("/api/changes/query"),
  );
  release();
  await (await settled).finished();
  await page.unroute("**/api/changes/query");
  await chooseWorkspaceTask(page, "Changes");
  await expect(lineage(page)).toHaveCount(0);
});
