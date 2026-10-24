import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";

const root = path.resolve("..");
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
async function peer(network = 3001) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.guided_router_peer import GuidedRouter
async def main():
 _,peer=await asyncio.get_running_loop().create_datagram_endpoint(lambda:GuidedRouter(int(sys.argv[1])),local_addr=('127.0.0.1',0))
 print(peer.endpoint,flush=True)
 try:await asyncio.Event().wait()
 finally:peer.close()
asyncio.run(main())
`,
      String(network),
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const writes: string[] = [],
    errors: string[] = [];
  const endpoint = await new Promise<string>((resolve, reject) => {
    let buffer = "",
      ready = false,
      stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Router startup: " + stderr));
    }, 10000);
    child.stderr!.on("data", (value) => (stderr += value.toString()));
    child.stdout!.on("data", (value) => {
      buffer += value.toString();
      while (buffer.includes("\n")) {
        const end = buffer.indexOf("\n"),
          line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(line);
        } else if (line.startsWith("WRITE ")) writes.push(line.slice(6));
        else if (line.startsWith("PEER ERROR ")) errors.push(line);
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Router ${code}: ${stderr}`));
    });
  });
  return {
    endpoint,
    network,
    writes,
    errors,
    close: () => child.kill("SIGTERM"),
  };
}
async function open(page: Page, request: APIRequestContext) {
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
  const guide = page.getByRole("region", {
    name: "Routed BACnet discovery",
    exact: true,
  });
  const instance = page.getByRole("region", {
    name: "Device instance commissioning",
    exact: true,
  });
  await expect(
    guide.getByRole("button", { name: "Find local routers", exact: true }),
  ).toBeEnabled();
  return { guide, instance, headers };
}
async function discoverFixture(
  page: Page,
  peers: Awaited<ReturnType<typeof peer>>[],
) {
  // Router-list UI evidence is authored here because Darwin does not deliver
  // subnet broadcasts on loopback. The production discovery packet/collector
  // has separate real-UDP mirror tests; all selected-router reads, trunk scans,
  // metadata, commissioning and readback below use actual HTTP/UDP services.
  await page.route("**/api/bacnet/discover-routers", (route) =>
    route.fulfill({
      json: {
        profile: "bacnet-local-router-discovery/1",
        complete: true,
        truncated: false,
        scope: "Authored loopback router list",
        warnings: peers.length ? [] : ["No router advertisements arrived."],
        routers: peers.map((server) => ({
          router: server.endpoint,
          networks: [server.network, server.network + 1],
        })),
      },
    }),
  );
}
async function selectTrunk(
  guide: ReturnType<Page["getByRole"]>,
  network: number,
) {
  await expect(
    guide
      .getByLabel("Commissioning trunk", { exact: true })
      .locator(`option[value="${network}"]`),
  ).toHaveCount(1);
  await guide
    .getByLabel("Commissioning trunk", { exact: true })
    .selectOption(String(network));
  await guide
    .getByLabel("Routed response window seconds", { exact: true })
    .fill("1");
  await guide
    .getByRole("button", { name: "Scan selected routed network", exact: true })
    .click();
  await expect(
    guide
      .getByLabel("Commissioning controller", { exact: true })
      .locator("option"),
  ).toHaveCount(3);
}
async function choose(
  guide: ReturnType<Page["getByRole"]>,
  network: number,
  mac: number,
) {
  await guide
    .getByLabel("Commissioning controller", { exact: true })
    .selectOption(JSON.stringify([`${network}:${mac}`, "device,5136"]));
  await guide
    .getByRole("button", { name: "Modify selected controller", exact: true })
    .click();
}

