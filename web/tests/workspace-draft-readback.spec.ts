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
async function controlledPeer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_device_instance import instance_peer
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
from bacpypes3.apdu import APDU,ConfirmedRequestPDU
from bacpypes3.pdu import PDU
async def main():
 port=free_udp();server=instance_peer(port,'hold');original=server.asap.confirmation
 async def track(pdu):
  packet=APDU.decode(PDU(bytes(pdu.pduData)))
  if isinstance(packet,ConfirmedRequestPDU) and packet.apduService==15:print('WRITE',flush=True)
  await original(pdu)
 server.asap.confirmation=track
 def command():
  value=sys.stdin.readline().strip()
  if value=='set-new':server.instance=15136
  elif value=='set-old':server.instance=5136
  else:raise AssertionError('Unknown authored peer command')
  print('ACK '+value,flush=True)
 asyncio.get_running_loop().add_reader(sys.stdin.fileno(),command)
 print('READY '+str(port),flush=True)
 try:await asyncio.Event().wait()
 finally:server.release.set();close_application(server)
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let writes = 0,
    pending = "",
    errors = "";
  const acknowledgements = new Map<string, () => void>();
  child.stderr!.on(
    "data",
    (chunk) => (errors = (errors + String(chunk)).slice(-8192)),
  );
  const port = await new Promise<number>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Peer startup: " + errors));
    }, 10000);
    child.stdout!.on("data", (chunk) => {
      pending += String(chunk);
      while (pending.includes("\n")) {
        const at = pending.indexOf("\n"),
          line = pending.slice(0, at).trim();
        pending = pending.slice(at + 1);
        if (line.startsWith("READY ")) {
          clearTimeout(timer);
          resolve(Number(line.slice(6)));
        } else if (line === "WRITE") writes++;
        else if (line.startsWith("ACK ")) {
          acknowledgements.get(line.slice(4))?.();
          acknowledgements.delete(line.slice(4));
        }
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Peer exit ${code}: ${errors}`));
    });
  });
  return {
    port,
    writes: () => writes,
    async command(value: string) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error("Peer command: " + value + errors)),
          5000,
        );
        acknowledgements.set(value, () => {
          clearTimeout(timer);
          resolve();
        });
        child.stdin!.write(value + "\n");
      });
    },
    async close() {
      if (child.exitCode !== null || child.signalCode !== null) return;
      await new Promise<void>((resolve) => {
        child.once("exit", () => resolve());
        child.kill("SIGTERM");
      });
    },
  };
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function select(page: Page, port: number) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(`127.0.0.1:${port}`);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill("");
  await page.getByLabel("Known network", { exact: true }).fill("");
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Edit instance number", exact: true })
    .click();
}
for (const { newer, elsewhere } of [
  { newer: false, elsewhere: false },
  { newer: true, elsewhere: false },
  { newer: false, elsewhere: true },
])
  test(`readback completion ${elsewhere ? "clears its original draft while another source is selected" : newer ? "preserves a newer unapplied draft" : "clears its completed draft"}`, async ({
    page,
    request,
  }) => {
    test.setTimeout(60000);
    const peer = await controlledPeer();
    const other = elsewhere ? await controlledPeer() : null;
    try {
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      });
      await page.goto("/");
      await page
        .getByRole("button", { name: /^Connect to a controller/ })
        .click();
      await page
        .getByLabel("Local bind address / UDP port", { exact: true })
        .fill(`127.0.0.1:${await freePort()}`);
      await page
        .getByRole("button", { name: "Open interface", exact: true })
        .click();
      await select(page, peer.port);
      const panel = page.getByRole("region", {
        name: "Device instance commissioning",
        exact: true,
      });
      const input = panel.getByLabel("New controller instance (0–4194302)", {
        exact: true,
      });
      await input.fill("15136");
      await panel
        .getByRole("button", { name: "Review instance change", exact: true })
        .click();
      await expect(
        panel.getByLabel("Reviewed instance change", { exact: true }),
      ).toBeVisible();
      await panel
        .getByRole("checkbox", {
          name: "I reserved this new number",
          exact: false,
        })
        .check();
      const applied = page.waitForResponse((response) =>
        response.url().endsWith("/device-instance/apply"),
      );
      await panel
        .getByRole("button", {
          name: "Apply controller instance change",
          exact: true,
        })
        .click();
      await expect.poll(peer.writes).toBe(1);
      await panel
        .getByRole("button", { name: "Cancel instance operation", exact: true })
        .click();
      await expect(
        panel.getByLabel("Instance change receipt", { exact: true }),
      ).toContainText("Result: unknown");
      const attempt = await (await applied).json();
      if (newer) await input.fill("15137");
      if (other) {
        await page
          .getByRole("button", { name: "Change controller", exact: true })
          .click();
        await select(page, other.port);
        await input.fill("15137");
        await panel
          .getByLabel("Retained instance receipts", { exact: true })
          .selectOption(attempt.id);
        await expect(
          panel.getByLabel("Instance change receipt", { exact: true }),
        ).toContainText(`127.0.0.1:${peer.port}`);
      }
      await peer.command("set-new");
      const finished = page.waitForResponse((response) =>
        response.url().endsWith("/device-instance/readback"),
      );
      await panel
        .getByRole("button", {
          name: "Read back instance (no write)",
          exact: true,
        })
        .click();
      expect((await (await finished).json()).readback.status).toBe(
        "verified_new",
      );
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText(other ? "device,5136" : "device,15136");
      if (other) await expect(input).toHaveValue("15137");
      await peer.command("set-old");
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      await select(page, peer.port);
      await expect(input).toHaveValue(newer ? "15137" : "");
      expect(peer.writes()).toBe(1);
      if (other) {
        await page
          .getByRole("button", { name: "Change controller", exact: true })
          .click();
        await select(page, other.port);
        await expect(input).toHaveValue("15137");
        expect(other.writes()).toBe(0);
      }
    } finally {
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      });
      await peer.close();
      await other?.close();
    }
  });
