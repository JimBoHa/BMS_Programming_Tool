import {
  test,
  expect,
  simulationServerResponseJSON,
  type Page,
} from "./simulationFixture";
import {
  sourceFixtureData,
  projectedSourceFixture,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python"),
  title = "Authored zone schedule browser";
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Zone-group schedule wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Zone-group schedule wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Schedule project name", { exact: true }),
  ).toBeVisible();
  await dialog.getByLabel("Schedule project name", { exact: true }).fill(title);
  return dialog;
}
async function declare(
  dialog: ReturnType<Page["getByRole"]>,
  i = 1,
  timezone = "UTC",
  start = "08:00",
  end = "18:00",
  lead = "180",
) {
  await dialog
    .getByLabel(`Group ${i} time zone`, { exact: true })
    .fill(timezone);
  await dialog
    .getByLabel(`Group ${i} mode`, { exact: true })
    .selectOption("window");
  await dialog.getByLabel(`Group ${i} start`, { exact: true }).fill(start);
  await dialog.getByLabel(`Group ${i} end`, { exact: true }).fill(end);
  await dialog
    .getByLabel(`Group ${i} lead minutes`, { exact: true })
    .fill(lead);
}
async function review(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  const pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/schedule-coordination/preview",
  );
  await dialog
    .getByRole("button", { name: "Preview zone-group schedule", exact: true })
    .click();
  const response = await pending;
  expect(response.ok()).toBe(true);
  const envelope = await response.json(),
    report = projectedSourceFixture(envelope);
  await expect(
    dialog.getByRole("region", {
      name: "Schedule coordination preview",
      exact: true,
    }),
  ).toBeVisible();
  return report;
}
async function monday(dialog: ReturnType<Page["getByRole"]>, i = 1) {
  for (const day of ["Tuesday", "Wednesday", "Thursday", "Friday"])
    await dialog.getByLabel(`Group ${i} ${day}`, { exact: true }).uncheck();
}
async function create(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", {
      name: "Create editable schedule project",
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
}

test("two group graph preserves occupied ends, composes original AHU occupancy, simulates and exchanges authoritative bytes", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog);
  await monday(dialog);
  await dialog
    .getByRole("button", { name: "Add zone group", exact: true })
    .click();
  await declare(dialog, 2, "UTC", "10:00", "20:00", "0");
  await monday(dialog, 2);
  // These valid IDs collided under suffix-derived graph namespaces.
  await dialog.getByLabel("Group 1 ID", { exact: true }).fill("zone");
  await dialog.getByLabel("Group 2 ID", { exact: true }).fill("zone_pre_or");
  await dialog
    .getByLabel("Logical AHU label", { exact: true })
    .fill("Declared AHU A");
  const clocks = [
    "2026-01-05T04:59:00Z",
    "2026-01-05T05:00:00Z",
    "2026-01-05T08:00:00Z",
    "2026-01-05T18:00:00Z",
    "2026-01-05T20:00:00Z",
  ];
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill(clocks.join("\n"));
  const report = await review(page, dialog);
  expect(report.groups.map((g: any) => g.id)).toEqual(["zone", "zone_pre_or"]);
  expect(report.groups.map((g: any) => g.outputs.occupied)).toEqual([
    "zg1_occupied",
    "zg2_occupied",
  ]);
  expect(new Set(report.program.nodes.map((n: any) => n.id)).size).toBe(
    report.program.nodes.length,
  );
  expect(report.evaluation.map((r: any) => r.outputs.ahu_occupied)).toEqual([
    false,
    false,
    true,
    true,
    false,
  ]);
  expect(report.evaluation.map((r: any) => r.outputs.zg1_pre_only)).toEqual([
    false,
    true,
    false,
    false,
    false,
  ]);
  expect(report.groups[0].pre_windows).toEqual([
    { days: [0], end: "18:00", start: "05:00" },
  ]);
  await expect(
    dialog.getByRole("table", { name: "Generated schedule windows" }),
  ).toContainText("05:00–18:00");
  let original: Buffer | undefined,
    header = "";
  await page.route("**/api/schedule-coordination/export", async (route) => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
    original = await response.body();
    header = response.headers()["x-file-sha256"];
    await route.fulfill({ response });
  });
  let pending = page.waitForEvent("download");
  await dialog
    .getByRole("button", {
      name: "Export original schedule review JSON",
      exact: true,
    })
    .click();
  const reviewFile = (await (await pending).path())!;
  expect(readFileSync(reviewFile)).toEqual(original);
  expect(header).toMatch(/^[a-f0-9]{64}$/);
  execFileSync(
    python,
    [
      "-c",
      "import hashlib,json,sys; from bms_tool.models import Program; b=open(sys.argv[1],'rb').read(); assert hashlib.sha256(b).hexdigest()==sys.argv[2]; r=json.loads(b); assert Program.model_validate(r['program']).digest()==r['program_sha256']; assert r['native_compile'] is False and r['controller_writes'] is False",
      reviewFile,
      header,
    ],
    { cwd: root },
  );
  await create(page, dialog);
  await page
    .getByLabel("Next scan UTC clock", { exact: true })
    .fill("2026-01-05T05:00");
  const receipt = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const outputs = simulationServerResponseJSON(await receipt).history.at(
    -1,
  ).outputs;
  expect(outputs.zg1_pre_only).toBe(true);
  expect(outputs.ahu_occupied).toBe(false);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByLabel("Last saved revision", { exact: true }),
  ).toContainText("r1");
  for (const format of ["json", "st", "plcopen", "graphml"]) {
    await page
      .getByLabel("Export format", { exact: true })
      .selectOption(format);
    pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const download = await pending,
      file = (await download.path())!;
    const digest = execFileSync(
      python,
      [
        "-c",
        "import sys; from bms_tool.formats import import_program; p=import_program(open(sys.argv[1],'rb').read(),sys.argv[2]); assert p.revision==1; assert not p.metadata['native_deployment_verified']; assert p.metadata['schedule_coordination']['choices']['ahu_label']=='Declared AHU A'; p.revision=0; print(p.digest())",
        file,
        download.suggestedFilename(),
      ],
      { cwd: root, encoding: "utf8" },
    ).trim();
    expect(digest).toBe(report.program_sha256);
  }
  await page.reload();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("midnight pre-start uses prior start weekday and retains Monday occupied end", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog, 1, "America/Los_Angeles", "00:30", "08:00", "60");
  await monday(dialog);
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill(
      [
        "2026-01-05T07:29:00Z",
        "2026-01-05T07:30:00Z",
        "2026-01-05T08:30:00Z",
        "2026-01-05T16:00:00Z",
      ].join("\n"),
    );
  const report = await review(page, dialog);
  expect(report.groups[0].pre_windows).toContainEqual({
    days: [6],
    start: "23:30",
    end: "00:00",
  });
  expect(report.evaluation.map((r: any) => r.outputs.zg1_occupied)).toEqual([
    false,
    false,
    true,
    false,
  ]);
  expect(
    report.evaluation.map((r: any) => r.outputs.zg1_pre_or_occupied),
  ).toEqual([false, true, true, false]);
  await expect(
    dialog.getByRole("table", { name: "Generated schedule windows" }),
  ).toContainText("Sunday 23:30–00:00");
});

