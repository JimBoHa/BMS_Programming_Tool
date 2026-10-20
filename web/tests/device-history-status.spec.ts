import { test, expect } from "@playwright/test";
import { createSocket } from "node:dgram";

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

test("a delayed initial history status cannot replace the refreshed real connector status", async ({
  page,
  request,
}) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  await request.post("/api/bacnet/disconnect", { headers, data: {} });
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let captured!: () => void;
  const received = new Promise<void>((resolve) => {
    captured = resolve;
  });
  let first = true;
  await page.route("**/api/bacnet/history/status", async (route) => {
    const hold = first;
    first = false;
    const response = await route.fetch();
    if (hold) {
      expect((await response.json()).connected).toBe(false);
      captured();
      await held;
    }
    await route.fulfill({ response });
  });
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: "Device history", exact: true })
      .click();
    await received;
    const connected = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(connected.ok()).toBeTruthy();
    await page
      .getByRole("button", { name: "Refresh history status", exact: true })
      .click();
    await expect(
      page.getByText("Shared BACnet interface: connected", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Read device history", exact: true }),
    ).toBeEnabled();
    const stale = page.waitForResponse((response) =>
      response.url().endsWith("/api/bacnet/history/status"),
    );
    release();
    await (await stale).finished();
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await expect(
      page.getByText("Shared BACnet interface: connected", { exact: true }),
    ).toBeVisible();
    expect(
      (await (await request.get("/api/bacnet/status")).json()).connected,
    ).toBe(true);
  } finally {
    release();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});
