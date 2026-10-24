import { test, expect, type Page, type Locator } from "./operationPowerFixture";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const endpoint = "/api/operation-power";
const digest = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
async function control(page: Page, action: string) {
  const token = (await (await page.request.get("/api/session")).json()).token;
  const result = await page.request.post("/__test_power/" + action, {
    headers: { "X-Studio-Token": token },
    data: {},
  });
  expect(result.status()).toBe(200);
  expect((await result.json()).OS_requests).toBe(0);
}
test.beforeEach(async ({ page }) => {
  await control(page, "reset");
});
test.afterEach(async ({ page, powerIdentity }) => {
  await control(page, "finish");
  await test.info().attach("owned-power-server-identity", {
    body: readFileSync(powerIdentity),
    contentType: "application/json",
  });
});
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Operation power status",
    exact: true,
  });
  await expect(panel).toBeVisible();
  return panel;
}
async function snapshot(page: Page, panel: Locator) {
  let raw: Buffer | undefined;
  await page.route(
    "**" + endpoint,
    async (route) => {
      expect(route.request().method()).toBe("GET");
      expect(route.request().headers()["x-studio-token"]).toBeTruthy();
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      expect(response.status()).toBe(200);
      raw = await response.body();
      await route.fulfill({ response, body: raw });
    },
    { times: 1 },
  );
  await panel
    .getByRole("button", {
      name: "Refresh operation power status",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Export original power status JSON",
      exact: true,
    }),
  ).toBeVisible();
  expect(raw).toBeDefined();
  await test.info().attach("original-upstream-power-status-response", {
    body: raw!,
    contentType: "application/json",
  });
  return raw!;
}
async function exported(page: Page, panel: Locator) {
  const waiting = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Export original power status JSON",
      exact: true,
    })
    .click();
  const file = await waiting;
  const bytes = readFileSync((await file.path())!);
  await test.info().attach("original-downloaded-power-status", {
    body: bytes,
    contentType: "application/json",
  });
  return { bytes, filename: file.suggestedFilename() };
}
async function held(page: Page) {
  let seen!: () => void, release!: () => void, done!: () => void;
  const incoming = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  await page.route(
    "**" + endpoint,
    async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
        body = await response.body();
      seen();
      await gate;
      await route.fulfill({ response, body });
      done();
    },
    { times: 1 },
  );
  return { incoming, release, finished };
}

test("explicit read only: idle Connect never polls or acquires, and one refresh shows exact lifecycle identities", async ({
  page,
}) => {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith(endpoint)) calls.push(r.method());
  });
  const panel = await open(page);
  await expect(
    panel.getByText("No snapshot requested.", { exact: false }),
  ).toBeVisible();
  await page.waitForTimeout(1100);
  expect(calls).toEqual([]);
  const raw = await snapshot(page, panel),
    report = JSON.parse(raw.toString());
  expect(calls).toEqual(["GET"]);
  expect(report.provider).toBe("simulated-browser-idle-provider");
  expect(report.active).toHaveLength(2);
  expect(report.recent).toHaveLength(3);
  const active = panel.getByRole("table", {
    name: "Active power leases",
    exact: true,
  });
  for (const row of report.active) {
    expect(typeof row.id).toBe("string");
    expect(row.id).toMatch(/^[a-f0-9]{32}$/);
    await expect(active.getByText(row.id, { exact: true })).toBeVisible();
  }
  const uncertain = active.locator("tr").filter({ hasText: "cleanup_failed" });
  await expect(uncertain).toContainText("Unconfirmed");
  await expect(uncertain).toContainText("Yes, as reported");
  await expect(panel).toContainText(
    "Windows guest request does not keep its physical Mac host awake",
  );
  await expect(panel).toContainText(
    "Native JCI compilation and transfer are not supported",
  );
  await page.waitForTimeout(1100);
  expect(calls).toEqual(["GET"]);
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("export preserves actual original HTTP response bytes and independently computed local SHA", async ({
  page,
}) => {
  const panel = await open(page),
    raw = await snapshot(page, panel),
    file = await exported(page, panel);
  expect(file.bytes).toEqual(raw);
  expect(file.filename).toBe(`operation-power-${digest(raw)}.json`);
  await expect(panel.getByText(digest(raw), { exact: true })).toBeVisible();
  await expect(panel).toContainText("computed locally");
  await expect(panel).toContainText("not a server signature");
});

test("deliberate whitespace delivery fixture remains original Blob instead of display JSON reserialization", async ({
  page,
}) => {
  const panel = await open(page);
  let original: Buffer | undefined, delivered: Buffer | undefined;
  await page.route(
    "**" + endpoint,
    async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      original = await response.body();
      delivered = Buffer.concat([
        Buffer.from("\n  "),
        original,
        Buffer.from("\n"),
      ]);
      await route.fulfill({ response, body: delivered });
    },
    { times: 1 },
  );
  await panel
    .getByRole("button", {
      name: "Refresh operation power status",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Export original power status JSON",
      exact: true,
    }),
  ).toBeVisible();
  const file = await exported(page, panel);
  expect(file.bytes).toEqual(delivered);
  expect(file.bytes).not.toEqual(original);
  expect(JSON.parse(file.bytes.toString())).toEqual(
    JSON.parse(original!.toString()),
  );
  await test.info().attach("unmodified-upstream-before-format-fixture", {
    body: original!,
    contentType: "application/json",
  });
  await test.info().attach("synthetic-whitespace-delivered-response", {
    body: delivered!,
    contentType: "application/json",
  });
});

