import { test, expect, type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";

async function engines() {
  const root = path.resolve("..");
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,signal
from tests.provenance_router_peer import ProvenanceRouter
async def main():
 loop=asyncio.get_running_loop(); stop=asyncio.Event(); peers=[]
 for name in ('East','West'):
  _,p=await loop.create_datagram_endpoint(ProvenanceRouter,local_addr=('127.0.0.1',0));p.phase=name;peers.append(p)
 loop.add_signal_handler(signal.SIGTERM,stop.set)
 print(json.dumps({'ready':[p.endpoint for p in peers]}),flush=True)
 await stop.wait()
 for p in peers:p.transport.close()
 print(json.dumps({'writes':[x for p in peers for x in p.writes],'errors':[x for p in peers for x in p.errors]}),flush=True)
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const events: any[] = [];
  let stderr = "",
    buffer = "";
  child.stderr!.on("data", (d) => (stderr += String(d)));
  const ready = new Promise<string[]>((resolve, reject) => {
    const timeout = setTimeout(() => {
      child.kill();
      reject(Error(stderr || "Engine peer startup timed out"));
    }, 10000);
    child.stdout!.on("data", (d) => {
      buffer += String(d);
      while (buffer.includes("\n")) {
        const end = buffer.indexOf("\n"),
          line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        const value = JSON.parse(line);
        events.push(value);
        if (value.ready) {
          clearTimeout(timeout);
          resolve(value.ready);
        }
      }
    });
    child.once("exit", () => {
      clearTimeout(timeout);
      if (!events.length) reject(Error(stderr));
    });
  });
  return {
    endpoints: await ready,
    async close() {
      child.kill("SIGTERM");
      await new Promise((resolve) => child.once("exit", resolve));
      const result = events.find((row) => row.writes);
      expect(result?.writes).toEqual([]);
      expect(result?.errors).toEqual([]);
    },
  };
}
async function setup(page: Page, endpoints: string[]) {
  await page.route("**/api/bacnet/interfaces", (route) =>
    route.fulfill({
      json: {
        interfaces: [
          {
            address: "127.0.0.1",
            name: "Authored building network",
            network: "127.0.0.0/8",
            recommended: true,
            broadcast_available: true,
          },
        ],
      },
    }),
  );
  await page.route("**/api/bacnet/discover-routers", (route) =>
    route.fulfill({
      json: {
        routers: [],
        complete: true,
        truncated: false,
        scope: "Authored empty router advertisements",
        warnings: ["No router advertisements arrived."],
      },
    }),
  );
  const report = {
    devices: endpoints.map((address) => ({ address, device: "device,5136" })),
    complete: true,
    truncated: false,
    warnings: [],
  };
  await page.route("**/api/bacnet/scan-ip", (route) => {
    expect(route.request().postDataJSON().mode).toBe("local");
    return route.fulfill({ json: report });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Computer network", { exact: true })
    .selectOption("127.0.0.1");
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "Routed BACnet discovery",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Find NAEs & routers", exact: true }),
  ).toBeEnabled();
  return { panel, report };
}

test("a user can find named engines, load their trunks and open a controller without typing network identities", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  const peer = await engines();
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/bacnet/"))
      posts.push(new URL(r.url()).pathname);
  });
  try {
    const { panel } = await setup(page, peer.endpoints);
    expect(posts).toEqual(["/api/bacnet/connect"]);
    await panel
      .getByRole("button", { name: "Find NAEs & routers", exact: true })
      .click();
    const router = panel.getByLabel("Commissioning router", { exact: true });
    await expect(
      router.locator("option").filter({ hasText: "East router name" }),
    ).toHaveCount(1);
    await expect(
      router.locator("option").filter({ hasText: "West router name" }),
    ).toHaveCount(1);
    await panel.getByLabel("Find NAE or router", { exact: true }).fill("East");
    await expect(router.locator("option")).toHaveCount(2);
    await router.selectOption(peer.endpoints[0]);
    await panel
      .getByLabel("Commissioning trunk", { exact: true })
      .selectOption("3001");
    await expect(
      panel.getByLabel("Routed response window seconds", { exact: true }),
    ).not.toBeVisible();
    await page.screenshot({
      path: info.outputPath("named-engine-and-trunks.png"),
      fullPage: true,
    });
    await panel
      .getByRole("button", { name: "Scan controllers", exact: true })
      .click();
    const controller = panel.getByLabel("Commissioning controller", {
      exact: true,
    });
    await expect(
      controller.locator("option").filter({ hasText: "East controller name" }),
    ).toHaveCount(1);
    await controller.selectOption(JSON.stringify(["3001:7", "device,5136"]));
    await panel
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("East controller name");
    expect(
      posts.filter((p) => /write|apply|restore|transfer|backup/.test(p)),
    ).toEqual([]);
  } finally {
    const token = (await (await request.get("/api/session")).json()).token;
    await request.post("/api/bacnet/disconnect", {
      headers: { "X-Studio-Token": token },
      data: {},
    });
    await peer.close();
  }
});

