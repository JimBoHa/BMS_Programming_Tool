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
  native: boolean | "records" = false,
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
 if sys.argv[5] in ('true','records'):
  import types
  from tests.test_bacnet_files import FilePeer
  from tests.test_controller_application import authored_application
  from bacpypes3.object import FileObject,AnalogValueObject
  from bacpypes3.basetypes import DateTime
  app.payload=authored_application()
  if sys.argv[5]=='records':
   import struct
   from tests.test_controller_application import native_record,encoded
   from bacpypes3.primitivedata import CharacterString,OctetString,Real
   records=[native_record(194,4190090,[(32527,encoded(CharacterString('controller'))),(75,encoded(ObjectIdentifier(('device',4190090)))),(2390,encoded(CharacterString(sys.argv[2]))),(70,encoded(CharacterString(sys.argv[2]))),(3113,encoded(Real(23.5)))]),native_record(127,1,[(65001,encoded(OctetString(b'retained metadata')))])]
   app.payload=struct.pack('<6sHHI',bytes.fromhex('02004d4f4900'),194,1,len(records))+b''.join(struct.pack('<H',len(record)+2)+record for record in records)
  app.stream=FileObject(objectIdentifier=('file',31),objectName='Controller/Archive',description='Authored application file',fileType='.moi',fileSize=len(app.payload),modificationDate=DateTime('2026-01-05 12:00:00'),archive=False,readOnly=True,fileAccessMethod='stream-access')
  app.add_object(app.stream)
  app.device_object.configurationFiles=[app.stream.objectIdentifier]
  app.atomic_requests=[];app.all_requests=[];app.drop=False;app.mutation=None;app.callback=None
  app.do_AtomicReadFileRequest=types.MethodType(FilePeer.do_AtomicReadFileRequest,app)
  app.do_AtomicWriteFileRequest=types.MethodType(FilePeer.do_AtomicWriteFileRequest,app)
  app.do_ReinitializeDeviceRequest=types.MethodType(FilePeer.do_ReinitializeDeviceRequest,app)
  app.do_WritePropertyRequest=types.MethodType(FilePeer.do_WritePropertyRequest,app)
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

async function readRecordApplication(
  page: Page,
  endpoint: string,
  name: string,
) {
  await openController(page, endpoint, name);
  await tasks(page)
    .getByRole("button", { name: "Program", exact: true })
    .click();
  const native = page.getByRole("region", {
    name: "Native controller application",
    exact: true,
  });
  const pending = page.waitForResponse((response) =>
    response.url().endsWith("/controller/application/read"),
  );
  await native
    .getByRole("button", { name: "Read controller application", exact: true })
    .click();
  const result = await (await pending).json();
  await expect(
    native.getByLabel("Captured native record explorer", { exact: true }),
  ).toBeVisible();
  return { native, capture: result.receipt };
}

