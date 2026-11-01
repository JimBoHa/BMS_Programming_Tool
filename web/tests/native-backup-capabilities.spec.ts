import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

function seed() {
  const root = path.resolve(".."),
    state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state) throw new Error("An isolated compiler state is required.");
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
a=retained(s)
b=retained(s,target={'address':'10','router':'127.0.0.1:47919','dnet':200})
files=signal_files();files[11]=b'Unknown saved directory';files[12]=b'Opaque saved values'
unknown=retained(s,files)
unverified=retained(s,source_identity_matches=False,source_identity_error='Authored mismatch')
print(json.dumps({key:value['id'] for key,value in locals().copy().items() if key in ('a','b','unknown','unverified')}))
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
  await inspection
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  const support = inspection.getByLabel("Native backup operation support", {
    exact: true,
  });
  await expect(support).toBeVisible();
  return { compiler, inspection, support };
}
test.beforeEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
});

test("offline backup analysis qualifies exact saved values while keeping local drafts and write review separate", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 820, height: 1100 });
  const ids = seed(),
    { compiler, support } = await enter(page, ids.a);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  await compiler
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("1e-");
  await support.locator(":scope > summary").click();
  const table = support.getByRole("table", {
    name: "Native backup operations",
    exact: true,
  });
  await expect(table.getByRole("row")).toHaveCount(17);
  await expect(
    table.locator('[data-operation="effective-default-compile"] td').first(),
  ).toHaveText("source qualified");
  await expect(
    table.locator('[data-operation="default-transfer"] td').first(),
  ).toHaveText("preflight required");
  await expect(
    table.locator('[data-operation="general-logic"] td').first(),
  ).toHaveText("unavailable");
  await expect(
    table.locator('[data-operation="physical-acceptance"] td').first(),
  ).toHaveText("not inferred");
  await expect(
    compiler.getByLabel("Proposed native Real default", { exact: true }),
  ).toHaveValue("1e-");
  await expect(
    support.getByRole("button", { name: "Apply to controller", exact: true }),
  ).toHaveCount(0);
  await support.locator(":scope > summary").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-backup-capabilities-820.png"),
  });
  await support
    .getByText("Operation qualification evidence", { exact: true })
    .click();
  await expect(support.locator("pre")).toContainText(
    '"effective_real_default_count": 2',
  );
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

for (const variant of ["unknown", "unverified", "b"]) {
  test(`actual ${variant} backup gets independent operation statuses`, async ({
    page,
  }) => {
    const ids = seed(),
      { support } = await enter(page, ids[variant]);
    await support.locator(":scope > summary").click();
    const row = (id: string) =>
      support.locator(`[data-operation="${id}"] td`).first();
    await expect(row("archive-read")).toHaveText("source qualified");
    await expect(row("saved-settings")).toHaveText(
      variant === "unknown" ? "unsupported source" : "source qualified",
    );
    await expect(row("effective-default-compile")).toHaveText(
      variant === "b" ? "source qualified" : "unsupported source",
    );
    await expect(row("default-transfer")).toHaveText(
      variant === "b"
        ? "preflight required"
        : variant === "unverified"
          ? "source mismatch"
          : "unsupported source",
    );
    if (variant === "b")
      await expect(
        page.getByLabel("Native archive inspection source", { exact: true }),
      ).toContainText("DNET 200");
  });
}

for (const altered of ["manifest", "archive", "station", "apply"]) {
  test(`altered ${altered} capability response is refused without hiding the readable archive`, async ({
    page,
  }) => {
    const ids = seed(),
      { inspection, support } = await enter(page, ids.a);
    await page.route(
      "**/native-application/inspection/capabilities",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = JSON.parse((await response.body()).toString());
        if (altered === "manifest") data.snapshot_sha256 = "0".repeat(64);
        if (altered === "archive") data.sha256 = "0".repeat(64);
        if (altered === "station") data.target.address = "127.0.0.1:47999";
        if (altered === "apply") data.can_apply = true;
        await route.fulfill({ response, json: data });
      },
    );
    await support.locator(":scope > summary").click();
    await expect(support.getByRole("alert")).toContainText(
      "differs from the selected source",
    );
    await expect(support.getByRole("table")).toHaveCount(0);
    await expect(
      inspection.getByLabel("Native archive inspection source", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      inspection.getByLabel("Captured native record explorer", { exact: true }),
    ).toBeVisible();
  });
}

test("held capability reply cannot reappear after source A B A selection", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, inspection, support } = await enter(page, ids.a);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route(
    "**/native-application/inspection/capabilities",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
  );
  try {
    await support.locator(":scope > summary").click();
    await received;
    const selected = compiler.getByLabel("Retained native backup", {
      exact: true,
    });
    await selected.selectOption(ids.b);
    await selected.selectOption(ids.a);
    release();
    await expect(
      inspection.getByLabel("Native backup operation support", { exact: true }),
    ).toHaveCount(0);
    await inspection
      .getByRole("button", {
        name: "Inspect retained native backup",
        exact: true,
      })
      .click();
    await expect(
      inspection.getByLabel("Native backup operation support", { exact: true }),
    ).toBeVisible();
    await expect(
      inspection.getByRole("table", {
        name: "Native backup operations",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    release();
  }
});
