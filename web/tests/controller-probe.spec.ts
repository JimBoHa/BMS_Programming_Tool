import { test, expect, type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      const port = typeof address === "string" ? 0 : address.port;
      socket.close(() => resolve(port));
    });
  });
}
async function probeRouter(partial = false) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_routed_discovery import RawRouter
async def main():
    transport,peer=await asyncio.get_running_loop().create_datagram_endpoint(RawRouter,local_addr=('127.0.0.1',0))
    if sys.argv[1]=='partial': peer.probe_reject_props={'application-software-version'}
    print(json.dumps({'router':peer.endpoint}),flush=True)
    try: await asyncio.to_thread(sys.stdin.readline)
    finally:
        transport.close()
        assert not peer.errors,peer.errors
        for frame in peer.frames:
            packet=frame[4:]
            assert packet[1]&0x20,'Every request must use the explicit routed destination'
            offset=2+3+packet[4]+1
            assert packet[offset-1]==255,'Native routed hop budget must survive forwarding'
            assert packet[offset]&0xf0==0 and packet[offset+3]==12,'Only confirmed ReadProperty is allowed'
        requests=[]
        while not peer.probe_received.empty(): requests.append(peer.probe_received.get_nowait())
        print(json.dumps({'requests':requests,'frames':len(peer.frames)}),flush=True)
        await asyncio.sleep(.05)
asyncio.run(main())`,
      partial ? "partial" : "complete",
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  let output = "",
    error = "",
    ready = false;
  child.stderr.on("data", (data) => {
    error += data.toString();
  });
  const router = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Probe router startup timed out: " + error));
    }, 6000);
    child.stdout.on("data", (data) => {
      output += data.toString();
      if (!ready && output.includes("\n")) {
        ready = true;
        clearTimeout(timer);
        resolve(JSON.parse(output.split("\n")[0]).router);
      }
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Probe router exited ${code}: ${error}`));
    });
  });
  return {
    router,
    async close() {
      const finished = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      child.stdin.end("close\n");
      const timer = setTimeout(() => child.kill(), 2000);
      const code = await finished;
      clearTimeout(timer);
      expect(code, error).toBe(0);
      return JSON.parse(output.trim().split("\n").at(-1)!);
    },
  };
}
async function openRoute(page: Page, router: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByLabel("BBMD address / UDP port (optional)", { exact: true })
    .fill("");
  await page.getByLabel("Router IP (optional)", { exact: true }).fill(router);
  await page
    .getByLabel("MS/TP destination network (optional)", { exact: true })
    .fill("2105");
  const panel = page.getByRole("region", {
    name: "Single controller address probe",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Discover controller by address",
      exact: true,
    }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByText("BACnet interface open", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", {
      name: "Discover controller by address",
      exact: true,
    }),
  ).toBeEnabled();
  return panel;
}

