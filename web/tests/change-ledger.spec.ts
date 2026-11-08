import { chooseWorkspaceTask } from "./workspace-navigation";
import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { freePort, peer } from "./workflow-peer";

const root = path.resolve("..");
const ledger = (page: Page) =>
  page.getByRole("region", { name: "Change ledger", exact: true });
const records = (page: Page) =>
  page.getByRole("region", { name: "Recorded changes", exact: true });
const tasks = (page: Page) =>
  page.getByRole("navigation", { name: "Workspace tasks" });
const evidence = (page: Page) =>
  page.getByRole("region", { name: "Change evidence", exact: true });
function row(source = "native", id = "a".repeat(32), extra = {}) {
  return {
    key: `${source}:${id}`,
    source,
    id,
    label: `Authored ${source} operation`,
    created_at: "2026-01-02T03:04:05+00:00",
    state: "unknown",
    outcome: "attention",
    kind: "receipt",
    target: {
      address: "3001:8",
      device: "device,5136",
      router: "127.0.0.1:49001",
      dnet: 3001,
    },
    object: "",
    local_source: "",
    pending: true,
    integrity: "source reader",
    detail_path: `/changes/records/${source}/${id}`,
    session_scoped: false,
    review_recorded: true,
    dispatch: "possible",
    readback: "unknown",
    ...extra,
  };
}
function report(rows: any[], extra = {}) {
  return {
    rows,
    errors: [],
    captured_at: "2026-01-02T03:04:05+00:00",
    next_cursor: null,
    coverage: [],
    window_per_source: 16,
    scope: "Authored UI fixture; no field acceptance",
    ...extra,
  };
}
async function session(request: APIRequestContext) {
  // Test-owned setup and cleanup must not reuse an idle socket across the UI work.
  const headers = {
    Connection: "close",
    "X-Studio-Token": (
      await (
        await request.get("/api/session", { headers: { Connection: "close" } })
      ).json()
    ).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  return headers;
}
async function openLedger(page: Page) {
  await page.goto("/");
  await page
    .getByRole("region", { name: "Continue local work", exact: true })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await chooseWorkspaceTask(page, "Changes");
  await expect(ledger(page)).toBeVisible();
}

for (const [kind, label, object] of [
  ["signal-default", "Native Real default transfer", "controller/526_1"],
  ["boolean-default", "Native Boolean default transfer", "controller/524_1"],
  ["wire-source", "Native wire source transfer", "controller/575_1"],
])
  test(`${kind} ledger evidence opens offline native Program tools without field dispatch`, async ({
    page,
  }) => {
    const id = "c".repeat(32),
      fieldCalls: string[] = [];
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        /\/api\/bacnet\/(connect|controller\/native-application\/(capture|reconcile|.*transfer\/(preview|apply)))/.test(
          new URL(request.url()).pathname,
        )
      )
        fieldCalls.push(request.url());
    });
    await page.route("**/api/changes/query", (route) =>
      route.fulfill({
        json: report([
          row("native", id, {
            native_change_kind: kind,
            label,
            object,
            detail_path: "/bacnet/controller/native-application/receipts/" + id,
          }),
        ]),
      }),
    );
    await page.route(
      "**/api/bacnet/controller/native-application/receipts/*",
      (route) =>
        route.fulfill({
          json: { intent: { id, change_kind: kind }, result: null },
        }),
    );
    await openLedger(page);
    await expect(records(page)).toContainText(label);
    await expect(records(page)).toContainText(object);
    await records(page)
      .getByRole("button", { name: `Details for native ${id}`, exact: true })
      .click();
    await expect(
      evidence(page).getByRole("button", {
        name: "Open identity tools",
        exact: true,
      }),
    ).toHaveCount(0);
    await evidence(page)
      .getByRole("button", { name: "Open native program tools", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Native backup default compiler",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("navigation", { name: "Current task tools", exact: true })
        .getByRole("button", { name: "Native backup defaults", exact: true }),
    ).toBeVisible();
    expect(fieldCalls).toEqual([]);
  });

