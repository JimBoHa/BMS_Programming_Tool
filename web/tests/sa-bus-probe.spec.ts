import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { freePort } from "./workflow-peer";

const root = path.resolve("..");
const base = "/api/bacnet/controller/sa-bus-probe";

async function peer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_sa_bus_probe import SaPeer
async def main():
    transport,peer=await asyncio.get_running_loop().create_datagram_endpoint(SaPeer,local_addr=('127.0.0.1',0))
    print(json.dumps({'endpoint':peer.endpoint}),flush=True)
    try: await asyncio.to_thread(sys.stdin.readline)
    finally:
        transport.close()
        print(json.dumps({'writes':peer.writes,'errors':peer.errors}),flush=True)
        await asyncio.sleep(.05)
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let output = "",
    errors = "",
    ready = false;
  child.stderr.on("data", (data) => {
    errors += String(data);
  });
  const endpoint = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("SA peer startup timed out: " + errors));
    }, 6000);
    child.stdout.on("data", (data) => {
      output += String(data);
      if (!ready && output.includes("\n")) {
        ready = true;
        clearTimeout(timer);
        resolve(JSON.parse(output.split("\n")[0]).endpoint);
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (!ready) {
        clearTimeout(timer);
        reject(new Error(`SA peer exited ${code}: ${errors}`));
      }
    });
  });
  return {
    endpoint,
    async close() {
      const done = new Promise<void>((resolve, reject) => {
        child.once("exit", (code) =>
          code === 0
            ? resolve()
            : reject(new Error(`SA peer exited ${code}: ${errors}`)),
        );
      });
      child.stdin.end("stop\n");
      await done;
      return JSON.parse(output.trim().split("\n").at(-1)!);
    },
  };
}

async function open(page: Page, request: APIRequestContext, endpoint: string) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
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
    .fill("2105:7");
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,1234500");
  await page.getByLabel("Known router", { exact: true }).fill(endpoint);
  await page.getByLabel("Known network", { exact: true }).fill("2105");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored SA diagnostic controller");
  await diagnostics(page);
  return headers;
}

async function diagnostics(page: Page) {
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Points & I/O", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Controller task tools" })
    .getByRole("button", { name: "SA-bus diagnostics", exact: true })
    .click();
}

const panel = (page: Page) =>
  page.getByRole("region", { name: "SA-bus address diagnostics", exact: true });
const review = (page: Page) =>
  panel(page).getByRole("button", { name: "Review SA-bus probe", exact: true });

