import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";
import { freePort } from "./workflow-peer";

const root = path.resolve("..");
async function controller(
  name: string,
  modules: number,
  value = 21,
  native = false,
) {
  const port = await freePort();
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_controller_workspace import workspace_device
from bms_tool.bacnet_read import close_application
from bacpypes3.primitivedata import ObjectIdentifier
async def main():
 app=workspace_device(int(sys.argv[1]),model=sys.argv[2],modules=int(sys.argv[3]))
 app.device_object.objectName=sys.argv[2]
 point=app.get_object_id(ObjectIdentifier(('analog-input',1)))
 point.presentValue=float(sys.argv[4])
 if sys.argv[5]=='true':
  import types
  from tests.test_bacnet_files import FilePeer
  from tests.test_controller_application import authored_application
  from bacpypes3.object import FileObject,AnalogValueObject
  from bacpypes3.basetypes import DateTime
  app.payload=authored_application()
  app.stream=FileObject(objectIdentifier=('file',31),objectName='Controller/Archive',description='Authored application file',fileType='.moi',fileSize=len(app.payload),modificationDate=DateTime('2026-01-05 12:00:00'),archive=False,readOnly=True,fileAccessMethod='stream-access')
  app.add_object(app.stream)
  app.device_object.configurationFiles=[app.stream.objectIdentifier]
  app.atomic_requests=[];app.all_requests=[];app.drop=False;app.mutation=None;app.callback=None
  app.do_AtomicReadFileRequest=types.MethodType(FilePeer.do_AtomicReadFileRequest,app)
  for number in (10,11):
   app.add_object(AnalogValueObject(objectIdentifier=('analog-value',number),objectName=f'Native live {number}',presentValue=float(sys.argv[4]),units='degrees-celsius',statusFlags=[0,0,0,0],reliability='no-fault-detected',outOfService=False))
 print('READY',flush=True)
 def change():
  line=sys.stdin.readline()
  if line:
   point.presentValue=float(line)
   native_point=app.get_object_id(ObjectIdentifier(('analog-value',10)))
   if native_point:native_point.presentValue=float(line)
   print('CHANGED',flush=True)
 asyncio.get_running_loop().add_reader(sys.stdin.fileno(),change)
 try:await asyncio.Event().wait()
 finally:close_application(app)
asyncio.run(main())
`,
      String(port),
      name,
      String(modules),
      String(value),
      String(native),
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Controller fixture startup timed out")),
      10000,
    );
    child.stdout!.once("data", () => {
      clearTimeout(timer);
      resolve();
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (code) reject(new Error("Controller fixture exited: " + code));
    });
  });
  return {
    endpoint: `127.0.0.1:${port}`,
    change: (next: number) => child.stdin!.write(String(next) + "\n"),
    close: () => child.kill(),
  };
}
async function session(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  await request.post("/api/bacnet/disconnect", { headers, data: {} });
}
async function interfaceSetup(page: Page) {
  await page.goto("/");
  // Retain a local graph first, to ensure connecting cannot substitute it for
  // the selected controller's actual application and point inventory.
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page
    .getByLabel("Working context")
    .getByRole("button", { name: "Connect", exact: true })
    .click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Known controller address", exact: true }),
  ).toBeEnabled();
}
async function openController(page: Page, endpoint: string, name: string) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,4190090");
  await page.getByLabel("Known router", { exact: true }).fill("");
  await page.getByLabel("Known network", { exact: true }).fill("");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText(name);
}
const tasks = (page: Page) =>
  page.getByRole("navigation", { name: "Workspace tasks" });

test("a connected controller supplies actual program information, discovered points and changing live values", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const device = await controller("Unlisted family A", 5);
  await session(request);
  try {
    await interfaceSetup(page);
    await openController(page, device.endpoint, "Unlisted family A");
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    const program = page.getByRole("region", {
      name: "Connected controller application",
    });
    await expect(program).toContainText("version-only-1.2");
    await expect(program).toContainText("Actual Program 1");
    await expect(program).toContainText("running");
    await expect(page.locator(".react-flow")).toHaveCount(0);
    await expect(page.getByLabel("Working context")).not.toContainText(
      "Local graph",
    );
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    const points = page.getByRole("region", {
      name: "Connected controller points",
    });
    const row = points.getByRole("row").filter({ hasText: "analog-input,1" });
    await expect(row).toContainText("Actual input 1");
    await expect(row).toContainText("degrees-celsius");
    await expect(
      row.getByRole("cell", { name: "21", exact: true }),
    ).toBeVisible();
    await points
      .getByLabel("Controller value refresh interval")
      .selectOption("5");
    device.change(37.25);
    await expect(
      row.getByRole("cell", { name: "37.25", exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await row
      .getByRole("button", { name: "Configuration", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Actual point configuration" }),
    ).toContainText("Configured sensor 1");
    await page.screenshot({
      path: test.info().outputPath("actual-points.png"),
      fullPage: true,
    });
  } finally {
    device.close();
  }
});

test("changing controllers with the same Device ID never retains the other controller's points", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const first = await controller("Unlisted family A", 1, 21),
    second = await controller("Another family B", 7, 88);
  await session(request);
  try {
    await interfaceSetup(page);
    await openController(page, first.endpoint, "Unlisted family A");
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    await expect(
      page
        .getByRole("region", { name: "Connected controller points" })
        .getByRole("cell", { name: "21", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await openController(page, second.endpoint, "Another family B");
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    const points = page.getByRole("region", {
      name: "Connected controller points",
    });
    await expect(points).toContainText("Another family B");
    await expect(
      points
        .getByRole("row")
        .filter({ hasText: "analog-input,1" })
        .getByRole("cell", { name: "88", exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Working context")).toContainText(
      second.endpoint,
    );
  } finally {
    first.close();
    second.close();
  }
});

test("one failed point read does not starve later points and its configuration is retried", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const device = await controller("Generic retry family", 7);
  await session(request);
  let failed = false;
  await page.route("**/api/bacnet/controller/properties", async (route) => {
    const body = route.request().postDataJSON();
    if (!failed && body.object_ids?.[0] === "analog-input,1") {
      failed = true;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Temporary read failure" }),
      });
    } else await route.continue();
  });
  try {
    await interfaceSetup(page);
    await openController(page, device.endpoint, "Generic retry family");
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    const points = page.getByRole("region", {
      name: "Connected controller points",
    });
    const failedPoint = points
      .getByRole("row")
      .filter({ hasText: "analog-input,1" });
    const lastPoint = points
      .getByRole("row")
      .filter({ hasText: "analog-input,8" });
    await expect(lastPoint).toContainText("Actual input 8");
    await expect(points).toContainText("Temporary read failure");
    await expect(failedPoint).toContainText("Actual input 1", {
      timeout: 20000,
    });
    await expect(
      failedPoint.getByRole("cell", { name: "21", exact: true }),
    ).toBeVisible();
    await expect(points).not.toContainText("Temporary read failure");
    expect(failed).toBeTruthy();
  } finally {
    device.close();
  }
});

test("Program reads a controller's published native application and displays actual diagrams, configuration and live block data", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const device = await controller("Unlisted native format family", 0, 21, true);
  await session(request);
  try {
    await interfaceSetup(page);
    await openController(
      page,
      device.endpoint,
      "Unlisted native format family",
    );
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    const native = page.getByRole("region", {
      name: "Native controller application",
      exact: true,
    });
    await native
      .getByRole("button", { name: "Read controller application", exact: true })
      .click();
    await expect(native).toContainText("3 native records", { timeout: 30000 });
    await expect(native).toContainText("Controller file snapshot");
    await expect(
      native
        .getByLabel("Actual native program diagram")
        .locator(".react-flow__edge"),
    ).toHaveCount(1);
    await native
      .getByLabel("Controller program block")
      .selectOption("site/575_1.2_10");
    const config = native.getByRole("region", {
      name: "Actual native block configuration",
      exact: true,
    });
    await expect(config).toContainText("23.5");
    await expect(
      config.getByRole("definition").filter({ hasText: /^21$/ }),
    ).toBeVisible();
    device.change(33.75);
    await expect(
      config.getByRole("definition").filter({ hasText: /^33.75$/ }),
    ).toBeVisible({ timeout: 20000 });
    await expect(page.getByLabel("Working context")).not.toContainText(
      "Local graph",
    );
    await native.getByLabel("Actual native program diagram").screenshot({
      path: test.info().outputPath("native-controller-application.png"),
    });
  } finally {
    device.close();
  }
});