test("router → its trunks → scan → duplicate-ID controller → reviewed native instance change", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width: 1440, height: 2400 });
  const first = await peer(),
    second = await peer(4101);
  try {
    await discoverFixture(page, [first, second]);
    const { guide, instance } = await open(page, request);
    await guide
      .getByRole("button", { name: "Find local routers", exact: true })
      .click();
    const routers = guide.getByLabel("Commissioning router", { exact: true });
    await expect(routers.locator("option")).toHaveCount(3);
    await routers.selectOption(first.endpoint);
    await expect(
      guide
        .getByLabel("Commissioning trunk", { exact: true })
        .locator('option[value="3001"]'),
    ).toHaveCount(1);
    await routers.selectOption(second.endpoint);
    await expect(
      guide
        .getByLabel("Commissioning trunk", { exact: true })
        .locator('option[value="3001"]'),
    ).toHaveCount(0);
    await selectTrunk(guide, 4101);
    await choose(guide, 4101, 8);
    await expect(
      instance.getByLabel("Controller address (IPv4 or DNET:MAC)", {
        exact: true,
      }),
    ).toHaveValue("4101:8");
    await expect(
      instance.getByLabel("Instance-change router (routed targets only)", {
        exact: true,
      }),
    ).toHaveValue(second.endpoint);
    await instance
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await instance
      .getByRole("button", { name: "Review instance change", exact: true })
      .click();
    await expect(
      instance.getByLabel("Reviewed instance change", { exact: true }),
    ).toContainText("Authored 4101 MAC 8");
    expect(second.writes).toEqual([]);
    // A new upstream router invalidates the selected controller and its Apply.
    await routers.selectOption(first.endpoint);
    await expect(
      instance.getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      instance.getByLabel("Current Device object (device,instance)", {
        exact: true,
      }),
    ).toHaveValue("");
    await expect(
      guide.getByLabel("Commissioning controller", { exact: true }),
    ).toHaveCount(0);
    await selectTrunk(guide, 3001);
    await expect(
      guide.getByLabel("Commissioning controller", { exact: true }),
    ).toContainText("device,5136");
    await expect(
      guide.getByLabel("Commissioning controller", { exact: true }),
    ).toContainText("Authored 3001 MAC 8");
    await choose(guide, 3001, 8);
    await expect(
      instance.getByLabel("Instance-change network (1–65534)", { exact: true }),
    ).toHaveValue("3001");
    await expect(
      instance.getByLabel("Current Device object (device,instance)", {
        exact: true,
      }),
    ).toHaveValue("device,5136");
    await instance
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await instance
      .getByRole("button", { name: "Review instance change", exact: true })
      .click();
    await expect(
      instance.getByLabel("Reviewed instance change", { exact: true }),
    ).toContainText("Authored 3001 MAC 8");
    expect(first.writes).toEqual([]);
    await instance
      .getByRole("checkbox", {
        name: "I reserved this new number",
        exact: false,
      })
      .check();
    await instance
      .getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      })
      .click();
    await expect(
      instance.getByLabel("Instance change receipt", { exact: true }),
    ).toContainText("verified_new");
    expect(first.writes).toEqual(["3001:8"]);
    expect(second.writes).toEqual([]);
    expect(first.errors).toEqual([]);
    expect(second.errors).toEqual([]);
    await guide.screenshot({
      path: test.info().outputPath("guided-router-selection.png"),
    });
  } finally {
    first.close();
    second.close();
  }
});

test("an empty local router list permits an explicit known-router query", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    await discoverFixture(page, []);
    const { guide } = await open(page, request);
    await guide
      .getByRole("button", { name: "Find local routers", exact: true })
      .click();
    await expect(guide).toContainText("No router advertisements arrived.");
    await guide
      .getByLabel("Discovery router address", { exact: true })
      .fill(server.endpoint);
    await guide
      .getByRole("button", { name: "Read router networks", exact: true })
      .click();
    await expect(
      guide.getByLabel("Commissioning router", { exact: true }),
    ).toHaveValue(server.endpoint);
    await expect(
      guide
        .getByLabel("Commissioning trunk", { exact: true })
        .locator("option"),
    ).toHaveCount(3);
    expect(server.writes).toEqual([]);
    expect(server.errors).toEqual([]);
  } finally {
    server.close();
  }
});

test("a late trunk scan cannot restore controller choices after the interface changes", async ({
  page,
  request,
}) => {
  const server = await peer();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let captured!: () => void;
  const ready = new Promise<void>((resolve) => {
    captured = resolve;
  });
  try {
    const { guide } = await open(page, request);
    await guide
      .getByLabel("Discovery router address", { exact: true })
      .fill(server.endpoint);
    await guide
      .getByRole("button", { name: "Read router networks", exact: true })
      .click();
    await guide
      .getByLabel("Commissioning trunk", { exact: true })
      .selectOption("3001");
    await guide
      .getByLabel("Routed response window seconds", { exact: true })
      .fill("1");
    await page.route("**/api/bacnet/scan-trunk", async (route) => {
      const response = await route.fetch();
      captured();
      await gate;
      await route.fulfill({ response });
    });
    await guide
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    await ready;
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    release();
    await expect(
      guide.getByLabel("Discovery router address", { exact: true }),
    ).toBeEnabled();
    await expect(
      guide.getByLabel("Commissioning controller", { exact: true }),
    ).toHaveCount(0);
    expect(server.writes).toEqual([]);
    expect(server.errors).toEqual([]);
  } finally {
    release();
    server.close();
  }
});
