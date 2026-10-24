import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { freePort, peer } from "./workflow-peer";

const root = path.resolve("..");
function caf() {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    { cwd: root },
  );
}
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  return headers;
}
async function connect(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Find local routers", exact: true }),
  ).toBeEnabled();
}
async function fillKnown(page: Page, endpoint: string, mac = 8) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(`3001:${mac}`);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill(endpoint);
  await page.getByLabel("Known network", { exact: true }).fill("3001");
}
async function known(page: Page, endpoint: string, mac = 8) {
  await fillKnown(page, endpoint, mac);
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText(`Authored 3001 MAC ${mac}`);
}
const tasks = (page: Page) =>
  page.getByRole("navigation", { name: "Workspace tasks" });
const nav = (page: Page) =>
  page.getByRole("navigation", { name: "Main navigation" });
const instance = (page: Page) =>
  page.getByRole("region", {
    name: "Device instance commissioning",
    exact: true,
  });

test("a router without network advertisements supplies cached choices that require a live scan", async ({
  page,
  request,
}) => {
  test.setTimeout(30000);
  await reset(request);
  const router = await peer(2105, true);
  const calls: { url: string; body: any }[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && /\/api\/bacnet\//.test(req.url()))
      calls.push({ url: req.url(), body: req.postDataJSON() });
  });
  try {
    await connect(page);
    const guide = page.getByRole("region", {
      name: "Routed BACnet discovery",
      exact: true,
    });
    await guide
      .getByLabel("Discovery router address", { exact: true })
      .fill(router.endpoint);
    await guide
      .getByRole("button", { name: "Read router networks", exact: true })
      .click();
    await expect(
      guide.getByLabel("Cached network discovery", { exact: true }),
    ).toContainText("Router Device 505: 3 cached network choice(s)");
    await expect(
      guide.getByLabel("Commissioning trunk", { exact: true }),
    ).toBeEnabled();
    await expect(
      guide.getByLabel("Commissioning trunk").locator('option[value="2105"]'),
    ).toContainText("cached; scan required");
    expect(
      calls.filter((call) => call.url.endsWith("/router-bindings"))[0].body,
    ).toEqual({ router: router.endpoint, max_bindings: 2048 });
    expect(calls.filter((call) => call.url.endsWith("/scan-trunk"))).toEqual(
      [],
    );
    await expect(guide.getByLabel("Commissioning controller")).toHaveCount(0);
    await guide
      .getByLabel("Commissioning trunk", { exact: true })
      .selectOption("2105");
    await guide
      .getByLabel("Routed response window seconds", { exact: true })
      .fill("1");
    await guide
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    await expect(
      guide.getByLabel("Commissioning controller").locator("option"),
    ).toHaveCount(2);
    await guide
      .getByLabel("Commissioning controller")
      .selectOption(JSON.stringify(["2105:7", "device,132007"]));
    await guide
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Independent controller7");
    await expect(page.getByLabel("Working context")).toContainText("2105:7");
  } finally {
    router.close();
  }
});

test("a late cached-network read cannot refill the selector after leaving discovery", async ({
  page,
  request,
}) => {
  await reset(request);
  const router = await peer(2105, true);
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  let arrive!: () => void;
  const ready = new Promise<void>((resolve) => (arrive = resolve));
  try {
    await connect(page);
    await page.route("**/api/bacnet/router-bindings", async (route) => {
      const response = await route.fetch();
      arrive();
      await held;
      await route.fulfill({ response });
    });
    const guide = page.getByRole("region", {
      name: "Routed BACnet discovery",
      exact: true,
    });
    await guide
      .getByLabel("Discovery router address", { exact: true })
      .fill(router.endpoint);
    await guide
      .getByRole("button", { name: "Read router networks", exact: true })
      .click();
    await ready;
    await nav(page)
      .getByRole("button", { name: "Library", exact: true })
      .click();
    release();
    await page.waitForLoadState("networkidle");
    await page
      .getByLabel("Working context")
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    await expect(guide.getByLabel("Cached network discovery")).toHaveCount(0);
    await expect(guide.getByLabel("Commissioning trunk")).toBeDisabled();
  } finally {
    release();
    router.close();
  }
});

test("a failed controller identity read keeps the previous verified target", async ({
  page,
  request,
}) => {
  await reset(request);
  const router = await peer();
  try {
    await connect(page);
    await known(page, router.endpoint, 8);
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page.route("**/api/bacnet/device-details", (route) =>
      route.fulfill({ json: { identity_verified: false, properties: {} } }),
    );
    await fillKnown(page, router.endpoint, 7);
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page
        .locator(".inline-error")
        .filter({ hasText: "Controller identity could not be verified" }),
    ).toBeVisible();
    await expect(page.getByLabel("Working context")).toContainText(
      "Authored 3001 MAC 8",
    );
    expect(router.writes).toEqual([]);
  } finally {
    router.close();
  }
});

