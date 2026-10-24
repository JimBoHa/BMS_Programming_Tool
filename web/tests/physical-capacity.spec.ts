import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const python = path.resolve("../.venv/bin/python");
const fixture = () =>
  execFileSync(
    python,
    [
      "-c",
      "from tests.test_hardware_workbench_api import offline_report; from tests.test_hardware_survey import authored_archive; from bms_tool.hardware_survey import analyze_archive,enrich_report; from bms_tool.hardware_workbench import canonical; import sys; r=enrich_report(offline_report(),analyze_archive(authored_archive())); r['archive_comparison']['conflicts'].append({'error':'Authored unresolved corroboration','native_zero':-0.0,'native_integral':1.0,'native_integer':9007199254740993}); sys.stdout.buffer.write(canonical(r))",
    ],
    {
      cwd: path.resolve(".."),
      env: { ...process.env, PYTHONPATH: path.resolve("../backend") },
    },
  );
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Physical capacity matrix",
    exact: true,
  });
  await panel
    .getByRole("button", { name: "Open capacity catalog", exact: true })
    .click();
  await expect(
    panel.getByLabel("Exact capacity model", { exact: true }),
  ).toBeVisible();
  return panel;
}
async function review(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", { name: "Review physical count fit", exact: true })
    .click();
  return panel.getByRole("region", {
    name: "Capacity count review",
    exact: true,
  });
}
async function importSurvey(page: Page) {
  await page
    .getByLabel("Import hardware survey JSON", { exact: true })
    .setInputFiles({
      name: "authored-survey.json",
      mimeType: "application/json",
      buffer: fixture(),
    });
  await expect(
    page
      .getByRole("region", { name: "Physical capacity matrix", exact: true })
      .getByLabel("Capacity survey host", { exact: true }),
  ).toBeVisible();
}

test("offline exact model matrix refuses analog demand on BI and exports sealed original response bytes", async ({
  page,
}) => {
  const forbidden: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/bacnet/") && r.method() !== "GET")
      forbidden.push(r.url());
  });
  const panel = await open(page);
  await expect(
    panel.getByLabel("Documented capacity model").locator("option"),
  ).toHaveCount(33);
  const pools = panel.getByRole("table", { name: "Physical resource pools" });
  await expect(pools).toContainText("BI");
  await expect(pools).toContainText("16");
  await expect(pools).not.toContainText("0–10 VDC");
  let result = await review(panel);
  await expect(result).toContainText("count-mode-shortfall");
  await expect(result).toContainText("0 / 1");
  await panel
    .getByLabel("Capacity signal family 1", { exact: true })
    .selectOption("input-contact");
  await panel.getByLabel("Capacity quantity 1", { exact: true }).fill("16");
  result = await review(panel);
  await expect(result).toContainText("count-mode-fit");
  await expect(result).toContainText("16 / 16");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Export original capacity review JSON",
      exact: true,
    })
    .click();
  const download = await pending;
  const filename = (await download.path())!;
  const data = JSON.parse(readFileSync(filename, "utf8"));
  expect(data.request.model).toBe("FX-PCX3721-0");
  expect(data.demands[0].pool_count_witness).toEqual([
    { pool: "BI", quantity: 16 },
  ]);
  expect(data.demands[0].terminal_assignment).toBeNull();
  expect(data.field_queries).toBe(false);
  expect(data.controller_writes).toBe(false);
  expect(
    execFileSync(
      python,
      [
        "-c",
        "import hashlib,json,sys; p=json.load(open(sys.argv[1])); h=p.pop('content_sha256'); b=json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode(); assert hashlib.sha256(b).hexdigest()==h; print(h)",
        filename,
      ],
      { encoding: "utf8" },
    ).trim(),
  ).toBe(data.content_sha256);
  await panel
    .getByRole("button", { name: "Add capacity demand", exact: true })
    .click();
  await panel
    .getByLabel("Capacity signal family 2", { exact: true })
    .selectOption("input-contact");
  result = await review(panel);
  await expect(result).toContainText("count-mode-shortfall");
  await expect(result).toContainText("16 / 17");
  expect(forbidden).toEqual([]);
});

