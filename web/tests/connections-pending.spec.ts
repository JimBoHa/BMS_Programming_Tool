import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
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

async function commandablePeer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `import asyncio,json,sys
from tests.test_connections import application,point,free_udp
from tests.test_foreign_bacnet import RawBBMD
async def main():
    port=free_udp()
    app=application(port,4190010)
    app.add_object(point())
    bt,bbmd=await asyncio.get_running_loop().create_datagram_endpoint(lambda:RawBBMD(None),local_addr=('127.0.0.1',0))
    await asyncio.sleep(.05)
    print(json.dumps({'port':port,'bbmd':bbmd.address[1]}),flush=True)
    try:
        await asyncio.to_thread(sys.stdin.readline)
    finally:
        app.close()
        bt.close()
        await asyncio.sleep(.05)
asyncio.run(main())`,
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  const ports = await new Promise<{ port: number; bbmd: number }>(
    (resolve, reject) => {
      let output = "",
        error = "",
        ready = false;
      const timer = setTimeout(() => {
        child.kill();
        reject(
          new Error("Loopback commandable peer startup timed out: " + error),
        );
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
        if (!ready) reject(new Error(`Loopback peer exited ${code}: ${error}`));
      });
    },
  );
  return { child, ...ports };
}

test("pending real BACnet preflight keeps point identity and transport drafts fixed until reviewed", async ({
  page,
  request,
}) => {
  const peer = await commandablePeer();
  const target = `127.0.0.1:${peer.port}`;
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let release!: () => void, received!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const captured = new Promise<void>((resolve) => {
    received = resolve;
  });
  let holdFirst = true;
  await page.route("**/api/bacnet/write-plan", async (route) => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    const plan = await response.json();
    expect(plan.address).toBe(target);
    expect(plan.object).toBe("analog-value,1");
    if (holdFirst) {
      holdFirst = false;
      received();
      await held;
    }
    await route.fulfill({ response });
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
    await page
      .getByLabel("MS/TP destination network (optional)", { exact: true })
      .fill("");
    await page
      .getByLabel("BBMD address / UDP port (optional)", { exact: true })
      .fill(`127.0.0.1:${peer.bbmd}`);
    await page
      .getByLabel("Foreign registration TTL (seconds)", { exact: true })
      .fill("1");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await expect(
      page.getByLabel("BACnet foreign registration status"),
    ).toContainText("Foreign registration active");
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(
      page.getByText("No BACnet interface open", { exact: true }),
    ).toBeVisible();
    // A former nondefault TTL must not prevent ordinary BACnet/IP connection
    // after the BBMD is cleared and its TTL control disappears.
    await page
      .getByLabel("BBMD address / UDP port (optional)", { exact: true })
      .fill("");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await expect(
      page.getByText("BACnet interface open", { exact: true }),
    ).toBeVisible();
    await page.getByLabel("Unicast target", { exact: true }).fill(target);
    await page
      .getByRole("button", { name: "Who-Is target", exact: true })
      .click();
    const discovered = page.getByRole("row").filter({ hasText: "4190010" });
    await expect(discovered).toContainText(target);
    await page.getByLabel("Command value", { exact: true }).fill("42.25");
    await page
      .getByRole("button", { name: "Preview command", exact: true })
      .click();
    await captured;
    // The request already made real priority/value/name BACnet reads. Only its
    // actual HTTP delivery is delayed; backend semantics are never fabricated.
    for (const label of [
      "Unicast target",
      "Object identifier",
      "Property",
      "Command value",
      "BACnet priority",
      "Local bind address / UDP port",
      "BBMD address / UDP port (optional)",
      "MS/TP master MAC",
    ]) {
      await expect(page.getByLabel(label, { exact: true })).toBeDisabled();
    }
    for (const name of ["MS/TP serial port", "MS/TP baud rate"]) {
      await expect(
        page.getByRole("combobox", { name, exact: true }),
      ).toBeDisabled();
    }
    await discovered.click({ force: true });
    await expect(
      page.getByLabel("Unicast target", { exact: true }),
    ).toHaveValue(target);
    await expect(
      page.getByLabel("Object identifier", { exact: true }),
    ).toHaveValue("analog-value,1");
    await expect(page.getByLabel("Property", { exact: true })).toHaveValue(
      "present-value",
    );
    const response = page.waitForResponse((response) =>
      response.url().endsWith("/api/bacnet/write-plan"),
    );
    release();
    await (await response).finished();
    const apply = page.getByRole("button", {
      name: "Apply previewed command",
      exact: true,
    });
    await expect(apply).toBeEnabled();
    await expect(
      page.getByLabel("Unicast target", { exact: true }),
    ).toBeEnabled();
    // Once editing resumes, a changed target invalidates the completed plan.
    await page
      .getByLabel("Unicast target", { exact: true })
      .fill("127.0.0.1:1");
    await expect(apply).toHaveCount(0);
    await page.getByLabel("Unicast target", { exact: true }).fill(target);
    await page
      .getByRole("button", { name: "Preview command", exact: true })
      .click();
    await expect(apply).toBeEnabled();
    await apply.click();
    await expect(page.locator(".owned-command")).toContainText(
      "analog-value,1",
    );
    const read = await request.post("/api/bacnet/read", {
      headers,
      data: { address: target, object_id: "analog-value,1" },
    });
    expect((await read.json()).value).toBe(42.25);
    await page.getByRole("button", { name: "Relinquish", exact: true }).click();
    await expect(page.locator(".owned-command")).toHaveCount(0);
    const restored = await request.post("/api/bacnet/read", {
      headers,
      data: { address: target, object_id: "analog-value,1" },
    });
    expect((await restored.json()).value).toBe(12.5);
  } finally {
    release();
    const status = await (await request.get("/api/bacnet/status")).json();
    for (const command of status.commands) {
      await request.post("/api/bacnet/release", {
        headers,
        data: { token: command.id },
      });
    }
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.child.stdin.end("close\n");
    peer.child.kill();
  }
});