test("controller verification locks navigation until the exact source result arrives", async ({
  page,
  request,
}) => {
  await reset(request);
  const router = await peer();
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  let arrived!: () => void;
  const ready = new Promise<void>((resolve) => (arrived = resolve));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  try {
    await connect(page);
    await page.route("**/api/bacnet/device-details", async (route) => {
      const response = await route.fetch();
      arrived();
      await held;
      await route.fulfill({ response });
    });
    await fillKnown(page, router.endpoint);
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await ready;
    await expect(
      nav(page).getByRole("button", { name: "Library", exact: true }),
    ).toBeDisabled();
    await expect(
      tasks(page).getByRole("button", { name: "Points & I/O", exact: true }),
    ).toBeDisabled();
    await expect(page.getByLabel("Working context")).toContainText(
      "No controller open",
    );
    release();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored 3001 MAC 8");
    await expect(
      nav(page).getByRole("button", { name: "Library", exact: true }),
    ).toBeEnabled();
    expect(errors).toEqual([]);
    expect(router.errors).toEqual([]);
  } finally {
    release();
    router.close();
  }
});

test("compact navigation remains labelled and the graph simulation is an explicit mode", async ({
  page,
  request,
}) => {
  await reset(request);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  await expect(
    nav(page).getByRole("button", { name: "Workspace", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await expect(page.getByLabel("Working context")).toContainText("Local graph");
  await expect(page.locator(".simulation-panel")).toHaveCount(0);
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Simulate", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "CAF simulation inputs", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Temco", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Temco program transfer" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Simulate", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.screenshot({
    path: test.info().outputPath("compact-graph.png"),
    fullPage: true,
  });
});

test("two entry paths and local navigation do not connect to a field network", async ({
  page,
  request,
}) => {
  await reset(request);
  const fieldCalls: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/bacnet\//.test(request.url()) && request.method() === "POST")
      fieldCalls.push(request.url());
  });
  await page.goto("/");
  await expect(nav(page).getByRole("button")).toHaveCount(6);
  await expect(
    page.getByRole("button", { name: /^Connect to a controller/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^Open a CAF file/ }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("start.png"),
    fullPage: true,
  });
  await nav(page).getByRole("button", { name: "Library", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Hardware definitions", exact: true }),
  ).toBeVisible();
  await nav(page).getByRole("button", { name: "Help", exact: true }).click();
  await nav(page).getByRole("button", { name: "Start", exact: true }).click();
  expect(fieldCalls).toEqual([]);
});

test("CAF edits survive task changes, save offline, and retain explicit file provenance", async ({
  page,
  request,
}) => {
  await reset(request);
  const fieldCalls: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/bacnet\//.test(request.url()) && request.method() === "POST")
      fieldCalls.push(request.url());
  });
  await page.goto("/");
  await page.locator("input[type=file][accept='.caf']").first().setInputFiles({
    name: "workflow-example.caf",
    mimeType: "application/octet-stream",
    buffer: caf(),
  });
  await expect(page.getByLabel("Working context")).toContainText(
    "workflow-example.caf",
  );
  const row = page
    .locator(".caf-layout tbody tr")
    .filter({ has: page.getByText("Block 10", { exact: true }) });
  await row.click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("42.5");
  await expect(page.getByLabel("Working context")).toContainText(
    "Local changes",
  );
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Logic", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Native CAF graph", exact: true }),
  ).toBeVisible();
  await nav(page).getByRole("button", { name: "Library", exact: true }).click();
  await nav(page)
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("42.5");
  await tasks(page)
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await page.getByRole("button", { name: "CAF changes", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Local CAF change review" }),
  ).toContainText("42.5");
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .last()
    .click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.caf$/);
  const saved = test.info().outputPath("saved.caf");
  await file.saveAs(saved);
  const values = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from bms_tool.caf import CafArchive; from pathlib import Path; import sys; print([row['stored_value'] for row in CafArchive(Path(sys.argv[1]).read_bytes()).inventory()])",
      saved,
    ],
    { cwd: root, encoding: "utf8" },
  );
  expect(values).toContain("42.5");
  expect(fieldCalls).toEqual([]);
  await page.screenshot({
    path: test.info().outputPath("caf-changes.png"),
    fullPage: true,
  });
});

