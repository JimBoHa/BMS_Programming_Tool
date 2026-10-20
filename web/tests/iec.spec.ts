import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function openIEC(page: Page, kind = "Add", values = "{'a':40,'b':2}") {
  const program = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `from tests.test_temco import graph; print(graph('${kind}', values=${values}).model_dump_json())`,
    ],
    { cwd: root },
  );
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "iec-example.bms.json",
    mimeType: "application/json",
    buffer: program,
  });
  await page.getByRole("button", { name: "IEC native", exact: true }).click();
  await expect(
    page.getByText("MatIEC compiler available", { exact: true }),
  ).toBeVisible();
}

test("real IEC compiler artifacts and native scan trace support changed inputs and fault quality", async ({
  page,
}) => {
  await openIEC(page);
  await page
    .getByRole("button", { name: "Compile native IEC", exact: true })
    .click();
  await expect(page.getByLabel("Compiled IEC Structured Text")).toContainText(
    "PROGRAM MAIN",
  );
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download generated C", exact: true })
    .click();
  const file = await downloading;
  expect(readFileSync((await file.path())!, "utf8")).toContain("MAIN_body__");
  await page.getByLabel("IEC scan count", { exact: true }).fill("3");
  await page
    .getByRole("button", { name: "Run IEC verification", exact: true })
    .click();
  const report = page.getByRole("region", { name: "IEC verification results" });
  await expect(report.getByRole("status")).toHaveText(
    "Matched compiled IEC/reference outputs",
  );
  await expect(report.locator("tbody tr")).toHaveCount(3);
  await expect(report.locator("tbody tr").last()).toContainText("result: 42");
  await page.getByLabel("IEC value a", { exact: true }).fill("50");
  await expect(report).toHaveCount(0);
  await page
    .getByRole("button", { name: "Run IEC verification", exact: true })
    .click();
  await expect(report.locator("tbody tr").last()).toContainText("result: 52");
  await page
    .getByLabel("IEC quality a", { exact: true })
    .selectOption("open-circuit");
  await page
    .getByRole("button", { name: "Run IEC verification", exact: true })
    .click();
  await expect(report.getByRole("status")).toHaveText(
    "Matched retained outputs after scan faults",
  );
  await expect(report).toContainText("3 scans held");
  await expect(report.locator("tbody tr").first()).toContainText(
    "open-circuit",
  );
  await page.screenshot({
    path: "test-results/studio-iec-quality.png",
    fullPage: true,
  });
});

test("native IEC timed events retain output on divide failure and recover on subsequent scans", async ({
  page,
}) => {
  await openIEC(page, "Divide");
  await page
    .getByLabel("IEC first scan clock UTC", { exact: true })
    .fill("2026-10-19T12:00");
  await page.getByLabel("IEC scenario events", { exact: true }).fill(
    JSON.stringify([
      { time: 0, inputs: { a: 12, b: 3 } },
      { time: 1, inputs: { b: 0 } },
      { time: 2, inputs: { b: 4 } },
    ]),
  );
  await page.getByLabel("IEC scenario duration", { exact: true }).fill("3");
  await page
    .getByRole("button", { name: "Run native scenario", exact: true })
    .click();
  const report = page.getByRole("region", { name: "IEC verification results" });
  await expect(report.getByRole("status")).toHaveText(
    "Matched retained outputs after scan faults",
  );
  const rows = report.locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("result: 4");
  await expect(rows.nth(0)).toContainText("2026-10-19T12:00:01+00:00");
  await expect(rows.nth(1)).toContainText("result: 4");
  await expect(rows.nth(2)).toContainText("result: 3");
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download full IEC trace", exact: true })
    .click();
  const file = await downloading;
  const trace = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(trace.rows.map((row: any) => row.fault)).toEqual([false, true, false]);
  expect(trace.native_runtime_verified).toBe(true);
});

test("IEC REAL overflow stays a visible native/reference mismatch", async ({
  page,
}) => {
  await openIEC(page, "Multiply", "{'a':1e30,'b':1e30}");
  await page.getByLabel("IEC scan count", { exact: true }).fill("1");
  await page
    .getByRole("button", { name: "Run IEC verification", exact: true })
    .click();
  const report = page.getByRole("region", { name: "IEC verification results" });
  await expect(report.getByRole("status")).toHaveText(
    "Compiled IEC/reference difference",
  );
  await expect(report.locator("tbody tr")).toContainText("Difference");
  await expect(page.locator(".temco-result-match")).toHaveCount(0);
});
