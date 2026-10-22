import { test, expect } from "@playwright/test";
import { createSocket } from "node:dgram";

async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      socket.close(() =>
        resolve(typeof address === "string" ? 0 : address.port),
      );
    });
  });
}

test("a delayed interface-open response preserves COV drafts for an unchanged empty optional DNET", async ({
  page,
  request,
}) => {
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  await request.post("/api/bacnet/disconnect", { headers, data: {} });
  let initialized!: () => void;
  const initial = new Promise<void>((resolve) => {
    initialized = resolve;
  });
  let first = true;
  await page.route("**/api/bacnet/status", async (route) => {
    if (first) {
      first = false;
      await route.fulfill({ json: { connected: false, commands: [] } });
      initialized();
    } else await route.continue();
  });
  let entered!: () => void;
  let release!: () => void;
  const opening = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/bacnet/connect", async (route) => {
    const response = await route.fetch();
    entered();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await initial;
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await opening;
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    await panel
      .getByLabel("COV device IP / port", { exact: true })
      .fill("192.0.2.7:47809");
    await panel
      .getByLabel("Expected COV Device", { exact: true })
      .fill("device,42");
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-input,9");
    await panel
      .getByLabel("Record COV receipts and eligible trends locally", {
        exact: true,
      })
      .check();
    release();
    await expect(
      page.getByRole("button", { name: "Close BACnet interface", exact: true }),
    ).toBeVisible();
    await expect(
      panel.getByLabel("Expected COV Device", { exact: true }),
    ).toHaveValue("device,42");
    await expect(
      panel.getByLabel("COV device IP / port", { exact: true }),
    ).toHaveValue("192.0.2.7:47809");
    await expect(
      panel.getByLabel("COV monitored object", { exact: true }),
    ).toHaveValue("analog-input,9");
    await expect(
      panel.getByLabel("Record COV receipts and eligible trends locally", {
        exact: true,
      }),
    ).toBeChecked();
    await expect(
      panel.getByRole("button", {
        name: "Start verified COV monitor",
        exact: true,
      }),
    ).toBeEnabled();
    // A genuinely different selected source still invalidates stale Device,
    // point and recording declarations. These are drafts; no field query occurs.
    await page
      .getByLabel("Unicast target", { exact: true })
      .fill("192.0.2.8:47809");
    await expect(
      panel.getByLabel("COV device IP / port", { exact: true }),
    ).toHaveValue("192.0.2.8:47809");
    await expect(
      panel.getByLabel("Expected COV Device", { exact: true }),
    ).toHaveValue("");
    await expect(
      panel.getByLabel("COV monitored object", { exact: true }),
    ).toHaveValue("analog-value,1");
    await expect(
      panel.getByLabel("Record COV receipts and eligible trends locally", {
        exact: true,
      }),
    ).not.toBeChecked();
  } finally {
    release();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});