for (const unsupportedKind of ["unsupported", "future-profile", null])
  test(`${String(unsupportedKind)} native operation keeps evidence without an invented identity or Program action`, async ({
    page,
  }) => {
    const id = "d".repeat(32);
    await page.route("**/api/changes/query", (route) =>
      route.fulfill({
        json: report([
          row("native", id, {
            native_change_kind: unsupportedKind,
            label: "Native application transfer (unsupported operation)",
          }),
        ]),
      }),
    );
    await page.route("**/api/changes/records/native/*", (route) =>
      route.fulfill({
        json: { intent: { id, change_kind: "future-profile" } },
      }),
    );
    await openLedger(page);
    await records(page)
      .getByRole("button", { name: `Details for native ${id}`, exact: true })
      .click();
    await expect(evidence(page)).toContainText(
      "unsupported by the ledger's tool links",
    );
    await expect(
      evidence(page).getByRole("button", {
        name: /^Open (identity|native program) tools$/,
      }),
    ).toHaveCount(0);
    await expect(
      evidence(page).getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toBeVisible();
  });
async function selectedController(page: Page, endpoint: string) {
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
    .fill("3001:8");
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill(endpoint);
  await page.getByLabel("Known network", { exact: true }).fill("3001");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored 3001 MAC 8");
}

test("offline Changes shows real saved project audit, searchable evidence and exact local download", async ({
  page,
  request,
}) => {
  const headers = await session(request);
  const program = (await (await request.get("/api/templates")).json())[0];
  program.id = `ledger-${Date.now()}-${test.info().project.name}`;
  program.revision = 0;
  const saved = await request.post("/api/projects", {
    headers,
    data: { program, expected_revision: 0 },
  });
  expect(saved.ok()).toBe(true);
  const fieldCalls: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/api/bacnet/"))
      fieldCalls.push(req.url());
  });
  await openLedger(page);
  await ledger(page).getByLabel("Search recorded changes").fill(program.id);
  await ledger(page)
    .getByRole("button", { name: "Refresh ledger", exact: true })
    .click();
  await expect(records(page)).toContainText(program.id);
  await records(page)
    .getByRole("button", { name: /^Details for audit / })
    .first()
    .click();
  await expect(evidence(page)).toContainText("Redacted local evidence view");
  await evidence(page).getByText("Technical evidence", { exact: true }).click();
  await expect(evidence(page).locator("pre")).toContainText(program.id);
  const download = page.waitForEvent("download");
  await evidence(page)
    .getByRole("button", { name: "Download evidence JSON", exact: true })
    .click();
  const file = await download;
  const body = JSON.parse(await readFile((await file.path())!, "utf8"));
  expect(body.read_only).toBe(true);
  expect(body.record.detail.id).toBe(program.id);
  expect(fieldCalls).toEqual([]);
});

test("CAF draft survives ledger navigation and remains a separate offline copy", async ({
  page,
  request,
}) => {
  await session(request);
  const bytes = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    { cwd: root },
  );
  const fieldCalls: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/api/bacnet/"))
      fieldCalls.push(req.url());
  });
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "ledger-draft.caf",
      mimeType: "application/octet-stream",
      buffer: bytes,
    });
  await page
    .locator(".caf-layout tbody tr")
    .filter({ has: page.getByText("Block 10", { exact: true }) })
    .click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("42.5");
  await tasks(page)
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await expect(
    ledger(page).getByRole("region", { name: "Local work", exact: true }),
  ).toContainText("ledger-draft.caf");
  await expect(ledger(page)).toContainText("1 local changes");
  await ledger(page)
    .getByRole("button", { name: "Review CAF changes", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Local CAF change review" }),
  ).toContainText("42.5");
  await tasks(page)
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await ledger(page)
    .getByRole("button", { name: "Open local graph", exact: true })
    .click();
  await expect(page.getByLabel("Working context")).toContainText(
    "ledger-draft.caf",
  );
  await tasks(page)
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await expect(ledger(page)).toContainText("1 local changes");
  expect(fieldCalls).toEqual([]);
});

