import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
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
async function rawRouter() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      String.raw`
import asyncio,json,sys
from tests.test_routed_discovery import RawRouter
class DiscoveryRouter(RawRouter):
    def datagram_received(self,data,address):
        packet=data[4:]
        # The joined Scan view now requests Device identity metadata. This
        # discovery-only peer explicitly rejects that read on the real wire.
        if len(packet)>=9 and packet[:2]==b'\x01\x24' and packet[4]==1:
            dnet=int.from_bytes(packet[2:4],'big');mac=packet[5:6];apdu=packet[7:]
            if len(apdu)==11 and apdu[0]&0xf0==0 and apdu[3]==12 and apdu[-2:]==b'\x19\x4b':
                try:
                    assert data[:2]==b'\x81\x0a' and int.from_bytes(data[2:4],'big')==len(data)
                    assert dnet==2105 and mac in (b'\x4f',b'\x50') and packet[6]==255
                    assert apdu[4]==12 and int.from_bytes(apdu[5:9],'big')==((8<<22)|(132000+mac[0]))
                    response=b'\x01\x08'+packet[2:6]+b'\x50'+apdu[2:3]+b'\x0c\x91\x02\x91\x20'
                    self.transport.sendto(b'\x81\x0a'+(len(response)+4).to_bytes(2,'big')+response,address)
                except Exception as error:self.errors.append(error)
                return
        super().datagram_received(data,address)
async def main():
    transport,peer=await asyncio.get_running_loop().create_datagram_endpoint(DiscoveryRouter,local_addr=('127.0.0.1',0))
    print(json.dumps({'router':peer.endpoint}),flush=True)
    try: await asyncio.to_thread(sys.stdin.readline)
    finally:
        transport.close()
        assert not peer.errors,peer.errors
        await asyncio.sleep(.05)
asyncio.run(main())
`,
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  let error = "";
  child.stderr.on("data", (data) => {
    error += data.toString();
  });
  const endpoint = await new Promise<string>((resolve, reject) => {
    let output = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Raw router startup timed out: " + error));
    }, 6000);
    child.stdout.on("data", (data) => {
      output += data.toString();
      if (!ready && output.includes("\n")) {
        ready = true;
        clearTimeout(timer);
        resolve(JSON.parse(output.split("\n")[0]).router);
      }
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Raw router exited ${code}: ${error}`));
    });
  });
  return {
    endpoint,
    async close() {
      const finished = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      child.stdin.end("close\n");
      const timer = setTimeout(() => child.kill(), 2000);
      const code = await finished;
      clearTimeout(timer);
      expect(code, error).toBe(0);
    },
  };
}

test("explicit routed discovery preserves cache uncertainty, bounded wire responses and hashed reports", async ({
  page,
  request,
}) => {
  const peer = await rawRouter();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByLabel("BBMD address / UDP port (optional)", { exact: true })
      .fill("");
    await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
    await page
      .getByLabel("MS/TP destination network (optional)", { exact: true })
      .fill("");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await expect(
      page.getByText("BACnet interface open", { exact: true }),
    ).toBeVisible();
    const panel = page.getByRole("region", {
      name: "Routed BACnet discovery",
      exact: true,
    });
    await panel
      .getByLabel("Discovery router address", { exact: true })
      .fill(peer.endpoint);
    await panel
      .getByRole("button", { name: "Read router networks", exact: true })
      .click();
    await expect(
      panel.getByLabel("Discovery router address", { exact: true }),
    ).toBeDisabled();
    const networks = panel.getByRole("region", {
      name: "Router network response",
      exact: true,
    });
    await expect(
      networks.getByRole("button", {
        name: "Select network 2105",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      networks.getByRole("button", {
        name: "Select network 2205",
        exact: true,
      }),
    ).toBeVisible();
    await expect(networks).toContainText("not a complete inventory");

    await panel
      .getByLabel("Discovery router device instance", { exact: true })
      .fill("505");
    await panel
      .getByRole("button", { name: "Read router cached bindings", exact: true })
      .click();
    const cache = panel.getByRole("region", {
      name: "Router cached address bindings",
      exact: true,
    });
    await expect(cache).toContainText("Unknown device instance");
    await expect(cache).toContainText("Cached · liveness unverified");
    await expect(cache).not.toContainText("device,4194303");
    const caching = page.waitForEvent("download");
    await cache
      .getByRole("button", {
        name: "Download cached bindings JSON",
        exact: true,
      })
      .click();
    const cached = JSON.parse(
      readFileSync((await (await caching).path())!, "utf8"),
    );
    expect(
      cached.report.bindings.some(
        (binding: any) => binding.device_instance === null,
      ),
    ).toBe(true);
    expect(
      cached.report.bindings.every(
        (binding: any) => binding.live_verified === false,
      ),
    ).toBe(true);
    expect(cached.report_sha256).toBe(
      createHash("sha256").update(JSON.stringify(cached.report)).digest("hex"),
    );
    await cache
      .getByRole("button", { name: "Select cached network 2105", exact: true })
      .click();
    await panel
      .getByLabel("Routed minimum device instance", { exact: true })
      .fill("132079");
    await panel
      .getByLabel("Routed maximum device instance", { exact: true })
      .fill("132080");
    await panel
      .getByLabel("Routed response window seconds", { exact: true })
      .fill("1");
    await panel
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    const report = panel.getByRole("region", {
      name: "Routed device response",
      exact: true,
    });
    await expect(report.locator("tbody tr")).toHaveCount(2);
    await expect(report).toContainText("2105:79");
    await expect(report).toContainText("device,132079");
    const downloading = page.waitForEvent("download");
    await report
      .getByRole("button", {
        name: "Download routed discovery JSON",
        exact: true,
      })
      .click();
    const archive = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    expect(archive.request).toMatchObject({
      router: peer.endpoint,
      dnet: 2105,
      low: 132079,
      high: 132080,
      timeout_seconds: 1,
    });
    expect(archive.report.devices).toHaveLength(2);
    expect(archive.report.complete).toBe(true);
    expect(archive.report_sha256).toBe(
      createHash("sha256").update(JSON.stringify(archive.report)).digest("hex"),
    );
    await report
      .getByRole("button", { name: "Use routed device 2105:79", exact: true })
      .click();
    await expect(
      page.getByLabel("Router IP (optional)", { exact: true }),
    ).toHaveValue(peer.endpoint);
    await expect(
      page.getByLabel("MS/TP destination network (optional)", { exact: true }),
    ).toHaveValue("2105");
    await expect(
      page.getByLabel("Unicast target", { exact: true }),
    ).toHaveValue("2105:79");
    await expect(
      page.getByRole("button", { name: "Read property", exact: true }),
    ).toBeDisabled();
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Read property", exact: true }),
    ).toBeEnabled();
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("analog-input,1");
    await page.getByLabel("Property", { exact: true }).fill("present-value");
    await page
      .getByRole("button", { name: "Read property", exact: true })
      .click();
    await expect(
      page
        .locator("pre.result")
        .filter({ hasText: '"property": "present-value"' }),
    ).toContainText('"value": 12.5');

    await panel
      .getByLabel("Routed device result limit", { exact: true })
      .fill("1");
    await panel
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    await expect(report).toContainText("Result truncated");
    await expect(report.locator("tbody tr")).toHaveCount(1);
    await panel
      .getByLabel("Routed destination network", { exact: true })
      .fill("2205");
    await panel
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    await expect(report).toContainText("No device replies were received");
    await expect(report).toContainText("does not prove the network is empty");
    await expect(report).toContainText(
      "Last reply none within the response window",
    );
    await expect(report.locator("tbody tr")).toHaveCount(0);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await peer.close();
  }
});
