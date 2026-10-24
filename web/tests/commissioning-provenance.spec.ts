import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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

async function stop(child: ChildProcess) {
  const exited = () => child.exitCode !== null || child.signalCode !== null;
  if (!exited()) {
    try {
      child.stdin?.write('{"command":"stop"}\n');
    } catch {
      /* signal below */
    }
    for (let i = 0; i < 60 && !exited(); i++) await delay(50);
  }
  if (!exited()) {
    child.kill("SIGTERM");
    for (let i = 0; i < 20 && !exited(); i++) await delay(50);
  }
  if (!exited()) {
    child.kill("SIGKILL");
    for (let i = 0; i < 20 && !exited(); i++) await delay(50);
    throw new Error(
      `Owned peer required forced retirement; reaped=${exited()}`,
    );
  }
}

async function routerPeer(info: TestInfo) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    ["-u", "-m", "tests.provenance_router_peer"],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  const events: Record<string, unknown>[] = [];
  let stdout = "",
    stderr = "",
    buffer = "";
  child.stdin?.on("error", () => {});
  child.stdout!.on("data", (chunk) => {
    stdout += chunk.toString();
    buffer += chunk.toString();
    while (buffer.includes("\n")) {
      const end = buffer.indexOf("\n"),
        line = buffer.slice(0, end);
      buffer = buffer.slice(end + 1);
      try {
        events.push(JSON.parse(line));
      } catch {
        /* retained in stdout */
      }
    }
  });
  child.stderr!.on("data", (chunk) => (stderr += chunk.toString()));
  let spawnError: Error | null = null;
  child.on("error", (error) => (spawnError = error));
  try {
    await expect
      .poll(
        () => {
          if (spawnError) throw spawnError;
          if (child.exitCode !== null || child.signalCode !== null)
            throw new Error(`Peer startup exited: ${stderr}`);
          return events.find((event) => event.event === "ready")?.endpoint;
        },
        { timeout: 10000 },
      )
      .toBeTruthy();
  } catch (error) {
    try {
      await stop(child);
    } finally {
      await info.attach("peer-startup", {
        body: JSON.stringify({ stdout, stderr }),
        contentType: "application/json",
      });
    }
    throw error;
  }
  return {
    endpoint: String(events.find((event) => event.event === "ready")!.endpoint),
    async phase(value: "Old" | "Current") {
      child.stdin!.write(JSON.stringify({ command: "phase", value }) + "\n");
      await expect
        .poll(() =>
          events.some(
            (event) => event.event === "phase" && event.value === value,
          ),
        )
        .toBe(true);
    },
    async close() {
      let failure: unknown;
      try {
        await stop(child);
      } catch (error) {
        failure = error;
      }
      await info.attach("actual-udp-peer", {
        body: JSON.stringify(
          {
            stdout,
            stderr,
            exitCode: child.exitCode,
            signalCode: child.signalCode,
            events,
          },
          null,
          2,
        ),
        contentType: "application/json",
      });
      if (failure) throw failure;
      const receipt = events.find((event) => event.event === "stopped");
      expect(
        receipt,
        "owned peer emitted its final request/retirement record",
      ).toBeTruthy();
      expect(receipt!.errors).toEqual([]);
      expect(receipt!.writes).toEqual([]);
    },
  };
}

async function scanIp(page: Page, endpoint: string) {
  const scan = page.getByRole("region", {
    name: "BACnet device scan",
    exact: true,
  });
  await scan.getByLabel("IP scan mode", { exact: true }).selectOption("single");
  await scan.getByLabel("Scan IP address", { exact: true }).fill("127.0.0.1");
  await scan
    .getByLabel("Scan UDP port", { exact: true })
    .fill(endpoint.split(":")[1]);
  await scan
    .getByLabel("Discovery response seconds", { exact: true })
    .fill("1");
  await scan
    .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
    .click();
}

