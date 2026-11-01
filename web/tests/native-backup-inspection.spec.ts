import { test, expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve("..");
function seed() {
  const state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state)
    throw new Error("The runner must provide isolated compiler state.");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained,signal_files
s=ApplicationStore(Store(sys.argv[1]))
a=retained(s);b=retained(s,target={'address':'127.0.0.1:47829','router':None,'dnet':None})
files=signal_files();files[11]=b'Unrecognized saved directory';files[12]=b'Opaque settings'
bad=retained(s,files,source_identity_matches=False,source_identity_error='Authored acquisition identity mismatch')
print(json.dumps({'a':a['id'],'b':b['id'],'bad':bad['id']}))
`,
        state,
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
}
async function enter(page: Page, id: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  const inspection = compiler.getByRole("region", {
    name: "Retained native backup inspection",
    exact: true,
  });
  return { compiler, inspection };
}
async function inspect(panel: Locator) {
  await panel
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("Native archive inspection source", { exact: true }),
  ).toBeVisible();
  const explorer = panel.getByLabel("Captured native record explorer", {
    exact: true,
  });
  await explorer.locator(":scope > summary").click();
  await expect(
    explorer
      .getByRole("table", { name: "Captured native records", exact: true })
      .getByRole("row"),
  ).toHaveCount(10);
  return explorer;
}
async function selectRecord(explorer: Locator, ref: string) {
  await explorer
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({ hasText: ref })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  return explorer.getByRole("region", {
    name: "Captured native record properties",
    exact: true,
  });
}
test.beforeEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
});

test("offline native backup records expose original archive values and preserve compiler drafts", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 820, height: 1100 });
  const ids = seed(),
    { compiler, inspection } = await enter(page, ids.a);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  await compiler
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("1e-");
  const explorer = await inspect(inspection);
  const props = await selectRecord(explorer, "controller/signal-10");
  await props
    .getByLabel("Search captured properties", { exact: true })
    .fill("3113");
  await props
    .getByRole("button", { name: "Search properties", exact: true })
    .click();
  await expect(
    props.getByRole("cell", { name: "23.5", exact: true }),
  ).toBeVisible();
  await expect(inspection).toContainText(
    "not merged saved settings or current live values",
  );
  await expect(
    compiler.getByLabel("Proposed native Real default", { exact: true }),
  ).toHaveValue("1e-");
  await props
    .getByRole("table", { name: "Captured record properties", exact: true })
    .screenshot({
      path: info.outputPath("native-backup-original-property.png"),
    });
  await inspection
    .getByLabel("Native archive inspection source", { exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-backup-source-context.png"),
  });
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Library", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  await expect(inspection.getByRole("table")).toHaveCount(0);
  await expect(
    compiler.getByLabel("Proposed native Real default", { exact: true }),
  ).toHaveValue("1e-");
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("unverified archive with unknown saved settings stays readable without qualifying compilation", async ({
  page,
  request,
}) => {
  const ids = seed(),
    { compiler, inspection } = await enter(page, ids.bad);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await expect(compiler.getByRole("alert").first()).toContainText(
    "identity-verified",
  );
  const explorer = await inspect(inspection);
  await expect(inspection).toContainText(
    "Authored acquisition identity mismatch",
  );
  const properties = await selectRecord(explorer, "controller/signal-11");
  await expect(
    properties.getByRole("table", {
      name: "Captured record properties",
      exact: true,
    }),
  ).toContainText("Default Value");
  await expect(
    compiler.getByLabel("Native Real default", { exact: true }),
  ).toHaveCount(0);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

for (const { endpoint, altered } of [
  { endpoint: "source", altered: "manifest" },
  { endpoint: "records", altered: "manifest" },
  { endpoint: "source", altered: "target" },
  { endpoint: "records", altered: "target" },
]) {
  test(`altered native archive ${endpoint} ${altered} response cannot display another source`, async ({
    page,
  }) => {
    const ids = seed(),
      { inspection } = await enter(page, ids.a);
    await page.route(
      `**/native-application/inspection/${endpoint}`,
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        const data = JSON.parse((await response.body()).toString());
        if (altered === "manifest") data.snapshot_sha256 = "0".repeat(64);
        else data.target.address = "127.0.0.1:47999";
        await route.fulfill({ response, json: data });
      },
    );
    await inspection
      .getByRole("button", {
        name: "Inspect retained native backup",
        exact: true,
      })
      .click();
    if (endpoint === "records")
      await inspection
        .getByLabel("Captured native record explorer", { exact: true })
        .locator(":scope > summary")
        .click();
    await expect(inspection.getByRole("alert")).toContainText(
      endpoint === "source"
        ? "does not match"
        : "differs from the selected source",
    );
    await expect(inspection.getByRole("table")).toHaveCount(0);
  });
}

test("late native backup properties cannot return after source A B A selection", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, inspection } = await enter(page, ids.a);
  const explorer = await inspect(inspection);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/native-application/inspection/record", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await explorer
      .getByRole("table", { name: "Captured native records", exact: true })
      .getByRole("row")
      .filter({ hasText: "controller/signal-10" })
      .getByRole("button", { name: "Inspect record", exact: true })
      .click();
    await received;
    const choices = compiler.getByLabel("Retained native backup", {
      exact: true,
    });
    await choices.selectOption(ids.b);
    await choices.selectOption(ids.a);
    release();
    await expect(
      inspection.getByLabel("Native archive inspection source", {
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      inspection.getByRole("region", {
        name: "Captured native record properties",
        exact: true,
      }),
    ).toHaveCount(0);
    await inspect(inspection);
    await expect(
      inspection.getByRole("region", {
        name: "Captured native record properties",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    release();
  }
});
