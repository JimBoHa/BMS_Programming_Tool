import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "./nativeScheduleWriteFixture";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
import { readFileSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import {
  seedDraft,
  openDraftCaf,
  editScalar,
  cafObjects,
} from "./caf-scalar-draft-recovery-fixture";
const root = path.resolve("..");
test.use({ holdPulseImport: true });
const backendEnvironment = () => ({
  ...process.env,
  PYTHONPATH: [
    process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
    root,
  ].join(path.delimiter),
});

async function pointTool(page: Page, label: string) {
  await chooseWorkspaceTask(page, "Points & I/O");
  const navigation = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  await expect(navigation).toBeVisible();
  const select = navigation.getByRole("combobox", {
    name: "Controller task tools",
    exact: true,
  });
  if (await select.isVisible()) await select.selectOption({ label });
  else
    await navigation.getByRole("button", { name: label, exact: true }).click();
  if (label === "Pulse metering review") {
    await expect(
      page.getByRole("heading", { name: "Pulse metering review", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("LOCAL SIMULATION", { exact: true }),
    ).toBeVisible();
  }
}
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
from tests.test_schedule_inventory import text,unsigned,oid,SchedulePeer
async def main():
 peer=await make_peer(routed=sys.argv[1]=='1',behavior=sys.argv[2]);original=peer.datagram_received
 peer.object_list=[(8,42),(23,1)]
 original_value=peer.value
 def value(obj,prop,index):
  if int(obj[0])==8:
   if prop in ('vendor-name','model-name','firmware-revision','application-software-version','location'):return text('Authored meter '+prop)
   if prop in ('vendor-identifier','protocol-revision','max-apdu-length-accepted'):return unsigned({'vendor-identifier':999,'protocol-revision':24,'max-apdu-length-accepted':1476}[prop])
   if prop in ('system-status','segmentation-supported'):return b'\\x91'+bytes([0 if prop=='system-status' else 3])
   if prop=='object-list':
    if index is None:return b''.join(b'\\xc4'+oid(*v) for v in peer.object_list)
    return SchedulePeer.value(peer,obj,prop,index)
  return original_value(obj,prop,index)
 peer.value=value
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
      env: backendEnvironment(),
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
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(routed ? "3001:7" : `127.0.0.1:${server.port}`);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,42");
  await page
    .getByLabel("Known router", { exact: true })
    .fill(routed ? `127.0.0.1:${server.port}` : "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Native device,42");
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(true);
  const acquisition = page.waitForResponse((r) =>
    r.url().endsWith("/api/bacnet/controller/inventory"),
  );
  await pointTool(page, "Detailed point evidence");
  const inventory = await (await acquisition).json();
  expect(inventory.identity_verified).toBe(true);
  expect(inventory.complete).toBe(true);
  expect(inventory.target).toEqual({
    address: routed ? "3001:7" : `127.0.0.1:${server.port}`,
    device: "device,42",
    router: routed ? `127.0.0.1:${server.port}` : null,
    dnet: routed ? 3001 : null,
  });
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
  await expect(
    panel.getByLabel("Point-status source address", { exact: true }),
  ).toHaveCount(0);
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
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await pointTool(page, "Pulse metering review");
  await expect(
    offline(page).getByRole("button", {
      name: "Review pulse batches",
      exact: true,
    }),
  ).toBeEnabled();
  return offline(page);
}
for (const compact of [false, true]) {
  test.describe(
    compact ? "compact pulse metering" : "desktop pulse metering",
    () => {
      test.use({
        viewport: compact
          ? { width: 412, height: 915 }
          : { width: 1440, height: 1000 },
      });
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
        await expect(result).toContainText(
          "retained PV 4 · numerator remainder 1",
        );
        const downloaded = page.waitForEvent("download");
        await p
          .getByRole("button", {
            name: "Export sealed pulse review",
            exact: true,
          })
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
            env: backendEnvironment(),
          },
        );
        const csvDownload = page.waitForEvent("download");
        await p
          .getByRole("button", { name: "Export pulse CSV", exact: true })
          .click();
        expect(
          readFileSync((await (await csvDownload).path())!, "utf8"),
        ).toContain("numerator");
        await page.reload();
        await page
          .getByRole("button", { name: "New application", exact: true })
          .click();
        await pointTool(page, "Pulse metering review");
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
            const verifiedReads = server.reads();
            expect(verifiedReads).toBeGreaterThan(0);
            await native
              .getByLabel("Selected native points", { exact: true })
              .fill("accumulator,1");
            await native
              .getByLabel(
                "Read native Accumulator prescale and metering metadata",
                {
                  exact: true,
                },
              )
              .check();
            expect(server.reads()).toBe(verifiedReads);
            const sent = page.waitForRequest((r) =>
              r.url().endsWith("/api/bacnet/point-status/read"),
            );
            await read(native);
            expect((await sent).postDataJSON()).toMatchObject({
              address: routed ? "3001:7" : `127.0.0.1:${server.port}`,
              device: "device,42",
              router: routed ? `127.0.0.1:${server.port}` : null,
              dnet: routed ? 3001 : null,
              object_ids: ["accumulator,1"],
              include_accumulator_metadata: true,
            });
            const count = server.reads();
            expect(count - verifiedReads).toBeGreaterThan(7);
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
              .getByRole("button", {
                name: "Review pulse batches",
                exact: true,
              })
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
            await pointTool(page, "Pulse metering review");
            const local = offline(page);
            await expect(
              local.getByLabel("Prescale multiplier", { exact: true }),
            ).toHaveValue("1");
            await expect(
              local.getByRole("button", { name: /^Use observed prescale/ }),
            ).toHaveCount(0);
            await local
              .getByLabel("Prescale multiplier", { exact: true })
              .fill("17");
            await local
              .getByRole("button", {
                name: "Review pulse batches",
                exact: true,
              })
              .click();
            await expect(
              local.getByLabel("Pulse review result", { exact: true }),
            ).toContainText("retained PV 25");
            const localFile = page.waitForEvent("download");
            await local
              .getByRole("button", {
                name: "Export sealed pulse review",
                exact: true,
              })
              .click();
            const localResult = JSON.parse(
              readFileSync((await (await localFile).path())!, "utf8"),
            );
            expect(localResult.native_source).toBeNull();
            expect(localResult.simulation.final_pv).toBe("25");
            expect(server.reads()).toBe(count);
            await pointTool(page, "Detailed point evidence");
            await expect(
              offline(page).getByLabel("Prescale multiplier", { exact: true }),
            ).toHaveValue("1");
            await expect(
              native.getByLabel("Native point evidence report", {
                exact: true,
              }),
            ).toHaveCount(0);
            await pointTool(page, "Pulse metering review");
            await expect(
              local.getByLabel("Prescale multiplier", { exact: true }),
            ).toHaveValue("17");
            await expect(
              local.getByLabel("Pulse review result", { exact: true }),
            ).toHaveCount(0);
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
          p.getByRole("button", {
            name: "Export sealed pulse review",
            exact: true,
          }),
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
        await page.route(
          "**/api/accumulator-prescale/review",
          async (route) => {
            const response = await route.fetch();
            seen();
            await gate;
            await route.fulfill({ response });
          },
        );
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
        await page.route(
          "**/api/accumulator-prescale/export/json",
          async (route) => {
            const response = await route.fetch();
            seenExport();
            await exportGate;
            await route.fulfill({ response });
          },
        );
        let downloads = 0;
        page.on("download", () => downloads++);
        await p
          .getByRole("button", {
            name: "Export sealed pulse review",
            exact: true,
          })
          .click();
        await exported;
        await chooseWorkspaceTask(page, "Program");
        releaseExport();
        await pointTool(page, "Pulse metering review");
        await expect(
          offline(page).getByLabel("Pulse review result", { exact: true }),
        ).toHaveCount(0);
        await expect(
          offline(page).getByLabel("Prescale multiplier", { exact: true }),
        ).toHaveValue("7");
        expect(downloads).toBe(0);
      });

      test("raw local declarations survive task and surface changes without restoring review authority", async ({
        page,
        request,
      }) => {
        const p = await openOffline(page);
        await p.getByLabel("Prescale multiplier", { exact: true }).fill("3");
        await p
          .getByRole("button", { name: "Review pulse batches", exact: true })
          .click();
        await expect(
          p.getByLabel("Pulse review result", { exact: true }),
        ).toContainText("retained PV 4");
        await chooseWorkspaceSurface(page, "Library");
        await chooseWorkspaceSurface(page, "Workspace");
        await pointTool(page, "Pulse metering review");
        await expect(
          p.getByLabel("Prescale multiplier", { exact: true }),
        ).toHaveValue("3");
        await expect(
          p.getByLabel("Pulse review result", { exact: true }),
        ).toHaveCount(0);
        await expect(
          p.getByRole("button", {
            name: "Export sealed pulse review",
            exact: true,
          }),
        ).toBeDisabled();
        await p.getByLabel("Prescale multiplier", { exact: true }).fill("1e-");
        await p
          .getByLabel("Synthetic initial PV", { exact: true })
          .fill("0008");
        await p
          .getByLabel("Pulse batches, one count per line", { exact: true })
          .fill("0001\ninvalid\n\n");
        await chooseWorkspaceTask(page, "Overview");
        await pointTool(page, "Pulse metering review");
        await expect(
          p.getByLabel("Prescale multiplier", { exact: true }),
        ).toHaveValue("1e-");
        await expect(
          p.getByLabel("Synthetic initial PV", { exact: true }),
        ).toHaveValue("0008");
        await expect(
          p.getByLabel("Pulse batches, one count per line", { exact: true }),
        ).toHaveValue("0001\ninvalid\n\n");
        await p
          .getByRole("button", { name: "Review pulse batches", exact: true })
          .click();
        await expect(p.getByRole("alert")).toBeVisible();
        await expect(
          p.getByRole("button", {
            name: "Export sealed pulse review",
            exact: true,
          }),
        ).toBeDisabled();
        expect(
          (await (await request.get("/api/session")).json()).field_network_open,
        ).toBe(false);
        await page.reload();
        await page
          .getByRole("button", { name: "New application", exact: true })
          .click();
        await pointTool(page, "Pulse metering review");
        await expect(
          p.getByLabel("Prescale multiplier", { exact: true }),
        ).toHaveValue("1");
        await expect(
          p.getByLabel("Pulse batches, one count per line", { exact: true }),
        ).toHaveValue("1\n1\n1");
      });

      test("a late configuration import cannot overwrite a newer local task draft", async ({
        page,
        request,
        nativeScheduleWriteServer,
      }) => {
        const p = await openOffline(page);
        await p.getByLabel("Prescale multiplier", { exact: true }).fill("3");
        await p
          .getByRole("button", { name: "Review pulse batches", exact: true })
          .click();
        await expect(
          p.getByLabel("Pulse review result", { exact: true }),
        ).toBeVisible();
        const file = page.waitForEvent("download");
        await p
          .getByRole("button", {
            name: "Export sealed pulse review",
            exact: true,
          })
          .click();
        const raw = readFileSync((await (await file).path())!);
        const gate = path.join(
            nativeScheduleWriteServer.directory,
            "hold-pulse-import",
          ),
          receipt = path.join(
            nativeScheduleWriteServer.directory,
            "pulse-import-processed.json",
          );
        writeFileSync(
          gate,
          "Hold this test's actual response after processing its original multipart upload.\n",
        );
        try {
          await p
            .getByLabel("Import pulse review configuration", { exact: true })
            .setInputFiles({
              name: "earlier.json",
              mimeType: "application/json",
              buffer: raw,
            });
          await expect.poll(() => existsSync(receipt)).toBe(true);
          expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
            status: 200,
            file_sha256: createHash("sha256").update(raw).digest("hex"),
          });
          await chooseWorkspaceTask(page, "Overview");
          await pointTool(page, "Pulse metering review");
          await p.getByLabel("Prescale multiplier", { exact: true }).fill("9");
          const delivery = page.waitForResponse((r) =>
            r.url().endsWith("/api/accumulator-prescale/import"),
          );
          rmSync(gate, { force: true });
          await (await delivery).finished();
          await page.evaluate(
            () =>
              new Promise<void>((r) =>
                requestAnimationFrame(() => requestAnimationFrame(() => r())),
              ),
          );
          await expect(
            p.getByLabel("Prescale multiplier", { exact: true }),
          ).toHaveValue("9");
          await expect(p.getByRole("status")).toHaveCount(0);
          await expect(
            p.getByLabel("Pulse review result", { exact: true }),
          ).toHaveCount(0);
          await chooseWorkspaceTask(page, "Overview");
          await pointTool(page, "Pulse metering review");
          await expect(
            p.getByLabel("Prescale multiplier", { exact: true }),
          ).toHaveValue("9");
          expect(
            (await (await request.get("/api/session")).json())
              .field_network_open,
          ).toBe(false);
        } finally {
          rmSync(gate, { force: true });
        }
      });
      test("coalesced tool changes retire a held export and completed review while keeping raw declarations", async ({
        page,
      }) => {
        const p = await openOffline(page);
        await p.getByLabel("Prescale multiplier", { exact: true }).fill("3");
        await p
          .getByRole("button", { name: "Review pulse batches", exact: true })
          .click();
        await expect(
          p.getByLabel("Pulse review result", { exact: true }),
        ).toContainText("retained PV 4");
        let release!: () => void, entered!: () => void;
        const received = new Promise<void>((r) => (entered = r)),
          gate = new Promise<void>((r) => (release = r));
        let downloads = 0;
        page.on("download", () => downloads++);
        await page.route(
          "**/api/accumulator-prescale/export/json",
          async (route) => {
            const response = await route.fetch();
            expect(response.status()).toBe(200);
            entered();
            await gate;
            await route.fulfill({ response });
          },
        );
        try {
          await p
            .getByRole("button", {
              name: "Export sealed pulse review",
              exact: true,
            })
            .click();
          await received;
          await page
            .getByRole("navigation", {
              name: "Controller task tools",
              exact: true,
            })
            .locator("select")
            .evaluate((element: HTMLSelectElement) => {
              element.value = "enum";
              element.dispatchEvent(new Event("change", { bubbles: true }));
              element.value = "pulse";
              element.dispatchEvent(new Event("change", { bubbles: true }));
            });
          await expect(
            p.getByLabel("Pulse review result", { exact: true }),
          ).toHaveCount(0);
          await expect(
            p.getByRole("button", {
              name: "Export sealed pulse review",
              exact: true,
            }),
          ).toBeDisabled();
          const delivery = page.waitForResponse((r) =>
            r.url().endsWith("/api/accumulator-prescale/export/json"),
          );
          release();
          await (await delivery).finished();
          await page.evaluate(
            () =>
              new Promise<void>((r) =>
                requestAnimationFrame(() => requestAnimationFrame(() => r())),
              ),
          );
          expect(downloads).toBe(0);
          await expect(
            p.getByLabel("Prescale multiplier", { exact: true }),
          ).toHaveValue("3");
          await p
            .getByRole("button", { name: "Review pulse batches", exact: true })
            .click();
          await expect(
            p.getByLabel("Pulse review result", { exact: true }),
          ).toContainText("retained PV 4");
        } finally {
          release();
          await page.unroute("**/api/accumulator-prescale/export/json");
        }
      });
      test("CAF and pulse drafts remain independent across both task views", async ({
        page,
        request,
      }) => {
        const f = seedDraft();
        await openDraftCaf(page, f.caf);
        await editScalar(page, "FLOAT_CMD", "3113", "12.5000");
        await pointTool(page, "Pulse metering review");
        const p = offline(page);
        await p.getByLabel("Prescale multiplier", { exact: true }).fill("3");
        await p
          .getByRole("button", { name: "Review pulse batches", exact: true })
          .click();
        await expect(
          p.getByLabel("Pulse review result", { exact: true }),
        ).toContainText("retained PV 4");
        await cafObjects(page);
        await page
          .getByRole("button", {
            name: "Inspect CAF object FLOAT_CMD",
            exact: true,
          })
          .click();
        await expect(
          page.getByLabel("CAF property 3113", { exact: true }),
        ).toHaveValue("12.5000");
        await pointTool(page, "Pulse metering review");
        await expect(
          p.getByLabel("Prescale multiplier", { exact: true }),
        ).toHaveValue("3");
        await expect(
          p.getByLabel("Pulse review result", { exact: true }),
        ).toHaveCount(0);
        await expect(
          p.getByRole("button", { name: /^Use observed prescale/ }),
        ).toHaveCount(0);
        expect(
          (await (await request.get("/api/session")).json()).field_network_open,
        ).toBe(false);
      });
    },
  );
}
