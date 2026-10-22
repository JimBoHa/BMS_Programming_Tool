import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
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

async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}

test.afterEach(async ({ request }) => {
  const closed = await request.post("/api/bacnet/disconnect", {
    headers: await headers(request),
    data: {},
  });
  expect(closed.ok()).toBe(true);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});

async function heldSavedStatus(page: Page, request: APIRequestContext) {
  const saved = {
    local_address: `127.0.0.1:${await freePort()}`,
    instance: 4190032,
    router: null,
    dnet: null,
    bbmd_address: null,
    foreign_ttl: 60,
  };
  expect(
    (
      await request.post("/api/bacnet/connect", {
        headers: await headers(request),
        data: saved,
      })
    ).ok(),
  ).toBe(true);
  let release!: () => void;
  let captured!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    captured = resolve;
  });
  let first = true;
  await page.route("**/api/bacnet/status", async (route) => {
    if (!first) return route.continue();
    first = false;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    expect((await response.json()).config.local_address).toBe(
      saved.local_address,
    );
    captured();
    await gate;
    await route.fulfill({ response });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await received;
  return { saved, release };
}

test("late saved status preserves a focused pre-input draft and its selection before opening the exact new interface", async ({
  page,
  request,
}) => {
  const held = await heldSavedStatus(page, request);
  try {
    const local = page.getByLabel("Local bind address / UDP port", {
      exact: true,
    });
    await expect(local).toHaveValue("127.0.0.1:47809");
    await local.focus();
    await local.evaluate((element) => (element as HTMLInputElement).select());
    const selection = await local.evaluate((element) => {
      const input = element as HTMLInputElement;
      return [input.selectionStart, input.selectionEnd];
    });
    const delivered = page.waitForResponse("**/api/bacnet/status");
    held.release();
    await (await delivered).finished();
    await expect(
      page.getByText("BACnet interface open", { exact: true }),
    ).toBeVisible();
    await expect(local).toHaveValue("127.0.0.1:47809");
    expect(
      await local.evaluate((element) => {
        const input = element as HTMLInputElement;
        return [input.selectionStart, input.selectionEnd];
      }),
    ).toEqual(selection);
    const requested = `127.0.0.1:${await freePort()}`;
    await page.keyboard.insertText(requested);
    await expect(local).toHaveValue(requested);
    const opening = page.waitForRequest("**/api/bacnet/connect");
    const opened = page.waitForResponse("**/api/bacnet/connect");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    expect((await opening).postDataJSON().local_address).toBe(requested);
    expect((await opened).ok()).toBe(true);
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/status")).json()).config
            .local_address,
      )
      .toBe(requested);
  } finally {
    held.release();
  }
});

test("late saved status still restores an untouched IP draft", async ({
  page,
  request,
}) => {
  const held = await heldSavedStatus(page, request);
  try {
    const delivered = page.waitForResponse("**/api/bacnet/status");
    held.release();
    await (await delivered).finished();
    await expect(
      page.getByLabel("Local bind address / UDP port", { exact: true }),
    ).toHaveValue(held.saved.local_address);
    await expect(
      page.getByLabel("Client device instance", { exact: true }),
    ).toHaveValue(String(held.saved.instance));
  } finally {
    held.release();
  }
});