test("captured native records expose metadata, typed values and byte evidence outside diagrams", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const device = await controller("Record capture A", 0, 21, "records");
  await session(request);
  try {
    await interfaceSetup(page);
    const { native, capture } = await readRecordApplication(
      page,
      device.endpoint,
      "Record capture A",
    );
    const explorer = native.getByLabel("Captured native record explorer", {
      exact: true,
    });
    await explorer.locator(":scope > summary").click();
    const records = explorer.getByRole("table", {
      name: "Captured native records",
      exact: true,
    });
    await expect(records.getByRole("row")).toHaveCount(3);
    await expect(explorer).toContainText("2 recognized records");
    await explorer
      .getByLabel("Search captured native records", { exact: true })
      .fill("65001");
    await explorer
      .getByRole("button", { name: "Search records", exact: true })
      .click();
    await expect(records.getByRole("row")).toHaveCount(2);
    await expect(records).toContainText("metadata");
    await records
      .getByRole("button", { name: "Inspect record", exact: true })
      .click();
    const properties = explorer.getByRole("region", {
      name: "Captured native record properties",
      exact: true,
    });
    await expect(properties).toContainText("Structured or undecoded value");
    await properties
      .getByText("Encoding evidence", { exact: true })
      .last()
      .click();
    await expect(properties.locator("code").first()).toContainText(
      /^[a-f0-9]{64}$/,
    );
    await properties.getByText("Record byte evidence", { exact: true }).click();
    await expect(properties).toContainText(capture.sha256);
    await explorer
      .getByLabel("Search captured native records", { exact: true })
      .fill("Record capture A");
    await explorer
      .getByRole("button", { name: "Search records", exact: true })
      .click();
    await expect(records.getByRole("row")).toHaveCount(2);
    await records
      .getByRole("button", { name: "Inspect record", exact: true })
      .click();
    await properties
      .getByLabel("Search captured properties", { exact: true })
      .fill("3113");
    await properties
      .getByRole("button", { name: "Search properties", exact: true })
      .click();
    const values = properties.getByRole("table", {
      name: "Captured record properties",
      exact: true,
    });
    await expect(values.getByRole("row")).toHaveCount(2);
    await expect(
      values.getByRole("cell", { name: "Real", exact: true }),
    ).toBeVisible();
    await expect(
      values.getByRole("cell", { name: "23.5", exact: true }),
    ).toBeVisible();
    await expect(values.getByRole("rowheader").first()).toHaveCSS(
      "font-size",
      "14px",
    );
    await page.setViewportSize({ width: 500, height: 900 });
    expect(
      await values.evaluate(
        (element) =>
          element.parentElement!.getBoundingClientRect().right <=
          window.innerWidth,
      ),
    ).toBe(true);
    const scroll = properties.getByRole("region", {
      name: "Captured property table scroll area",
      exact: true,
    });
    await scroll.focus();
    await expect(scroll).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(() => scroll.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
    await values.screenshot({
      path: test.info().outputPath("captured-record-properties.png"),
    });
  } finally {
    device.close();
  }
});

test("a native record response cannot identify another captured file", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const device = await controller("Record source guard", 0, 21, "records");
  await session(request);
  try {
    await interfaceSetup(page);
    const { native } = await readRecordApplication(
      page,
      device.endpoint,
      "Record source guard",
    );
    await page.route(
      "**/api/bacnet/controller/application/records",
      async (route) => {
        const response = await route.fetch();
        expect(response.ok()).toBe(true);
        const body = await response.json();
        body.capture_id = "b".repeat(32);
        await route.fulfill({ response, json: body });
      },
    );
    const explorer = native.getByLabel("Captured native record explorer", {
      exact: true,
    });
    await explorer.locator(":scope > summary").click();
    await expect(explorer.getByRole("alert")).toContainText(
      "differs from the selected source or request",
    );
    await expect(explorer.getByRole("table")).toHaveCount(0);
  } finally {
    device.close();
  }
});

test("late native properties cannot return after selecting another controller with the same Device ID", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const first = await controller("Record station A", 0, 21, "records"),
    second = await controller("Record station B", 0, 21, "records");
  await session(request);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let received!: () => void;
  const captured = new Promise<void>((resolve) => {
    received = resolve;
  });
  let intercepted = false;
  try {
    await interfaceSetup(page);
    const { native } = await readRecordApplication(
      page,
      first.endpoint,
      "Record station A",
    );
    await page.route(
      "**/api/bacnet/controller/application/record",
      async (route) => {
        if (intercepted) {
          await route.continue();
          return;
        }
        intercepted = true;
        const response = await route.fetch();
        expect(response.ok()).toBe(true);
        received();
        await held;
        await route.fulfill({ response });
      },
    );
    let explorer = native.getByLabel("Captured native record explorer", {
      exact: true,
    });
    await explorer.locator(":scope > summary").click();
    const root = explorer
      .getByRole("table", { name: "Captured native records", exact: true })
      .getByRole("row")
      .filter({ hasText: "Record station A" });
    await root
      .getByRole("button", { name: "Inspect record", exact: true })
      .click();
    await captured;
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await readRecordApplication(page, second.endpoint, "Record station B");
    explorer = native.getByLabel("Captured native record explorer", {
      exact: true,
    });
    await explorer.locator(":scope > summary").click();
    await expect(
      explorer.getByRole("table", {
        name: "Captured native records",
        exact: true,
      }),
    ).toContainText("Record station B");
    const returned = page.waitForResponse((response) =>
      response.url().endsWith("/controller/application/record"),
    );
    release();
    await returned;
    await expect(
      explorer.getByRole("region", {
        name: "Captured native record properties",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(explorer).not.toContainText("Record station A");
  } finally {
    release();
    first.close();
    second.close();
  }
});
