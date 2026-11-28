import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { openTemcoProgram } from "./temco-workflow";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";

const root = path.resolve("..");
function program(kind = "Add", values = "{'a':40,'b':2}") {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `from tests.test_temco import graph; print(graph('${kind}', values=${values}).model_dump_json())`,
    ],
    { cwd: root },
  );
}
async function openNative(page: Page, kind = "Add", values?: string) {
  await openTemcoProgram(page, "temco-example.bms.json", program(kind, values));
  await expect(
    page.getByText("Native compiler available", { exact: true }),
  ).toBeVisible();
}

test("compile genuine Control Basic, download bytecode and execute the native interpreter", async ({
  page,
}) => {
  await openNative(page);
  await expect(
    page.getByRole("region", { name: "Temco target profile" }),
  ).toContainText("27 block types with retained state");
  await expect(page.locator(".temco-scope").first()).toContainText(
    "review controller transfer in Changes",
  );
  await page.getByLabel("Temco point for a", { exact: true }).fill("VAR4");
  await page
    .getByLabel("Temco point for result", { exact: true })
    .fill("VAR256");
  await page
    .getByRole("button", { name: "Compile Control Basic", exact: true })
    .click();
  await expect(page.getByLabel("Compiled Control Basic source")).toContainText(
    "T1 = VAR4",
  );
  await expect(page.getByLabel("Compiled Control Basic source")).toContainText(
    "VAR256 = T4",
  );
  const sourceEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download BASIC source", exact: true })
    .click();
  const source = await sourceEvent;
  expect(source.suggestedFilename()).toMatch(/\.bas$/);
  const sourceText = readFileSync((await source.path())!, "utf8");
  expect(sourceText).toMatch(/^10 REM BMS STUDIO CONTROL BASIC/);
  const binaryEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download Temco bytecode", exact: true })
    .click();
  const binary = await binaryEvent;
  expect(binary.suggestedFilename()).toMatch(/\.temco\.bin$/);
  const bytecode = readFileSync((await binary.path())!);
  expect(bytecode.length).toBeGreaterThan(9);
  expect(bytecode.length).toBeLessThan(2000);
  expect(bytecode.readUInt16LE(0)).toBeLessThan(bytecode.length);
  expect(bytecode.toString("utf8", 0, 1)).not.toBe("{");
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  const report = page.getByRole("region", {
    name: "Native verification results",
  });
  await expect(report.getByRole("status")).toHaveText(
    "Matched native/reference outputs",
  );
  await expect(report.locator("tbody tr").first()).toContainText("42");
  await expect(report.locator("tbody tr").first()).toContainText("Match");
  await page.getByLabel("Native value a", { exact: true }).fill("50");
  await expect(report).toHaveCount(0);
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  await expect(report.locator("tbody tr").first()).toContainText("52");
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "Temco application transfer");
  await expect(page.getByLabel("Compiled Control Basic source")).toContainText(
    "VAR256 = T4",
  );
  await expect(
    page.getByLabel("Temco point for a", { exact: true }),
  ).toHaveValue("VAR4");
  await expect(
    page.getByRole("region", { name: "Reviewed Temco transfer plan" }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "test-results/studio-temco-native.png",
    fullPage: true,
  });
});

test("editing bindings or replacing the local program clears the previous compiled transfer source", async ({
  page,
}) => {
  await openNative(page);
  const compile = page.getByRole("button", {
    name: "Compile Control Basic",
    exact: true,
  });
  const review = page.getByRole("button", {
    name: "Review controller transfer",
    exact: true,
  });
  await compile.click();
  await expect(review).toBeVisible();
  await page.getByLabel("Temco point for a", { exact: true }).fill("VAR5");
  await expect(review).toHaveCount(0);
  await compile.click();
  await expect(page.getByLabel("Compiled Control Basic source")).toContainText(
    "T1 = VAR5",
  );
  await chooseWorkspaceTask(page, "Program");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "Temco application transfer");
  await expect(page.getByLabel("Compiled Control Basic source")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Reviewed Temco transfer plan" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Plan compiled program transfer",
      exact: true,
    }),
  ).toBeDisabled();
});

