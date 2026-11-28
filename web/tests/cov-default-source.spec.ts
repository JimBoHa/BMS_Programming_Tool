import { test, expect } from "@playwright/test";
import { scheduleControllerPeer } from "./schedule-controller-peer";
import { freePort } from "./workflow-peer";
import {
  openConnectionDetails,
  selectKnownController,
} from "./workflow-navigation";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";

test("a delayed interface-open response preserves COV drafts for an unchanged empty optional DNET", async ({
  page,
  request,
}) => {
  const first = await scheduleControllerPeer();
  const other = await scheduleControllerPeer();
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  let unlock!: () => void;
  const hold = new Promise<void>((resolve) => {
    unlock = resolve;
  });
  let startCalls = 0;
  page.on("request", (req) => {
    if (req.url().endsWith("/api/bacnet/cov/start")) startCalls++;
  });
  let legacyStatus = true;
  await page.route("**/api/bacnet/status", async (route) => {
    const response = await route.fetch();
    const status = await response.json();
    if (legacyStatus && status.config && status.config.dnet == null)
      delete status.config.dnet;
    await route.fulfill({ response, json: status });
  });
  const cov = page.getByRole("region", {
    name: "BACnet COV monitoring",
    exact: true,
  });
  const point = cov.getByLabel("COV monitored object", { exact: true });
  const lifetime = cov.getByLabel("COV lease seconds", { exact: true });
  const mode = cov.getByLabel("COV notification mode", { exact: true });
  const recording = cov.getByLabel(
    "Record COV receipts and eligible trends locally",
    { exact: true },
  );
  const show = async (target: { address: string; device: string }) => {
    await selectKnownController(page, target.address, target.device);
    await chooseWorkspaceTask(page, "Trends & Alarms");
    await chooseWorkspaceTool(
      page,
      "Live COV monitor",
      "Controller task tools",
    );
    await expect(cov).toBeVisible();
  };
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await page.goto("/");
    await openConnectionDetails(page);
    const bind = "127.0.0.1:" + (await freePort());
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(bind);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await show(first.target);
    await point.fill("analog-input,5");
    await lifetime.fill("120");
    await mode.selectOption("unconfirmed");
    await recording.check();
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(
      cov.getByRole("button", { name: "Start verified COV monitor" }),
    ).toBeDisabled();
    await expect(point).toHaveValue("analog-input,5");
    await expect(recording).toBeChecked();
    await expect(lifetime).toHaveValue("120");
    await expect(mode).toHaveValue("unconfirmed");
    await openConnectionDetails(page);
    await expect(
      page.getByLabel("Local bind address / UDP port", { exact: true }),
    ).toHaveValue(bind);
    let sawOpen!: () => void;
    const opened = new Promise<void>((resolve) => {
      sawOpen = resolve;
    });
    await page.route("**/api/bacnet/connect", async (route) => {
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      sawOpen();
      await hold;
      await route.fulfill({ response });
    });
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await opened;
    const actual = await (await request.get("/api/bacnet/status")).json();
    expect(actual.connected).toBe(true);
    expect(actual.config.dnet).toBeNull();
    legacyStatus = false;
    unlock();
    await expect(
      page.getByRole("button", { name: "Close BACnet interface", exact: true }),
    ).toBeVisible();
    await page.unroute("**/api/bacnet/connect");
    await show(first.target);
    await expect(point).toHaveValue("analog-input,5");
    await expect(recording).toBeChecked();
    await expect(lifetime).toHaveValue("120");
    await expect(mode).toHaveValue("unconfirmed");
    await expect(
      cov.getByRole("button", { name: "Start verified COV monitor" }),
    ).toBeEnabled();
    await show(other.target);
    await expect(point).toHaveValue("");
    await expect(recording).not.toBeChecked();
    await show(first.target);
    await expect(point).toHaveValue("");
    await expect(recording).not.toBeChecked();
    expect(startCalls).toBe(0);
    for (const peer of [first, other]) {
      const stats = await peer.stats();
      expect(stats.reads).toBeGreaterThan(0);
      expect(stats.writes).toBe(0);
    }
    expect(
      (await (await request.get("/api/bacnet/cov/status")).json()).jobs,
    ).toEqual([]);
  } finally {
    unlock();
    await Promise.all([first.close(), other.close()]);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});