test("families distinguish original targets, ownership and session receipts; download keeps exact number bytes", async ({
  page,
}) => {
  const rows = [
    row(),
    row("schedule", "b".repeat(32), {
      detail_path: "/bacnet/schedules/writes/receipts/" + "b".repeat(32),
    }),
    row("command", "owned-one", {
      kind: "ownership",
      state: "active",
      target: {
        address: "3002:8",
        device: "device,5136",
        router: "127.0.0.1:49002",
        dnet: 3002,
      },
    }),
    row("event", "session-one", { session_scoped: true }),
  ];
  await page.route("**/api/changes/query", (route) =>
    route.fulfill({ json: report(rows) }),
  );
  const raw =
    '{"id":"' +
    "b".repeat(32) +
    '","negative_zero":-0.0,"counter":9007199254740993}';
  await page.route("**/api/bacnet/schedules/writes/receipts/*", (route) =>
    route.fulfill({ contentType: "application/json", body: raw }),
  );
  await page.route("**/api/changes/records/native/*", (route) =>
    route.fulfill({ json: { status: "unknown" } }),
  );
  await openLedger(page);
  await expect(records(page)).toContainText("3002:8");
  await expect(records(page)).toContainText("ownership");
  await expect(records(page)).toContainText("Session-scoped receipt");
  await records(page)
    .getByRole("button", {
      name: `Details for native ${rows[0].id}`,
      exact: true,
    })
    .click();
  await expect(
    evidence(page).getByRole("button", {
      name: "Open identity tools",
      exact: true,
    }),
  ).toBeDisabled();
  await records(page)
    .getByRole("button", {
      name: `Details for schedule ${rows[1].id}`,
      exact: true,
    })
    .click();
  await expect(evidence(page)).toContainText(
    "Original source endpoint response",
  );
  const download = page.waitForEvent("download");
  await evidence(page)
    .getByRole("button", { name: "Download evidence JSON", exact: true })
    .click();
  const file = await download;
  expect(await readFile((await file.path())!, "utf8")).toBe(raw);
});

test("pagination keeps source cursors, displays partial errors and resets windows on filter change", async ({
  page,
}) => {
  const requests: any[] = [];
  const cursor = {
    before: { audit: "15" },
    exhausted: [
      "native",
      "instance",
      "schedule",
      "bbmd",
      "event",
      "temco",
      "command",
    ],
  };
  await page.route("**/api/changes/query", (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    return route.fulfill({
      json: report(
        body.before ? [row("audit", "3", { label: "Older match" })] : [],
        {
          next_cursor: body.before ? null : cursor,
          errors: [{ source: "bbmd", error: "Authored unavailable journal" }],
        },
      ),
    });
  });
  await openLedger(page);
  await expect(ledger(page)).toContainText(
    "Some local evidence is unavailable",
  );
  await expect(records(page)).toContainText(
    "No matching records in this window",
  );
  await ledger(page)
    .getByRole("button", { name: "Older window", exact: true })
    .click();
  await expect(records(page)).toContainText("Older match");
  expect(requests.at(-1).exhausted).toEqual(cursor.exhausted);
  await expect(
    ledger(page).getByRole("button", { name: "Older window", exact: true }),
  ).toBeDisabled();
  await ledger(page)
    .getByRole("button", { name: "Previous window", exact: true })
    .click();
  await expect(records(page)).toContainText(
    "No matching records in this window",
  );
  await ledger(page)
    .getByRole("button", { name: "Older window", exact: true })
    .click();
  await expect(records(page)).toContainText("Older match");
  await ledger(page)
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  await expect(records(page)).toContainText(
    "No matching records in this window",
  );
  expect(requests.at(-1).before).toBeUndefined();
  expect(requests.at(-1).source).toBe("native");
});

test("late query after source ABA cannot replace the newer window", async ({
  page,
}) => {
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const ready = new Promise<void>((resolve) => (arrived = resolve));
  let first = true;
  await page.route("**/api/changes/query", async (route) => {
    if (first) {
      first = false;
      arrived();
      await held;
      return route.fulfill({
        json: report([row("audit", "old", { label: "Retired old response" })]),
      });
    }
    return route.fulfill({
      json: report([row("audit", "new", { label: "Current response" })]),
    });
  });
  try {
    await openLedger(page);
    await ready;
    await ledger(page)
      .getByLabel("Record family", { exact: true })
      .selectOption("native");
    await expect(records(page)).toContainText("Current response");
    await ledger(page)
      .getByLabel("Record family", { exact: true })
      .selectOption("all");
    await expect(records(page)).toContainText("Current response");
    release();
    await page.waitForLoadState("networkidle");
    await expect(records(page)).not.toContainText("Retired old response");
  } finally {
    release?.();
  }
});

