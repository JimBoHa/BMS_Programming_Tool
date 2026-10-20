import { test, expect } from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { createSocket } from "node:dgram";
import path from "node:path";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      const port = typeof address === "string" ? 0 : address.port;
      socket.close(() => resolve(port));
    });
  });
}
async function controller(): Promise<{ process: ChildProcess; port: number }> {
  const process = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_temco_transfer import Controller, free_udp, INSTANCE, MODEL, FIRMWARE
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
async def main():
    port=free_udp()
    server=Controller.from_object_list([
        DeviceObject(objectIdentifier=('device', INSTANCE), objectName='Browser Temco emulator', vendorIdentifier=148, modelName=MODEL, firmwareRevision=FIRMWARE),
        NetworkPortObject(f'127.0.0.1:{port}', objectIdentifier=('network-port',1), objectName='Loopback port')])
    server.setup()
    print(port, flush=True)
    try: await asyncio.Event().wait()
    finally: server.close()
asyncio.run(main())
`,
    ],
    { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
  );
  const port = await new Promise<number>((resolve, reject) => {
    let output = "",
      error = "";
    const timer = setTimeout(() => {
      process.kill();
      reject(new Error("Temco emulator startup timed out: " + error));
    }, 10000);
    process.stderr!.on("data", (value) => {
      error += value.toString();
    });
    process.stdout!.on("data", (value) => {
      output += value.toString();
      if (output.includes("\n")) {
        clearTimeout(timer);
        resolve(Number(output.split("\n")[0]));
      }
    });
    process.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    process.on("exit", (code) => {
      clearTimeout(timer);
      if (!output) reject(new Error(`Temco emulator exited ${code}: ${error}`));
    });
  });
  return { process, port };
}

test("native Temco UI replaces and restores an actual loopback BACnet program image", async ({
  page,
  request,
}) => {
  const server = await controller();
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  let releaseReply: (() => void) | undefined;
  try {
    const opened = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(opened.ok()).toBeTruthy();
    const program = execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_temco import graph; print(graph('Add',values={'a':40,'b':2}).model_dump_json())",
      ],
      { cwd: root },
    );
    await page.goto("/");
    await page.locator('input[type=file][accept*=".st"]').setInputFiles({
      name: "temco-transfer.bms.json",
      mimeType: "application/json",
      buffer: program,
    });
    await page
      .getByRole("button", { name: "Temco native", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Compile Control Basic", exact: true })
      .click();
    await expect(
      page.getByLabel("Compiled Control Basic source"),
    ).toBeVisible();
    await page
      .getByLabel("Temco device address", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await page
      .getByLabel("Temco device instance", { exact: true })
      .fill("4190050");
    await page
      .getByLabel("Temco program slot (0–15)", { exact: true })
      .fill("3");
    await page
      .getByLabel("Temco expected model", { exact: true })
      .fill("T3-ESP32");
    await page
      .getByLabel("Temco expected firmware", { exact: true })
      .fill("5.4-fixture");
    await page
      .getByRole("button", { name: "Inspect Temco program slot", exact: true })
      .click();
    await expect(
      page.getByText("Verified slot snapshot", { exact: true }),
    ).toBeVisible();
    const identity = {
      address: `127.0.0.1:${server.port}`,
      device_instance: 4190050,
      slot: 3,
      expected_model: "T3-ESP32",
      expected_firmware: "5.4-fixture",
    };
    const original = await (
      await request.post("/api/temco/transfer/inspect", {
        headers,
        data: identity,
      })
    ).json();
    await page
      .getByLabel("Resume previously running Temco program", { exact: true })
      .uncheck();
    await page
      .getByRole("button", {
        name: "Plan compiled program transfer",
        exact: true,
      })
      .click();
    const plan = page.getByRole("region", {
      name: "Reviewed Temco transfer plan",
    });
    await expect(plan).toBeVisible();
    await expect(plan).toContainText("remain stopped");
    await expect(
      page.getByRole("button", {
        name: "Apply reviewed Temco transfer",
        exact: true,
      }),
    ).toBeDisabled();
    await page
      .getByLabel("Reviewed Temco program stop and replacement", {
        exact: true,
      })
      .check();
    let completed!: () => void;
    const applied = new Promise<void>((resolve) => {
      completed = resolve;
    });
    const heldReply = new Promise<void>((resolve) => {
      releaseReply = resolve;
    });
    let holdFirstApply = true;
    // Keep interception installed through the post-apply status request. Removing
    // a one-shot route while its fulfilled reply starts another browser fetch can
    // leave that fetch paused inside Chromium, even though the API stays healthy.
    await page.route("**/api/temco/transfer/apply", async (route) => {
      const response = await route.fetch();
      if (holdFirstApply) {
        holdFirstApply = false;
        completed();
        await heldReply;
      }
      await route.fulfill({ response });
    });
    await page
      .getByRole("button", {
        name: "Apply reviewed Temco transfer",
        exact: true,
      })
      .click();
    await applied;
    // Editing authoring bindings while a committed field reply is in flight
    // must invalidate compilation without discarding that operation's result.
    await page.getByLabel("Temco point for a", { exact: true }).fill("VAR4");
    releaseReply!();
    const result = page.getByRole("region", { name: "Temco transfer result" });
    await expect(result).toContainText('"readback_verified": true');
    const changed = await (
      await request.post("/api/temco/transfer/inspect", {
        headers,
        data: identity,
      })
    ).json();
    expect(changed.image_sha256).not.toBe(original.image_sha256);
    expect(changed.metadata.running).toBe(false);
    const backups = await (
      await request.get("/api/temco/transfer/backups")
    ).json();
    const saved = backups.find(
      (item: any) =>
        item.target.address === identity.address &&
        item.target.slot === 3 &&
        item.image_sha256 === original.image_sha256,
    );
    expect(saved).toBeTruthy();
    await page
      .getByLabel("Temco durable slot backup", { exact: true })
      .selectOption(saved.id);
    const downloading = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Download Temco backup JSON", exact: true })
      .click();
    const file = await downloading;
    const backup = JSON.parse(readFileSync((await file.path())!, "utf8"));
    expect(Buffer.from(backup.image_base64, "base64")).toHaveLength(2000);
    expect(backup.image_sha256).toBe(original.image_sha256);
    await page
      .getByLabel("Resume previously running Temco program", { exact: true })
      .check();
    await page
      .getByRole("button", { name: "Plan backup restoration", exact: true })
      .click();
    await expect(plan).toContainText("Restore plan");
    await expect(plan).toContainText("After readback, the program will run");
    await page
      .getByLabel("Reviewed Temco program stop and replacement", {
        exact: true,
      })
      .check();
    await page
      .getByRole("button", {
        name: "Apply reviewed Temco transfer",
        exact: true,
      })
      .click();
    await expect(result).toContainText('"readback_verified": true');
    const restored = await (
      await request.post("/api/temco/transfer/inspect", {
        headers,
        data: identity,
      })
    ).json();
    expect(restored.image_sha256).toBe(original.image_sha256);
    expect(restored.metadata.running).toBe(true);
    await page.screenshot({
      path: "test-results/studio-temco-transfer.png",
      fullPage: true,
    });
  } finally {
    releaseReply?.();
    try {
      await request.post("/api/bacnet/disconnect", {
        headers,
        data: {},
        timeout: 3000,
      });
    } catch {
      // Playwright closes its request context on timeout. Preserve that original
      // failure while still terminating the emulator owned by this test.
    } finally {
      server.process.kill();
    }
  }
});
