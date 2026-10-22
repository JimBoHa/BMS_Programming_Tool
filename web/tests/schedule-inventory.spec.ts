import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
const root = path.resolve("..");
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
from tests.test_schedule_inventory import make_peer
async def main():
 peer=await make_peer(routed=sys.argv[1]=='1',behavior=sys.argv[2]);original=peer.datagram_received
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
    name: "Native Calendar and Schedule inventory",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Read native schedules", exact: true }),
  ).toBeEnabled();
  await panel
    .getByLabel("Schedule source address", { exact: true })
    .fill(routed ? "3001:7" : `127.0.0.1:${server.port}`);
  await panel
    .getByLabel("Schedule Device identifier", { exact: true })
    .fill("device,42");
  if (routed) {
    await panel
      .getByLabel("Schedule router endpoint", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await panel.getByLabel("Schedule DNET", { exact: true }).fill("3001");
  }
  await panel
    .getByLabel("Calendar/Schedule object selection", { exact: true })
    .fill("calendar,1; schedule,1");
  return panel;
}
async function read(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", { name: "Read native schedules", exact: true })
    .click();
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
    server.process.kill();
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
    server.process.kill();
  }
});
for (const action of ["draft", "selection", "receipt", "navigation"] as const)
  test(`late exact export discarded after ${action} change`, async ({
    page,
    request,
  }) => {
    const server = await peer();
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
          .getByLabel("Schedule Device identifier", { exact: true })
          .fill("device,43");
      else if (action === "selection")
        await page
          .getByLabel("Unicast target", { exact: true })
          .fill("127.0.0.1:47809");
      else if (action === "receipt")
        await panel
          .getByRole("button", { name: /^Open schedule report/ })
          .first()
          .click();
      else
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
      release();
      await page.waitForTimeout(350);
      expect(downloads).toBe(0);
    } finally {
      release();
      server.process.kill();
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
    await page.getByRole("button", { name: "Program", exact: true }).click();
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
    server.process.kill();
  }
});

test("late read response cannot populate a newly selected source", async ({
  page,
  request,
}) => {
  const server = await peer();
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
    await page
      .getByLabel("Unicast target", { exact: true })
      .fill("127.0.0.1:47809");
    await expect(
      panel.getByLabel("Schedule source address", { exact: true }),
    ).toHaveValue("127.0.0.1:47809");
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
    server.process.kill();
  }
});
