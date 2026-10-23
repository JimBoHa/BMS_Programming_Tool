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
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../..", import.meta.url));
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
from tests.test_point_status import make_point_peer as make_peer
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

async function stop(server: Awaited<ReturnType<typeof peer>>) {
  if (server.process.exitCode !== null) return;
  const exited = new Promise<void>((resolve) =>
    server.process.once("exit", () => resolve()),
  );
  server.process.kill();
  await exited;
}
for (const routed of [false, true]) {
  test(`opt-in ${routed ? "routed" : "direct"} trace downloads original envelope and exact native core bytes`, async ({
    page,
    request,
  }) => {
    const server = await peer(routed);
    try {
      const panel = await open(page, request, server, routed);
      const toggle = panel.getByLabel(
        "Include diagnostic trace for this read",
        { exact: true },
      );
      await expect(toggle).not.toBeChecked();
      await toggle.check();
      await page.request.get("/api/session");
      expect(server.reads()).toBe(0);
      await panel
        .getByText("Read optional priority slots and relinquish defaults", {
          exact: true,
        })
        .check();
      let received: Buffer | undefined;
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
            maxRedirects: 0,
            maxRetries: 0,
          });
          expect(response.status()).toBe(200);
          received = await response.body();
          expect(received.length).toBe(
            Number(response.headers()["content-length"]),
          );
          await route.fulfill({ response, body: received });
        },
      );
      await read(panel);
      expect(received).toBeDefined();
      const original = received!,
        envelope = JSON.parse(original.toString());
      const core = Buffer.from(envelope.core_report_json, "utf8"),
        report = JSON.parse(envelope.core_report_json);
      await expect(
        panel.getByRole("region", {
          name: "Read diagnostic trace",
          exact: true,
        }),
      ).toContainText("Diagnostic capture truncated");
      expect(report.complete).toBe(true);
      await expect.poll(server.reads).toBe(report.read_budget.requests);
      const count = server.reads();
      let downloading = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        })
        .click();
      const file = (await (await downloading).path())!;
      expect(readFileSync(file)).toEqual(original);
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "import json,hashlib,sys;r=json.load(open(sys.argv[1]));b=r['core_report_json'].encode();assert hashlib.sha256(b).hexdigest()==r['core_report_sha256'];c=json.loads(b);assert c['id']==r['core_report_id'];assert r['trace']['profile']=='studio-readproperty-phase-trace/1';assert 'not all UDP ingress' in r['trace']['visibility'];assert 'trace' not in c;u=dict(c);s=u.pop('evidence_sha256');assert hashlib.sha256(json.dumps(u,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==s",
          file,
        ],
        { cwd: root },
      );
      downloading = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Export exact point evidence",
          exact: true,
        })
        .click();
      const coreFile = (await (await downloading).path())!;
      expect(readFileSync(coreFile)).toEqual(core);
      expect(core.toString()).toContain('"value":-0.0');
      expect(core.toString()).toContain('"value":2.0');
      expect(server.reads()).toBe(count);
      await toggle.uncheck();
      await expect(
        panel.getByRole("region", {
          name: "Read diagnostic trace",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(server.reads()).toBe(count);
    } finally {
      await stop(server);
    }
  });
}