test("empty equal-time windows, explicit all-day and disabled modes remain distinct", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog, 1, "UTC", "08:00", "08:00", "1440");
  await monday(dialog);
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill(
      [
        "2026-01-05T00:00:00Z",
        "2026-01-05T23:59:00Z",
        "2026-01-06T00:00:00Z",
      ].join("\n"),
    );
  let report = await review(page, dialog);
  expect(report.groups[0].occupied_windows).toEqual([]);
  expect(report.groups[0].pre_windows).toEqual([]);
  await dialog
    .getByLabel("Group 1 mode", { exact: true })
    .selectOption("all-day");
  await dialog.getByLabel("Group 1 lead minutes", { exact: true }).fill("0");
  await expect(dialog.getByLabel("Group 1 start", { exact: true })).toHaveCount(
    0,
  );
  report = await review(page, dialog);
  expect(report.evaluation.map((r: any) => r.outputs.ahu_occupied)).toEqual([
    true,
    true,
    false,
  ]);
  expect(report.groups[0].occupied_windows).toEqual([
    { days: [0], start: "00:00", end: "12:00" },
    { days: [0], start: "12:00", end: "00:00" },
  ]);
  await dialog
    .getByLabel("Group 1 mode", { exact: true })
    .selectOption("disabled");
  report = await review(page, dialog);
  expect(
    report.evaluation.every((r: any) =>
      Object.values(r.outputs).every((v) => v === false),
    ),
  ).toBe(true);
});

test("named-zone spring gaps and repeated autumn folds are pointwise wall-clock behavior, not elapsed countdown", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog, 1, "America/Los_Angeles", "02:30", "03:30", "60");
  for (const day of ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    await dialog.getByLabel(`Group 1 ${day}`, { exact: true }).uncheck();
  await dialog.getByLabel("Group 1 Sunday", { exact: true }).check();
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill(
      [
        "2026-03-08T09:29:00Z",
        "2026-03-08T09:30:00Z",
        "2026-03-08T10:00:00Z",
        "2026-03-08T10:30:00Z",
      ].join("\n"),
    );
  let report = await review(page, dialog);
  expect(report.evaluation.map((r: any) => r.outputs.zg1_occupied)).toEqual([
    false,
    false,
    true,
    false,
  ]);
  expect(report.evaluation.map((r: any) => r.outputs.zg1_pre_only)).toEqual([
    false,
    true,
    false,
    false,
  ]);
  await dialog.getByLabel("Group 1 start", { exact: true }).fill("01:30");
  await dialog.getByLabel("Group 1 end", { exact: true }).fill("01:45");
  await dialog.getByLabel("Group 1 lead minutes", { exact: true }).fill("30");
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill(
      [
        "2026-11-01T08:20:00Z",
        "2026-11-01T08:35:00Z",
        "2026-11-01T08:50:00Z",
        "2026-11-01T09:20:00Z",
        "2026-11-01T09:35:00Z",
        "2026-11-01T09:50:00Z",
      ].join("\n"),
    );
  report = await review(page, dialog);
  expect(report.evaluation.map((r: any) => r.outputs.zg1_occupied)).toEqual([
    false,
    true,
    false,
    false,
    true,
    false,
  ]);
  expect(report.evaluation.map((r: any) => r.outputs.zg1_pre_only)).toEqual([
    true,
    false,
    false,
    true,
    false,
    false,
  ]);
  await expect(dialog).toContainText(
    "repeated autumn minutes evaluate in both folds",
  );
});