for (const partial of [false, true]) {
  test(`single-address controller identification uses real routed ReadProperty and preserves ${partial ? "partial" : "complete"} metadata`, async ({
    page,
    request,
  }) => {
    const peer = await probeRouter(partial);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    try {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      const panel = await openRoute(page, peer.router);
      await expect(panel).toContainText("No Who-Is, bus scan");
      await panel
        .getByLabel("Controller MS/TP MAC address", { exact: true })
        .fill("255");
      await panel
        .getByRole("button", {
          name: "Discover controller by address",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText("0 to 254");
      await panel
        .getByLabel("Controller MS/TP MAC address", { exact: true })
        .fill("7");
      await panel
        .getByRole("button", {
          name: "Discover controller by address",
          exact: true,
        })
        .click();
      const identity = panel.getByRole("region", {
        name: "Probed controller identity",
        exact: true,
      });
      await expect(identity).toContainText("device,132007 · 2105:7");
      await expect(identity).toContainText("Independent controller7");
      await expect(identity).toContainText("VMA1630 independent fixture");
      await expect(identity).toContainText(
        partial
          ? "Identity verified · metadata incomplete"
          : "Identity metadata complete",
      );
      if (partial)
        await expect(
          identity.getByLabel("Controller identity metadata errors", {
            exact: true,
          }),
        ).toContainText("application-software-version");
      const downloading = page.waitForEvent("download");
      await identity
        .getByRole("button", { name: "Download probe JSON", exact: true })
        .click();
      const downloaded = await downloading;
      const report = JSON.parse(
        readFileSync((await downloaded.path())!, "utf8"),
      );
      expect(downloaded.suggestedFilename()).toBe(
        "bacnet-controller-2105-7-identity.json",
      );
      expect(report).toMatchObject({
        router: peer.router,
        dnet: 2105,
        mac: 7,
        address: "2105:7",
        device: "device,132007",
        device_instance: 132007,
        live_verified: true,
        complete: !partial,
      });
      expect(report.properties["vendor-identifier"]).toBe(5);
      expect(report.properties["firmware-revision"]).toBe("7.0");
      expect(report.connector_config.router).toBe(peer.router);
      expect(report.connector_config.dnet).toBe(2105);
      expect(Date.parse(report.finished_at)).toBeGreaterThanOrEqual(
        Date.parse(report.started_at),
      );
      expect(report.errors).toHaveLength(partial ? 1 : 0);
      await identity
        .getByRole("button", { name: "Use identified controller", exact: true })
        .click();
      await expect(
        page.getByLabel("Unicast target", { exact: true }),
      ).toHaveValue("2105:7");
      await expect(
        page.getByLabel("Object identifier", { exact: true }),
      ).toHaveValue("device,132007");
      await expect(
        page.getByLabel("Router IP (optional)", { exact: true }),
      ).toHaveValue(peer.router);
      await expect(
        page.getByLabel("MS/TP destination network (optional)", {
          exact: true,
        }),
      ).toHaveValue("2105");
      await expect(
        page.getByLabel("File Device object", { exact: true }),
      ).toHaveValue("device,132007");
      await page
        .getByLabel("MS/TP destination network (optional)", { exact: true })
        .fill("2205");
      await expect(
        panel.getByRole("button", {
          name: "Discover controller by address",
          exact: true,
        }),
      ).toBeDisabled();
      await expect(identity).toHaveCount(0);
    } finally {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      const evidence = await peer.close();
      expect(evidence.requests[0]).toEqual(["object-identifier", 4194303]);
      expect(evidence.requests).toHaveLength(6);
      expect(
        evidence.requests.slice(1).every((row: any) => row[1] === 132007),
      ).toBe(true);
    }
  });
}

test("a route draft change discards a delayed actual controller probe", async ({
  page,
  request,
}) => {
  const peer = await probeRouter();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const waiting = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openRoute(page, peer.router);
    await page.route("**/api/bacnet/probe-controller", async (route) => {
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      arrived();
      await held;
      await route.fulfill({ response });
    });
    await panel
      .getByRole("button", {
        name: "Discover controller by address",
        exact: true,
      })
      .click();
    await waiting;
    await page
      .getByLabel("MS/TP destination network (optional)", { exact: true })
      .fill("2205");
    release();
    await expect(
      panel.getByText("Reading one controller identity…", { exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("region", {
        name: "Probed controller identity",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Use identified controller",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Discover controller by address",
        exact: true,
      }),
    ).toBeDisabled();
  } finally {
    release?.();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await peer.close();
  }
});

test("a paced address page uses real wildcard reads, preserves unknown addresses and never starts the next page automatically", async ({
  page,
  request,
}) => {
  const peer = await probeRouter();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let pages = 0;
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/probe-trunk")) pages++;
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openRoute(page, peer.router);
    const range = panel.getByRole("region", {
      name: "Bounded controller address page",
      exact: true,
    });
    await expect(
      range.getByLabel("Per-MAC response seconds", { exact: true }),
    ).toHaveValue("0.75");
    await expect(
      range.getByLabel("Request spacing seconds", { exact: true }),
    ).toHaveValue("0.1");
    await expect(
      range.getByLabel("Page deadline seconds", { exact: true }),
    ).toHaveValue("30");
    await range.getByLabel("Last MAC in page", { exact: true }).fill("32");
    await range
      .getByRole("button", { name: "Probe one MAC address page", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "at most 32 addresses",
    );
    expect(pages).toBe(0);
    await range.getByLabel("First MAC in page", { exact: true }).fill("6");
    await range.getByLabel("Last MAC in page", { exact: true }).fill("8");
    for (const [label, invalid, expected] of [
      [
        "Per-MAC response seconds",
        "0.4",
        "Per-MAC response window must be from 0.5 to 2 seconds.",
      ],
      [
        "Request spacing seconds",
        "1.1",
        "Request spacing must be from 0.1 to 1 seconds.",
      ],
      [
        "Page deadline seconds",
        "31",
        "Page deadline must be from 1 to 30 seconds.",
      ],
    ]) {
      const field = range.getByLabel(label, { exact: true });
      const previous = await field.inputValue();
      await field.fill(invalid);
      await range
        .getByRole("button", {
          name: "Probe one MAC address page",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText(expected);
      expect(pages).toBe(0);
      await field.fill(previous);
    }
    await range
      .getByLabel("Per-MAC response seconds", { exact: true })
      .fill("1.5");
    await range
      .getByLabel("Request spacing seconds", { exact: true })
      .fill("0.2");
    await range.getByLabel("Page deadline seconds", { exact: true }).fill("10");
    await range
      .getByRole("button", { name: "Probe one MAC address page", exact: true })
      .click();
    await expect(
      range.getByLabel("First MAC in page", { exact: true }),
    ).toBeDisabled();
    await expect(
      range.getByLabel("Per-MAC response seconds", { exact: true }),
    ).toBeDisabled();
    await expect(
      range.getByLabel("Request spacing seconds", { exact: true }),
    ).toBeDisabled();
    await expect(
      range.getByLabel("Page deadline seconds", { exact: true }),
    ).toBeDisabled();
    const result = range.getByRole("region", {
      name: "Controller address page results",
      exact: true,
    });
    await expect(result).toContainText(
      "1 identities returned; 3 addresses attempted",
    );
    await expect(result).toContainText(
      "not an exhaustive controller inventory",
    );
    const rows = result.locator("tbody tr");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("2105:6");
    await expect(rows.nth(0)).toContainText("No response · unknown");
    await expect(rows.nth(1)).toContainText("device,132007");
    await expect(rows.nth(2)).toContainText("No response · unknown");
    const downloading = page.waitForEvent("download");
    await result
      .getByRole("button", { name: "Download address page JSON", exact: true })
      .click();
    const report = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    expect(report).toMatchObject({
      router: peer.router,
      dnet: 2105,
      complete: true,
      truncated: false,
      next_mac: null,
      request: {
        mac_low: 6,
        mac_high: 8,
        per_mac_timeout_seconds: 1.5,
        spacing_seconds: 0.2,
        timeout_seconds: 10,
      },
    });
    expect(report.attempts.map((row: any) => row.outcome)).toEqual([
      "timeout",
      "identified",
      "timeout",
    ]);
    expect(report.devices).toHaveLength(1);
    expect(report.devices[0]).toMatchObject({
      router: peer.router,
      dnet: 2105,
      mac: 7,
      address: "2105:7",
      device: "device,132007",
      live_verified: true,
    });
    await result
      .getByRole("button", { name: "Read metadata for 2105:7", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Probed controller identity",
        exact: true,
      }),
    ).toContainText("VMA1630 independent fixture");
    await range
      .getByLabel("Request spacing seconds", { exact: true })
      .fill("0.25");
    await expect(result).toHaveCount(0);
    await expect(
      range.getByRole("button", {
        name: "Download address page JSON",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(pages).toBe(1);
    await range
      .getByRole("button", { name: "Probe one MAC address page", exact: true })
      .click();
    await expect(result).toContainText(
      "1 identities returned; 3 addresses attempted",
    );
    await result
      .getByRole("button", { name: "Prepare next MAC page", exact: true })
      .click();
    await expect(
      range.getByLabel("First MAC in page", { exact: true }),
    ).toHaveValue("9");
    await expect(
      range.getByLabel("Last MAC in page", { exact: true }),
    ).toHaveValue("40");
    await expect(panel).toContainText("Next page is a draft");
    expect(pages).toBe(2);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await peer.close();
    expect(evidence.frames).toBe(12);
  }
});