for (const mode of [
  "changed bind endpoint",
  "explicit same-config reopen",
] as const) {
  test(`fresh routed choices retire retained names after ${mode}`, async ({
    page,
    request,
  }, info) => {
    const peer = await routerPeer(info);
    const bodies: unknown[] = [],
      pending = new Set<Promise<void>>();
    let hold = false,
      release = () => {},
      heldCount = 0;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const detailsHandler: Parameters<Page["route"]>[1] = async (route) => {
      const task = (async () => {
        const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
        const body = await response.body();
        bodies.push({
          endpoint: new URL(route.request().url()).pathname,
          request: route.request().postDataJSON(),
          status: response.status(),
          headers: response.headers(),
          body_base64: body.toString("base64"),
        });
        if (hold) {
          heldCount++;
          await gate;
        }
        await route.fulfill({ response, body });
      })();
      pending.add(task);
      try {
        await task;
      } finally {
        pending.delete(task);
      }
    };
    let primary: unknown;
    try {
      expect(
        (
          await request.post("/api/bacnet/connect", {
            headers,
            data: { local_address: `127.0.0.1:${await freePort()}` },
          })
        ).ok(),
      ).toBe(true);
      await page.route("**/api/bacnet/device-details", detailsHandler);
      await page.route("**/api/bacnet/device-name", detailsHandler);
      // Darwin loopback cannot receive the router-list broadcast. Only this list
      // is authored; IP scan, router-networks, routed Who-Is and metadata use UDP.
      await page.route("**/api/bacnet/discover-routers", (route) =>
        route.fulfill({
          json: {
            profile: "bacnet-local-router-discovery/1",
            complete: true,
            truncated: false,
            scope: "Authored loopback router list",
            warnings: [],
            routers: [{ router: peer.endpoint, networks: [3001] }],
          },
        }),
      );
      page.on("response", (response) => {
        if (
          !/\/api\/bacnet\/(scan-ip|scan-trunk|router-networks|connect|disconnect)$/.test(
            response.url(),
          )
        )
          return;
        const task = (async () => {
          const body = await response.body();
          bodies.push({
            endpoint: new URL(response.url()).pathname,
            request: response.request().postData(),
            status: response.status(),
            body_base64: body.toString("base64"),
          });
        })();
        pending.add(task);
        void task.catch(() => {}).finally(() => pending.delete(task));
      });
      await page.goto("/");
      await page
        .getByRole("button", { name: /^Connect to a controller/ })
        .click();
      await page
        .getByRole("button", { name: "2 · Discover & select", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Direct BACnet/IP", exact: true })
        .click();
      const guide = page.getByRole("region", {
        name: "Routed BACnet discovery",
        exact: true,
        includeHidden: true,
      });
      const scan = page.getByRole("region", {
        name: "BACnet device scan",
        exact: true,
        includeHidden: true,
      });
      await scanIp(page, peer.endpoint);
      await expect(
        scan.getByText("Old router name", { exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Router & trunk", exact: true })
        .click();
      await guide
        .getByRole("button", { name: "Find local routers", exact: true })
        .click();
      const routers = guide.getByLabel("Commissioning router", { exact: true });
      await expect(
        routers.locator("option").filter({ hasText: "Old router name" }),
      ).toHaveCount(1);
      await routers.selectOption(peer.endpoint);
      await guide
        .getByLabel("Commissioning trunk", { exact: true })
        .selectOption("3001");
      await guide
        .getByLabel("Routed response window seconds", { exact: true })
        .fill("1");
      await guide
        .getByRole("button", {
          name: "Scan selected routed network",
          exact: true,
        })
        .click();
      const controllers = guide.getByLabel("Commissioning controller", {
        exact: true,
      });
      await expect(
        controllers
          .locator("option")
          .filter({ hasText: "Old controller name" }),
      ).toHaveCount(1);
      await peer.phase("Current");
      await page
        .getByRole("button", { name: "1 · Connection", exact: true })
        .click();
      if (mode === "changed bind endpoint") {
        await page
          .getByLabel("Local bind address / UDP port", { exact: true })
          .fill(`127.0.0.1:${await freePort()}`);
      }
      // Open is deliberate even when the submitted config is byte-identical.
      await page
        .getByRole("button", { name: "Open interface", exact: true })
        .click();
      await page
        .getByRole("button", { name: "2 · Discover & select", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Router & trunk", exact: true })
        .click();
      await expect(
        guide.getByRole("button", { name: "Find local routers", exact: true }),
      ).toBeEnabled();
      hold = true;
      await guide
        .getByRole("button", { name: "Find local routers", exact: true })
        .click();
      await routers.selectOption(peer.endpoint);
      await guide
        .getByLabel("Commissioning trunk", { exact: true })
        .selectOption("3001");
      await guide
        .getByRole("button", {
          name: "Scan selected routed network",
          exact: true,
        })
        .click();
      await expect.poll(() => heldCount).toBeGreaterThan(0);
      // Same router/DNET/MAC/instance has a new observation. Historical Scan
      // rows remain retained in their task, but cannot name current choices.
      await expect(
        scan.getByText("Old router name", { exact: true }),
      ).toBeAttached();
      await expect(routers).not.toContainText("Old router name");
      await expect(controllers).not.toContainText("Old controller name");
      await info.attach("held-current-choices", {
        body: JSON.stringify({
          routers: await routers.textContent(),
          controllers: await controllers.textContent(),
          heldCount,
        }),
        contentType: "application/json",
      });
      hold = false;
      release();
      await expect(controllers).toContainText("Current controller name");
      await page
        .getByRole("button", { name: "Direct BACnet/IP", exact: true })
        .click();
      await scanIp(page, peer.endpoint);
      await expect(routers).toContainText("Current router name");
      await expect(routers).not.toContainText("Old router name");
      await expect(controllers).toContainText("Current controller name");
    } catch (error) {
      primary = error;
    }
    const cleanup: unknown[] = [];
    hold = false;
    release();
    try {
      await Promise.allSettled([...pending]);
    } catch (error) {
      cleanup.push(error);
    }
    try {
      await page.unroute("**/api/bacnet/device-details", detailsHandler);
      await page.unroute("**/api/bacnet/device-name", detailsHandler);
    } catch (error) {
      cleanup.push(error);
    }
    try {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
    } catch (error) {
      cleanup.push(error);
    }
    try {
      await peer.close();
    } catch (error) {
      cleanup.push(error);
    }
    await info.attach("actual-http-originals", {
      body: JSON.stringify(bodies, null, 2),
      contentType: "application/json",
    });
    if (primary && cleanup.length)
      throw new AggregateError(
        [primary, ...cleanup],
        "Provenance assertion and owned cleanup failed",
      );
    if (primary) throw primary;
    if (cleanup.length)
      throw new AggregateError(cleanup, "Provenance cleanup failed");
  });
}
