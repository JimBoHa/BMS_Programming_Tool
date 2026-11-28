import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import {
  openMonitoringInterface,
  selectKnownMonitoringController,
  showControllerMonitor,
} from "./event-workspace";
import { disconnectTestInterface, freePort } from "./workflow-peer";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function controller(foreign = false) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_connections import application, free_udp, point
from tests.test_foreign_bacnet import RawBBMD, RawPoint
async def main():
    port=free_udp(); server=application(port,4190010)
    value=point(); value.covIncrement=0.1; server.add_object(value)
    await asyncio.sleep(0.05)
    transports=[];bbmd_port=None
    if sys.argv[1]=="foreign":
        loop=asyncio.get_running_loop()
        pt,raw=await loop.create_datagram_endpoint(RawPoint,local_addr=("127.0.0.1",0))
        bt,bbmd=await loop.create_datagram_endpoint(lambda:RawBBMD(raw),local_addr=("127.0.0.1",0))
        transports=[pt,bt];bbmd_port=bbmd.address[1]
    print(json.dumps({"port":port,"bbmd":bbmd_port}),flush=True)
    try: await asyncio.Event().wait()
    finally:
        for transport in transports: transport.close()
        server.close()
asyncio.run(main())
`,
      foreign ? "foreign" : "direct",
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const endpoints = await new Promise<{ port: number; bbmd: number | null }>(
    (resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("Loopback controller did not start"));
      }, 5000);
      child.once("error", reject);
      child.stdout!.on("data", (data) => {
        output += data.toString();
        if (output.includes("\n")) {
          clearTimeout(timer);
          resolve(JSON.parse(output.split("\n")[0]));
        }
      });
    },
  );
  return { process: child, ...endpoints };
}

test("Connect COV UI performs real verified subscription, renewal, evidence export and cancellation", async ({
  page,
  request,
}) => {
  const server = await controller();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  try {
    await disconnectTestInterface(request);
    await openMonitoringInterface(page);
    await expect(
      page.getByRole("button", { name: "Start verified COV monitor" }),
    ).toHaveCount(0);
    await selectKnownMonitoringController(
      page,
      `127.0.0.1:${server.port}`,
      "device,4190010",
    );
    await showControllerMonitor(page, "Live COV monitor");
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    await expect(panel.getByLabel("COV device IP / port")).toHaveCount(0);
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-value,1");
    await panel
      .getByRole("button", { name: "Start verified COV monitor" })
      .click();
    await expect(panel).toContainText("1 active monitors");
    const monitor = panel
      .getByRole("region", { name: /^COV monitor cov-/ })
      .first();
    await expect(monitor.getByText(/^Notification 1 ·/)).toBeVisible();
    await monitor.getByRole("button", { name: "Renew COV lease" }).click();
    await expect(panel).toContainText("Explicit renewal acknowledged.");
    const pending = page.waitForEvent("download");
    await monitor.getByRole("button", { name: "Export COV evidence" }).click();
    const downloaded = await pending;
    const evidence = JSON.parse(
      readFileSync((await downloaded.path())!, "utf8"),
    );
    expect(evidence.events[0].values[0].value).toBe(12.5);
    expect(evidence.config.confirmed).toBe(true);
    expect(evidence.config.address).toBe(`127.0.0.1:${server.port}`);
    expect(evidence.events[0].device).toBe("device,4190010");
    await monitor.getByRole("button", { name: "Stop COV monitor" }).click();
    await expect(panel).toContainText("Cancellation acknowledged.");
    await expect(panel).toContainText("0 active monitors");
    await panel
      .getByLabel("COV notification mode", { exact: true })
      .selectOption("unconfirmed");
    await panel
      .getByRole("button", { name: "Start verified COV monitor" })
      .click();
    await expect(panel).toContainText("1 active monitors");
    const job = (
      await (await request.get("/api/bacnet/cov/status")).json()
    ).jobs.find((v: { active: boolean }) => v.active);
    expect(job.config.confirmed).toBe(false);
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/bacnet/cov/jobs/${job.id}`)).json())
            .state,
      )
      .toBe("interface_changed");
    expect(
      (await (await request.get("/api/bacnet/cov/status")).json()).jobs.filter(
        (v: { active: boolean }) => v.active,
      ),
    ).toHaveLength(0);
    expect(errors).toEqual([]);
  } finally {
    server.process.kill();
  }
});

test("COV monitor does not imply BBMD transport support", async ({
  page,
  request,
}) => {
  const server = await controller(true);
  try {
    await disconnectTestInterface(request);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const address = `127.0.0.1:${server.port}`;
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers,
          data: {
            local_address: `127.0.0.1:${await freePort()}`,
            bbmd_address: `127.0.0.1:${server.bbmd}`,
            foreign_ttl: 60,
          },
        })
      ).ok(),
    ).toBe(true);
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/status")).json())
            .foreign_device?.registered,
      )
      .toBe(true);
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await selectKnownMonitoringController(page, address, "device,4190010");
    await showControllerMonitor(page, "Live COV monitor");
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    await expect(
      panel.getByRole("button", { name: "Start verified COV monitor" }),
    ).toBeDisabled();
    await expect(panel).toContainText("without BBMD or direct serial");
    const refused = await request.post("/api/bacnet/cov/start", {
      headers,
      data: {
        address,
        device: "device,4190010",
        object_id: "analog-value,1",
        lifetime: 60,
        confirmed: false,
      },
    });
    expect(refused.ok()).toBe(false);
    expect((await refused.json()).detail).toMatch(/BBMD/i);
    expect(
      (await (await request.get("/api/bacnet/cov/status")).json()).jobs.filter(
        (v: { active: boolean }) => v.active,
      ),
    ).toHaveLength(0);
  } finally {
    if (!page.isClosed()) await disconnectTestInterface(request);
    server.process.kill();
  }
});