test("explicit refresh updates admission and lifecycle without interpreting cleanup failure as released", async ({
  page,
}) => {
  const panel = await open(page),
    before = JSON.parse((await snapshot(page, panel)).toString());
  const currentId = before.active.find((r: any) => r.state === "active").id;
  await control(page, "finish");
  const raw = await snapshot(page, panel),
    after = JSON.parse(raw.toString());
  expect(after.provider_available).toBe(false);
  expect(after.accepting).toBe(false);
  expect(after.active).toHaveLength(1);
  expect(after.active[0].state).toBe("cleanup_failed");
  const row = after.recent.find((r: any) => r.id === currentId);
  expect(row.state).toBe("released");
  expect(row.cleanup_confirmed).toBe(true);
  expect(row.request_active).toBe(false);
  await expect(
    panel
      .getByRole("table", { name: "Recent power leases", exact: true })
      .getByText(currentId, { exact: true }),
  ).toBeVisible();
  expect((await exported(page, panel)).bytes).toEqual(raw);
});

test("failed refresh retires old snapshot and export, reports error and never retries automatically", async ({
  page,
}) => {
  const panel = await open(page);
  await snapshot(page, panel);
  let attempts = 0;
  await page.route("**" + endpoint, async (route) => {
    attempts++;
    await route.fulfill({
      status: 503,
      json: { detail: "Simulated status read unavailable" },
    });
  });
  await panel
    .getByRole("button", {
      name: "Refresh operation power status",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "Simulated status read unavailable",
  );
  await expect(
    panel.getByRole("button", {
      name: "Export original power status JSON",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(panel.getByRole("table")).toHaveCount(0);
  await page.waitForTimeout(1100);
  expect(attempts).toBe(1);
});

test("unmount retires held read without downloads or restoring a report after returning to Connect", async ({
  page,
}) => {
  const panel = await open(page),
    pending = await held(page);
  let downloads = 0;
  page.on("download", () => downloads++);
  try {
    await panel
      .getByRole("button", {
        name: "Refresh operation power status",
        exact: true,
      })
      .click();
    await pending.incoming;
    await page.getByRole("button", { name: "Program", exact: true }).click();
    pending.release();
    await pending.finished;
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const fresh = page.getByRole("region", {
      name: "Operation power status",
      exact: true,
    });
    await expect(fresh).toContainText("No snapshot requested");
    await expect(
      fresh.getByRole("button", {
        name: "Export original power status JSON",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toBe(0);
  } finally {
    pending.release();
  }
});

test("discarded older response cannot overwrite a newer explicit status read or original export", async ({
  page,
}) => {
  const panel = await open(page);
  let seen!: () => void, release!: () => void, done!: () => void;
  const incoming = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  let requests = 0,
    fresh: Buffer | undefined;
  // One route owner captures both GETs; do not register a competing handler
  // while its earlier request is still held.
  await page.route("**" + endpoint, async (route) => {
    const index = ++requests,
      response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
      body = await response.body();
    if (index === 1) {
      seen();
      await gate;
    } else {
      expect(index).toBe(2);
      fresh = body;
    }
    await route.fulfill({ response, body });
    if (index === 1) done();
  });
  try {
    await panel
      .getByRole("button", {
        name: "Refresh operation power status",
        exact: true,
      })
      .click();
    await incoming;
    await panel
      .getByRole("button", {
        name: "Discard pending power response",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText("ignored");
    await control(page, "finish");
    await panel
      .getByRole("button", {
        name: "Refresh operation power status",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("button", {
        name: "Export original power status JSON",
        exact: true,
      }),
    ).toBeVisible();
    expect(fresh).toBeDefined();
    release();
    await finished;
    await page.waitForTimeout(250);
    expect((await exported(page, panel)).bytes).toEqual(fresh);
    expect(requests).toBe(2);
    await test.info().attach("original-newer-power-status-response", {
      body: fresh!,
      contentType: "application/json",
    });
    await expect(
      panel
        .getByRole("table", { name: "Active power leases", exact: true })
        .locator("tbody tr"),
    ).toHaveCount(1);
  } finally {
    release();
  }
});

for (const malformed of [
  "profile-hash",
  "profile-content",
  "duplicate-id",
  "numeric-id",
  "classification",
  "native-claim",
  "row-bound",
])
  test(`refuse ${malformed} without authorizing status export`, async ({
    page,
  }) => {
    const panel = await open(page);
    await snapshot(page, panel);
    await page.route("**" + endpoint, async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
        value = await response.json();
      if (malformed === "profile-hash") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "profile-content")
        value.profile.scope = "Incorrect host protection claim";
      else if (malformed === "duplicate-id")
        value.recent[0].id = value.active[0].id;
      else if (malformed === "numeric-id")
        value.active[0].id = 9007199254740992;
      else if (malformed === "classification")
        value.active.find(
          (r: any) => r.state === "cleanup_failed",
        ).request_active = false;
      else if (malformed === "row-bound")
        value.active = Array(9).fill(value.active[0]);
      else value.native_jci_transfer = true;
      await route.fulfill({ response, json: value });
    });
    await panel
      .getByRole("button", {
        name: "Refresh operation power status",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toBeVisible();
    await expect(
      panel.getByRole("button", {
        name: "Export original power status JSON",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(panel.getByRole("table")).toHaveCount(0);
  });