test("explicit zone/mode, unique IDs, lead integers and UTC samples reject unsupported drafts without replacement", async ({
  page,
}) => {
  const dialog = await open(page),
    original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
  await expect(dialog.getByLabel("Group 1 mode", { exact: true })).toHaveValue(
    "",
  );
  await expect(
    dialog.getByLabel("Group 1 time zone", { exact: true }),
  ).toHaveValue("");
  await dialog
    .getByRole("button", { name: "Preview zone-group schedule", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", {
      name: "Create editable schedule project",
      exact: true,
    }),
  ).toHaveCount(0);
  await declare(dialog);
  await dialog.getByLabel("Group 1 lead minutes", { exact: true }).fill("1.5");
  await dialog
    .getByRole("button", { name: "Preview zone-group schedule", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog.getByLabel("Group 1 lead minutes", { exact: true }).fill("60");
  await dialog
    .getByLabel("Group 1 time zone", { exact: true })
    .fill("Not/A_Timezone");
  await dialog
    .getByRole("button", { name: "Preview zone-group schedule", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("IANA");
  await dialog.getByLabel("Group 1 time zone", { exact: true }).fill("UTC");
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill("2026-01-05T07:00:00");
  await dialog
    .getByRole("button", { name: "Preview zone-group schedule", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("UTC");
  await dialog
    .getByLabel("Schedule UTC sample instants", { exact: true })
    .fill("");
  await dialog
    .getByRole("button", { name: "Add zone group", exact: true })
    .click();
  await declare(dialog, 2);
  await dialog.getByLabel("Group 2 ID", { exact: true }).fill("group1");
  await dialog
    .getByRole("button", { name: "Preview zone-group schedule", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("unique");
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});

for (const kind of [
  "preview-source",
  "preview-close",
  "export-source",
  "export-back",
])
  test(`held ${kind} cannot create or download stale schedule evidence`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await declare(dialog);
    if (kind.startsWith("export")) await review(page, dialog);
    const endpoint = kind.startsWith("export") ? "export" : "preview";
    let seen!: () => void, release!: () => void, done!: () => void;
    const requested = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      completed = new Promise<void>((r) => (done = r));
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route(
      `**/api/schedule-coordination/${endpoint}`,
      async (route) => {
        const response = await route.fetch();
        seen();
        await gate;
        await route.fulfill({ response });
        done();
      },
    );
    await dialog
      .getByRole("button", {
        name:
          endpoint === "preview"
            ? "Preview zone-group schedule"
            : "Export original schedule review JSON",
        exact: true,
      })
      .click();
    await requested;
    if (kind.endsWith("source"))
      await page
        .getByLabel("Program name", { exact: true })
        .fill("Changed schedule editor source");
    else if (kind.endsWith("back"))
      await dialog
        .getByRole("button", { name: "Back to equipment wizard", exact: true })
        .click();
    else
      await dialog
        .getByRole("button", { name: "Cancel schedule wizard", exact: true })
        .click();
    release();
    await completed;
    expect(downloads).toBe(0);
    await expect(
      page.getByRole("button", {
        name: "Create editable schedule project",
        exact: true,
      }),
    ).toHaveCount(0);
    if (kind.endsWith("source"))
      await expect(dialog.getByRole("alert")).toContainText(
        "Current editor changed",
      );
    else await expect(dialog).toHaveCount(0);
  });

for (const malformed of ["profile", "group-windows"])
  test(`malformed ${malformed} preview never authorizes creation`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await declare(dialog);
    await page.route("**/api/schedule-coordination/preview", async (route) => {
      const response = await route.fetch(),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else value.groups[0].occupied_windows = null;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", { name: "Preview zone-group schedule", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toContainText(
      "does not match these exact choices",
    );
    await expect(
      dialog.getByRole("button", {
        name: "Create editable schedule project",
        exact: true,
      }),
    ).toHaveCount(0);
  });

test("source-independent catalog can finish after editor changes during its initial load", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  let seen!: () => void, release!: () => void, done!: () => void;
  const requested = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    completed = new Promise<void>((r) => (done = r));
  await page.route("**/api/schedule-coordination/catalog", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
    done();
  });
  await page
    .getByRole("button", { name: "Zone-group schedule wizard", exact: true })
    .click();
  await requested;
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Editor changed during catalog");
  release();
  await completed;
  const dialog = page.getByRole("dialog", {
    name: "Zone-group schedule wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Schedule project name", { exact: true }),
  ).toBeVisible();
  await declare(dialog);
  await review(page, dialog);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Editor changed during catalog",
  );
});