test("late evidence cannot replace another selection or return after close", async ({
  page,
}) => {
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const ready = new Promise<void>((resolve) => (arrived = resolve));
  await page.route("**/api/changes/query", (route) =>
    route.fulfill({ json: report([row("audit", "one"), row("audit", "two")]) }),
  );
  await page.route("**/api/changes/records/audit/*", async (route) => {
    if (route.request().url().endsWith("/one")) {
      arrived();
      await held;
      return route.fulfill({ json: { detail: "Retired evidence" } });
    }
    return route.fulfill({ json: { detail: "Selected evidence" } });
  });
  try {
    await openLedger(page);
    await records(page)
      .getByRole("button", { name: "Details for audit one", exact: true })
      .click();
    await ready;
    await records(page)
      .getByRole("button", { name: "Details for audit two", exact: true })
      .click();
    await evidence(page)
      .getByText("Technical evidence", { exact: true })
      .click();
    await expect(evidence(page).locator("pre")).toContainText(
      "Selected evidence",
    );
    release();
    await page.waitForLoadState("networkidle");
    await expect(evidence(page)).not.toContainText("Retired evidence");
    await evidence(page)
      .getByRole("button", { name: "Close evidence", exact: true })
      .click();
    await expect(evidence(page)).toHaveCount(0);
  } finally {
    release?.();
  }
});

test("native Program link preserves the selected routed controller when its receipt belongs elsewhere", async ({
  page,
  request,
}) => {
  await session(request);
  const router = await peer(3001),
    id = "e".repeat(32);
  await page.route("**/api/changes/query", (route) =>
    route.fulfill({
      json: report([
        row("native", id, {
          native_change_kind: "wire-source",
          label: "Native wire source transfer",
          object: "controller/575_1",
          target: {
            address: "3002:8",
            device: "device,5136",
            router: "127.0.0.1:49099",
            dnet: 3002,
          },
        }),
      ]),
    }),
  );
  await page.route("**/api/changes/records/native/*", (route) =>
    route.fulfill({ json: { intent: { id, change_kind: "wire-source" } } }),
  );
  try {
    await selectedController(page, router.endpoint);
    const fieldCalls: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().includes("/api/bacnet/"))
        fieldCalls.push(req.url());
    });
    await tasks(page)
      .getByRole("button", { name: "Changes", exact: true })
      .click();
    await expect(records(page)).toContainText("3002:8");
    await records(page)
      .getByRole("button", { name: `Details for native ${id}`, exact: true })
      .click();
    await evidence(page)
      .getByRole("button", { name: "Open native program tools", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Native backup default compiler",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByLabel("Working context")).toContainText("3001:8");
    await expect(page.getByLabel("Working context")).toContainText(
      router.endpoint,
    );
    await expect(page.getByLabel("Working context")).not.toContainText(
      "3002:8",
    );
    expect(fieldCalls).toEqual([]);
    expect(router.writes).toEqual([]);
  } finally {
    await session(request);
    router.close();
  }
});

test("selected routed controller propagates once; source tools navigate without a write or implicit readback", async ({
  page,
  request,
}) => {
  await session(request);
  const router = await peer(3001);
  const queries: any[] = [];
  await page.route("**/api/changes/query", (route) => {
    queries.push(route.request().postDataJSON());
    return route.fulfill({
      json: report([
        row("instance", "a".repeat(32), {
          target: {
            address: "3001:8",
            device: "device,5136",
            router: router.endpoint,
            dnet: 3001,
          },
        }),
      ]),
    });
  });
  await page.route("**/api/changes/records/instance/*", (route) =>
    route.fulfill({ json: { attempt: { status: "unknown" } } }),
  );
  try {
    await selectedController(page, router.endpoint);
    const fieldCalls: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().includes("/api/bacnet/"))
        fieldCalls.push(req.url());
    });
    await tasks(page)
      .getByRole("button", { name: "Changes", exact: true })
      .click();
    await ledger(page)
      .getByLabel("Target scope", { exact: true })
      .selectOption("station");
    await expect(records(page)).toContainText(router.endpoint);
    expect(queries.at(-1).selected_target).toEqual({
      address: "3001:8",
      device: "device,5136",
      router: router.endpoint,
      dnet: 3001,
      interface_key: expect.any(String),
    });
    expect(
      JSON.parse(queries.at(-1).selected_target.interface_key),
    ).toMatchObject({ router: router.endpoint, dnet: 3001 });
    await records(page)
      .getByRole("button", { name: /^Details for instance / })
      .click();
    await evidence(page)
      .getByRole("button", { name: "Open identity tools", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Device instance commissioning",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByLabel("Working context")).toContainText("3001:8");
    await expect(page.getByLabel("Working context")).toContainText(
      router.endpoint,
    );
    expect(fieldCalls).toEqual([]);
    expect(router.writes).toEqual([]);
  } finally {
    await session(request);
    router.close();
  }
});

