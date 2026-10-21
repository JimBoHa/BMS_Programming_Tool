import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const a = socket.address();
      socket.close(() => resolve(typeof a === "string" ? 0 : a.port));
    });
  });
}
async function routedPeer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json
from tests.test_bacnet_cov_routed import routed_pair
async def main():
    router,field,analog,config,frames=routed_pair()
    await asyncio.sleep(.05)
    print(json.dumps(config),flush=True)
    try: await asyncio.Event().wait()
    finally: field.close(); router.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const config = await new Promise<any>((resolve, reject) => {
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
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const ready = new Promise<void>((resolve) => {
    started = resolve;
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByLabel("Router IP (optional)", { exact: true })
      .fill(peer.config.router);
    await page
      .getByLabel("MS/TP destination network (optional)", { exact: true })
      .fill("2001");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await page.getByLabel("Unicast target", { exact: true }).fill("2001:4");
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("device,4190012");
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    await expect(
      panel.getByLabel("COV source path", { exact: true }),
    ).toHaveValue("routed");
    await expect(
      panel.getByLabel("COV router IP / port", { exact: true }),
    ).toHaveValue(peer.config.router);
    await expect(
      panel.getByLabel("COV destination network", { exact: true }),
    ).toHaveValue("2001");
    await expect(
      panel.getByLabel("COV controller MAC", { exact: true }),
    ).toHaveValue("4");
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-value,1");
    await page.route("**/api/bacnet/cov/start", async (route) => {
      const response = await route.fetch();
      started();
      await held;
      await route.fulfill({ response });
    });
    await panel
      .getByRole("button", { name: "Start verified COV monitor" })
      .click();
    await ready;
    await page.getByLabel("Unicast target", { exact: true }).fill("2001:5");
    release();
    await expect(panel).toContainText(
      "Monitor started for the earlier selection",
    );
    await expect(
      panel.getByLabel("COV controller MAC", { exact: true }),
    ).toHaveValue("5");
    await expect(
      panel.getByLabel("Expected COV Device", { exact: true }),
    ).toHaveValue("");
    await expect(panel).toContainText("2001:4 via");
    await expect(panel.getByText(/^Notification 1 ·/)).toBeVisible();
    const download = page.waitForEvent("download");
    await panel.getByRole("button", { name: "Export COV evidence" }).click();
    const file = await download;
    const evidence = JSON.parse(readFileSync((await file.path())!, "utf8"));
    expect(evidence.config.address).toBe("2001:4");
    expect(evidence.events[0].route.next_hop).toBe(peer.config.router);
    expect(evidence.events[0].route.source).toBe("2001:4");
    expect(evidence.events[0].values[0].value).toBe(12.5);
    await panel.getByRole("button", { name: "Renew COV lease" }).click();
    await expect(panel).toContainText("Explicit renewal acknowledged.");
    await panel.getByRole("button", { name: "Stop COV monitor" }).click();
    await expect(panel).toContainText("Cancellation acknowledged.");
    await panel
      .getByLabel("COV source path", { exact: true })
      .selectOption("direct");
    await expect(
      panel.getByLabel("Expected COV Device", { exact: true }),
    ).toHaveValue("");
    await expect(
      panel.getByLabel("COV monitored object", { exact: true }),
    ).toHaveValue("");
  } finally {
    release?.();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.child.kill();
  }
});
