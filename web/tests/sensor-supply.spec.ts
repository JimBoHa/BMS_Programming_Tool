import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByText("Sensor power supply budget", { exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Sensor supply budgeting",
    exact: true,
  });
  await expect(panel.getByLabel("Supply plan name")).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Save supply plan", exact: true }),
  ).toBeEnabled();
  return panel;
}

async function documentedRail(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByLabel("Supply rail profile")
    .selectOption("MS-VMA1630-0:universal-15v");
  await panel
    .getByLabel("Supply physical instance")
    .fill("Authored VMA auxiliary source");
  await panel.getByLabel("Supply operating minimum").fill("15");
  await panel.getByLabel("Supply operating maximum").fill("15");
  await panel.getByLabel("Supply all loads included").check();
  await panel
    .getByRole("button", { name: "Add supply rail", exact: true })
    .click();
}

test("documented sensor profile keeps maximum/startup unknown, detects shared overload and persists portable guarded plans", async ({
  page,
}) => {
  let panel = await open(page);
  await panel
    .getByLabel("Supply plan name")
    .fill("Authored VMA dual-output sensor budget");
  await documentedRail(panel);
  await panel
    .getByLabel("Supply load profile")
    .selectOption("Belimo:22UTH-510X:2026-08-26");
  await panel
    .getByRole("button", { name: "Add supply load", exact: true })
    .click();
  await panel
    .getByRole("button", { name: "Calculate supply budget", exact: true })
    .click();
  const results = panel.getByRole("region", { name: "Supply budget results" });
  await expect(results).toContainText("Budget status: incomplete");
  await expect(results).toContainText("26.666667 mA (published-unspecified)");
  await expect(results).toContainText("startup Unknown mA (unknown)");
  await expect(
    panel
      .getByRole("table", { name: "Supply load records" })
      .locator("tbody tr"),
  ).toHaveCount(1);
  await panel.getByRole("button", { name: "Edit load", exact: true }).click();
  await panel.getByLabel("Supply load quantity").fill("2");
  await panel
    .getByRole("button", { name: "Update supply load", exact: true })
    .click();
  await panel
    .getByRole("button", { name: "Calculate supply budget", exact: true })
    .click();
  await expect(results).toContainText("Budget status: over-budget");
  await expect(results).toContainText("53.333333");
  await panel
    .getByRole("button", { name: "Save supply plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("revision 1");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export supply plan JSON", exact: true })
    .click();
  const exported = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  expect(exported.loads).toHaveLength(1);
  expect(exported.loads[0].quantity).toBe(2);
  expect(exported.loads[0].spec.dc.steady.basis).toBe("published-unspecified");
  expect(exported.rails[0].spec.current_limit_ma).toBe(35);
  expect(exported.rails[0].profile_sha256).toMatch(/^[a-f0-9]{64}$/);
  await page.reload();
  panel = await open(page);
  const option = panel
    .getByLabel("Saved supply plans")
    .locator("option")
    .filter({ hasText: "Authored VMA dual-output sensor budget" })
    .first();
  await panel
    .getByLabel("Saved supply plans")
    .selectOption((await option.getAttribute("value"))!);
  await panel
    .getByRole("button", { name: "Reopen supply plan", exact: true })
    .click();
  await expect(
    panel.getByRole("table", { name: "Supply load records" }),
  ).toContainText("2");
  await panel
    .getByRole("button", { name: "Calculate supply budget", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Supply budget results" }),
  ).toContainText("over-budget");
  const tampered = structuredClone(exported);
  tampered.rails[0].spec.current_limit_ma = 1000;
  await panel.getByLabel("Supply plan JSON", { exact: true }).setInputFiles({
    name: "forged.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(tampered)),
  });
  await expect(panel.getByRole("alert")).toContainText(
    "guarded specification changed",
  );
  await panel
    .getByRole("button", { name: "New supply plan", exact: true })
    .click();
  await panel.getByLabel("Supply plan JSON", { exact: true }).setInputFiles({
    name: "original.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(exported)),
  });
  await expect(panel.getByRole("status")).toContainText(
    "Imported source-checked",
  );
  await panel
    .getByRole("button", { name: "Save supply plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("revision 1");
});

test("external AC supply checks terminal startup limits and refuses watts without power factor", async ({
  page,
}) => {
  const panel = await open(page);
  await panel
    .getByLabel("Supply plan name")
    .fill("Authored external AC supply budget");
  await panel.getByLabel("Supply power type").selectOption("ac");
  await panel.getByLabel("Supply shared current limit").fill("100");
  await panel.getByLabel("Supply terminal limit 1").fill("50");
  await panel.getByLabel("Supply operating minimum").fill("24");
  await panel.getByLabel("Supply operating maximum").fill("24");
  await panel.getByLabel("Supply all loads included").check();
  await panel
    .getByRole("button", { name: "Add supply rail", exact: true })
    .click();
  await panel.getByLabel("Load supports DC").uncheck();
  await panel.getByLabel("Load supports AC").check();
  for (const [phase, amount] of [
    ["steady", "40"],
    ["startup", "60"],
  ]) {
    await panel.getByLabel(`Load ac ${phase} basis`).selectOption("maximum");
    await panel.getByLabel(`Load ac ${phase} amount`).fill(amount);
  }
  await panel
    .getByRole("button", { name: "Add supply load", exact: true })
    .click();
  await panel
    .getByRole("button", { name: "Calculate supply budget", exact: true })
    .click();
  const results = panel.getByRole("region", { name: "Supply budget results" });
  await expect(results).toContainText("over-budget");
  await expect(results).toContainText("exceeded");
  await panel.getByRole("button", { name: "Edit rail", exact: true }).click();
  await panel.getByLabel("Supply terminal limit 1").fill("70");
  await panel
    .getByRole("button", { name: "Update supply rail", exact: true })
    .click();
  await panel
    .getByRole("button", { name: "Calculate supply budget", exact: true })
    .click();
  await expect(results).toContainText("within-declared-limits");
  await panel.getByRole("button", { name: "Edit load", exact: true }).click();
  await panel.getByLabel("Load ac steady unit").selectOption("W");
  await panel.getByLabel("Load ac steady amount").fill("0.4");
  await panel
    .getByRole("button", { name: "Update supply load", exact: true })
    .click();
  await panel
    .getByRole("button", { name: "Calculate supply budget", exact: true })
    .click();
  await expect(results).toContainText("incomplete");
  await expect(results).toContainText("steady Unknown mA");
  await panel
    .getByRole("button", { name: "Save supply plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("revision 1");
  const options = panel.getByLabel("Saved supply plans").locator("option");
  const prior = await options.count();
  await panel
    .getByRole("button", { name: "Save supply plan copy", exact: true })
    .click();
  await expect(options).toHaveCount(prior + 1);
  page.once("dialog", (dialog) => dialog.accept());
  await panel
    .getByRole("button", { name: "Delete selected supply plan", exact: true })
    .click();
  await expect(options).toHaveCount(prior);
  await expect(
    panel
      .getByRole("table", { name: "Supply load records" })
      .locator("tbody tr"),
  ).toHaveCount(1);
});

test("supply plans explicitly bind the saved hardware survey hash and export scoped calculation evidence without field traffic", async ({
  page,
}) => {
  const panel = await open(page);
  const root = path.resolve("..");
  const fixture = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_hardware_workbench_api import offline_report; import json; print(json.dumps(offline_report()))",
    ],
    { cwd: root },
  );
  await page
    .getByLabel("Import hardware survey JSON", { exact: true })
    .setInputFiles({
      name: "authored-survey.json",
      mimeType: "application/json",
      buffer: fixture,
    });
  await expect(
    panel.getByRole("button", {
      name: "Bind current hardware survey",
      exact: true,
    }),
  ).toBeEnabled();
  await panel
    .getByRole("button", { name: "Bind current hardware survey", exact: true })
    .click();
  await expect(panel).toContainText("Survey binding:");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export supply plan JSON", exact: true })
    .click();
  const bound = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  expect(bound.source_report.id).toMatch(/^[a-f0-9]{32}$/);
  expect(bound.source_report.content_sha256).toMatch(/^[a-f0-9]{64}$/);
  const stale = structuredClone(bound);
  stale.source_report.content_sha256 = "0".repeat(64);
  page.once("dialog", (dialog) => dialog.accept());
  await panel.getByLabel("Supply plan JSON", { exact: true }).setInputFiles({
    name: "stale-report.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(stale)),
  });
  await expect(panel.getByRole("alert")).toContainText("source survey hash");
  const reportDownload = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export budget report JSON", exact: true })
    .click();
  const report = JSON.parse(
    readFileSync((await (await reportDownload).path())!, "utf8"),
  );
  expect(report.source_report).toEqual(bound.source_report);
  expect(report.controller_writes).toBe(false);
  expect(report.wiring_verified).toBe(false);
  expect(report.status).toBe("incomplete");
  const status = await page.request.get("/api/bacnet/status");
  expect((await status.json()).connected).toBe(false);
});

test("closing the supply panel suppresses a delayed export while preserving the draft", async ({
  page,
}) => {
  const panel = await open(page);
  await panel
    .getByLabel("Supply plan name")
    .fill("Authored hidden export draft");
  let release!: () => void;
  let entered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const seen = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route("**/api/sensor-supply/validate", async (route) => {
    entered();
    await held;
    await route.continue();
  });
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  await panel
    .getByRole("button", { name: "Export supply plan JSON", exact: true })
    .click();
  await seen;
  await page.getByText("Sensor power supply budget", { exact: true }).click();
  release();
  await page.unrouteAll({ behavior: "wait" });
  await expect(
    page
      .getByRole("region", {
        name: "Sensor supply budgeting",
        includeHidden: true,
      })
      .getByRole("button", {
        name: "Save supply plan",
        exact: true,
        includeHidden: true,
      }),
  ).toBeEnabled();
  expect(downloads).toEqual([]);
  await page.getByText("Sensor power supply budget", { exact: true }).click();
  await expect(panel.getByLabel("Supply plan name")).toHaveValue(
    "Authored hidden export draft",
  );
});
