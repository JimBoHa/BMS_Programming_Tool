import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
import { readFileSync } from "node:fs";
const root = path.resolve("..");
test.afterEach(async ({ request }) => {
  const token = (await (await request.get("/api/session")).json()).token;
  const closed = await request.post("/api/bacnet/disconnect", {
    headers: { "X-Studio-Token": token },
    data: {},
  });
  expect(
    closed.ok(),
    "This test's loopback interface must close even after failures",
  ).toBe(true);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as any).port;
      socket.close(() => resolve(port));
    });
  });
}
async function peer(routed = false, behavior = "normal") {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_accumulator_prescale import make_meter_peer as make_peer
async def main():
 peer=await make_peer(routed=sys.argv[1]=='1',behavior=sys.argv[2]);original=peer.datagram_received
 if sys.argv[2]=='unsupported': peer.behavior='native_error';peer.corrupt_property='reliability'
 def observed(data,source):
  print('READ',flush=True);original(data,source)
 peer.datagram_received=observed
 print(peer.endpoint.split(':')[-1],flush=True)
 try: await asyncio.Event().wait()
 finally: peer.close()
asyncio.run(main())
`,
      routed ? "1" : "0",
      behavior,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let count = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let pending = "",
      error = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Schedule peer startup " + error));
    }, 5000);
    child.stderr!.on("data", (value) => {
      error += String(value);
    });
    child.stdout!.on("data", (value) => {
      pending += String(value);
      while (pending.includes("\n")) {
        const end = pending.indexOf("\n"),
          line = pending.slice(0, end);
        pending = pending.slice(end + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "READ") count++;
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Schedule peer exited ${code}: ${error}`));
    });
  });
  return { process: child, port, reads: () => count };
}
async function open(
  page: Page,
  request: APIRequestContext,
  server: { port: number },
  routed = false,
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post("/api/bacnet/connect", {
        headers,
        data: { local_address: `127.0.0.1:${await freePort()}` },
      })
    ).ok(),
  ).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Native point status inspection",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Inspect native point status",
      exact: true,
    }),
  ).toBeEnabled();
  await panel
    .getByLabel("Point-status source address", { exact: true })
    .fill(routed ? "3001:7" : `127.0.0.1:${server.port}`);
  await panel
    .getByLabel("Point-status Device identifier", { exact: true })
    .fill("device,42");
  if (routed) {
    await panel
      .getByLabel("Point-status router endpoint", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await panel.getByLabel("Point-status DNET", { exact: true }).fill("3001");
  }
  await panel
    .getByLabel("Selected native points", { exact: true })
    .fill("analog-input,1; analog-output,2");
  return panel;
}
async function read(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", { name: "Inspect native point status", exact: true })
    .click();
  await expect(
    panel.getByLabel("Native point evidence report", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Cancel point inspection", exact: true }),
  ).toBeDisabled();
}
const offline = (page: Page) =>
  page.getByRole("region", {
    name: "Offline Accumulator pulse review",
    exact: true,
  });
async function openOffline(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    offline(page).getByRole("button", {
      name: "Review pulse batches",
      exact: true,
    }),
  ).toBeEnabled();
  return offline(page);
}
test("offline carried pulses export sealed arithmetic and import configuration only", async ({
  page,
  request,
}) => {
  const p = await openOffline(page);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await p.getByLabel("Prescale multiplier", { exact: true }).fill("3");
  await p
    .getByRole("button", { name: "Review pulse batches", exact: true })
    .click();
  const result = p.getByLabel("Pulse review result", { exact: true });
  await expect(result).toContainText("retained PV 4 · numerator remainder 1");
  const downloaded = page.waitForEvent("download");
  await p
    .getByRole("button", { name: "Export sealed pulse review", exact: true })
    .click();
  const file = await (await downloaded).path();
  if (!file) throw Error("Missing pulse review download");
  const raw = readFileSync(file);
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `
import json,sys
from bms_tool.accumulator_prescale import canonical,calculate,digest,PROFILE
raw=open(sys.argv[1],'rb').read();d=json.loads(raw)
assert raw==canonical(d)+b'\\n'
assert d['content_sha256']==digest({k:v for k,v in d.items() if k!='content_sha256'})
assert d['profile']==PROFILE and d['simulation']==calculate(d['configuration'])
assert [(r['retained_pv'],r['retained_remainder']) for r in d['simulation']['rows']]==[('1','1'),('3','0'),('4','1')]
`,
      file,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const csvDownload = page.waitForEvent("download");
  await p
    .getByRole("button", { name: "Export pulse CSV", exact: true })
    .click();
  expect(readFileSync((await (await csvDownload).path())!, "utf8")).toContain(
    "numerator",
  );
  await page.reload();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await offline(page)
    .getByLabel("Import pulse review configuration", { exact: true })
    .setInputFiles({
      name: "review.json",
      mimeType: "application/json",
      buffer: raw,
    });
  await expect(offline(page).getByRole("status")).toContainText(
    "Imported configuration only",
  );
  await expect(
    offline(page).getByLabel("Prescale multiplier", { exact: true }),
  ).toHaveValue("3");
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
for (const routed of [false, true])
  test(`explicit ${routed ? "routed" : "direct"} native metering remains independent from simulated state`, async ({
    page,
    request,
  }) => {
    const server = await peer(routed);
    try {
      const native = await open(page, request, server, routed),
        p = offline(page);
      expect(server.reads()).toBe(0);
      await native
        .getByLabel("Selected native points", { exact: true })
        .fill("accumulator,1");
      await native
        .getByLabel("Read native Accumulator prescale and metering metadata", {
          exact: true,
        })
        .check();
      await read(native);
      const count = server.reads();
      expect(count).toBeGreaterThan(7);
      await p
        .getByRole("button", {
          name: "Use observed prescale accumulator,1",
          exact: true,
        })
        .click();
      await expect(
        p.getByLabel("Prescale multiplier", { exact: true }),
      ).toHaveValue("3");
      await expect(
        p.getByLabel("Synthetic initial PV", { exact: true }),
      ).toHaveValue("0");
      await p
        .getByRole("button", { name: "Review pulse batches", exact: true })
        .click();
      await expect(
        p.getByLabel("Pulse review result", { exact: true }),
      ).toContainText("retained PV 4");
      const download = page.waitForEvent("download");
      await p
        .getByRole("button", {
          name: "Export sealed pulse review",
          exact: true,
        })
        .click();
      const raw = readFileSync((await (await download).path())!, "utf8"),
        d = JSON.parse(raw);
      expect(raw).toContain('"value":-0.0');
      expect(d.native_source.properties["present-value"].value).toBe(900);
      expect(d.simulation.final_pv).toBe("4");
      expect(server.reads()).toBe(count);
    } finally {
      server.process.kill();
    }
  });
test("declared limit rejects whole batch and invalid input never reuses review", async ({
  page,
}) => {
  const p = await openOffline(page);
  await p.getByLabel("Prescale multiplier", { exact: true }).fill("3");
  await p.getByLabel("Synthetic initial PV", { exact: true }).fill("8");
  await p.getByLabel("Declared maximum PV", { exact: true }).fill("10");
  await p
    .getByRole("button", { name: "Review pulse batches", exact: true })
    .click();
  await expect(
    p.getByLabel("Pulse review result", { exact: true }),
  ).toContainText("retained PV 9 · numerator remainder 1");
  await expect(
    p.getByLabel("Pulse review result", { exact: true }),
  ).toContainText("declared_limit_exceeded");
  await expect(
    p.getByLabel("Pulse review result", { exact: true }),
  ).toContainText("not_evaluated_after_limit");
  await p.getByLabel("Prescale modulo divide", { exact: true }).fill("0");
  await expect(
    p.getByRole("button", { name: "Export sealed pulse review", exact: true }),
  ).toBeDisabled();
  await p
    .getByRole("button", { name: "Review pulse batches", exact: true })
    .click();
  await expect(p.getByRole("alert")).toContainText("greater than zero");
});
test("late review and unmounted export cannot restore old configuration", async ({
  page,
}) => {
  const p = await openOffline(page);
  let release!: () => void, seen!: () => void;
  const entered = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r));
  await page.route("**/api/accumulator-prescale/review", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
  });
  await p
    .getByRole("button", { name: "Review pulse batches", exact: true })
    .click();
  await entered;
  await p.getByLabel("Prescale multiplier", { exact: true }).fill("7");
  release();
  await expect(
    p.getByLabel("Pulse review result", { exact: true }),
  ).toHaveCount(0);
  await page.unroute("**/api/accumulator-prescale/review");
  await p
    .getByRole("button", { name: "Review pulse batches", exact: true })
    .click();
  await expect(
    p.getByLabel("Pulse review result", { exact: true }),
  ).toBeVisible();
  let releaseExport!: () => void, seenExport!: () => void;
  const exported = new Promise<void>((r) => (seenExport = r)),
    exportGate = new Promise<void>((r) => (releaseExport = r));
  await page.route("**/api/accumulator-prescale/export/json", async (route) => {
    const response = await route.fetch();
    seenExport();
    await exportGate;
    await route.fulfill({ response });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await p
    .getByRole("button", { name: "Export sealed pulse review", exact: true })
    .click();
  await exported;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  releaseExport();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    offline(page).getByLabel("Pulse review result", { exact: true }),
  ).toHaveCount(0);
  expect(downloads).toBe(0);
});
