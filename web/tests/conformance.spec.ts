import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
async function open(
  page: Page,
  code = "from tests.test_conformance import program; print(program().model_dump_json())",
) {
  await page.goto("/");
  const buffer = execFileSync(python, ["-c", code], { cwd: root });
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "delay.bms.json",
      mimeType: "application/json",
      buffer,
    });
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/conformance/catalog"),
  );
  await page
    .getByRole("button", { name: "Conformance tests", exact: true })
    .click();
  const response = await pending;
  await expect(
    page.getByLabel("Conformance suite name", { exact: true }),
  ).toBeEnabled();
  return {
    program: response.request().postDataJSON().program,
    catalog: await response.json(),
  };
}
async function check(page: Page, time: string, expected: string) {
  await page.getByLabel("Expected scan end", { exact: true }).fill(time);
  await page
    .getByLabel("Expected signal", { exact: true })
    .selectOption("result");
  await page.getByLabel("Expected value", { exact: true }).fill(expected);
  await page
    .getByRole("button", { name: "Add expected check", exact: true })
    .click();
}
async function author(page: Page) {
  const source = await open(page);
  await page
    .getByLabel("Conformance suite name", { exact: true })
    .fill("Browser delay criteria");
  await page
    .getByLabel("Conformance case name", { exact: true })
    .fill("Hand-calculated delay");
  await page.getByLabel("Conformance duration", { exact: true }).fill("3");
  await page
    .getByLabel("Stimulus input", { exact: true })
    .selectOption("sensor");
  await page.getByLabel("Stimulus value", { exact: true }).fill("5");
  await page
    .getByRole("button", { name: "Add or replace stimulus", exact: true })
    .click();
  await page.getByLabel("Stimulus scan start", { exact: true }).fill("1");
  await page.getByLabel("Stimulus value", { exact: true }).fill("-3");
  await page
    .getByRole("button", { name: "Add or replace stimulus", exact: true })
    .click();
  await check(page, "1", "-1");
  await check(page, "2", "5");
  await check(page, "3", "-3");
  return source;
}
async function run(page: Page) {
  await page
    .getByRole("button", { name: "Run declared checks", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Declared checks: passed", exact: true }),
  ).toBeVisible();
}
async function download(page: Page, name: string) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name, exact: true }).click();
  return await (await pending).path();
}

