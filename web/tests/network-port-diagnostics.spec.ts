import { expect, test, type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import { freePort } from "./workflow-peer";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";

async function controllers() {
  const root = path.resolve("..");
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    ["-u", "-m", "tests.network_port_peer"],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let errors = "";
  child.stderr.on("data", (v) => {
    errors = (errors + v.toString()).slice(-2000);
  });
  const lines = createInterface({ input: child.stdout });
  try {
    const endpoints = await new Promise<[string, string]>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("Port peer startup timed out: " + errors)),
        8000,
      );
      lines.once("line", (line) => {
        clearTimeout(timer);
        resolve(JSON.parse(line));
      });
      child.once("exit", () => {
        clearTimeout(timer);
        reject(new Error("Port peer exited: " + errors));
      });
      child.once("error", (e) => {
        clearTimeout(timer);
        reject(e);
      });
    });
    return { endpoints, close: () => child.kill() };
  } catch (error) {
    child.kill();
    throw error;
  } finally {
    lines.close();
  }
}

async function select(page: Page, address: string) {
  const connect = page.getByRole("button", {
    name: /^Connect to a controller/,
  });
  if (!(await connect.isVisible())) await chooseWorkspaceSurface(page, "Start");
  await connect.click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  const form = page.getByRole("region", {
    name: "Known controller connection",
    exact: true,
  });
  await form
    .getByLabel("Known controller address", { exact: true })
    .fill(address);
  await form
    .getByLabel("Known Device object", { exact: true })
    .fill("device,42");
  await form
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toBeVisible();
  await chooseWorkspaceTask(page, "Points & I/O");
  const nav = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  const choices = nav.getByRole("combobox");
  if (await choices.isVisible())
    await choices.selectOption({ label: "Read properties" });
  else
    await nav
      .getByRole("button", { name: "Read properties", exact: true })
      .click();
}

test("MS/TP port readings keep verified counter changes with the selected port and vendor", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const peers = await controllers();
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  const counters: string[] = [];
  page.on("request", (r) => {
    if (
      r.url().endsWith("/api/bacnet/controller/properties") &&
      r.postDataJSON()?.properties?.includes("2867")
    )
      counters.push(r.postDataJSON().address);
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const ready = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(ready.ok()).toBe(true);
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: /^Connect to a controller/ }),
    ).toBeVisible();
    await select(page, peers.endpoints[0]);
    await page
      .getByRole("button", { name: "Read object list", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Select port network-port,7", exact: true })
      .click();
    const region = page.getByRole("region", {
      name: "Network port diagnostics",
      exact: true,
    });
    const firstRead = region.getByRole("button", {
      name: "Read port diagnostics",
      exact: true,
    });
    expect(counters).toEqual([]);
    await firstRead.click();
    await expect(region).toContainText("Test field port");
    await expect(region).toContainText("38400 bit/s");
    const sent = region.getByRole("row", { name: /Token frames sent/ });
    await expect(sent.getByRole("cell").first()).toHaveText("10");
    await expect(sent.getByRole("cell").last()).toHaveText("—");
    const again = region.getByRole("button", {
      name: "Read port diagnostics again",
      exact: true,
    });
    await again.click();
    await expect(sent.getByRole("cell").first()).toHaveText("20");
    await expect(sent.getByRole("cell").last()).toHaveText("10");
    await expect(
      region.getByRole("row", { name: /Token frames received/ }),
    ).toContainText("Counter decreased");
    await expect(
      region.getByRole("row", { name: /Packets timed out/ }),
    ).toContainText("Unexpected counter type");
    let resumed!: () => void, reached!: () => void;
    const announced = new Promise<void>((resolve) => {
      reached = resolve;
    });
    const hold = new Promise<void>((resolve) => {
      resumed = resolve;
    });
    await page.route("**/api/bacnet/controller/properties", async (route) => {
      const res = await route.fetch();
      if (route.request().postDataJSON()?.properties?.includes("2867")) {
        reached();
        await hold;
      }
      await route.fulfill({ response: res });
    });
    try {
      await again.click();
      await announced;
      await page
        .getByLabel("Object identifier", { exact: true })
        .fill("network-port,8");
      resumed();
      await firstRead.click();
      await expect(region).toContainText("Test IP port");
      await expect(region.getByRole("table")).toHaveCount(0);
      await expect(region).not.toContainText("Test field port");
    } finally {
      resumed();
    }
    await page.unroute("**/api/bacnet/controller/properties");
    const object = page.getByLabel("Object identifier", { exact: true });
    await object.fill("device,42");
    await page
      .getByRole("button", { name: "Read object list", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Select port 195,11", exact: true })
      .click();
    await firstRead.click();
    await expect(region).toContainText("Example legacy field bus");
    await expect(region).toContainText("Network 123");
    await expect(region).toContainText("Active baud rate code 3");
    await expect(region).toContainText("Maximum manager address 127");
    await expect(sent.getByRole("cell").first()).toHaveText("13");
    await again.click();
    await expect(sent.getByRole("cell").first()).toHaveText("26");
    await expect(sent.getByRole("cell").last()).toHaveText("13");
    await object.fill("195,12");
    await firstRead.click();
    await expect(region.getByRole("alert")).toContainText("active baud code");
    await expect(region.getByRole("table")).toHaveCount(0);
    await select(page, peers.endpoints[1]);
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("network-port,7");
    await firstRead.click();
    await expect(region).toContainText("Test field port");
    await expect(region.getByRole("table")).toHaveCount(0);
    const otherVendorReads: string[][] = [];
    page.on("request", (r) => {
      if (r.url().endsWith("/api/bacnet/controller/properties")) {
        otherVendorReads.push(r.postDataJSON().properties);
      }
    });
    await object.fill("195,11");
    await firstRead.click();
    await expect(region.getByRole("alert")).toContainText(
      "verified Johnson Controls",
    );
    expect(otherVendorReads).toEqual([["vendor-identifier"]]);
    expect(counters).toEqual([
      peers.endpoints[0],
      peers.endpoints[0],
      peers.endpoints[0],
      peers.endpoints[0],
      peers.endpoints[0],
    ]);
  } finally {
    peers.close();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});
