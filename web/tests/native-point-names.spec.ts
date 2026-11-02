import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import {
  emptyPointNameWork,
  rememberPointNameWork,
  type PointNameWork,
} from "../src/nativePointNameWork";
const base = "/api/bacnet/controller/native-application";
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  expect(
    (
      await request.post(base + "/credentials", {
        headers,
        data: { backup: "authored-backup", restore: "authored-restore" },
      })
    ).ok(),
  ).toBe(true);
}
async function open(page: Page, endpoint: string) {
  let published = "Authored input";
  await page.route("**/api/bacnet/controller/inventory", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: route.request().postDataJSON(),
        offset: 0,
        total: 1,
        next_offset: null,
        objects: [
          {
            object: "analog-input,101",
            object_type: 0,
            has_present_value: true,
          },
        ],
        errors: [],
        finished_at: new Date().toISOString(),
      },
    }),
  );
  await page.route("**/api/bacnet/controller/properties", (route) => {
    const body = route.request().postDataJSON();
    const fields: Record<string, unknown> = {
      "object-name": published,
      "present-value": 72,
      units: "degrees-fahrenheit",
      reliability: 0,
      "out-of-service": false,
      "status-flags": [0, 0, 0, 0],
      description: "Authored local point",
    };
    return route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: body,
        objects: body.object_ids.map((object: string) => ({
          object,
          identity_verified: true,
          properties: Object.fromEntries(
            body.properties.map((p: string) => [
              p,
              { status: "ok", value: fields[p] ?? "Authored configuration" },
            ]),
          ),
        })),
        errors: [],
        finished_at: new Date().toISOString(),
      },
    });
  });
  await page.route("**/native-application/point-name/apply", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    const data = await response.json();
    if (data.result?.status === "verified")
      published = data.result.published_point_name;
    await route.fulfill({ response, json: data });
  });
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
    .fill(endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill("");
  await page.getByLabel("Known network", { exact: true }).fill("");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored controller");
  await chooseWorkspaceTask(page, "Points & I/O");
  return configure(page);
}
async function configure(page: Page) {
  const row = page
    .getByRole("region", { name: "Connected controller points" })
    .getByRole("row")
    .filter({ hasText: "analog-input,101" });
  await row.getByRole("button", { name: "Configuration", exact: true }).click();
  await page.getByText("Edit point name", { exact: true }).click();
  return page.getByRole("region", {
    name: "Native point name configuration",
    exact: true,
  });
}
test("point configuration keeps drafts across tasks, retires reviews, and verifies one owned native transfer", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  await reset(request);
  const peer = await nativeDefaultPeer("consume", "point-name");
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/point-name/apply")) writes.push(r.url());
  });
  try {
    let p = await open(page, peer.direct);
    await p
      .getByRole("button", { name: "Read point name backup", exact: true })
      .click();
    await expect(p).toContainText("Captured name: Authored input");
    await p
      .getByLabel("New point name", { exact: true })
      .fill("Reviewed input");
    await p
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await expect(
      p.getByRole("button", { name: "Apply point name", exact: true }),
    ).toBeDisabled();
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    p = await configure(page);
    await expect(p.getByLabel("New point name", { exact: true })).toHaveValue(
      "Reviewed input",
    );
    await expect(
      p.getByRole("button", { name: "Apply point name", exact: true }),
    ).toHaveCount(0);
    expect(writes).toEqual([]);
    await p
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await p
      .getByLabel("I confirm this point name change.", { exact: true })
      .check();
    await p
      .getByLabel(
        "I reviewed the application transfer and brief interruption.",
        { exact: true },
      )
      .check();
    await p
      .getByRole("button", { name: "Apply point name", exact: true })
      .click();
    await expect(
      p.getByRole("region", { name: "Point name transfer receipt" }),
    ).toContainText("Published name: Reviewed input.", { timeout: 30000 });
    expect(writes).toHaveLength(1);
    const stats = await peer.command("stats");
    expect(
      stats.events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
    await p
      .getByRole("button", { name: "Read back point name", exact: true })
      .click();
    await expect(
      p.getByRole("button", { name: "Read back point name", exact: true }),
    ).toBeEnabled();
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
    await page.screenshot({
      path: info.outputPath("point-name-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 1100 });
    await p.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("point-name-phone.png"),
      fullPage: true,
    });
  } finally {
    peer.close();
  }
});

async function prepareName(page: Page, endpoint: string) {
  const panel = await open(page, endpoint);
  await panel
    .getByRole("button", { name: "Read point name backup", exact: true })
    .click();
  await expect(panel).toContainText("Captured name: Authored input");
  await panel
    .getByLabel("New point name", { exact: true })
    .fill("Reviewed input");
  return panel;
}