for (const delayed of ["IP candidates", "engine name"] as const) {
  test(`late ${delayed} cannot return after reopening the computer connection`, async ({
    page,
    request,
  }) => {
    test.setTimeout(60000);
    const peer = await engines();
    let release!: () => void, arrived!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      pending = new Promise<void>((r) => (arrived = r));
    try {
      const { panel, report } = await setup(page, peer.endpoints);
      const endpoint = delayed === "IP candidates" ? "scan-ip" : "device-name";
      let once = false;
      await page.route(`**/api/bacnet/${endpoint}`, async (route) => {
        if (once) return route.fallback();
        once = true;
        const data =
          delayed === "IP candidates"
            ? report
            : await (await route.fetch()).json();
        arrived();
        await gate;
        await route.fulfill({ json: data });
      });
      await panel
        .getByRole("button", { name: "Find NAEs & routers", exact: true })
        .click();
      await pending;
      await page
        .getByRole("button", { name: "1 · Connection", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Open interface", exact: true })
        .click();
      const delivered = page.waitForResponse((r) =>
        r.url().endsWith(`/bacnet/${endpoint}`),
      );
      release();
      await delivered;
      await expect(
        panel
          .getByLabel("Commissioning router", { exact: true })
          .locator("option"),
      ).toHaveCount(1);
      await expect(
        panel
          .getByLabel("Commissioning trunk", { exact: true })
          .locator("option"),
      ).toHaveCount(1);
      await expect(panel).not.toContainText("East router name");
    } finally {
      release?.();
      const token = (await (await request.get("/api/session")).json()).token;
      await request.post("/api/bacnet/disconnect", {
        headers: { "X-Studio-Token": token },
        data: {},
      });
      await peer.close();
    }
  });
}

test("failed discovery shows a connection problem instead of claiming there are no engines", async ({
  page,
  request,
}) => {
  const { panel } = await setup(page, []);
  try {
    for (const endpoint of ["discover-routers", "scan-ip"]) {
      await page.route(`**/api/bacnet/${endpoint}`, (route) =>
        route.fulfill({
          status: 400,
          json: { detail: "The chosen connection has no broadcast subnet." },
        }),
      );
    }
    await panel
      .getByRole("button", { name: "Find NAEs & routers", exact: true })
      .click();
    await expect(
      panel.getByLabel("Engine discovery results", { exact: true }),
    ).toContainText("search could not complete");
    await expect(panel).not.toContainText("No engines answered this search");
    await expect(
      panel.getByLabel("Commissioning router", { exact: true }),
    ).toBeDisabled();
    await expect(
      panel.getByText("Enter an engine IP address instead", { exact: true }),
    ).toBeVisible();
  } finally {
    const token = (await (await request.get("/api/session")).json()).token;
    await request.post("/api/bacnet/disconnect", {
      headers: { "X-Studio-Token": token },
      data: {},
    });
  }
});
