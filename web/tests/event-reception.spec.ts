import { test, expect } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";

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
async function peer(routed: boolean) {
  const root = path.resolve("..");
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_event_reception import RawEvents,notification
class Peer(RawEvents):
    def datagram_received(self,data,source):
        super().datagram_received(data,source)
        print(json.dumps({"acks":len(self.acks),"frames":len(self.frames),"errors":[str(e) for e in self.errors]}),flush=True)
async def main():
    transport,peer=await asyncio.get_running_loop().create_datagram_endpoint(lambda:Peer(${routed ? "True" : "False"}),local_addr=("127.0.0.1",0))
    print(json.dumps({"endpoint":f"127.0.0.1:{peer.endpoint[1]}"}),flush=True)
    try:
        while True:
            line=await asyncio.to_thread(sys.stdin.readline)
            if not line: break
            peer.send(notification(confirmed=True,exceeding=-0.0))
            peer.send(notification(confirmed=False))
            peer.send(notification(confirmed=True,unknown=True,invoke=43))
    finally: transport.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const state = { acks: 0, frames: 0, errors: [] as string[] };
  const endpoint = await new Promise<string>((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Event peer did not start"));
    }, 5000);
    child.once("error", reject);
    child.stdout.on("data", (bytes) => {
      buffer += bytes.toString();
      while (buffer.includes("\n")) {
        const end = buffer.indexOf("\n");
        const message = JSON.parse(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
        if (message.endpoint) {
          clearTimeout(timer);
          resolve(message.endpoint);
        } else Object.assign(state, message);
      }
    });
  });
  return { child, endpoint, state };
}

for (const routed of [false, true]) {
  test(`${routed ? "Routed" : "Direct"} event UI explicitly listens, receives real events, stops and saves source-qualified evidence`, async ({
    page,
    request,
  }) => {
    const server = await peer(routed);
    const token = (await (await request.get("/api/session")).json()).token;
    const headers = { "X-Studio-Token": token };
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    try {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      await request.post("/api/bacnet/connect", {
        headers,
        data: { local_address: `127.0.0.1:${await freePort()}` },
      });
      await page.goto("/");
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      const panel = page.getByRole("region", {
        name: "Finite BACnet event reception",
        exact: true,
      });
      expect(server.state.frames).toBe(0);
      await panel
        .getByLabel("Event source address", { exact: true })
        .fill(routed ? "2001:4" : server.endpoint);
      await panel
        .getByLabel("Event source Device", { exact: true })
        .fill("device,4190010");
      await panel
        .getByLabel("Optional event object filter", { exact: true })
        .fill("analog-value,1");
      await panel
        .getByLabel("Listen duration in seconds", { exact: true })
        .fill("30");
      if (routed) {
        await panel
          .getByLabel("Event router endpoint", { exact: true })
          .fill(server.endpoint);
        await panel.getByLabel("Event DNET", { exact: true }).fill("2001");
      }
      await panel
        .getByRole("button", {
          name: "Verify identity and start finite listener",
          exact: true,
        })
        .click();
      const receipt = panel.getByRole("region", {
        name: /^Event reception receipt listen-/,
      });
      await expect(receipt).toContainText("State: listening");
      await expect(
        receipt.getByRole("button", {
          name: "Save stopped event receipt",
          exact: true,
        }),
      ).toBeDisabled();
      expect(server.state.frames).toBe(2);
      server.child.stdin.write("emit\n");
      await expect(receipt).toContainText("Received: 3");
      await expect.poll(() => server.state.acks).toBe(2);
      await panel
        .getByLabel("Event source address", { exact: true })
        .fill("127.0.0.1:49998");
      await receipt
        .getByRole("button", { name: "Stop event listener", exact: true })
        .click();
      await expect(receipt).toContainText("State: stopped");
      await receipt
        .getByRole("button", {
          name: "Save stopped event receipt",
          exact: true,
        })
        .click();
      await expect(receipt).toContainText("Saved immutable snapshot");
      const downloadPromise = page.waitForEvent("download");
      await receipt
        .getByRole("button", {
          name: "Export event reception receipt",
          exact: true,
        })
        .click();
      const file = await downloadPromise;
      const data = JSON.parse(readFileSync((await file.path())!, "utf8"));
      const verification = execFileSync(
        path.resolve("../.venv/bin/python"),
        [
          "-c",
          `
import hashlib,json,math,sys
data=json.load(open(sys.argv[1]))
seal=data.pop('saved_sha256'); data.pop('saved_at'); data.pop('auto_resume')
wire=json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
assert hashlib.sha256(wire).hexdigest()==seal
values=data['events'][0]['event_values']['value']
assert math.copysign(1,values['exceedingValue'])==-1
assert type(values['deadband']) is float and values['deadband']==2.0
print('native-floats-and-seal-verified')
`,
          (await file.path())!,
        ],
        { encoding: "utf8" },
      );
      expect(verification.trim()).toBe("native-floats-and-seal-verified");
      expect(data.received).toBe(3);
      expect(data.config.address).toBe(routed ? "2001:4" : server.endpoint);
      expect(data.events[2].event_values_decode_status).toBe("opaque");
      expect(data.events[0].operator_acknowledged).toBeNull();
      expect(data.events[0].source_clock_utc).toBeNull();
      expect(data.saved_sha256).toHaveLength(64);
      expect(server.state.errors).toEqual([]);
      expect(errors).toEqual([]);
      for (const change of ["source", "navigation"]) {
        let release!: () => void;
        let entered!: () => void;
        const gate = new Promise<void>((resolve) => {
          release = resolve;
        });
        const requested = new Promise<void>((resolve) => {
          entered = resolve;
        });
        const routePath = `**/api/bacnet/event-reception/snapshots/${data.id}`;
        await page.route(routePath, async (route) => {
          const response = await route.fetch();
          entered();
          await gate;
          await route.fulfill({ response });
        });
        const unexpected: string[] = [];
        const downloaded = (item: any) =>
          unexpected.push(item.suggestedFilename());
        page.on("download", downloaded);
        await receipt
          .getByRole("button", {
            name: "Export event reception receipt",
            exact: true,
          })
          .click();
        await requested;
        if (change === "source") {
          await page
            .getByLabel("Unicast target", { exact: true })
            .fill("127.0.0.1:49996");
          await expect(
            panel.getByLabel("Event source address", { exact: true }),
          ).toHaveValue("127.0.0.1:49996");
        } else {
          await page
            .getByRole("button", { name: "Program", exact: true })
            .click();
          await expect(panel).toHaveCount(0);
        }
        const refreshed = page.waitForResponse((response) =>
          response.url().endsWith("/api/bacnet/event-reception/status"),
        );
        release();
        await refreshed;
        expect(unexpected).toEqual([]);
        page.off("download", downloaded);
        await page.unroute(routePath);
        if (change === "source")
          await expect(
            receipt.getByRole("button", {
              name: "Export event reception receipt",
              exact: true,
            }),
          ).toBeEnabled();
      }
      await page.reload();
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      await panel
        .getByRole("button", { name: "Load saved event receipts", exact: true })
        .click();
      await panel
        .getByRole("button", { name: new RegExp(`^${data.id} ·`) })
        .click();
      await expect(
        panel.getByRole("region", {
          name: `Event reception receipt ${data.id}`,
        }),
      ).toContainText("Received: 3");
    } finally {
      server.child.kill();
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
    }
  });
}
