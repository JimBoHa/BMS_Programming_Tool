import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import path from "node:path";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import {
  logicReadingConditions,
  logicReadingUnit,
} from "../src/logicPointReading";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python"),
  ref = "authored/575_1";
const env = { ...process.env, PYTHONPATH: path.join(root, "backend") };

async function peer() {
  const port = await freePort();
  const child = spawn(
    python,
    [
      "-u",
      "-c",
      `
import asyncio,sys,types
from tests.test_controller_workspace import workspace_device
from tests.test_bacnet_files import FilePeer
from tests.test_logic_display import pid_native
from bacpypes3.object import FileObject,AnalogValueObject
from bacpypes3.basetypes import DateTime
from bacpypes3.primitivedata import ObjectIdentifier
async def main():
 app=workspace_device(int(sys.argv[1]),model='Authored PID controller',vendor=999,modules=1)
 app.payload=pid_native()
 app.stream=FileObject(objectIdentifier=('file',31),objectName='Controller/Archive',fileType='.moi',fileSize=len(app.payload),modificationDate=DateTime('2026-01-05 12:00:00'),archive=False,readOnly=True,fileAccessMethod='stream-access')
 app.add_object(app.stream);app.device_object.configurationFiles=[app.stream.objectIdentifier]
 app.atomic_requests=[];app.all_requests=[];app.drop=False;app.mutation=None;app.callback=None
 for method in ('do_AtomicReadFileRequest','do_AtomicWriteFileRequest','do_ReinitializeDeviceRequest','do_WritePropertyRequest'):
  setattr(app,method,types.MethodType(getattr(FilePeer,method),app))
 for n,v in [(10,21),(11,77),(12,0)]:
  flags=[0,0,1,0] if n==11 else [0,0,0,0]
  app.add_object(AnalogValueObject(objectIdentifier=('analog-value',n),objectName=f'Actual point {n}',presentValue=v,units='degrees-fahrenheit',statusFlags=flags,reliability='no-fault-detected',outOfService=False))
 print('READY',flush=True)
 try:await asyncio.Event().wait()
 finally:app.close()
asyncio.run(main())
`,
      String(port),
    ],
    { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] },
  );
  let stderr = "";
  child.stderr!.on("data", (d) => (stderr += String(d)));
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(Error(stderr || "Peer startup timed out"));
    }, 10000);
    child.stdout!.on("data", (d) => {
      if (String(d).includes("READY")) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.once("exit", () => {
      clearTimeout(timer);
      reject(Error(stderr));
    });
  });
  return { endpoint: `127.0.0.1:${port}`, close: () => child.kill() };
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function closeCompactInspector(page: Page) {
  const close = page.getByRole("button", { name: /^Close (controller|CAF) logic inspector$/i });
  if (await close.isVisible()) await close.click();
}

async function openController(page: Page, endpoint: string) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
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
  ).toContainText("Authored PID controller");
  await chooseWorkspaceTask(page, "Program");
  await page
    .getByRole("button", { name: "Read controller application", exact: true })
    .click();
  const graph = page.getByLabel("Actual native program diagram", {
    exact: true,
  });
  await expect(graph.locator(".react-flow__node")).toHaveCount(4);
  return graph;
}

test("connected native program uses engineering symbols and exact pin handles, with source-owned live readings", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  const device = await peer(),
    posts: string[] = [],
    cafCalls: string[] = [];
  await request.post("/api/bacnet/disconnect", {
    headers: await headers(request),
    data: {},
  });
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(new URL(r.url()).pathname);
    if (/\/api\/caf\//.test(r.url())) cafCalls.push(r.url());
  });
  let release!: () => void;
  try {
    const graph = await openController(page, device.endpoint);
    await expect(
      graph.locator('.engineering-node[data-function="PID"]'),
    ).toHaveCount(1);
    await expect(graph.locator(".engineering-node.input")).toHaveCount(2);
    await expect(graph.locator(".engineering-node.output")).toHaveCount(1);
    const pid = graph.locator(`.react-flow__node[data-id="${ref}.252_20"]`);
    await expect(
      pid.getByText("Process Variable", { exact: true }),
    ).toBeVisible();
    await expect(pid.getByText("Loop setpoint", { exact: true })).toBeVisible();
    await expect(pid.locator('[data-handleid="in:695"]')).toHaveCount(1);
    await expect(pid.locator('[data-handleid="in:108"]')).toHaveCount(1);
    expect(await graph.locator(".react-flow__handle.connectable").count()).toBe(
      0,
    );
    await graph
      .getByRole("button", { name: "Expand logic view", exact: true })
      .click();
    await expect(graph.locator(".engineering-expanded")).toBeVisible();
    await graph.getByRole("button", { name: /^Zone temperature/ }).click();
    await expect(
      graph.locator(`.react-flow__node[data-id="${ref}.2_10"] .logic-value`),
    ).toHaveText("Live 21 °F");
    await closeCompactInspector(page);
    await graph.getByRole("button", { name: /^Cooling setpoint/ }).click();
    await expect(
      graph.locator(`.react-flow__node[data-id="${ref}.2_11"] .logic-value`),
    ).toHaveText("Overridden 77 °F");
    await expect(page.getByText("Overridden", { exact: true })).toBeVisible();
    await closeCompactInspector(page);
    await graph.getByRole("button", { name: /^Zone temperature/ }).click();
    await expect(
      graph.locator(`.react-flow__node[data-id="${ref}.2_10"] .logic-value`),
    ).toHaveText("Live 21 °F");
    let once = false;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**/api/bacnet/controller/properties", async (route) => {
      const response = await route.fetch();
      if (
        !once &&
        route.request().postDataJSON().object_ids[0] === "analog-value,11"
      ) {
        once = true;
        await gate;
      }
      await route.fulfill({ response });
    });
    await closeCompactInspector(page);
    await graph.getByRole("button", { name: /^Cooling setpoint/ }).click();
    await expect
      .poll(() => once, {
        message: "The selected setpoint read reached the held response",
      })
      .toBe(true);
    await closeCompactInspector(page);
    await graph.getByRole("button", { name: /^Zone temperature/ }).click();
    await expect(
      graph.locator(`.react-flow__node[data-id="${ref}.2_10"] .logic-value`),
    ).toHaveText("Live 21 °F");
    const delivered = page.waitForResponse(
      (r) =>
        r.url().endsWith("/controller/properties") &&
        r.request().postDataJSON().object_ids[0] === "analog-value,11",
    );
    release();
    await delivered;
    await expect(
      graph.locator(`.react-flow__node[data-id="${ref}.2_11"] .logic-value`),
    ).toHaveText("Stored 74.0");
    await expect(
      graph.locator(`.react-flow__node[data-id="${ref}.2_10"] .logic-value`),
    ).toHaveText("Live 21 °F");
    await closeCompactInspector(page);
    await graph
      .getByRole("button", { name: "Fit diagram", exact: true })
      .click();
    await page.screenshot({
      path: info.outputPath("connected-pid-engineering.png"),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await expect(graph.locator(".engineering-expanded")).toHaveCount(0);
    expect(cafCalls).toEqual([]);
    expect(
      posts.filter((path) => /write|apply|transfer|restore|backup/.test(path)),
    ).toEqual([]);
  } finally {
    release?.();
    try {
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      });
    } finally {
      device.close();
    }
  }
});

