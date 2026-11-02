import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";
const root = path.resolve("..");
const targets = new WeakMap<
  Page,
  {
    address: string;
    device: string;
    router: string | null;
    dnet: number | null;
  }
>();
test.afterEach(async ({ request }) => {
  const session = await (await request.get("/api/session")).json();
  const response = await request.post("/api/bacnet/disconnect", {
    headers: { "X-Studio-Token": session.token },
    data: {},
  });
  expect(response.ok()).toBe(true);
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
from tests.test_schedule_inventory import SchedulePeer,text,unsigned
class Peer(SchedulePeer):
 def value(self,obj,prop,index):
  if prop in ('model-name','firmware-revision','application-software-version','vendor-name','location'):return text('Authored')
  if prop=='protocol-revision':return unsigned(22)
  if prop=='max-apdu-length-accepted':return unsigned(480)
  if prop=='segmentation-supported':return b'\\x91\\x03'
  if prop=='vendor-identifier':return unsigned(5)
  if prop=='system-status':return b'\\x91\\x00'
  return super().value(obj,prop,index)
async def main():
 peer=Peer(routed=sys.argv[1]=='1',behavior='normal' if sys.argv[2]=='hold' else sys.argv[2])
 await asyncio.get_running_loop().create_datagram_endpoint(lambda:peer,local_addr=('127.0.0.1',0))
 original=peer.datagram_received
 def observed(data,source):
  print('READ',flush=True);original(data,source)
 peer.datagram_received=observed
 def mark():
  if sys.stdin.readline().strip()!='mark':raise AssertionError('Unknown authored peer command')
  if sys.argv[2]=='hold':peer.behavior='hold'
  print('MARK',flush=True)
 asyncio.get_running_loop().add_reader(sys.stdin.fileno(),mark)
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
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let count = 0,
    baseline = 0,
    marked: (() => void) | null = null;
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
        else if (line === "MARK") {
          baseline = count;
          marked?.();
          marked = null;
        }
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Schedule peer exited ${code}: ${error}`));
    });
  });
  return {
    port,
    reads: () => count - baseline,
    async mark() {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error("Authored peer mark timed out")),
          5000,
        );
        marked = () => {
          clearTimeout(timer);
          resolve();
        };
        child.stdin!.write("mark\n");
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
async function selectController(
  page: Page,
  server: { port: number },
  routed = false,
) {
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
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Native device,42");
  await chooseWorkspaceTask(page, "Schedules");
  targets.set(page, {
    address: routed ? "3001:7" : `127.0.0.1:${server.port}`,
    device: "device,42",
    router: routed ? `127.0.0.1:${server.port}` : null,
    dnet: routed ? 3001 : null,
  });
}
async function changeController(page: Page, server: { port: number }) {
  await page
    .getByRole("button", { name: "Change controller", exact: true })
    .click();
  await selectController(page, server);
}
async function open(
  page: Page,
  request: APIRequestContext,
  server: { port: number; mark: () => Promise<void> },
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
  const scheduleCalls: string[] = [];
  page.on("request", (request) => {
    if (
      /\/api\/bacnet\/schedules\/(read|read-diagnostics)$/.test(request.url())
    )
      scheduleCalls.push(request.url());
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await selectController(page, server, routed);
  const panel = page.getByRole("region", {
    name: "Native Calendar and Schedule inventory",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Read native schedules", exact: true }),
  ).toBeEnabled();
  const context = page.getByLabel("Working context", { exact: true });
  await expect(context).toContainText("device,42");
  await expect(context).toContainText(
    routed ? "3001:7" : `127.0.0.1:${server.port}`,
  );
  if (routed) await expect(context).toContainText(`127.0.0.1:${server.port}`);
  await panel
    .getByLabel("Calendar/Schedule object selection", { exact: true })
    .fill("calendar,1; schedule,1");
  expect(scheduleCalls).toEqual([]);
  // Opening a controller performs identity reads. Count subsequent schedule
  // requests separately, after an ordered acknowledgement from the owned peer.
  await server.mark();
  return panel;
}
async function read(panel: ReturnType<Page["getByRole"]>) {
  const page = panel.page();
  const response = page.waitForResponse((r) =>
    r.url().endsWith("/api/bacnet/schedules/read"),
  );
  await panel
    .getByRole("button", { name: "Read native schedules", exact: true })
    .click();
  expect((await response).request().postDataJSON()).toMatchObject(
    targets.get(page)!,
  );
  await expect(
    panel.getByLabel("Schedule evidence report", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Cancel schedule read", exact: true }),
  ).toBeDisabled();
}
test("native Calendar choices and numeric bytes survive actual browser download", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const panel = await open(page, request, server);
    expect(server.reads()).toBe(0);
    await read(panel);
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toContainText("Device identity verified");
    await expect(
      panel.getByText(
        "calendar,1 · all selected properties read · identity verified",
        { exact: true },
      ),
    ).toBeVisible();
    const pending = page.waitForEvent("download");
    await panel
      .getByRole("button", {
        name: "Export exact schedule evidence",
        exact: true,
      })
      .click();
    const file = (await (await pending).path())!;
    expect(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          `
import hashlib,json,math,sys
raw=open(sys.argv[1],'rb').read();d=json.loads(raw);seal=d.pop('evidence_sha256')
assert hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==seal
p=d['objects'][1]['properties'];assert math.copysign(1,p['present-value']['value']['value'])==-1
assert b'"value":-0.0' in raw and b'"value":2.0' in raw
assert d['objects'][0]['properties']['date-list']['value'][0]['value']['fields']==[255,13,32,255]
assert p['exception-schedule']['elements'][1]['value']['period']['type']=='calendarReference'
print('verified')
`,
          file,
        ],
        { encoding: "utf8" },
      ).trim(),
    ).toBe("verified");
    const count = server.reads();
    await panel
      .getByRole("button", {
        name: "Refresh retained schedule reports",
        exact: true,
      })
      .click();
    await panel
      .getByText("Retained reports and limits", { exact: true })
      .click();
    await panel
      .getByRole("button", { name: /^Open schedule report/ })
      .last()
      .click();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toBeVisible();
    expect(server.reads()).toBe(count);
  } finally {
    await server.close();
  }
});
test("routed native read retains endpoint DNET and opaque nested choices", async ({
  page,
  request,
}) => {
  const server = await peer(true, "unknown_any");
  try {
    const panel = await open(page, request, server, true);
    await read(panel);
    const evidence = panel.getByLabel("Schedule evidence report", {
      exact: true,
    });
    await expect(evidence).toContainText(
      `device,42 at 3001:7 via 127.0.0.1:${server.port} / DNET 3001`,
    );
    await expect(evidence).toContainText("partial");
    await panel
      .getByText(
        "Complete evidence, native choices, per-property failures and transport provenance",
        { exact: true },
      )
      .click();
    await expect(evidence).toContainText('"decode_status": "opaque"');
    await expect(evidence).toContainText('"npdu_source": "3001:7"');
  } finally {
    await server.close();
  }
});
for (const action of ["draft", "selection", "receipt", "navigation"] as const)
  test(`late exact export discarded after ${action} change`, async ({
    page,
    request,
  }) => {
    const server = await peer();
    let alternate: Awaited<ReturnType<typeof peer>> | null = null;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let entered!: () => void;
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      const panel = await open(page, request, server);
      await read(panel);
      if (action === "receipt") {
        await panel
          .getByRole("button", { name: "Read native schedules", exact: true })
          .click();
        await expect(
          panel.getByLabel("Schedule evidence report", { exact: true }),
        ).toBeVisible();
        await panel
          .getByRole("button", {
            name: "Refresh retained schedule reports",
            exact: true,
          })
          .click();
        await panel
          .getByText("Retained reports and limits", { exact: true })
          .click();
      }
      await page.route("**/api/bacnet/schedules/export", async (route) => {
        const response = await route.fetch();
        entered();
        await gate;
        await route.fulfill({ response });
      });
      await panel
        .getByRole("button", {
          name: "Export exact schedule evidence",
          exact: true,
        })
        .click();
      await started;
      if (action === "draft")
        await panel
          .getByLabel("Calendar/Schedule object selection", { exact: true })
          .fill("calendar,2");
      else if (action === "selection") {
        alternate = await peer();
        await changeController(page, alternate);
      } else if (action === "receipt")
        await panel
          .getByRole("button", { name: /^Open schedule report/ })
          .first()
          .click();
      else await chooseWorkspaceTask(page, "Program");
      release();
      await page.waitForTimeout(350);
      expect(downloads).toBe(0);
    } finally {
      release();
      await server.close();
      await alternate?.close();
    }
  });
test("cancel and navigation retire owned pending reads without retries", async ({
  page,
  request,
}) => {
  const server = await peer(false, "hold");
  try {
    const panel = await open(page, request, server);
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    await expect.poll(server.reads).toBe(1);
    await panel
      .getByRole("button", { name: "Cancel schedule read", exact: true })
      .click();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toContainText("cancelled");
    await page.waitForTimeout(150);
    expect(server.reads()).toBe(1);
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    await expect.poll(server.reads).toBe(2);
    const cancelled = page.waitForResponse((response) =>
      response.url().endsWith("/api/bacnet/schedules/cancel"),
    );
    await chooseWorkspaceSurface(page, "Library");
    expect((await cancelled).ok()).toBe(true);
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/schedules/profile")).json())
            .active_operation,
      )
      .toBeNull();
    await page.waitForTimeout(100);
    expect(server.reads()).toBe(2);
  } finally {
    await server.close();
  }
});

test("late read response cannot populate a newly selected source", async ({
  page,
  request,
}) => {
  const server = await peer();
  let alternate: Awaited<ReturnType<typeof peer>> | null = null;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let entered!: () => void;
  const started = new Promise<void>((resolve) => {
    entered = resolve;
  });
  try {
    const panel = await open(page, request, server);
    await page.route("**/api/bacnet/schedules/read", async (route) => {
      const response = await route.fetch();
      entered();
      await gate;
      await route.fulfill({ response });
    });
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    await started;
    alternate = await peer();
    await changeController(page, alternate);
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText(`127.0.0.1:${alternate.port}`);
    release();
    await expect(
      panel.getByRole("button", { name: "Read native schedules", exact: true }),
    ).toBeEnabled();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toHaveCount(0);
    expect(server.reads()).toBeGreaterThan(1);
  } finally {
    release();
    await server.close();
    await alternate?.close();
  }
});