test("author criteria, run, persist, reopen after reload and download original sealed bytes", async ({
  page,
}) => {
  const source = await author(page);
  let raw = Buffer.alloc(0);
  await page.route("**/api/conformance/run", async (route) => {
    const response = await route.fetch();
    raw = await response.body();
    await route.fulfill({ response });
  });
  await run(page);
  const filename = await download(page, "Download conformance report JSON");
  expect(readFileSync(filename!)).toEqual(raw);
  const result = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "import json,sys;from tests.test_conformance import verify_report;r=json.load(open(sys.argv[1]));verify_report(r);print(json.dumps({'actual':[c['actual'] for c in r['cases'][0]['comparisons']],'source':r['program_sha256']}))",
        filename!,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  expect(result.actual).toEqual([-1, 5, -3]);
  expect(result.source).toBe(source.catalog.template.program_sha256);
  await page
    .getByRole("button", { name: "Save conformance suite", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Portable graph conformance tests", { exact: true })
      .getByRole("status"),
  ).toContainText("Saved conformance suite revision 1");
  const saved = readFileSync(
    (await download(page, "Export conformance suite JSON"))!,
  );
  await page.reload();
  await page
    .getByRole("button", { name: "Conformance tests", exact: true })
    .click();
  await page
    .getByLabel("Saved conformance suites", { exact: true })
    .selectOption({ label: "Browser delay criteria · revision 1" });
  await page
    .getByRole("button", { name: "Reopen conformance suite", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Conformance expectations", { exact: true })
      .locator("tbody tr"),
  ).toHaveCount(3);
  await run(page);
  await page
    .getByRole("button", { name: "New conformance suite", exact: true })
    .click();
  await page
    .getByLabel("Import conformance suite JSON", { exact: true })
    .setInputFiles({
      name: "criteria.json",
      mimeType: "application/json",
      buffer: saved,
    });
  await expect(
    page
      .getByLabel("Portable graph conformance tests", { exact: true })
      .getByRole("status"),
  ).toContainText("Imported source-checked suite");
  await run(page);
  await page
    .getByLabel("Conformance expectations", { exact: true })
    .getByRole("button", { name: "Edit expected check", exact: true })
    .first()
    .click();
  await page.getByLabel("Expected value", { exact: true }).fill("999");
  await page
    .getByRole("button", { name: "Update expected check", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Download conformance report JSON",
      exact: true,
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Run declared checks", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Declared checks: failed", exact: true }),
  ).toBeVisible();
});
test("quality input explicitly tests an unchanged-state final fault", async ({
  page,
}) => {
  await open(page);
  await page.getByLabel("Conformance duration", { exact: true }).fill("2");
  await page.getByLabel("Stimulus scan start", { exact: true }).fill("1");
  await page
    .getByLabel("Stimulus input", { exact: true })
    .selectOption("sensor");
  await page.getByLabel("Stimulus value", { exact: true }).fill("12");
  await page
    .getByLabel("Stimulus quality", { exact: true })
    .selectOption("open-circuit");
  await page
    .getByRole("button", { name: "Add or replace stimulus", exact: true })
    .click();
  await check(page, "1", "-1");
  await page.getByLabel("Expect final scan fault", { exact: true }).check();
  await page.getByLabel("Expected fault time", { exact: true }).fill("2");
  await page
    .getByLabel("Expected fault message", { exact: true })
    .fill("open-circuit");
  await run(page);
  await expect(
    page.getByLabel("Conformance results", { exact: true }),
  ).toContainText("Snapshot unchanged: true");
  await expect(
    page.getByLabel("Portable graph conformance tests", { exact: true }),
  ).toContainText("Native CAF logic is not executed");
});
test("stale and duplicate imported criteria cannot replace current source", async ({
  page,
}) => {
  const { catalog } = await open(page);
  const suite = structuredClone(catalog.template);
  suite.cases[0].checks = [
    {
      id: "test",
      signal: "result",
      unit: "degF",
      time: 1,
      expected: -1,
      abs_tol: 0,
      rel_tol: 0,
    },
  ];
  suite.program_sha256 = "0".repeat(64);
  await page
    .getByLabel("Import conformance suite JSON", { exact: true })
    .setInputFiles({
      name: "stale.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(suite)),
    });
  await expect(page.getByRole("alert")).toContainText("exact source program");
  await expect(
    page.getByLabel("Conformance suite name", { exact: true }),
  ).toHaveValue("New conformance suite");
  await page
    .getByLabel("Import conformance suite JSON", { exact: true })
    .setInputFiles({
      name: "duplicate.json",
      mimeType: "application/json",
      buffer: Buffer.from('{"name":"a","name":"b"}'),
    });
  await expect(page.getByRole("alert")).toContainText("duplicate fields");
});
test("late report after source edit is discarded and requires explicit rebinding", async ({
  page,
}) => {
  await author(page);
  let release!: () => void, seen!: () => void, done!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    requested = new Promise<void>((r) => (seen = r)),
    completed = new Promise<void>((r) => (done = r));
  await page.route("**/api/conformance/run", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
    done();
  });
  await page
    .getByRole("button", { name: "Run declared checks", exact: true })
    .click();
  await requested;
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Changed during local run");
  release();
  await completed;
  await expect(page.getByRole("alert")).toContainText("Source program changed");
  await expect(
    page.getByLabel("Conformance results", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Run declared checks", exact: true }),
  ).toBeDisabled();
  page.on("dialog", (d) => d.accept());
  await page
    .getByRole("button", { name: "New conformance suite", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Conformance expectations", { exact: true })
      .locator("tbody tr"),
  ).toHaveCount(0);
});
for (const mode of [
  "wrong-source",
  "wrong-suite",
  "wrapper",
  "malformed",
  "http-error",
  "bad-case-shape",
]) {
  test(`refuse ${mode} response and clear old evidence`, async ({ page }) => {
    await author(page);
    await run(page);
    await page.route("**/api/conformance/run", async (route) => {
      const response = await route.fetch();
      const value = await response.json();
      if (mode === "wrong-source") value.program_sha256 = "0".repeat(64);
      if (mode === "wrong-suite") value.suite_sha256 = "0".repeat(64);
      if (mode === "bad-case-shape") delete value.cases[0].comparisons;
      const body =
        mode === "wrapper"
          ? JSON.stringify({ report: value })
          : mode === "malformed"
            ? "{"
            : mode === "http-error"
              ? JSON.stringify({ detail: "Simulated local service error" })
              : JSON.stringify(value);
      await route.fulfill({
        response,
        status: mode === "http-error" ? 422 : 200,
        body,
      });
    });
    await page
      .getByRole("button", { name: "Run declared checks", exact: true })
      .click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(
      page.getByLabel("Conformance results", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: "Download conformance report JSON",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

test("actual downloaded report preserves signed zero and integral/exponent float evidence", async ({
  page,
}) => {
  await open(
    page,
    "from tests.test_engine import graph;p=graph('Multiply',a=0.0,b=-1.0);print(p.model_dump_json())",
  );
  await page.getByLabel("Conformance duration", { exact: true }).fill("1");
  await page.getByLabel("Stimulus input", { exact: true }).selectOption("a");
  await page.getByLabel("Stimulus value", { exact: true }).fill("0");
  await page
    .getByRole("button", { name: "Add or replace stimulus", exact: true })
    .click();
  await check(page, "1", "0");
  await page
    .getByLabel("Conformance expectations", { exact: true })
    .getByRole("button", { name: "Edit expected check", exact: true })
    .click();
  await page
    .getByLabel("Expected absolute tolerance", { exact: true })
    .fill("1e-7");
  await page
    .getByRole("button", { name: "Update expected check", exact: true })
    .click();
  let raw = Buffer.alloc(0);
  await page.route("**/api/conformance/run", async (route) => {
    const response = await route.fetch();
    raw = await response.body();
    await route.fulfill({ response });
  });
  await run(page);
  const filename = (await download(page, "Download conformance report JSON"))!;
  expect(readFileSync(filename)).toEqual(raw);
  expect(raw.toString()).toContain('"actual":-0.0');
  expect(raw.toString()).toContain('"expected":0.0');
  expect(raw.toString()).toContain('"abs_tol":1e-07');
  execFileSync(
    python,
    [
      "-c",
      "import json,sys,math;from tests.test_conformance import verify_report;r=json.load(open(sys.argv[1]));verify_report(r);assert math.copysign(1,r['cases'][0]['comparisons'][0]['actual'])==-1",
      filename,
    ],
    { cwd: root },
  );
});

test("integer criterion is refused before browser numeric rounding", async ({
  page,
}) => {
  await open(page);
  await page
    .getByLabel("Expected signal", { exact: true })
    .selectOption("result");
  await page
    .getByLabel("Expected value", { exact: true })
    .fill("9007199254740993");
  await page
    .getByRole("button", { name: "Add expected check", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "exactly representable as binary64",
  );
  await expect(
    page
      .getByLabel("Conformance expectations", { exact: true })
      .locator("tbody tr"),
  ).toHaveCount(0);
});