test("shared UO modes compete; relay conflicts and unknown suffixes stay visible", async ({
  page,
}) => {
  const panel = await open(page);
  await panel
    .getByLabel("Documented capacity model")
    .selectOption("FX-PCX3711-2");
  await expect(panel.getByRole("note")).toContainText("24 VAC");
  await expect(panel.getByRole("note")).toContainText("240 VAC");
  await panel
    .getByLabel("Capacity signal family 1", { exact: true })
    .selectOption("output-voltage");
  await panel.getByLabel("Capacity quantity 1", { exact: true }).fill("4");
  await panel
    .getByRole("button", { name: "Add capacity demand", exact: true })
    .click();
  await panel
    .getByLabel("Capacity signal family 2", { exact: true })
    .selectOption("output-current");
  await panel.getByLabel("Capacity quantity 2", { exact: true }).fill("4");
  let result = await review(panel);
  await expect(result).toContainText("4 / 8");
  await expect(result).toContainText("Source conflicts remain unresolved");
  await panel
    .getByLabel("Exact capacity model", { exact: true })
    .fill("FX-PCX3711-2U");
  await expect(
    panel.getByRole("table", { name: "Physical resource pools" }),
  ).toHaveCount(0);
  await expect(panel.getByRole("status")).toContainText("Unknown exact model");
  result = await review(panel);
  await expect(result).toContainText("unknown-model");
  await expect(result).toContainText("0 / 8");
});

