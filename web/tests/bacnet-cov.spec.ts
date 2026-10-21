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
      const address = socket.address();
      socket.close(() =>
        resolve(typeof address === "string" ? 0 : address.port),
      );
    });
  });
}
async function controller() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_connections import application, free_udp, point
async def main():
    port=free_udp(); server=application(port,4190010)
    value=point(); value.covIncrement=0.1; server.add_object(value)
    await asyncio.sleep(0.05)
    print(port,flush=True)
    try: await asyncio.Event().wait()
    finally: server.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const port = await new Promise<number>((resolve, reject) => {
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
        resolve(Number(output.split("\n")[0]));
      }
    });
  });
  return { process: child, port };
}

test("Connect COV UI performs real verified subscription, renewal, evidence export and cancellation", async ({
  page,
  request,
}) => {
  const server = await controller();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  try {
    const token = (await (await request.get("/api/session")).json()).token;
    await request.post("/api/bacnet/disconnect", {
      headers: { "X-Studio-Token": token },
      data: {},
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    await expect(
      panel.getByRole("button", { name: "Start verified COV monitor" }),
    ).toBeDisabled();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
    await page
      .getByLabel("MS/TP destination network (optional)", { exact: true })
      .fill("");
    await page
      .getByLabel("BBMD address / UDP port (optional)", { exact: true })
      .fill("");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await panel
      .getByLabel("COV device IP / port", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await panel
      .getByLabel("Expected COV Device", { exact: true })
      .fill("device,4190010");
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
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(panel).toContainText("interface_changed");
    await expect(panel).toContainText("0 active monitors");
    expect(errors).toEqual([]);
  } finally {
    server.process.kill();
  }
});

test("COV monitor does not imply BBMD transport support", async ({ page }) => {
  await page.route("**/api/bacnet/status", (route) =>
    route.fulfill({
      json: {
        connected: true,
        commands: [],
        config: {
          local_address: "127.0.0.1:47809",
          bbmd_address: "127.0.0.1:47808",
        },
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "BACnet COV monitoring",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Start verified COV monitor" }),
  ).toBeDisabled();
  await expect(panel).toContainText("without BBMD or direct serial");
});
