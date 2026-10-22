import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
const profiles = {
  history: {
    device: "device,4190101",
    object: "trend-log,1",
    panel: "BACnet history request",
    address: "History device address",
    zone: "History device clock timezone",
    reference: "History range reference",
    read: "Read device history",
    download: "Download device history JSON",
    save: "Save immutable history capture",
    capture: "Saved device history capture",
    load: "Open history capture",
  },
  "history-multiple": {
    device: "device,4190102",
    object: "trend-log-multiple,1",
    panel: "BACnet Trend Log Multiple history",
    address: "Multiple history device address",
    zone: "Multiple history clock timezone",
    reference: "Multiple history range reference",
    read: "Read multiple-channel history",
    download: "Export multiple-history JSON",
    save: "Save multiple-history capture",
    capture: "Saved multiple-history capture",
    load: "Load multiple-history capture",
  },
  "event-log": {
    device: "device,4190103",
    object: "event-log,1",
    panel: "BACnet Event Log history",
    address: "Event log device address",
    zone: "Event log logger timezone",
    reference: "Event log range reference",
    read: "Read event-log history",
    download: "Export event-log JSON",
    save: "Save event-log capture",
    capture: "Saved event-log capture",
    load: "Load event-log capture",
  },
};
type Profile = keyof typeof profiles;

async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as { port: number }).port;
      socket.close(() => resolve(port));
    });
  });
}
async function peer(
  profile: Profile,
  behavior = "normal",
): Promise<{ child: ChildProcess; port: number; reads: () => number }> {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.history_evidence_fixtures import numeric_peer
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
async def main():
 port=free_udp();server=numeric_peer(sys.argv[1],port);server.behavior=sys.argv[2]
 original=server.do_ReadRangeRequest
 async def tracked(request):
  print('RANGE',flush=True);await original(request)
 server.do_ReadRangeRequest=tracked
 print(port,flush=True)
 try: await asyncio.Event().wait()
 finally: close_application(server)
asyncio.run(main())
`,
      profile,
      behavior,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let reads = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let output = "",
      errors = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(errors || "Numeric peer startup timeout"));
    }, 5000);
    child.stderr!.on("data", (chunk) => {
      errors += String(chunk);
    });
    child.stdout!.on("data", (chunk) => {
      output += String(chunk);
      while (output.includes("\n")) {
        const index = output.indexOf("\n"),
          line = output.slice(0, index);
        output = output.slice(index + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "RANGE") reads++;
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Numeric peer ${code}: ${errors}`));
    });
  });
  return { child, port, reads: () => reads };
}
async function open(
  page: Page,
  request: APIRequestContext,
  profile: Profile,
  port: number,
) {
  const config = profiles[profile];
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const response = await request.post("/api/bacnet/connect", {
    headers,
    data: { local_address: `127.0.0.1:${await freePort()}` },
  });
  expect(response.ok()).toBe(true);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Device history", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: config.read, exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel(config.address, { exact: true })
    .fill(`127.0.0.1:${port}`);
  if (profile !== "history")
    await page
      .getByLabel(
        profile === "event-log"
          ? "Event log Device object"
          : "Multiple history Device object",
        { exact: true },
      )
      .fill(config.device);
  await page.getByLabel(config.zone, { exact: true }).fill("UTC");
  await page.getByLabel(config.reference, { exact: true }).fill("100");
  return headers;
}
async function read(page: Page, profile: Profile) {
  const url = `**/api/bacnet/${profile}/read`;
  let original!: Buffer;
  // Record the real response before Chromium stores it as a Blob. CDP may
  // otherwise expose an empty body for that binary response reader.
  await page.route(url, async (route) => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    original = await response.body();
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: profiles[profile].read, exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: profiles[profile].download, exact: true }),
  ).toBeEnabled();
  await page.unroute(url);
  return original;
}
async function download(
  page: Page,
  profile: Profile,
  original: Buffer,
  summaryHash?: string,
) {
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: profiles[profile].download, exact: true })
    .click();
  const file = (await (await pending).path())!;
  const reference = test
    .info()
    .outputPath(`${profile}-${summaryHash ? "capture" : "read"}-server.json`);
  writeFileSync(reference, original);
  // Independent Python JSON parsing and SHA-256, never the production hash helper
  // or JavaScript's number conversion, checks the actual browser file.
  const checked = JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import hashlib,json,math,sys
