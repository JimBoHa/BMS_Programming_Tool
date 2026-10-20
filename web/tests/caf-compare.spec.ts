import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
function fixture(side: "original" | "candidate" | "other-model") {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `
from tests.test_formats_caf import make_caf
from bms_tool.caf import CafArchive
import sys
xml=CafArchive(make_caf()).xml.replace(b'</object>',b'<simulationProperty id="3113"><data><float>900</float></data></simulationProperty></object>')
if sys.argv[1]!='original': xml=xml.replace(b'72.000000',b'73.5').replace(b'<float>900</float>',b'<float>901</float>')
if sys.argv[1]=='other-model': xml=xml.replace(b'MS-VMA1630-0',b'FX-PCV1630-0')
sys.stdout.buffer.write(make_caf(xml))
`,
      side,
    ],
    { cwd: root },
  );
}

test("native CAF comparison separates simulation/application values and exports source-hashed review", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF compare", exact: true }).click();
  await page.getByLabel("Original CAF file", { exact: true }).setInputFiles({
    name: "original.caf",
    mimeType: "application/octet-stream",
    buffer: fixture("original"),
  });
  await expect(
    page.getByRole("region", { name: "Original CAF", exact: true }),
  ).toContainText("MS-VMA1630-0");
  await page.getByLabel("Candidate CAF file", { exact: true }).setInputFiles({
    name: "candidate.caf",
    mimeType: "application/octet-stream",
    buffer: fixture("candidate"),
  });
  await expect(
    page.getByRole("region", { name: "Candidate CAF", exact: true }),
  ).toContainText("candidate.caf");
  await page
    .getByRole("button", { name: "Compare CAF records", exact: true })
    .click();
  const report = page.getByRole("region", {
    name: "CAF comparison results",
    exact: true,
  });
  await expect(report).toContainText("2 changed records");
  await expect(report).toContainText("application value: 1");
  await expect(report).toContainText("simulation value: 1");
  await expect(report.locator("tbody tr")).toHaveCount(2);
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download CAF change review", exact: true })
    .click();
  const file = await downloading;
  const evidence = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(evidence.can_apply).toBe(false);
  expect(evidence.before.sha256).not.toBe(evidence.after.sha256);
  expect(evidence.changes.map((row: any) => row.category).sort()).toEqual([
    "application_value",
    "simulation_value",
  ]);
  await page
    .getByLabel("CAF comparison category", { exact: true })
    .selectOption("application_value");
  await expect(report).toHaveCount(0);
  await page
    .getByRole("button", { name: "Compare CAF records", exact: true })
    .click();
  await expect(report.locator("tbody tr")).toHaveCount(1);
  await expect(report.locator("tbody tr")).toContainText("73.5");
  await page.screenshot({
    path: "test-results/studio-caf-comparison.png",
    fullPage: true,
  });
  await page.getByLabel("Candidate CAF file", { exact: true }).setInputFiles({
    name: "other-model.caf",
    mimeType: "application/octet-stream",
    buffer: fixture("other-model"),
  });
  await expect(
    page.getByRole("region", { name: "Candidate CAF", exact: true }),
  ).toContainText("FX-PCV1630-0");
  await page
    .getByRole("button", { name: "Compare CAF records", exact: true })
    .click();
  await expect(report).toContainText("Model or release-mode metadata differs");
});

test("CAF review export includes every changed record beyond the displayed and API page limits", async ({
  page,
}) => {
  const makeMany = (delta: number) =>
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
from tests.test_formats_caf import make_caf
import sys
properties=''.join(f'<property id="{10000+i}"><data><float>{i+int(sys.argv[1])}</float></data></property>' for i in range(501))
xml='<objects xmlns="http://johnsoncontrols.com/MetasysIII/2002/3/Core"><object ref="a" classid="526">'+properties+'</object></objects>'
sys.stdout.buffer.write(make_caf(xml.encode()))
`,
        String(delta),
      ],
      { cwd: root },
    );
  await page.goto("/");
  await page.getByRole("button", { name: "CAF compare", exact: true }).click();
  for (const [label, delta] of [
    ["Original", 0],
    ["Candidate", 1],
  ] as const) {
    await page
      .getByLabel(`${label} CAF file`, { exact: true })
      .setInputFiles({
        name: `${label}.caf`,
        mimeType: "application/octet-stream",
        buffer: makeMany(delta),
      });
    await expect(
      page.getByRole("region", { name: `${label} CAF`, exact: true }),
    ).toContainText(`${label}.caf`);
  }
  await page
    .getByRole("button", { name: "Compare CAF records", exact: true })
    .click();
  const report = page.getByRole("region", {
    name: "CAF comparison results",
    exact: true,
  });
  await expect(report).toContainText("501 changed records");
  await expect(report.locator("tbody tr")).toHaveCount(100);
  await page
    .getByRole("button", { name: "Next comparison page", exact: true })
    .click();
  await expect(report).toContainText("101–200 of 501 filtered records");
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download CAF change review", exact: true })
    .click();
  const file = await downloading;
  const evidence = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(evidence.changes).toHaveLength(501);
  expect(evidence.changes.map((row: any) => row.index)).toEqual(
    Array.from({ length: 501 }, (_, i) => i),
  );
  expect(evidence.changes[500].property_id).toBe("10500");
  expect(evidence.changes[500].after.scalar.text).toBe("501");
  expect(evidence.offset).toBe(0);
  expect(evidence.filtered_total).toBe(501);
});
