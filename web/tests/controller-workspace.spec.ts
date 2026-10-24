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
async function controller(name: string, modules: number, value = 21) {
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
 print('READY',flush=True)
 def change():
  line=sys.stdin.readline()
  if line:point.presentValue=float(line);print('CHANGED',flush=True)
 asyncio.get_running_loop().add_reader(sys.stdin.fileno(),change)
 try:await asyncio.Event().wait()
 finally:close_application(app)
asyncio.run(main())
`,
      String(port),
      name,
      String(modules),
      String(value),
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