test("an Apply receipt from another operation cannot clear this point-name draft", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const peer = await nativeDefaultPeer("consume", "point-name");
  try {
    const panel = await prepareName(page, peer.direct);
    let originalReceipt: any;
    await page.route(
      "**/native-application/point-name/apply",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        originalReceipt = await response.json();
        expect(originalReceipt.result.status).toBe("verified");
        const substituted = structuredClone(originalReceipt);
        substituted.intent.operation_id = "another-owned-operation";
        await route.fulfill({ response, json: substituted });
      },
    );
    await panel
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await panel
      .getByLabel("I confirm this point name change.", { exact: true })
      .check();
    await panel
      .getByLabel(
        "I reviewed the application transfer and brief interruption.",
        { exact: true },
      )
      .check();
    const applied = page.waitForResponse(
      (r) => r.url().endsWith("/point-name/apply"),
      { timeout: 30000 },
    );
    await panel
      .getByRole("button", { name: "Apply point name", exact: true })
      .click();
    await applied;
    await expect(panel.getByRole("alert")).toContainText(
      "does not match this operation",
    );
    await expect(
      panel.getByLabel("New point name", { exact: true }),
    ).toHaveValue("Reviewed input");
    await expect(
      panel.getByRole("region", { name: "Point name transfer receipt" }),
    ).toHaveCount(0);
    await panel
      .getByLabel("Retained point name transfer", { exact: true })
      .selectOption(originalReceipt.intent.id);
    await expect(
      panel.getByRole("region", { name: "Point name transfer receipt" }),
    ).toContainText("Published name: Reviewed input.");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    peer.close();
  }
});

test("point-name work refuses a 33rd source, preserves all drafts, and frees only explicitly discarded work", () => {
  const drafts = new Map<string, PointNameWork>();
  for (let index = 0; index < 32; index++) {
    expect(
      rememberPointNameWork(drafts, `point-${index}`, {
        ...emptyPointNameWork(),
        name: `Unfinished ${index}`,
        capture: { id: index },
      }),
    ).toBe(true);
  }
  const before = [...drafts];
  expect(
    rememberPointNameWork(drafts, "point-33", {
      ...emptyPointNameWork(),
      name: "New",
    }),
  ).toBe(false);
  expect([...drafts]).toEqual(before);
  expect(
    rememberPointNameWork(drafts, "empty-mount", emptyPointNameWork()),
  ).toBe(true);
  expect(drafts.size).toBe(32);
  expect(
    rememberPointNameWork(drafts, "point-31", {
      ...drafts.get("point-31")!,
      name: "Still unfinished",
    }),
  ).toBe(true);
  expect(drafts.get("point-0")!.name).toBe("Unfinished 0");
  expect(rememberPointNameWork(drafts, "point-31", emptyPointNameWork())).toBe(
    true,
  );
  expect(
    rememberPointNameWork(drafts, "point-33", {
      ...emptyPointNameWork(),
      name: "New",
    }),
  ).toBe(true);
  expect(drafts.size).toBe(32);
});