test("default-off keeps the original native read endpoint and does not manufacture a trace", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const panel = await open(page, request, server);
    const receiving = page.waitForResponse((r) =>
      r.url().endsWith("/api/bacnet/point-status/read"),
    );
    await read(panel);
    const report = await (await receiving).json();
    expect(report.profile).toBe("native-point-status/1");
    expect(report.format).toBeUndefined();
    await expect(
      panel.getByRole("region", { name: "Read diagnostic trace", exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Download original diagnostic bundle",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    await stop(server);
  }
});

for (const action of ["source", "navigation"]) {
  test(`held diagnostic ${action} reply cannot repopulate stale evidence or downloads`, async ({
    page,
    request,
  }) => {
    const server = await peer();
    let release!: () => void;
    try {
      const panel = await open(page, request, server);
      await panel
        .getByLabel("Include diagnostic trace for this read", { exact: true })
        .check();
      let seen!: () => void, done!: () => void;
      const entered = new Promise<void>((r) => (seen = r)),
        gate = new Promise<void>((r) => (release = r)),
        completed = new Promise<void>((r) => (done = r));
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
            maxRedirects: 0,
            maxRetries: 0,
          });
          seen();
          await gate;
          await route.fulfill({ response });
          done();
        },
      );
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      await entered;
      if (action === "source")
        await page
          .getByLabel("Unicast target", { exact: true })
          .fill("127.0.0.1:47809");
      else
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
      release();
      await completed;
      await expect(
        page.getByRole("region", {
          name: "Read diagnostic trace",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        }),
      ).toHaveCount(0);
      if (action === "source")
        await expect(
          panel.getByLabel("Native point evidence report", { exact: true }),
        ).toHaveCount(0);
    } finally {
      release?.();
      await stop(server);
    }
  });
}
for (const corruption of ["core-hash", "core-id", "trace-profile"]) {
  test(`corrupted ${corruption} cannot authorize diagnostic exports`, async ({
    page,
    request,
  }) => {
    const server = await peer();
    try {
      const panel = await open(page, request, server);
      await panel
        .getByLabel("Include diagnostic trace for this read", { exact: true })
        .check();
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
              maxRedirects: 0,
              maxRetries: 0,
            }),
            value = await response.json();
          if (corruption === "core-hash")
            value.core_report_sha256 = "0".repeat(64);
          else if (corruption === "core-id")
            value.core_report_id = "0".repeat(32);
          else value.trace.profile = "unsupported-trace/9";
          await route.fulfill({ response, json: value });
        },
      );
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText(
        corruption === "core-id" ? "another core report" : "invalid",
      );
      await expect(
        panel.getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        panel.getByLabel("Native point evidence report", { exact: true }),
      ).toHaveCount(0);
    } finally {
      await stop(server);
    }
  });
}
for (const declared of [false, true]) {
  test(`plain-core fallback ${declared ? "with" : "without"} explicit unavailable header preserves its qualification`, async ({
    page,
    request,
  }) => {
    const server = await peer();
    let original: Buffer | undefined;
    try {
      const panel = await open(page, request, server);
      await panel
        .getByLabel("Include diagnostic trace for this read", { exact: true })
        .check();
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
              maxRedirects: 0,
              maxRetries: 0,
            }),
            value = await response.json();
          original = Buffer.from(value.core_report_json, "utf8");
          const headers = { ...response.headers() };
          if (declared) headers["x-studio-diagnostics"] = "unavailable";
          await route.fulfill({ response, headers, body: original });
        },
      );
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      if (declared) {
        await expect(
          panel.getByRole("region", {
            name: "Read diagnostic trace",
            exact: true,
          }),
        ).toContainText("Diagnostic capture unavailable");
        const downloading = page.waitForEvent("download");
        await panel
          .getByRole("button", {
            name: "Export exact point evidence",
            exact: true,
          })
          .click();
        expect(readFileSync((await (await downloading).path())!)).toEqual(
          original,
        );
      } else {
        await expect(panel.getByRole("alert")).toContainText(
          "lacks its explicit server state",
        );
        await expect(
          panel.getByLabel("Native point evidence report", { exact: true }),
        ).toHaveCount(0);
      }
      await expect(
        panel.getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      await stop(server);
    }
  });
}

test("cancelled diagnostic read retains only the existing cancelled core result without another query", async ({
  page,
  request,
}) => {
  const server = await peer(false, "hold");
  try {
    const panel = await open(page, request, server);
    await panel
      .getByLabel("Include diagnostic trace for this read", { exact: true })
      .check();
    await panel
      .getByRole("button", { name: "Inspect native point status", exact: true })
      .click();
    await expect.poll(server.reads).toBe(1);
    await panel
      .getByRole("button", { name: "Cancel point inspection", exact: true })
      .click();
    await expect(
      panel.getByLabel("Native point evidence report", { exact: true }),
    ).toContainText("cancelled");
    await expect(
      panel.getByRole("region", { name: "Read diagnostic trace", exact: true }),
    ).toBeVisible();
    expect(server.reads()).toBe(1);
  } finally {
    await stop(server);
  }
});