test("router → native trunks → scan → verified workspace → instance review and readback", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const router = await peer();
  try {
    // Darwin loopback does not receive subnet broadcasts. Only this router-list
    // advertisement is authored; trunk queries, scans, metadata and writes use UDP.
    await page.route("**/api/bacnet/discover-routers", (route) =>
      route.fulfill({
        json: {
          profile: "bacnet-local-router-discovery/1",
          complete: true,
          truncated: false,
          scope: "Authored loopback router list",
          warnings: [],
          routers: [{ router: router.endpoint, networks: [3001, 3002] }],
        },
      }),
    );
    await connect(page);
    const guide = page.getByRole("region", {
      name: "Routed BACnet discovery",
      exact: true,
    });
    await guide
      .getByRole("button", { name: "Find local routers", exact: true })
      .click();
    await guide
      .getByLabel("Commissioning router", { exact: true })
      .selectOption(router.endpoint);
    await expect(
      guide.getByLabel("Commissioning trunk").locator('option[value="3001"]'),
    ).toHaveCount(1);
    await guide
      .getByLabel("Commissioning trunk", { exact: true })
      .selectOption("3001");
    await guide
      .getByLabel("Routed response window seconds", { exact: true })
      .fill("1");
    await guide
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    await expect(
      guide.getByLabel("Commissioning controller").locator("option"),
    ).toHaveCount(3);
    await guide
      .getByLabel("Commissioning controller")
      .selectOption(JSON.stringify(["3001:8", "device,5136"]));
    await guide
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored 3001 MAC 8");
    await expect(page.getByLabel("Working context")).toContainText(
      "device,5136",
    );
    await expect(page.getByLabel("Working context")).toContainText(
      "Device verified",
    );
    await page.screenshot({
      path: test.info().outputPath("controller-overview.png"),
      fullPage: true,
    });
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    await expect(
      page.getByLabel("Point status address", { exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".workflow-target-row")).toContainText("3001:8");
    await tasks(page)
      .getByRole("button", { name: "Schedules", exact: true })
      .click();
    await expect(page.locator(".workflow-target-row")).toContainText(
      "Authored 3001 MAC 8",
    );
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Open an application to work on its program",
      }),
    ).toBeVisible();
    await tasks(page)
      .getByRole("button", { name: "Trends & Alarms", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Field recording", exact: true })
      .click();
    await expect(
      page.getByLabel("Field address 1", { exact: true }),
    ).toHaveValue("3001:8");
    await expect(
      page.getByLabel("Field address 1", { exact: true }),
    ).toHaveAttribute("readonly", "");
    await page
      .getByRole("button", { name: "Controller history", exact: true })
      .click();
    await expect(
      page.getByLabel("History device address", { exact: true }),
    ).toHaveValue("3001:8");
    await expect(
      page.getByLabel("Multiple history Device object", { exact: true }),
    ).toHaveValue("device,5136");
    await expect(
      page.getByLabel("Multiple history router", { exact: true }),
    ).toHaveValue(router.endpoint);
    await tasks(page)
      .getByRole("button", { name: "Overview", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await expect(
      instance(page).getByLabel("Current Device object (device,instance)", {
        exact: true,
      }),
    ).toHaveCount(0);
    await instance(page)
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await instance(page)
      .getByRole("button", { name: "Review instance change", exact: true })
      .click();
    await expect(
      instance(page).getByLabel("Reviewed instance change"),
    ).toContainText("5136 → 15136");
    expect(router.writes).toEqual([]);
    await instance(page)
      .getByRole("checkbox", {
        name: "I reserved this new number",
        exact: false,
      })
      .check();
    await instance(page)
      .getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      })
      .click();
    await expect(
      instance(page).getByLabel("Instance change receipt"),
    ).toContainText("verified_new");
    await expect(page.getByLabel("Working context")).toContainText(
      "device,15136",
    );
    expect(router.writes).toEqual(["3001:8"]);
    expect(router.errors).toEqual([]);
  } finally {
    router.close();
  }
});

test("connecting with a CAF open retains its draft and keeps the controller match unverified", async ({
  page,
  request,
}) => {
  await reset(request);
  const router = await peer();
  try {
    await page.goto("/");
    await page
      .locator("input[type=file][accept='.caf']")
      .first()
      .setInputFiles({
        name: "local-draft.caf",
        mimeType: "application/octet-stream",
        buffer: caf(),
      });
    await page
      .locator(".caf-layout tbody tr")
      .filter({ has: page.getByText("Block 10", { exact: true }) })
      .click();
    await page.getByLabel("CAF property 3113", { exact: true }).fill("77");
    await page
      .getByLabel("Working context")
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await known(page, router.endpoint);
    await expect(page.getByLabel("Working context")).toContainText(
      "local-draft.caf",
    );
    await expect(page.getByLabel("Working context")).toContainText(
      "controller match unverified",
    );
    await tasks(page)
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await expect(
      page.getByLabel("CAF property 3113", { exact: true }),
    ).toHaveValue("77");
    expect(router.writes).toEqual([]);
  } finally {
    router.close();
  }
});

test("changing controller discards its old write review and a closed interface is explicit", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const router = await peer();
  try {
    await connect(page);
    await known(page, router.endpoint, 8);
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await instance(page)
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await instance(page)
      .getByRole("button", { name: "Review instance change", exact: true })
      .click();
    await expect(
      instance(page).getByLabel("Reviewed instance change"),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await known(page, router.endpoint, 7);
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await expect(
      instance(page).getByLabel("Reviewed instance change"),
    ).toHaveCount(0);
    await expect(
      instance(page).getByLabel("New controller instance (0–4194302)", {
        exact: true,
      }),
    ).toHaveValue("");
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(page.getByLabel("Working context")).toContainText(
      "Interface closed",
    );
    await expect(
      instance(page).getByRole("button", {
        name: "Review instance change",
        exact: true,
      }),
    ).toBeDisabled();
    expect(router.writes).toEqual([]);
  } finally {
    router.close();
  }
});