raw=open(sys.argv[1],'rb').read(); source=open(sys.argv[2],'rb').read()
assert raw==source, 'Browser changed authoritative response bytes'
report=json.loads(raw)
canonical=lambda obj:json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
if 'evidence_sha256' in report:
 assert hashlib.sha256(canonical({k:v for k,v in report.items() if k!='evidence_sha256'})).hexdigest()==report['evidence_sha256']
if sys.argv[4]: assert hashlib.sha256(canonical(report)).hexdigest()==sys.argv[4]
profile=sys.argv[3]
if profile=='history': values=[row['value'] for row in report['records']]
elif profile=='history-multiple': values=[row['channels'][0]['raw']['value'] for row in report['records']]
else: values=[row['notification']['event_values']['value']['exceedingValue'] for row in report['records'] if row['datum_type']=='notification']
assert all(type(value) is float for value in values)
assert values[0]==2.0 and math.copysign(1,values[1])==-1
if len(values)>2: assert 0<values[2]<1e-6 and values[3]>=1e20
print(json.dumps({'id':report['id'],'source_kind':report['source_kind']}))
`,
        file,
        reference,
        profile,
        summaryHash ?? "",
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  expect(checked.id).toBe(JSON.parse(original.toString()).id);
  const downloaded = readFileSync(file);
  writeFileSync(
    test
      .info()
      .outputPath(
        `${profile}-${summaryHash ? "capture" : "read"}-download.json`,
      ),
    downloaded,
  );
  return downloaded;
}

for (const profile of Object.keys(profiles) as Profile[]) {
  test(`${profile} downloads native numeric evidence and reopened captures without browser reserialization`, async ({
    page,
    request,
  }) => {
    const server = await peer(profile);
    let headers: Record<string, string> = {};
    try {
      headers = await open(page, request, profile, server.port);
      const original = await read(page, profile);
      const report = JSON.parse(original.toString());
      await download(page, profile, original);
      const saved = await request.post(`/api/bacnet/${profile}/save`, {
        headers,
        data: { id: report.id },
      });
      expect(saved.ok()).toBe(true);
      const summary = await saved.json();
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      await page.reload();
      await page
        .getByRole("button", { name: "Device history", exact: true })
        .click();
      const select = page.getByLabel(profiles[profile].capture, {
        exact: true,
      });
      await expect(select.locator(`option[value="${report.id}"]`)).toHaveCount(
        1,
      );
      await select.selectOption(report.id);
      const captured = await (
        await request.get(`/api/bacnet/${profile}/captures/${report.id}`)
      ).body();
      await page
        .getByRole("button", { name: profiles[profile].load, exact: true })
        .click();
      await expect(
        page.getByRole("button", {
          name: profiles[profile].download,
          exact: true,
        }),
      ).toBeEnabled();
      await download(page, profile, captured, summary.sha256);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      await select.selectOption("");
      if (profile === "history")
        await expect(
          page.getByRole("button", {
            name: profiles[profile].download,
            exact: true,
          }),
        ).toHaveCount(0);
      else
        await expect(
          page.getByRole("button", {
            name: profiles[profile].download,
            exact: true,
          }),
        ).toBeDisabled();
    } finally {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      server.child.kill();
    }
  });

  if (profile !== "history")
    test(`${profile} cancelled partial reports retain the exact completed numeric evidence`, async ({
      page,
      request,
    }) => {
      const server = await peer(profile, "hold-second");
      let headers: Record<string, string> = {};
      try {
        headers = await open(page, request, profile, server.port);
        const pending = read(page, profile);
        await expect.poll(server.reads).toBe(2);
        await page
          .getByRole("button", {
            name:
              profile === "event-log"
                ? "Cancel event-log read"
                : "Cancel multiple-history read",
            exact: true,
          })
          .click();
        const original = await pending;
        const report = JSON.parse(original.toString());
        expect(report.complete).toBe(false);
        expect(report.records).toHaveLength(2);
        expect(report.status).toBe("cancelled");
        await download(page, profile, original);
        expect(server.reads()).toBe(2);
      } finally {
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
        server.child.kill();
      }
    });

  test(`${profile} rejects a wrapper or unrelated capture and never revives a delayed document after navigation`, async ({
    page,
    request,
  }) => {
    const server = await peer(profile);
    let release = () => {};
    let headers: Record<string, string> = {};
    try {
      headers = await open(page, request, profile, server.port);
      const original = await read(page, profile);
      const report = JSON.parse(original.toString());
      await request.post(`/api/bacnet/${profile}/save`, {
        headers,
        data: { id: report.id },
      });
      const url = `**/api/bacnet/${profile}/read`;
      await page.route(url, (route) => route.fulfill({ json: { report } }));
      await page
        .getByRole("button", { name: profiles[profile].read, exact: true })
        .click();
      await expect(page.getByRole("alert")).toContainText(
        "does not identify the requested report",
      );
      if (profile === "history")
        await expect(
          page.getByRole("button", {
            name: profiles[profile].download,
            exact: true,
          }),
        ).toHaveCount(0);
      else
        await expect(
          page.getByRole("button", {
            name: profiles[profile].download,
            exact: true,
          }),
        ).toBeDisabled();
      await page.unroute(url);
      for (const failure of [
        {
          status: 200,
          contentType: "application/json",
          body: '{"broken":',
          expected: /JSON|Unexpected/,
        },
        {
          status: 409,
          contentType: "application/json",
          body: '{"detail":"Authored unavailable history"}',
          expected: /Authored unavailable history/,
        },
        {
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...report, profile: "unrelated-profile/1" }),
          expected: /does not identify the requested report/,
        },
        ...(profile === "history"
          ? [
              {
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                  ...report,
                  request: { ...report.request, address: "127.0.0.2" },
                  target: { ...report.target, address: "127.0.0.2" },
                }),
                expected: /source differs from the submitted request/,
              },
              {
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                  ...report,
                  target: { ...report.target, object_id: "trend-log,2" },
                }),
                expected: /source differs from the submitted request/,
              },
            ]
          : [
              {
                status: 200,
                contentType: "application/json",
                body: original.toString(),
                expected: /source differs from the submitted request/,
              },
            ]),
      ]) {
        const { expected, ...response } = failure;
        await page.route(url, (route) => route.fulfill(response));
        await page
          .getByRole("button", { name: profiles[profile].read, exact: true })
          .click();
        await expect(page.getByRole("alert")).toContainText(expected);
        await page.unroute(url);
      }
      await page.reload();
      await page
        .getByRole("button", { name: "Device history", exact: true })
        .click();
      await page
        .getByLabel(profiles[profile].capture, { exact: true })
        .selectOption(report.id);
      const captureUrl = `**/api/bacnet/${profile}/captures/${report.id}`;
      await page.route(captureUrl, (route) =>
        route.fulfill({ json: { ...report, id: "f".repeat(32) } }),
      );
      await page
        .getByRole("button", { name: profiles[profile].load, exact: true })
        .click();
      await expect(page.getByRole("alert")).toContainText(
        "does not identify the requested report",
      );
      await page.unroute(captureUrl);
      let entered!: () => void;
      const received = new Promise<void>((resolve) => {
        entered = resolve;
      });
      const held = new Promise<void>((resolve) => {
        release = resolve;
      });
      let delivered!: () => void;
      const completed = new Promise<void>((resolve) => {
        delivered = resolve;
      });
      await page.route(captureUrl, async (route) => {
        const response = await route.fetch();
        entered();
        await held;
        await route.fulfill({ response });
        delivered();
      });
      await page
        .getByRole("button", { name: profiles[profile].load, exact: true })
        .click();
      await received;
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      release();
      await completed;
      await page.unroute(captureUrl);
      await page
        .getByRole("button", { name: "Device history", exact: true })
        .click();
      if (profile === "history")
        await expect(
          page.getByRole("button", {
            name: profiles[profile].download,
            exact: true,
          }),
        ).toHaveCount(0);
      else
        await expect(
          page.getByRole("button", {
            name: profiles[profile].download,
            exact: true,
          }),
        ).toBeDisabled();
      await expect(
        page.getByLabel(profiles[profile].capture, { exact: true }),
      ).toHaveValue("");
    } finally {
      release();
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      server.child.kill();
    }
  });
}