test("local CAF uses the same PID presentation, stored values and keyboard-safe expanded view", async ({
  page,
  request,
}, info) => {
  await request.post("/api/bacnet/disconnect", {
    headers: await headers(request),
    data: {},
  });
  const field: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      field.push(r.url());
  });
  await page.goto("/");
  const buffer = execFileSync(
    python,
    [
      "-c",
      "from tests.test_logic_display import pid_caf; import sys; sys.stdout.buffer.write(pid_caf())",
    ],
    { cwd: root, env },
  );
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "authored-cooling-template.caf",
      mimeType: "application/octet-stream",
      buffer,
    });
  const cafTools = page.getByRole("navigation", {
    name: "CAF application tasks",
    exact: true,
  });
  await expect(cafTools).toBeVisible();
  const compactTools = cafTools.getByRole("combobox", {
    name: "CAF application tasks",
    exact: true,
  });
  if (await compactTools.isVisible())
    await compactTools.selectOption({ label: "Logic" });
  else
    await cafTools.getByRole("button", { name: "Logic", exact: true }).click();
  const graph = page.getByLabel("CAF graphical logic workspace", {
    exact: true,
  });
  await expect(
    graph.locator('.engineering-node[data-function="PID"]'),
  ).toHaveCount(1);
  await expect(graph.locator(".engineering-node.input")).toHaveCount(2);
  await graph
    .getByRole("button", { name: "Expand logic view", exact: true })
    .click();
  await graph.getByRole("button", { name: /^Cooling loop/ }).click();
  await closeCompactInspector(page);
  await graph.getByRole("button", { name: "Fit diagram", exact: true }).click();
  await expect(graph).toContainText(
    "authored-cooling-template.caf · local CAF",
  );
  await expect(
    graph.getByText("Process Variable", { exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("caf-pid-engineering.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(
    graph.getByRole("button", { name: "Expand logic view", exact: true }),
  ).toBeFocused();
  expect(field).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("verified units and quality preserve unknown and unavailable property evidence", () => {
  const row = (value: unknown) => ({ status: "ok", value });
  const unit = {
    native_datatype: "EngineeringUnits",
    value: 84,
    known: true,
    name: "cubic-feet-per-minute",
  };
  expect(logicReadingUnit({ units: row(unit) })).toBe("CFM");
  expect(
    logicReadingUnit({ units: row({ ...unit, known: false, value: 60001 }) }),
  ).toBe("unit 60001");
  expect(
    logicReadingUnit({
      units: {
        ...row({ ...unit, known: false, value: 264 }),
        display_label: "% open",
      },
    }),
  ).toBe("% open");
  expect(logicReadingUnit({ units: { status: "timeout", value: unit } })).toBe(
    "",
  );
  expect(logicReadingUnit({ units: row({ ...unit, name: "no-units" }) })).toBe(
    "",
  );
  expect(
    logicReadingConditions({
      "status-flags": row([1, 1, 1, 1]),
      "out-of-service": row(true),
      reliability: row(3),
    }),
  ).toEqual(["Out of service", "Fault", "Overridden", "In alarm"]);
  expect(
    logicReadingConditions({
      "status-flags": row([0, 0, 0, 0]),
      reliability: row({ native_datatype: "Reliability", value: 3 }),
    }),
  ).toEqual(["Fault"]);
  expect(
    logicReadingConditions({ "status-flags": row(["0", 0, 0, 0]) }),
  ).toEqual(["Status flags unavailable"]);
  expect(
    logicReadingConditions({
      "status-flags": { status: "timeout", value: [0, 0, 0, 0] },
    }),
  ).toEqual(["Status flags unavailable"]);
});
