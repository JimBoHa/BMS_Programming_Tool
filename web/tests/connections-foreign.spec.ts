import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
import {
  openConnectionDetails,
  selectKnownController,
} from "./workflow-navigation";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const value = socket.address();
      const port = typeof value === "string" ? 0 : value.port;
      socket.close(() => resolve(port));
    });
  });
}

async function peers() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_foreign_bacnet import RawPoint,RawBBMD,bvlc
from tests.browser_device_identity import device_property_reply
class Station(RawPoint):
    def datagram_received(self,data,address):
        response=device_property_reply(data[6:],4190012)
        if response is not None:
            self.transport.sendto(bvlc(10,bytes([1,0])+response),address)
        else:
            super().datagram_received(data,address)
async def main():
    loop=asyncio.get_running_loop()
    pt,point=await loop.create_datagram_endpoint(Station,local_addr=('127.0.0.1',0))
    bt,bbmd=await loop.create_datagram_endpoint(lambda:RawBBMD(point),local_addr=('127.0.0.1',0))
    print(json.dumps({'bbmd':bbmd.address[1],'point':point.address[1]}),flush=True)
    try:
        while True:
            command=await asyncio.to_thread(sys.stdin.readline)
            if not command: break
            if command.strip()=='reject': bbmd.code=0x0030
    finally:
        bt.close();pt.close()
asyncio.run(main())
`,
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  const ports = await new Promise<{ bbmd: number; point: number }>(
    (resolve, reject) => {
      let output = "",
        error = "",
        ready = false;
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("BBMD emulator startup timed out: " + error));
      }, 6000);
      child.stderr.on("data", (data) => {
        error += data.toString();
      });
      child.stdout.on("data", (data) => {
        output += data.toString();
        if (!ready && output.includes("\n")) {
          ready = true;
          clearTimeout(timer);
          resolve(JSON.parse(output.split("\n")[0]));
        }
      });
      child.on("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.on("exit", (code) => {
        clearTimeout(timer);
        if (!ready) reject(new Error(`BBMD emulator exited ${code}: ${error}`));
      });
    },
  );
  return { child, ...ports };
}

async function session(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}

async function connect(page: Page, bbmd: number) {
  await page.goto("/");
  await openConnectionDetails(page);
  await expect(
    page.getByLabel("Local bind address / UDP port", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByLabel("BBMD address / UDP port (optional)", { exact: true })
    .fill(`127.0.0.1:${bbmd}`);
  await page
    .getByLabel("Foreign registration TTL (seconds)", { exact: true })
    .fill("1");
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByLabel("BACnet foreign registration status"),
  ).toContainText("Foreign registration active");
}

test("BBMD UI registers, discovers forwarded devices, reads actual wire data and restores exact interface settings", async ({
  page,
  request,
}) => {
  const server = await peers(),
    headers = await session(request);
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await connect(page, server.bbmd);
    await selectKnownController(
      page,
      `127.0.0.1:${server.point}`,
      "device,4190012",
    );
    await chooseWorkspaceTask(page, "Points & I/O");
    await chooseWorkspaceTool(page, "Read properties", "Controller task tools");
    await page
      .getByLabel("BBMD discovery minimum instance", { exact: true })
      .fill("4190012");
    await page
      .getByLabel("BBMD discovery maximum instance", { exact: true })
      .fill("4190012");
    const scanning = page.waitForResponse((response) =>
      response.url().endsWith("/api/bacnet/discover-foreign"),
    );
    await page
      .getByRole("button", { name: "Discover through BBMD", exact: true })
      .click();
    const scan = await (await scanning).json();
    expect(scan).toContainEqual(
      expect.objectContaining({
        device: "device,4190012",
        address: `127.0.0.1:${server.point}`,
      }),
    );
    const row = page
      .getByRole("region", { name: "Discovery replies" })
      .getByRole("row")
      .filter({ hasText: "4190012" });
    await expect(row).toContainText(`127.0.0.1:${server.point}`);
    await row.getByRole("button", { name: /^Open controller/ }).click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("device,4190012");
    await chooseWorkspaceTask(page, "Points & I/O");
    await chooseWorkspaceTool(page, "Read properties", "Controller task tools");
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("analog-input,1");
    await page.getByLabel("Property", { exact: true }).fill("present-value");
    await page
      .getByRole("button", { name: "Read property", exact: true })
      .click();
    await expect(page.locator("pre.result")).toContainText('"value": 12.5');
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/status")).json())
            .foreign_device.acknowledgements,
      )
      .toBeGreaterThanOrEqual(2);
    await page.reload();
    await openConnectionDetails(page);
    await expect(
      page.getByLabel("BBMD address / UDP port (optional)", { exact: true }),
    ).toHaveValue(`127.0.0.1:${server.bbmd}`);
    await expect(
      page.getByLabel("Foreign registration TTL (seconds)", { exact: true }),
    ).toHaveValue("1");
    await page.screenshot({
      path: "test-results/studio-foreign-bbmd.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(
      page.getByLabel("BACnet foreign registration status"),
    ).toHaveCount(0);
    expect(
      (await (await request.get("/api/bacnet/status")).json()).connected,
    ).toBe(false);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    server.child.kill();
  }
});

test("a rejected BBMD renewal disables point operations and still allows closing the failed interface", async ({
  page,
  request,
}) => {
  const server = await peers(),
    headers = await session(request);
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await connect(page, server.bbmd);
    await selectKnownController(
      page,
      `127.0.0.1:${server.point}`,
      "device,4190012",
    );
    await chooseWorkspaceTask(page, "Points & I/O");
    await chooseWorkspaceTool(page, "Read properties", "Controller task tools");
    await expect(
      page.getByRole("button", { name: "Read property", exact: true }),
    ).toBeEnabled();
    await openConnectionDetails(page);
    server.child.stdin.write("reject\n");
    await expect(
      page.getByLabel("BACnet foreign registration status"),
    ).toContainText("Foreign registration unavailable", { timeout: 10000 });
    await chooseWorkspaceSurface(page, "Workspace");
    await chooseWorkspaceTask(page, "Points & I/O");
    await chooseWorkspaceTool(page, "Read properties", "Controller task tools");
    await expect(
      page.getByRole("button", { name: "Read property", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Discover through BBMD", exact: true }),
    ).toBeDisabled();
    await openConnectionDetails(page);
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(
      page.getByLabel("BACnet foreign registration status"),
    ).toHaveCount(0);
    expect(
      (await (await request.get("/api/bacnet/status")).json()).connected,
    ).toBe(false);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    server.child.kill();
  }
});
