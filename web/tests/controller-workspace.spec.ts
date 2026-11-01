import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { freePort } from "./workflow-peer";

const root = path.resolve("..");
async function controller(
  name: string,
  modules: number,
  value = 21,
  native: boolean | "signal-default" | "identity" | "moz" | "records" = false,
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
 app=workspace_device(int(sys.argv[1]),model=sys.argv[2],modules=int(sys.argv[3]),vendor=5 if sys.argv[5]=='identity' else 999)
 app.device_object.objectName=sys.argv[2]
 point=app.get_object_id(ObjectIdentifier(('analog-input',1)))
 point.presentValue=float(sys.argv[4])
 if sys.argv[5] in ('true','signal-default','identity','moz','records'):
  import types
  from tests.test_bacnet_files import FilePeer
  from tests.test_controller_application import authored_application
  from bacpypes3.object import FileObject,AnalogValueObject
  from bacpypes3.basetypes import DateTime
  app.payload=authored_application()
  if sys.argv[5]=='signal-default':
   from tests.test_moi_signal_defaults import source
   app.payload=source(compressed=True)
  elif sys.argv[5]=='identity':
   import struct
   from tests.test_controller_application import native_record,encoded
   from bacpypes3.primitivedata import CharacterString,Unsigned
   record=native_record(194,4190090,[(32527,encoded(CharacterString('controller'))),(75,encoded(ObjectIdentifier(('device',4190090)))),(2390,encoded(CharacterString(sys.argv[2]))),(70,encoded(CharacterString(sys.argv[2]))),(4128,encoded(Unsigned(62))),(4129,encoded(Unsigned(62)))])
   app.payload=struct.pack('<6sHHI',bytes.fromhex('02004d4f4900'),194,1,1)+struct.pack('<H',len(record)+2)+record
  elif sys.argv[5]=='records':
   import struct
   from tests.test_controller_application import native_record,encoded
   from bacpypes3.primitivedata import CharacterString,OctetString,Real
   records=[native_record(194,4190090,[(32527,encoded(CharacterString('controller'))),(75,encoded(ObjectIdentifier(('device',4190090)))),(2390,encoded(CharacterString(sys.argv[2]))),(70,encoded(CharacterString(sys.argv[2]))),(3113,encoded(Real(23.5)))]),native_record(127,1,[(65001,encoded(OctetString(b'retained metadata')))])]
   app.payload=struct.pack('<6sHHI',bytes.fromhex('02004d4f4900'),194,1,len(records))+b''.join(struct.pack('<H',len(record)+2)+record for record in records)
  app.stream=FileObject(objectIdentifier=('file',31),objectName='Controller/Archive',description='Authored application file',fileType='.MoZ' if sys.argv[5]=='moz' else '.moi',fileSize=len(app.payload),modificationDate=DateTime('2026-01-05 12:00:00'),archive=False,readOnly=True,fileAccessMethod='stream-access')
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
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let stderr = "";
  child.stderr!.on("data", (data) => {
    stderr = (stderr + String(data)).slice(-8192);
  });
  await new Promise<void>((resolve, reject) => {
    let output = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Controller fixture startup timed out: " + stderr));
    }, 10000);
    child.stdout!.on("data", (data) => {
      output += String(data);
      if (!ready && output.split(/\r?\n/).includes("READY")) {
        ready = true;
        clearTimeout(timer);
        resolve();
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready)
        reject(new Error("Controller fixture exited: " + code + ": " + stderr));
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

for (const nativeKind of [true, "moz"] as const) {
  test(`Program reads ${nativeKind === "moz" ? ".moz" : ".moi"} native diagrams, configuration and live block data`, async ({
    page,
    request,
  }) => {
    test.setTimeout(90000);
    const device = await controller(
      "Unlisted native format family",
      0,
      21,
      nativeKind,
    );
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
        .getByRole("button", {
          name: "Read controller application",
          exact: true,
        })
        .click();
      await expect(native).toContainText("3 native records", {
        timeout: 30000,
      });
      await expect(native).toContainText("Controller file snapshot");
      const support = native.getByLabel(
        "Controller application operation support",
        { exact: true },
      );
      await support.locator("summary").click();
      await expect(
        support.locator('[data-operation="diagram-read"]'),
      ).toContainText("source qualified");
      await expect(
        support.locator('[data-operation="identity-compile"]'),
      ).toContainText("unsupported source");
      await expect(
        support.locator('[data-operation="general-logic"]'),
      ).toContainText("unavailable");
      await expect(
        support.locator('[data-operation="physical-acceptance"]'),
      ).toContainText("not inferred");
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
}

async function signalEditor(page: Page, endpoint: string, name: string) {
  await openController(page, endpoint, name);
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
  await expect(native).toContainText("4 native records", { timeout: 30000 });
  await native
    .getByLabel("Controller program block")
    .selectOption("site/575_1.2_10");
  return page.getByRole("region", {
    name: "Native signal default file copy",
    exact: true,
  });
}

test("native signal copies retain source-bound drafts and download exact reviewed Real bytes", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const device = await controller(
    "Authored native defaults",
    0,
    21,
    "signal-default",
  );
  await session(request);
  try {
    await interfaceSetup(page);
    const response = page.waitForResponse(
      "**/api/bacnet/controller/application/read",
    );
    const editor = await signalEditor(
      page,
      device.endpoint,
      "Authored native defaults",
    );
    await expect(editor.locator("p").first()).toHaveCSS("font-size", "14px");
    await expect(editor.getByLabel("Proposed signal default")).toHaveCSS(
      "font-size",
      "14px",
    );
    const report = await (await response).json();
    const original = gunzipSync(
      await (
        await request.get(
          `/api/bacnet/files/captures/${report.receipt.id}/export`,
        )
      ).body(),
    );
    await editor.getByLabel("Proposed signal default").fill("1e-");
    await page
      .getByLabel("Controller program block")
      .selectOption("site/575_1.2_11");
    await expect(editor.getByLabel("Proposed signal default")).toHaveValue(
      "24.5",
    );
    await editor.getByLabel("Proposed signal default").fill("27.5");
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await page
      .getByLabel("Controller program block")
      .selectOption("site/575_1.2_10");
    await expect(editor.getByLabel("Proposed signal default")).toHaveValue(
      "1e-",
    );
    await editor
      .getByRole("button", { name: "Review file copy", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "finite decimal text",
    );
    await editor.getByLabel("Proposed signal default").fill("0.1");
    const reviewed = page.waitForResponse("**/signal-default/preview");
    await editor
      .getByRole("button", { name: "Review file copy", exact: true })
      .click();
    const review = await (await reviewed).json();
    await expect(editor).toContainText("0.10000000149011612");
    await expect(editor).toContainText("rounds to the displayed float32");
    await editor
      .getByText("File-copy review evidence", { exact: true })
      .click();
    await expect(editor).toContainText("3dcccccd");
    const download = page.waitForEvent("download");
    await editor
      .getByRole("button", { name: "Save edited File copy", exact: true })
      .click();
    const saved = await download;
    expect(saved.suggestedFilename()).toBe(
      "controller-signal-default-copy.moi",
    );
    const bytes = gunzipSync(readFileSync((await saved.path())!));
    const expected = Buffer.from(original);
    expected.writeUInt32BE(0x3dcccccd, review.edit.native_byte_offset);
    expect(bytes.equals(expected)).toBeTruthy();
    expect(createHash("sha256").update(original).digest("hex")).toBe(
      review.edit.native_source_sha256,
    );
    const unchanged = await (
      await request.get(
        `/api/bacnet/files/captures/${report.receipt.id}/export`,
      )
    ).body();
    expect(createHash("sha256").update(unchanged).digest("hex")).toBe(
      report.receipt.sha256,
    );
    await expect(editor).toContainText("no controller write");
    await page
      .getByLabel("Controller program block")
      .selectOption("site/575_1.2_11");
    await expect(editor.getByLabel("Proposed signal default")).toHaveValue(
      "27.5",
    );
    await page.screenshot({
      path: test.info().outputPath("native-default-copy.png"),
      fullPage: true,
    });
  } finally {
    device.close();
  }
});

test("native signal copy retires late reviews and rejects an altered download digest", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const device = await controller(
    "Authored source guards",
    0,
    21,
    "signal-default",
  );
  await session(request);
  try {
    await interfaceSetup(page);
    const editor = await signalEditor(
      page,
      device.endpoint,
      "Authored source guards",
    );
    let release: (() => void) | undefined;
    await page.route("**/signal-default/preview", async (route) => {
      const response = await route.fetch();
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      await route.fulfill({ response });
    });
    await editor.getByLabel("Proposed signal default").fill("25");
    const latePreview = page.waitForResponse("**/signal-default/preview");
    await editor
      .getByRole("button", { name: "Review file copy", exact: true })
      .click();
    await expect.poll(() => Boolean(release)).toBeTruthy();
    await editor.getByLabel("Proposed signal default").fill("26");
    release!();
    await latePreview;
    await page.unroute("**/signal-default/preview");
    await expect(
      editor.getByRole("button", {
        name: "Save edited File copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await editor
      .getByRole("button", { name: "Review file copy", exact: true })
      .click();
    await expect(editor).toContainText("Proposed text: 26");
    const downloads: string[] = [];
    page.on("download", (download) =>
      downloads.push(download.suggestedFilename()),
    );
    await page.route("**/signal-default/export", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        headers: { ...response.headers(), "x-output-sha256": "0".repeat(64) },
      });
    });
    await editor
      .getByRole("button", { name: "Save edited File copy", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "File evidence does not match",
    );
    expect(downloads).toEqual([]);
    await expect(editor.getByLabel("Proposed signal default")).toHaveValue(
      "26",
    );
    await expect(
      editor.getByRole("button", { name: "Review file copy", exact: true }),
    ).toBeEnabled();
  } finally {
    device.close();
  }
});

test("native signal draft and pending export cannot move to a different controller with the same Device ID", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const first = await controller("Default owner A", 0, 21, "signal-default"),
    second = await controller("Default owner B", 0, 33, "signal-default");
  await session(request);
  let release: (() => void) | undefined;
  try {
    await interfaceSetup(page);
    const editor = await signalEditor(page, first.endpoint, "Default owner A");
    await editor.getByLabel("Proposed signal default").fill("28");
    await editor
      .getByRole("button", { name: "Review file copy", exact: true })
      .click();
    await expect(
      editor.getByRole("button", {
        name: "Save edited File copy",
        exact: true,
      }),
    ).toBeVisible();
    const downloads: string[] = [];
    page.on("download", (download) =>
      downloads.push(download.suggestedFilename()),
    );
    const lateExport = page.waitForResponse("**/signal-default/export");
    await page.route("**/signal-default/export", async (route) => {
      const response = await route.fetch();
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      await route.fulfill({ response });
    });
    await editor
      .getByRole("button", { name: "Save edited File copy", exact: true })
      .click();
    await expect.poll(() => Boolean(release)).toBeTruthy();
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await signalEditor(page, second.endpoint, "Default owner B");
    await expect(editor.getByLabel("Proposed signal default")).toHaveValue(
      "23.5",
    );
    release!();
    await lateExport;
    await page.unroute("**/signal-default/export");
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await signalEditor(page, first.endpoint, "Default owner A");
    await expect(editor.getByLabel("Proposed signal default")).toHaveValue(
      "28",
    );
    await expect(
      editor.getByRole("button", {
        name: "Save edited File copy",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toEqual([]);
  } finally {
    release?.();
    first.close();
    second.close();
  }
});

test("native signal storage failure remains visible and keyboard review still works", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const device = await controller(
    "Default storage failure",
    0,
    21,
    "signal-default",
  );
  await session(request);
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("bms-native-signal-copy/1/"))
        throw new DOMException(
          "Authored storage failure",
          "QuotaExceededError",
        );
      return original.call(this, key, value);
    };
  });
  try {
    await interfaceSetup(page);
    const editor = await signalEditor(
      page,
      device.endpoint,
      "Default storage failure",
    );
    await editor.getByLabel("Proposed signal default").fill("-0");
    await expect(editor.getByRole("status")).toContainText(
      "Keep this view open to retain this draft",
    );
    await editor.getByLabel("Proposed signal default").press("Enter");
    await expect(editor).toContainText("Stored Real: -0");
    await editor
      .getByText("File-copy review evidence", { exact: true })
      .click();
    await expect(editor).toContainText("80000000");
  } finally {
    device.close();
  }
});

test("operation support follows the exact source and controller instead of a model list", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const first = await controller("Unlisted identity A", 0, 21, "identity"),
    second = await controller("Unlisted identity B", 0, 21, "identity");
  await session(request);
  try {
    await interfaceSetup(page);
    await openController(page, first.endpoint, "Unlisted identity A");
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    const native = page.getByRole("region", {
      name: "Native controller application",
      exact: true,
    });
    const support = () =>
      native.getByLabel("Controller application operation support", {
        exact: true,
      });
    await native
      .getByRole("button", { name: "Read controller application", exact: true })
      .click();
    await expect(support()).toBeVisible();
    await support().locator("summary").click();
    await expect(
      support().locator('[data-operation="identity-compile"]'),
    ).toContainText("source qualified");
    await expect(
      support().locator('[data-operation="name-compile"]'),
    ).toContainText("source qualified");
    await expect(
      support().locator('[data-operation="identity-transfer"]'),
    ).toContainText("preflight required");
    await expect(support()).toContainText("Native ACS code: 62");
    await expect(support()).toContainText("Native DMCS code: 62");
    await expect(support()).toContainText("Captured firmware: 7.0");
    await expect(
      support().locator('[data-operation="general-logic"]'),
    ).toContainText("unavailable");
    await expect(
      support().locator('[data-operation="release-packages"]'),
    ).toContainText("not evaluated");
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await openController(page, second.endpoint, "Unlisted identity B");
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await expect(support()).toHaveCount(0);
    await native
      .getByRole("button", { name: "Read controller application", exact: true })
      .click();
    await expect(support()).toBeVisible();
    await support().locator("summary").click();
    await expect(
      support().locator('[data-operation="identity-transfer"]'),
    ).toContainText("preflight required");
    await expect(page.getByLabel("Working context")).toContainText(
      second.endpoint,
    );
    await expect(native).not.toContainText("Unlisted identity A");
    await expect(support().getByRole("rowheader").first()).toHaveCSS(
      "font-size",
      "14px",
    );
    await support()
      .locator('[data-operation="physical-acceptance"]')
      .scrollIntoViewIfNeeded();
    await expect(
      support().locator('[data-operation="physical-acceptance"]'),
    ).toBeInViewport();
    await support().screenshot({
      path: test.info().outputPath("operation-support.png"),
    });
    const testContext = test.info();
    for (const width of [700, 500]) {
      await page.setViewportSize({ width, height: 900 });
      const table = support().locator(".application-operation-table");
      const geometry = await table.evaluate((element) => ({
        client: element.clientWidth,
        scroll: element.scrollWidth,
        right: element.getBoundingClientRect().right,
        viewport: window.innerWidth,
        minimum: parseFloat(
          getComputedStyle(element.querySelector("table")!).minWidth,
        ),
      }));
      await testContext.attach(`table-${width}-geometry.json`, {
        body: JSON.stringify(geometry),
        contentType: "application/json",
      });
      expect(geometry.right).toBeLessThanOrEqual(geometry.viewport);
      if (geometry.client < geometry.minimum)
        expect(geometry.scroll).toBeGreaterThan(geometry.client);
      await support()
        .locator('[data-operation="physical-acceptance"]')
        .scrollIntoViewIfNeeded();
      await expect(
        support().locator('[data-operation="physical-acceptance"]'),
      ).toBeInViewport();
    }
  } finally {
    first.close();
    second.close();
  }
});

test("operation support rejects a response that names another capture", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const device = await controller(
    "Unlisted identity source",
    0,
    21,
    "identity",
  );
  await session(request);
  try {
    await interfaceSetup(page);
    await openController(page, device.endpoint, "Unlisted identity source");
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await page.route(
      "**/api/bacnet/controller/application/read",
      async (route) => {
        const response = await route.fetch();
        expect(response.ok()).toBe(true);
        const result = await response.json();
        result.operation_capabilities.source.capture_id = "b".repeat(32);
        await route.fulfill({ response, json: result });
      },
    );
    const native = page.getByRole("region", {
      name: "Native controller application",
      exact: true,
    });
    await native
      .getByRole("button", { name: "Read controller application", exact: true })
      .click();
    await expect(native.getByRole("alert")).toContainText(
      "Operation support differs from the application capture",
    );
    await expect(
      native.getByLabel("Controller application operation support", {
        exact: true,
      }),
    ).toHaveCount(0);
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
