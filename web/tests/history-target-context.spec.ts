import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const pause = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
async function finish(primary: unknown, actions: (() => Promise<unknown>)[]) {
  const failures: unknown[] = [];
  for (const action of actions) {
    try {
      await action();
    } catch (error) {
      failures.push(error);
    }
  }
  if (primary && failures.length)
    throw new AggregateError(
      [primary, ...failures],
      "History assertion and owned cleanup failed",
    );
  if (primary) throw primary;
  if (failures.length)
    throw new AggregateError(failures, "History owned cleanup failed");
}
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

async function peer(routed: boolean, info: TestInfo) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,signal,sys
from tests.test_controller_acquisition_context import make_peer,target
async def main():
 peer=await make_peer(sys.argv[1]=='true')
 stop=asyncio.Event();loop=asyncio.get_running_loop()
 for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
 print(json.dumps({'event':'ready','target':target(peer)}),flush=True)
 try:await stop.wait()
 finally:
  peer.close();await asyncio.sleep(.02)
  print(json.dumps({'event':'stopped','requests':peer.requests,'errors':peer.errors}),flush=True)
asyncio.run(main())
`,
      String(routed),
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let stdout = "",
    stderr = "",
    spawnError: Error | null = null;
  child.stdout!.on("data", (chunk) => (stdout += chunk.toString()));
  child.stderr!.on("data", (chunk) => (stderr += chunk.toString()));
  child.on("error", (error) => (spawnError = error));
  const exited = () => child.exitCode !== null || child.signalCode !== null;
  async function close() {
    if (!exited()) child.kill("SIGTERM");
    for (let i = 0; i < 60 && !exited(); i++) await pause(50);
    let forced = false;
    if (!exited()) {
      forced = true;
      child.kill("SIGKILL");
      for (let i = 0; i < 20 && !exited(); i++) await pause(50);
    }
    await info.attach(`history-context-peer-${routed ? "routed" : "direct"}`, {
      body: JSON.stringify({
        stdout,
        stderr,
        exitCode: child.exitCode,
        signalCode: child.signalCode,
      }),
      contentType: "application/json",
    });
    expect(forced, "owned peer must shut down gracefully").toBe(false);
    expect(exited()).toBe(true);
    const receipt = stdout
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .find((row) => row.event === "stopped");
    expect(receipt).toBeTruthy();
    expect(receipt.errors).toEqual([]);
    expect(
      receipt.requests.every((row: string[]) =>
        ["ReadPropertyRequest", "ReadRangeRequest"].includes(row[0]),
      ),
    ).toBe(true);
  }
  try {
    await expect
      .poll(
        () => {
          if (spawnError) throw spawnError;
          if (exited()) throw new Error(`Peer exited before ready: ${stderr}`);
          return stdout.includes("\n");
        },
        { timeout: 10000 },
      )
      .toBe(true);
  } catch (error) {
    try {
      await close();
    } catch (cleanup) {
      throw new AggregateError(
        [error, cleanup],
        "Peer startup and cleanup failed",
      );
    }
    throw error;
  }
  const ready = JSON.parse(stdout.split("\n")[0]);
  return {
    target: ready.target as {
      address: string;
      device: string;
      router: string | null;
      dnet: number | null;
    },
    close,
  };
}

async function connect(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Known controller address", exact: true }),
  ).toBeEnabled();
}
async function openController(
  page: Page,
  target: Awaited<ReturnType<typeof peer>>["target"],
) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(target.address);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill(target.device);
  await page
    .getByLabel("Known router", { exact: true })
    .fill(target.router || "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(target.dnet == null ? "" : String(target.dnet));
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored device,42");
}
async function history(page: Page) {
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Trends & Alarms", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Controller history", exact: true })
    .click();
  await expect(
    page.getByLabel("History device address", { exact: true }),
  ).toHaveAttribute("readonly", "");
  const choices = page.getByLabel("History Trend Log object object", {
    exact: true,
  });
  await expect(choices.locator('option[value="trend-log,1"]')).toContainText(
    "Authored trend-log,1",
  );
  await choices.selectOption("trend-log,1");
  await page
    .getByLabel("History device clock timezone", { exact: true })
    .fill("UTC");
  await page.getByLabel("History range reference", { exact: true }).fill("100");
  await page.getByLabel("History record limit", { exact: true }).fill("3");
  await page.getByLabel("History page size", { exact: true }).fill("2");
}
const records = (page: Page) =>
  page.getByRole("region", { name: "Device history records", exact: true });

for (const routed of [false, true]) {
  test(`selected ${routed ? "routed" : "direct"} controller history preserves its full context and original capture offline`, async ({
    page,
    request,
  }, info) => {
    const server = await peer(routed, info);
    let headers: Record<string, string> = {},
      primary: unknown;
    const originals: {
      path: string;
      request: unknown;
      status: number;
      body: Buffer;
    }[] = [];
    try {
      headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      await page.route("**/api/bacnet/history/read", async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
        const body = await response.body();
        originals.push({
          path: "read",
          request: route.request().postDataJSON(),
          status: response.status(),
          body,
        });
        await route.fulfill({ response, body });
      });
      await connect(page);
      await openController(page, server.target);
      await history(page);
      await page
        .getByRole("button", { name: "Read device history", exact: true })
        .click();
      await expect(records(page)).toContainText("3 device-history records");
      expect(originals).toHaveLength(1);
      const original = originals[0],
        report = JSON.parse(original.body.toString());
      expect(original.status).toBe(200);
      expect((original.request as any).controller_target).toEqual(
        server.target,
      );
      expect((original.request as any).expected_connector_config).toEqual(
        report.connector_config,
      );
      expect(report.controller_target).toEqual(server.target);
      expect(report.target).toEqual({
        ...server.target,
        object_id: "trend-log,1",
      });
      expect(report.identity_verified).toBe(true);
      expect(Object.is(report.records[0].value, -0)).toBe(true);
      let downloaded = page.waitForEvent("download");
      await page
        .getByRole("button", {
          name: "Download device history JSON",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await downloaded).path())!)).toEqual(
        original.body,
      );
      await page
        .getByRole("button", {
          name: "Save immutable history capture",
          exact: true,
        })
        .click();
      await expect(
        page.getByText("Saved an immutable local device-history capture.", {
          exact: false,
        }),
      ).toBeVisible();
      expect(
        (
          await request.post("/api/bacnet/disconnect", { headers, data: {} })
        ).ok(),
      ).toBe(true);
      await page.reload();
      await page.getByRole("button", { name: "History", exact: true }).click();
      await page
        .getByRole("button", { name: "Controller history", exact: true })
        .click();
      await page
        .getByLabel("Saved device history capture", { exact: true })
        .selectOption(report.id);
      await page.route(
        `**/api/bacnet/history/captures/${report.id}`,
        async (route) => {
          const response = await route.fetch({
            maxRetries: 0,
            maxRedirects: 0,
          });
          const body = await response.body();
          originals.push({
            path: "load",
            request: null,
            status: response.status(),
            body,
          });
          await route.fulfill({ response, body });
        },
      );
      await page
        .getByRole("button", { name: "Open history capture", exact: true })
        .click();
      await expect(records(page)).toContainText(
        "Saved local capture: historical evidence",
      );
      await expect(
        page.getByRole("button", { name: "Read device history", exact: true }),
      ).toBeDisabled();
      expect(JSON.parse(originals[1].body.toString())).toEqual(report);
      downloaded = page.waitForEvent("download");
      await page
        .getByRole("button", {
          name: "Download device history JSON",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await downloaded).path())!)).toEqual(
        originals[1].body,
      );
      expect(originals).toHaveLength(2);
    } catch (error) {
      primary = error;
    } finally {
      await finish(primary, [
        () =>
          info.attach("history-context-originals", {
            body: JSON.stringify(
              originals.map((row) => ({
                ...row,
                body: undefined,
                body_base64: row.body.toString("base64"),
              })),
            ),
            contentType: "application/json",
          }),
        async () => {
          if (Object.keys(headers).length)
            await request.post("/api/bacnet/disconnect", { headers, data: {} });
        },
        server.close,
      ]);
    }
  });
}

for (const replacement of [
  "another physical station",
  "the same station after interface reopen",
] as const) {
  test(`held history cannot return after selecting ${replacement}`, async ({
    page,
    request,
  }, info) => {
    const first = await peer(false, info);
    let second: Awaited<ReturnType<typeof peer>> | null = null;
    let headers: Record<string, string> = {},
      primary: unknown;
    let release = () => {},
      entered = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const observed = new Promise<void>((resolve) => (entered = resolve));
    let upstream: Buffer | null = null,
      handlerDone: Promise<void> | null = null;
    const pattern = "**/api/bacnet/history/read";
    try {
      second = replacement.startsWith("another")
        ? await peer(true, info)
        : null;
      headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      await connect(page);
      await openController(page, first.target);
      await history(page);
      const handler: Parameters<Page["route"]>[1] = async (route) => {
        handlerDone = (async () => {
          const response = await route.fetch({
            maxRetries: 0,
            maxRedirects: 0,
          });
          upstream = await response.body();
          expect(response.status()).toBe(200);
          entered();
          await gate;
          await route.fulfill({ response, body: upstream });
        })();
        await handlerDone;
      };
      await page.route(pattern, handler);
      await page
        .getByRole("button", { name: "Read device history", exact: true })
        .click();
      await observed;
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      if (!second) {
        await page
          .getByRole("button", { name: "1 · Connection", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Open interface", exact: true })
          .click();
        await expect(
          page.getByRole("button", {
            name: "Known controller address",
            exact: true,
          }),
        ).toBeEnabled();
      }
      await openController(page, second?.target ?? first.target);
      await history(page);
      release();
      await handlerDone;
      await page.unroute(pattern, handler);
      await expect(records(page)).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Download device history JSON",
          exact: true,
        }),
      ).toHaveCount(0);
      await page
        .getByRole("button", { name: "Read device history", exact: true })
        .click();
      await expect(records(page)).toContainText("3 device-history records");
      await expect(
        page.getByLabel("History selected controller", { exact: true }),
      ).toContainText(second?.target.address ?? first.target.address);
    } catch (error) {
      primary = error;
    } finally {
      release();
      await finish(primary, [
        async () => {
          if (handlerDone) await handlerDone;
        },
        async () => {
          if (upstream)
            await info.attach("retired-original-history-response", {
              body: upstream,
              contentType: "application/json",
            });
        },
        async () => {
          if (Object.keys(headers).length)
            await request.post("/api/bacnet/disconnect", { headers, data: {} });
        },
        first.close,
        async () => {
          if (second) await second.close();
        },
      ]);
    }
  });
}

test("history from a different Device or Log cannot become selected-controller evidence", async ({
  page,
  request,
}, info) => {
  const server = await peer(false, info);
  let headers: Record<string, string> = {},
    primary: unknown;
  try {
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    await connect(page);
    await openController(page, server.target);
    await history(page);
    for (const change of ["Device", "Log"]) {
      const handler: Parameters<Page["route"]>[1] = async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
        const original = await response.body(),
          forged = JSON.parse(original.toString());
        if (change === "Device") forged.target.device = "device,99";
        else {
          forged.target.object_id = "trend-log,99";
          forged.request.object_id = "trend-log,99";
        }
        await info.attach(`actual-history-before-disclosed-${change}-forgery`, {
          body: original,
          contentType: "application/json",
        });
        await route.fulfill({ response, json: forged });
      };
      await page.route("**/api/bacnet/history/read", handler);
      await page
        .getByRole("button", { name: "Read device history", exact: true })
        .click();
      await expect(page.getByRole("alert")).toContainText(
        "History response does not identify the selected controller route",
      );
      await expect(records(page)).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Save immutable history capture",
          exact: true,
        }),
      ).toHaveCount(0);
      await page.unroute("**/api/bacnet/history/read", handler);
    }
  } catch (error) {
    primary = error;
  } finally {
    await finish(primary, [
      async () => {
        if (Object.keys(headers).length)
          await request.post("/api/bacnet/disconnect", { headers, data: {} });
      },
      server.close,
    ]);
  }
});