test("SA probe reviews, runs and exports real parent-scoped diagnostics; cancellation restores the selector", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  const station = await peer();
  let headers: Record<string, string> = {};
  try {
    headers = await open(page, request, station.endpoint);
    const view = panel(page);
    await view.getByLabel("Last SA MAC", { exact: true }).fill("200");
    await review(page).click();
    await expect(
      view.getByRole("button", { name: "Run SA-bus probe", exact: true }),
    ).toBeDisabled();
    await expect(view).toContainText("Firmware 10.0");
    // Editing a reviewed range invalidates its one-use field authority.
    await view.getByLabel("First SA MAC", { exact: true }).fill("200");
    await expect(
      view.getByRole("button", { name: "Run SA-bus probe", exact: true }),
    ).toHaveCount(0);
    await view.getByLabel("First SA MAC", { exact: true }).fill("199");
    await review(page).click();
    const confirmation = view.getByRole("checkbox", {
      name: "Run temporary SA-port diagnostics on this controller",
    });
    await confirmation.focus();
    await page.keyboard.press("Space");
    await expect(confirmation).toBeChecked();
    await view
      .getByRole("button", { name: "Run SA-bus probe", exact: true })
      .click();
    await expect(view).toContainText("Probe: complete", { timeout: 20000 });
    await expect(view).toContainText("Diagnostic restoration: verified");
    const rows = view.locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("432");
    await expect(rows.nth(1)).toContainText("Diagnostic success reported");
    await page.screenshot({
      path: info.outputPath("sa-probe-desktop.png"),
      fullPage: true,
    });
    const downloaded = page.waitForEvent("download");
    await view
      .getByRole("button", { name: "Download probe evidence", exact: true })
      .click();
    const document = JSON.parse(
      readFileSync((await (await downloaded).path())!, "utf8"),
    );
    expect(document.plan.target).toMatchObject({
      address: "2105:7",
      device: "device,1234500",
      router: station.endpoint,
      mac_low: 199,
      mac_high: 200,
    });
    expect(document).toMatchObject({
      state: "complete",
      restoration: "verified",
      recovery_required: false,
    });
    // Navigation retires a pending review, while the saved report remains local.
    await review(page).click();
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Overview", exact: true })
      .click();
    await diagnostics(page);
    await expect(
      view.getByRole("button", { name: "Run SA-bus probe", exact: true }),
    ).toHaveCount(0);
    await view.getByLabel("Last SA MAC", { exact: true }).fill("200");
    await review(page).click();
    await confirmation.check();
    await view
      .getByRole("button", { name: "Run SA-bus probe", exact: true })
      .click();
    await expect(view.locator("tbody tr").first()).toContainText("Testing");
    await expect
      .poll(async () => {
        const summaries = await (await request.get(base + "/reports")).json();
        const current = summaries.find((item: any) => item.state === "running");
        return current?.recovery_required;
      })
      .toBe(true);
    await view
      .getByRole("button", { name: "Cancel SA-bus probe", exact: true })
      .click();
    await expect(view).toContainText("Probe: cancelled", { timeout: 20000 });
    await expect(view).toContainText("Diagnostic restoration: verified");
    await page.setViewportSize({ width: 760, height: 1000 });
    await page.screenshot({
      path: info.outputPath("sa-probe-narrow.png"),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  } finally {
    // Leave no background diagnostic operation owned by this test.
    const reports = await (await request.get(base + "/reports")).json();
    for (const report of reports) {
      if (report.state === "running")
        await request.post(`${base}/reports/${report.id}/cancel`, {
          headers,
          data: {},
        });
    }
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await station.close();
    expect(evidence.errors).toEqual([]);
    expect(evidence.writes).toEqual([199, 200, 0, 199, 0]);
  }
});

test("an SA review arriving after navigation cannot restore its authority", async ({
  page,
  request,
}) => {
  const station = await peer();
  let release: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let arrived: (() => void) | undefined;
  const received = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  let headers: Record<string, string> = {};
  try {
    headers = await open(page, request, station.endpoint);
    await page.route("**" + base + "/review", async (route) => {
      const response = await route.fetch();
      arrived!();
      await held;
      await route.fulfill({ response });
    });
    await review(page).click();
    await received;
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Overview", exact: true })
      .click();
    release!();
    await diagnostics(page);
    await expect(
      panel(page).getByRole("button", {
        name: "Run SA-bus probe",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(review(page)).toBeEnabled();
  } finally {
    release!();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await station.close();
    expect(evidence.errors).toEqual([]);
    expect(evidence.writes).toEqual([]);
  }
});

test("a lost start response can be reopened without repeating the diagnostic", async ({
  page,
  request,
}) => {
  const station = await peer();
  let headers: Record<string, string> = {};
  try {
    headers = await open(page, request, station.endpoint);
    const view = panel(page);
    await view.getByLabel("First SA MAC", { exact: true }).fill("200");
    await view.getByLabel("Last SA MAC", { exact: true }).fill("200");
    await review(page).click();
    await view
      .getByRole("checkbox", {
        name: "Run temporary SA-port diagnostics on this controller",
      })
      .check();
    let starts = 0;
    await page.route("**" + base + "/run", async (route) => {
      starts++;
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      await route.abort();
    });
    await view
      .getByRole("button", { name: "Run SA-bus probe", exact: true })
      .click();
    await expect(view.getByRole("alert")).toContainText(
      "server may still be testing",
    );
    await expect(
      view.getByRole("button", { name: "Run SA-bus probe", exact: true }),
    ).toHaveCount(0);
    await view.getByText("Saved probe reports", { exact: true }).click();
    await view
      .getByRole("button", { name: "Refresh saved reports", exact: true })
      .click();
    await view.getByRole("button", { name: /^Open / }).click();
    await expect(view).toContainText("Probe: complete", { timeout: 20000 });
    await expect(view).toContainText("Diagnostic restoration: verified");
    expect(starts).toBe(1);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await station.close();
    expect(evidence.errors).toEqual([]);
    expect(evidence.writes).toEqual([200, 0]);
  }
});
