import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
const root = path.resolve("..");
const records = (p: Page) =>
  p.getByRole("region", { name: "Recorded changes", exact: true });
const details = (p: Page, id: string) =>
  records(p).getByRole("button", {
    name: "Details for native " + id,
    exact: true,
  });
const evidence = (p: Page) =>
  p.getByRole("region", { name: "Change evidence", exact: true });
const point = (p: Page) =>
  p.getByRole("region", {
    name: "Recorded native point name",
    exact: true,
  });
function seed(directory: string, invalid = false) {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import asyncio,json,sys
from pathlib import Path
from tests.test_native_point_name_ledger import seed_point_name_record,authored_body
from tests.test_change_ledger import native
from bms_tool.app import create_app
row=asyncio.run(seed_point_name_record(Path(sys.argv[1])))
result={'id':row['intent']['id'],'meta':row['intent']['compilation']['selected_edit']}
if sys.argv[2]=='invalid':
 a=create_app(sys.argv[1]);body=authored_body();body['operation_profile']='future-point-name/2';intent=native(a,**body);result['invalid']=intent['id']
print(json.dumps(result))
`,
        directory,
        invalid ? "invalid" : "valid",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
        encoding: "utf8",
      },
    ),
  );
}
async function open(page: Page, caf = false, history = false) {
  await page.goto("/");
  if (caf) {
    const buffer = execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
      },
    );
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "point-name-ledger.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("point-name-ledger.caf");
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
  await expect(records(page)).toContainText("Native point-name transfer");
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
  test(`recorded point name stays local through ${caf ? "CAF" : "graph"} ${history ? "History" : "Changes"}`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const data = seed(nativeScheduleWriteServer.directory),
      calls = traffic(page);
    await open(page, caf, history);
    await details(page, data.id).click();
    await expect(point(page)).toContainText("Recorded point-name proposal");
    await expect(point(page)).toContainText(JSON.stringify(data.meta.before));
    await expect(point(page)).toContainText('"Changed input"');
    await expect(point(page)).toContainText(data.meta.object_id);
    await expect(point(page)).toContainText("No original-backup revalidation");
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
    await page.setViewportSize({ width: 390, height: 1100 });
    await point(page).scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("point-name-ledger-phone.png"),
      fullPage: true,
    });
    await expect(
      evidence(page).getByRole("button", {
        name: "Open point tools",
        exact: true,
      }),
    ).toBeDisabled();
    if (caf)
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("point-name-ledger.caf");
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(calls).toEqual([]);
  });
test("inconsistent point-name receipt keeps original JSON and withholds its tool link", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, true),
    calls = traffic(page);
  await open(page);
  await details(page, data.invalid).click();
  await expect(point(page)).toContainText("Point-name metadata unavailable");
  await expect(
    evidence(page).getByRole("button", {
      name: "Open point tools",
      exact: true,
    }),
  ).toHaveCount(0);
  const original = await request.get(
    "/api/bacnet/controller/native-application/receipts/" + data.invalid,
  );
  expect(original.ok()).toBe(true);
  expect((await original.json()).intent.operation_profile).toBe(
    "future-point-name/2",
  );
  expect(calls).toEqual([]);
});

test("point-tools link keeps the selected routed controller and does not adopt a historical target", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory),
    current = {
      address: "3002:9",
      device: "device,6001",
      router: "192.0.2.9:47808",
      dnet: 3002,
    };
  // These authored HTTP responses exercise navigation while the backend bus is closed.
  let config: any = {
    local_address: "127.0.0.1:59997",
    instance: 4190001,
    transport: "ip",
    router: null,
    dnet: null,
  };
  await page.route("**/api/bacnet/connect", (route) => {
    config = { ...route.request().postDataJSON(), transport: "ip" };
    return route.fulfill({ json: { connected: true, config, commands: [] } });
  });
  await page.route("**/api/bacnet/status", (route) =>
    route.fulfill({ json: { connected: true, config, commands: [] } }),
  );
  await page.route("**/api/bacnet/device-details", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        address: current.address,
        properties: {
          "object-identifier": current.device,
          "object-name": "Current selected controller",
          "model-name": "Authored navigation context",
        },
        finished_at: new Date().toISOString(),
      },
    }),
  );
  const inventories: any[] = [];
  await page.route("**/api/bacnet/controller/inventory", (route) => {
    const body = route.request().postDataJSON();
    inventories.push(body);
    return route.fulfill({
      json: {
        identity_verified: true,
        target: current,
        objects: [],
        errors: [],
        offset: 0,
        total: 0,
        complete: true,
        finished_at: new Date().toISOString(),
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [name, value] of [
    ["Known controller address", current.address],
    ["Known Device object", current.device],
    ["Known router", current.router],
    ["Known network", String(current.dnet)],
  ])
    await page.getByLabel(name, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Current selected controller");
  await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  await details(page, data.id).click();
  await expect(point(page)).toContainText(data.meta.object_id);
  await evidence(page)
    .getByRole("button", { name: "Open point tools", exact: true })
    .click();
  await expect(
    page.getByRole("region", {
      name: "Connected controller points",
      exact: true,
    }),
  ).toContainText("Current selected controller");
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText(current.device);
  await expect.poll(() => inventories.length).toBeGreaterThan(0);
  for (const body of inventories)
    expect({
      address: body.address,
      device: body.device,
      router: body.router,
      dnet: body.dnet,
    }).toEqual(current);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