test("native verification rejects invalid points and quality without retaining stale success", async ({
  page,
}) => {
  await openNative(page);
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  await expect(page.locator(".temco-result-match")).toBeVisible();
  await page
    .getByLabel("Native quality a", { exact: true })
    .selectOption("open-circuit");
  await expect(page.locator(".temco-result-match")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("good input quality");
  await page
    .getByLabel("Native quality a", { exact: true })
    .selectOption("good");
  await page.getByLabel("Temco point for a", { exact: true }).fill("1-IN1");
  await page
    .getByRole("button", { name: "Compile Control Basic", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("bare IN1..64");
  await expect(
    page.getByRole("region", { name: "Compiled native Control Basic" }),
  ).toHaveCount(0);
});

test("native retained state advances across scans and exposes the actual trace", async ({
  page,
}) => {
  await openNative(page, "Slew", "{}");
  await page.getByLabel("Native scan count", { exact: true }).fill("3");
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  const report = page.getByRole("region", {
    name: "Native verification results",
  });
  await expect(report.getByRole("status")).toHaveText(
    "Matched native/reference outputs",
  );
  await expect(report.locator("tbody tr").first()).toContainText("3");
  await page.getByText("Inspect native scan trace", { exact: true }).click();
  await expect(page.locator(".temco-trace tbody tr")).toHaveCount(3);
  await expect(page.locator(".temco-trace tbody tr").first()).toContainText(
    "result: 1",
  );
  await expect(page.locator(".temco-trace tbody tr").last()).toContainText(
    "result: 3",
  );
});

test("native schedule consumes explicit UTC host calendar flags", async ({
  page,
}) => {
  await openNative(page, "Schedule", "{}");
  await page
    .getByLabel("First native scan clock UTC", { exact: true })
    .fill("2026-10-19T17:59:59");
  await page.getByLabel("Native scan count", { exact: true }).fill("3");
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  const report = page.getByRole("region", {
    name: "Native verification results",
  });
  await expect(report.getByRole("status")).toHaveText(
    "Matched native/reference outputs",
  );
  await expect(report).toContainText("Host-evaluated calendar flags");
  await expect(report).toContainText("VAR256 active / VAR255 valid");
  await page.getByText("Inspect native scan trace", { exact: true }).click();
  await expect(page.locator(".temco-trace tbody tr").first()).toContainText(
    "result: TRUE",
  );
  await expect(page.locator(".temco-trace tbody tr").last()).toContainText(
    "result: FALSE",
  );
});

test("foreign native extensions are visibly rejected instead of omitted", async ({
  page,
}) => {
  const data = JSON.parse(program().toString());
  data.metadata.native_sedona = { version: 1, components: [], links: [] };
  await openTemcoProgram(
    page,
    "native-extension.bms.json",
    Buffer.from(JSON.stringify(data)),
  );
  await expect(page.getByRole("alert")).toContainText(
    "native Sedona extensions",
  );
  await expect(
    page.getByRole("button", { name: "Compile Control Basic", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("region", { name: "Native verification results" }),
  ).toHaveCount(0);
});

test("native fixed point overflow remains a visible mismatch", async ({
  page,
}) => {
  await openNative(page, "Multiply", "{'a':2000000,'b':2000000}");
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  const report = page.getByRole("region", {
    name: "Native verification results",
  });
  await expect(report.getByRole("status")).toHaveText(
    "Native/reference difference",
  );
  await expect(report.locator("tbody tr").first()).toContainText(
    "4000000000000",
  );
  await expect(report.locator("tbody tr").first()).toContainText("Difference");
  await expect(page.locator(".temco-result-match")).toHaveCount(0);
});