test("failed query and retired session receipt remain explicit and never show verified success", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/changes/query", (route) =>
    fail
      ? route.fulfill({
          status: 422,
          json: { detail: "Authored unavailable source" },
        })
      : route.fulfill({
          json: report([row("event", "retired", { session_scoped: true })]),
        }),
  );
  await page.route("**/api/changes/records/event/retired", (route) =>
    route.fulfill({
      status: 422,
      json: { detail: "Receipt no longer available in this session" },
    }),
  );
  await openLedger(page);
  await expect(ledger(page).getByRole("alert")).toContainText(
    "Authored unavailable source",
  );
  fail = false;
  await ledger(page)
    .getByRole("button", { name: "Refresh ledger", exact: true })
    .click();
  await records(page)
    .getByRole("button", { name: "Details for event retired", exact: true })
    .click();
  await expect(evidence(page).getByRole("alert")).toContainText(
    "no longer available",
  );
  await expect(evidence(page)).toContainText("Needs attention");
  await expect(
    evidence(page).getByRole("button", {
      name: "Download evidence JSON",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("changing the selected station retires old evidence and filters with the new exact target", async ({
  page,
  request,
}) => {
  await session(request);
  const router = await peer(3001);
  const queries: any[] = [];
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const ready = new Promise<void>((resolve) => (arrived = resolve));
  await page.route("**/api/changes/query", (route) => {
    const body = route.request().postDataJSON();
    queries.push(body);
    return route.fulfill({
      json: report(
        body.selected_target?.address === "3001:7"
          ? []
          : [row("audit", "original-eight")],
      ),
    });
  });
  await page.route(
    "**/api/changes/records/audit/original-eight",
    async (route) => {
      arrived();
      await held;
      await route.fulfill({
        json: { detail: "Evidence for original station 8" },
      });
    },
  );
  try {
    await selectedController(page, router.endpoint);
    await tasks(page)
      .getByRole("button", { name: "Changes", exact: true })
      .click();
    await ledger(page)
      .getByLabel("Target scope", { exact: true })
      .selectOption("station");
    await records(page)
      .getByRole("button", {
        name: "Details for audit original-eight",
        exact: true,
      })
      .click();
    await ready;
    await page
      .getByLabel("Working context")
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill("3001:7");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored 3001 MAC 7");
    await tasks(page)
      .getByRole("button", { name: "Changes", exact: true })
      .click();
    await ledger(page)
      .getByLabel("Target scope", { exact: true })
      .selectOption("station");
    await expect(records(page)).toContainText(
      "No matching records in this window",
    );
    expect(queries.at(-1).selected_target).toEqual({
      address: "3001:7",
      device: "device,5136",
      router: router.endpoint,
      dnet: 3001,
      interface_key: expect.any(String),
    });
    expect(
      JSON.parse(queries.at(-1).selected_target.interface_key),
    ).toMatchObject({ router: router.endpoint, dnet: 3001 });
    release();
    await page.waitForLoadState("networkidle");
    await expect(evidence(page)).toHaveCount(0);
    await expect(ledger(page)).not.toContainText(
      "Evidence for original station 8",
    );
    expect(router.writes).toEqual([]);
  } finally {
    release?.();
    await session(request);
    router.close();
  }
});

test("narrow ledger preserves keyboard access and scrolls its engineering table inside the panel", async ({
  page,
}) => {
  await page.setViewportSize({ width: 600, height: 900 });
  await page.route("**/api/changes/query", (route) =>
    route.fulfill({ json: report([row()]) }),
  );
  await openLedger(page);
  await expect(records(page)).toContainText("Authored native operation");
  const input = ledger(page).getByLabel("Search recorded changes", {
    exact: true,
  });
  await input.focus();
  await expect(input).toBeFocused();
  await input.press("Tab");
  await expect(
    ledger(page).getByLabel("Record family", { exact: true }),
  ).toBeFocused();
  expect(
    await records(page).evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    ),
  ).toBe(true);
  expect(
    await ledger(page).evaluate(
      (element) => element.getBoundingClientRect().width <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("change-ledger-narrow.png"),
    fullPage: true,
  });
});

test("desktop ledger keeps the current workspace navigation and readable evidence columns", async ({
  page,
}) => {
  await page.route("**/api/changes/query", (route) =>
    route.fulfill({ json: report([row()]) }),
  );
  await openLedger(page);
  await expect(records(page)).toContainText("Authored native operation");
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await expect(
    tasks(page).getByRole("button", { name: "Changes", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("change-ledger-desktop.png"),
    fullPage: true,
  });
});