test("explicit saved-survey host binding preserves original hash and invalidates when selected source is replaced", async ({
  page,
}) => {
  const panel = await open(page);
  await importSurvey(page);
  await panel.getByLabel("Capacity survey host").selectOption("sa:7");
  await panel
    .getByRole("button", { name: "Use selected survey model", exact: true })
    .click();
  await expect(
    panel.getByLabel("Exact capacity model", { exact: true }),
  ).toHaveValue("FX-PCX3721-0");
  await expect(panel).toContainText("Bound to original survey");
  await panel
    .getByLabel("Capacity signal family 1", { exact: true })
    .selectOption("input-contact");
  await expect(await review(panel)).toContainText("count-mode-fit");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Export original capacity review JSON",
      exact: true,
    })
    .click();
  const doc = JSON.parse(readFileSync((await (await pending).path())!, "utf8"));
  expect(doc.survey_binding.reference.host).toBe("sa");
  expect(doc.survey_binding.reference.sa_mac).toBe(7);
  expect(doc.survey_binding.occupancy_applied).toBe(false);
  expect(doc.survey_binding.source_conflicts).toHaveLength(1);
  expect(
    execFileSync(
      python,
      [
        "-c",
        "import hashlib,json,math,sys; p=json.load(open(sys.argv[1])); h=p.pop('content_sha256'); b=json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode(); assert hashlib.sha256(b).hexdigest()==h; c=p['survey_binding']['source_conflicts'][0]; assert math.copysign(1,c['native_zero'])<0 and type(c['native_integral']) is float and c['native_integer']==9007199254740993; print('exact')",
        (await (await pending).path())!,
      ],
      { encoding: "utf8" },
    ).trim(),
  ).toBe("exact");
  const stored = await page.request.get(
    `/api/bacnet/hardware/reports/${doc.survey_binding.reference.id}`,
  );
  expect((await stored.json()).content_sha256).toBe(
    doc.survey_binding.reference.content_sha256,
  );
  await importSurvey(page);
  await expect(
    panel.getByRole("region", { name: "Capacity count review", exact: true }),
  ).toHaveCount(0);
  await expect(panel.getByText(/^Bound to original survey/)).toHaveCount(0);
  await expect(
    panel.getByRole("button", {
      name: "Export original capacity review JSON",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("held review cannot adopt or export after demand/source edits or navigation", async ({
  page,
}) => {
  const panel = await open(page);
  let release!: () => void, entered!: () => void, completed!: () => void;
  let done = new Promise<void>((resolve) => {
    completed = resolve;
  });
  let held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let ready = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route("**/api/hardware-capacity/review", async (route) => {
    const response = await route.fetch();
    entered();
    await held;
    await route.fulfill({ response });
    completed();
  });
  await panel
    .getByRole("button", { name: "Review physical count fit", exact: true })
    .click();
  await ready;
  await panel
    .getByLabel("Exact capacity model", { exact: true })
    .fill("MS-IOM3721-0");
  release();
  await done;
  await page.unroute("**/api/hardware-capacity/review");
  await expect(
    panel.getByRole("region", { name: "Capacity count review", exact: true }),
  ).toHaveCount(0);
  await expect(await review(panel)).toContainText("count-mode-shortfall");
  await importSurvey(page);
  await panel
    .getByRole("button", { name: "Use selected survey model", exact: true })
    .click();
  done = new Promise<void>((resolve) => {
    completed = resolve;
  });
  held = new Promise<void>((resolve) => {
    release = resolve;
  });
  ready = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route("**/api/hardware-capacity/review", async (route) => {
    const response = await route.fetch();
    entered();
    await held;
    await route.fulfill({ response });
    completed();
  });
  await panel
    .getByRole("button", { name: "Review physical count fit", exact: true })
    .click();
  await ready;
  await importSurvey(page);
  release();
  await done;
  await page.unroute("**/api/hardware-capacity/review");
  await expect(
    panel.getByRole("region", { name: "Capacity count review", exact: true }),
  ).toHaveCount(0);
  done = new Promise<void>((resolve) => {
    completed = resolve;
  });
  held = new Promise<void>((resolve) => {
    release = resolve;
  });
  ready = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route("**/api/hardware-capacity/review", async (route) => {
    const response = await route.fetch();
    entered();
    await held;
    await route.fulfill({ response });
    completed();
  });
  await panel
    .getByRole("button", { name: "Review physical count fit", exact: true })
    .click();
  await ready;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  release();
  await done;
  await page.unroute("**/api/hardware-capacity/review");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Capacity count review", exact: true }),
  ).toHaveCount(0);
});

test("malformed catalog/review retain draft and never become downloadable evidence", async ({
  page,
}) => {
  await page.route("**/api/hardware-capacity/catalog", (route) =>
    route.fulfill({ json: { profile: "jci-physical-counts/1", captures: {} } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Physical capacity matrix",
    exact: true,
  });
  await panel
    .getByRole("button", { name: "Open capacity catalog", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("malformed");
  await page.unroute("**/api/hardware-capacity/catalog");
  await panel
    .getByRole("button", { name: "Open capacity catalog", exact: true })
    .click();
  await panel
    .getByLabel("Exact capacity model", { exact: true })
    .fill("MS-IOM3721-0");
  await page.route("**/api/hardware-capacity/review", async (route) => {
    const response = await route.fetch();
    const value = await response.json();
    value.request.model = "FX-PCX4711-0";
    await route.fulfill({ json: value });
  });
  await panel
    .getByRole("button", { name: "Review physical count fit", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("another source/draft");
  await expect(
    panel.getByLabel("Exact capacity model", { exact: true }),
  ).toHaveValue("MS-IOM3721-0");
  await expect(
    panel.getByRole("button", {
      name: "Export original capacity review JSON",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.unroute("**/api/hardware-capacity/review");
  for (const flag of [
    "installed_verified",
    "electrical_compatibility_verified",
    "power_verified",
  ]) {
    await page.route("**/api/hardware-capacity/review", async (route) => {
      const response = await route.fetch();
      const value = await response.json();
      value[flag] = true;
      await route.fulfill({ json: value });
    });
    await panel
      .getByRole("button", { name: "Review physical count fit", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText("malformed");
    await expect(
      panel.getByRole("region", { name: "Capacity count review", exact: true }),
    ).toHaveCount(0);
    await page.unroute("**/api/hardware-capacity/review");
  }
  await page.route("**/api/hardware-capacity/catalog", async (route) => {
    const response = await route.fetch();
    const value = await response.json();
    value.sources["fx-2024"].document = {};
    await route.fulfill({ json: value });
  });
  await panel
    .getByRole("button", { name: "Reload capacity catalog", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("malformed");
  await expect(
    panel.getByLabel("Exact capacity model", { exact: true }),
  ).toHaveValue("MS-IOM3721-0");
});