for (const changed of ["operation", "capture", "record", "snapshot", "profile"])
  test(`a point-name review with a substituted ${changed} never grants Apply`, async ({
    page,
    request,
  }) => {
    await reset(request);
    const peer = await nativeDefaultPeer("consume", "point-name");
    try {
      const panel = await prepareName(page, peer.direct);
      await page.route(
        "**/native-application/point-name/preview",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          const data = await response.json();
          if (changed === "operation")
            data.operation_id = "another-preview-operation";
          if (changed === "capture") data.capture_id = "f".repeat(32);
          if (changed === "record") data.point_name_edit.record_ref += "/other";
          if (changed === "snapshot") data.snapshot_sha256 = "f".repeat(64);
          if (changed === "profile")
            data.operation_profile = "other-name-transfer/1";
          await route.fulfill({ response, json: data });
        },
      );
      await panel
        .getByRole("button", { name: "Review point name change", exact: true })
        .click();
      await expect(panel.getByRole("alert")).toContainText(
        "review differs from this draft",
      );
      await expect(
        panel.getByRole("button", { name: "Apply point name", exact: true }),
      ).toHaveCount(0);
      await expect(
        panel.getByLabel("New point name", { exact: true }),
      ).toHaveValue("Reviewed input");
      expect(
        (await peer.command("stats")).events.filter(
          (e: any[]) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(0);
    } finally {
      peer.close();
    }
  });

test("visibility retirement preserves the proposal and cannot revive an Apply review", async ({
  page,
  request,
}) => {
  await reset(request);
  const peer = await nativeDefaultPeer("consume", "point-name");
  try {
    const panel = await prepareName(page, peer.direct);
    await panel
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await expect(
      panel.getByRole("region", { name: "Reviewed point name change" }),
    ).toBeVisible();
    await page.evaluate(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect(
      panel.getByRole("button", { name: "Apply point name", exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByLabel("New point name", { exact: true }),
    ).toHaveValue("Reviewed input");
    await panel
      .getByRole("button", {
        name: "Discard local point name work",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("New point name", { exact: true }),
    ).toHaveCount(0);
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    const reopened = await configure(page);
    await expect(
      reopened.getByLabel("New point name", { exact: true }),
    ).toHaveCount(0);
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("late receipt export is retired, original bytes remain downloadable, and old readback keeps newer work", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const peer = await nativeDefaultPeer("consume", "point-name");
  let release = () => {};
  try {
    let panel = await prepareName(page, peer.direct);
    await panel
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await panel
      .getByLabel("I confirm this point name change.", { exact: true })
      .check();
    await panel
      .getByLabel(
        "I reviewed the application transfer and brief interruption.",
        { exact: true },
      )
      .check();
    await panel
      .getByRole("button", { name: "Apply point name", exact: true })
      .click();
    await expect(
      panel.getByRole("region", { name: "Point name transfer receipt" }),
    ).toContainText("Published name: Reviewed input.", { timeout: 30000 });
    const downloads: string[] = [];
    page.on("download", (download) =>
      downloads.push(download.suggestedFilename()),
    );
    let arrived!: () => void, finished!: () => void;
    const held = new Promise<void>((resolve) => {
      arrived = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const delivered = new Promise<void>((resolve) => {
      finished = resolve;
    });
    let original = Buffer.alloc(0);
    await page.route(
      "**/native-application/receipts/*",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        original = await response.body();
        arrived();
        await gate;
        await route.fulfill({ response, body: original });
        finished();
      },
      { times: 1 },
    );
    await panel
      .getByRole("button", { name: "Save point name receipt", exact: true })
      .click();
    await held;
    await chooseWorkspaceTask(page, "Overview");
    release();
    await delivered;
    await chooseWorkspaceTask(page, "Points & I/O");
    panel = await configure(page);
    await expect(
      panel.getByRole("button", {
        name: "Save point name receipt",
        exact: true,
      }),
    ).toBeEnabled();
    expect(downloads).toEqual([]);
    const saved = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Save point name receipt", exact: true })
      .click();
    const stream = await (await saved).createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks)).toEqual(original);
    await panel
      .getByRole("button", { name: "Read point name backup", exact: true })
      .click();
    await expect(panel).toContainText("Captured name: Reviewed input");
    await panel
      .getByLabel("New point name", { exact: true })
      .fill("Next unfinished input");
    await panel
      .getByRole("button", { name: "Read back point name", exact: true })
      .click();
    await expect(
      panel.getByRole("button", { name: "Read back point name", exact: true }),
    ).toBeEnabled({ timeout: 30000 });
    await expect(
      panel.getByLabel("New point name", { exact: true }),
    ).toHaveValue("Next unfinished input");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    release();
    peer.close();
  }
});

test("a published-name mismatch remains uncertain and retains the unfinished proposal", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const peer = await nativeDefaultPeer("published-old", "point-name");
  try {
    const panel = await prepareName(page, peer.direct);
    await panel
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await panel
      .getByLabel("I confirm this point name change.", { exact: true })
      .check();
    await panel
      .getByLabel(
        "I reviewed the application transfer and brief interruption.",
        { exact: true },
      )
      .check();
    await panel
      .getByRole("button", { name: "Apply point name", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "Point name transfer receipt",
    });
    await expect(receipt).toContainText("Outcome uncertain", {
      timeout: 30000,
    });
    await expect(
      panel.getByLabel("New point name", { exact: true }),
    ).toHaveValue("Reviewed input");
    await expect(
      receipt.getByRole("button", {
        name: "Read back point name",
        exact: true,
      }),
    ).toBeEnabled();
    // Resolve this owned controller's uncertain intent through real readback.
    // The next test must not inherit an intentionally unresolved field action.
    await peer.command("point-name-publish-current");
    await receipt
      .getByRole("button", { name: "Read back point name", exact: true })
      .click();
    await expect(receipt).toContainText("Result: verified", { timeout: 30000 });
    await expect(receipt).not.toContainText("Outcome uncertain");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    peer.close();
  }
});
