import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  openMonitoringInterface,
  selectKnownMonitoringController,
  showControllerMonitor,
} from "./event-workspace";
import { disconnectTestInterface } from "./workflow-peer";

const root = path.resolve("..");
async function routedPeer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json
from bacpypes3.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from tests.test_bacnet_cov_routed import close_routed_pair, routed_pair
from tests.test_connections import point
async def main():
    router,field,analog,config,frames=await routed_pair()
    value=point(); value.presentValue=28.0
    second=Application.from_object_list([
        DeviceObject(objectIdentifier=("device",4190013),objectName="Second virtual terminal"),
        NetworkPortObject(objectIdentifier=("network-port",1),objectName="Second field link",
            macAddress=bytes([5]),networkType="virtual",networkInterfaceName=router._routed_cov_network.name,
            protocolLevel="bacnet-application"),
        value,
    ])
    print(json.dumps(config),flush=True)
    try: await asyncio.Event().wait()
    finally: second.close(); close_routed_pair(router,field)
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const config = await new Promise<{
    router: string;
    address: string;
    device: string;
    dnet: number;
  }>((resolve, reject) => {
    let out = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Routed COV peer did not start"));
    }, 5000);
    child.once("error", reject);
    child.stdout!.on("data", (data) => {
      out += data.toString();
      if (out.includes("\n")) {
        clearTimeout(timer);
        resolve(JSON.parse(out.split("\n")[0]));
      }
    });
  });
  return { child, config };
}

test("routed COV UI defaults selected route, keeps pending source identity, exports real provenance and cancels", async ({
  page,
  request,
}) => {
  const peer = await routedPeer();
  const starts: string[] = [];
  let jobId = "";
  let release!: () => void;
  let started!: () => void;
  let delivered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const ready = new Promise<void>((resolve) => {
    started = resolve;
  });
  const completed = new Promise<void>((resolve) => {
    delivered = resolve;
  });
  try {
    await disconnectTestInterface(request);
    await openMonitoringInterface(page);
    await selectKnownMonitoringController(
      page,
      peer.config.address,
      peer.config.device,
      peer.config.router,
      String(peer.config.dnet),
    );
    await showControllerMonitor(page, "Live COV monitor");
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    for (const label of [
      "COV source path",
      "COV router IP / port",
      "COV destination network",
      "COV controller MAC",
    ]) {
      await expect(panel.getByLabel(label, { exact: true })).toHaveCount(0);
    }
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-value,1");
    await page.route("**/api/bacnet/cov/start", async (route) => {
      starts.push(route.request().postDataJSON().address);
      const response = await route.fetch();
      jobId = (await response.json()).id;
      started();
      await held;
      await route.fulfill({ response });
      delivered();
    });
    await panel
      .getByRole("button", { name: "Start verified COV monitor" })
      .click();
    await ready;
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await selectKnownMonitoringController(
      page,
      "2001:5",
      "device,4190013",
      peer.config.router,
      "2001",
    );
    release();
    await completed;
    await showControllerMonitor(page, "Live COV monitor");
    await expect(
      panel.getByLabel("COV monitored object", { exact: true }),
    ).toHaveValue("");
    await expect(
      panel.getByRole("button", { name: "Start verified COV monitor" }),
    ).toBeDisabled();
    expect(jobId).toMatch(/^cov-/);
    const current = panel.getByRole("region", {
      name: `COV monitor ${jobId}`,
      exact: true,
    });
    await expect(current).toContainText(`2001:4 via ${peer.config.router}`);
    await expect(current.getByText(/^Notification 1 ·/)).toBeVisible();
    const download = page.waitForEvent("download");
    await current.getByRole("button", { name: "Export COV evidence" }).click();
    const file = await download;
    const evidence = JSON.parse(readFileSync((await file.path())!, "utf8"));
    expect(evidence.id).toBe(jobId);
    expect(evidence.config).toMatchObject({
      address: "2001:4",
      router: peer.config.router,
      dnet: 2001,
      device: "device,4190012",
      object_id: "analog-value,1",
    });
    expect(evidence.events[0].route.next_hop).toBe(peer.config.router);
    expect(evidence.events[0].route.source).toBe("2001:4");
    expect(evidence.events[0].values[0].value).toBe(12.5);
    await current.getByRole("button", { name: "Renew COV lease" }).click();
    await expect(panel).toContainText("Explicit renewal acknowledged.");
    await current.getByRole("button", { name: "Stop COV monitor" }).click();
    await expect(panel).toContainText("Cancellation acknowledged.");
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await selectKnownMonitoringController(
      page,
      peer.config.router,
      "device,4190011",
    );
    await showControllerMonitor(page, "Live COV monitor");
    await expect(
      panel.getByLabel("COV monitored object", { exact: true }),
    ).toHaveValue("");
    await expect(
      panel.getByRole("button", { name: "Start verified COV monitor" }),
    ).toBeDisabled();
    await expect(current).toContainText("Cancellation acknowledged.");
    expect(starts).toEqual(["2001:4"]);
  } finally {
    release?.();
    try {
      await disconnectTestInterface(request);
    } finally {
      peer.child.kill();
    }
  }
});
