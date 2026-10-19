import { expect, test, type Locator, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

async function loadMacroSource(page: Page) {
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from bms_tool.models import Program,Node,Edge; p=Program(id='macro-browser',name='Independent rate limiters',nodes=[Node(id='input',kind='Input',label='Long ramp',params={'default':100},x=0,y=100),Node(id='rate',kind='Slew',label='Original rate limiter',params={'rate':1,'initial':0},x=320,y=100),Node(id='out',kind='Output',x=640,y=100),Node(id='input_second',kind='Input',label='Short ramp',params={'default':2},x=0,y=420),Node(id='out_second',kind='Output',x=640,y=420)],edges=[Edge(id='source_link',source='input',target='rate'),Edge(id='result_link',source='rate',target='out'),Edge(id='second_link',source='rate',target='out_second')]); print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "rate-limiters.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
}

async function wire(page: Page, source: Locator, target: Locator) {
  const start = await source.boundingBox();
  const end = await target.boundingBox();
  expect(start).not.toBeNull();
  expect(end).not.toBeNull();
  await page.mouse.move(
    start!.x + start!.width / 2,
    start!.y + start!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(end!.x + end!.width / 2, end!.y + end!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
}

async function removeWire(page: Page, id: string) {
  await page
    .locator(`.react-flow__edge[data-id="${id}"] .react-flow__edge-path`)
    .dispatchEvent("dblclick");
}

async function stepSimulation(page: Page) {
  const response = page.waitForResponse(
    (result) =>
      result.url().endsWith("/api/simulation/step") &&
      result.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  expect((await response).ok()).toBe(true);
}

test("extract a typed macro, run independent instances and exchange its library", async ({
  page,
}) => {
  await page.goto("/");
  await loadMacroSource(page);
  await page.locator('.react-flow__node[data-id="rate"]').click();
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await expect(page.locator(".macro-selection-summary")).toContainText(
    "1 selected block",
  );
  await page.getByLabel("Macro name", { exact: true }).fill("Rate limiter");
  await page.getByRole("button", { name: "Create macro", exact: true }).click();
  await expect(page.locator(".macro-count")).toHaveText("1 definition");
  await expect(page.locator(".macro-inspection")).toContainText("Slew");
  await expect(page.locator(".macro-interface")).toContainText("Long ramp");
  await expect(page.locator(".macro-interface")).toContainText("number");
  await expect(
    page.getByRole("button", { name: "Delete unused", exact: true }),
  ).toBeDisabled();

  await page.getByLabel("Canvas X", { exact: true }).fill("320");
  await page.getByLabel("Canvas Y", { exact: true }).fill("420");
  await page
    .getByRole("button", { name: "Add instance to program", exact: true })
    .click();
  await expect(page.locator(".macro-stat-row")).toContainText("2 instances");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  const instance = page
    .locator('.react-flow__node[data-id^="use_macro_Rate_limiter"]')
    .last();
  await expect(instance.locator(".react-flow__handle-left")).toHaveCount(1);
  await removeWire(page, "second_link");
  await expect(page.locator(".react-flow__edge")).toHaveCount(2);
  await wire(
    page,
    page
      .locator('.react-flow__node[data-id="input_second"]')
      .locator(".react-flow__handle-right"),
    instance.locator(".react-flow__handle-left"),
  );
  await wire(
    page,
    instance.locator(".react-flow__handle-right"),
    page
      .locator('.react-flow__node[data-id="out_second"]')
      .locator(".react-flow__handle-left"),
  );
  await expect(page.locator(".react-flow__edge")).toHaveCount(4);
  for (let index = 0; index < 3; index++) {
    await stepSimulation(page);
  }
  await expect(page.locator(".trend-legend")).toContainText("out: 3");
  await expect(page.locator(".trend-legend")).toContainText("out_second: 2");

  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await page
    .getByRole("button", { name: "Edit definition on wiresheet", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toContainText(
    "Editing definition: macro_Rate_limiter",
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await page.locator('.react-flow__node[data-id="rate"]').click();
  const rateParameter = page
    .locator(".inspector label")
    .filter({ hasText: /^rate$/ })
    .locator("input");
  await rateParameter.fill("2");
  await expect
    .poll(() =>
      page.evaluate(() => {
        const saved = JSON.parse(
          localStorage.getItem("bms-studio-macro-edit-v1") || "null",
        );
        return saved?.draft?.nodes.find((node: any) => node.id === "rate")
          ?.params.rate;
      }),
    )
    .toBe(2);
  await page.reload();
  await expect(page.locator(".macro-edit-banner")).toContainText(
    "Editing definition: macro_Rate_limiter",
  );
  await page.locator('.react-flow__node[data-id="rate"]').click();
  await expect(rateParameter).toHaveValue("2");
  const applied = page.waitForResponse((result) =>
    result.url().endsWith("/api/macros/update"),
  );
  await page
    .getByRole("button", { name: "Apply definition changes", exact: true })
    .click();
  expect((await applied).ok()).toBe(true);
  await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await expect(
    page.locator('.react-flow__node[data-id^="use_macro_Rate_limiter"]'),
  ).toHaveCount(2);
  await page.getByTitle("Reset simulation", { exact: true }).click();
  await stepSimulation(page);
  await stepSimulation(page);
  await expect(page.locator(".trend-legend")).toContainText("out: 4");
  await expect(page.locator(".trend-legend")).toContainText("out_second: 2");

  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await page
    .getByRole("button", { name: "Edit definition on wiresheet", exact: true })
    .click();
  await page.locator('.react-flow__node[data-id="rate"]').click();
  await rateParameter.fill("9");
  await page
    .getByRole("button", { name: "Discard definition changes", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await page.getByTitle("Reset simulation", { exact: true }).click();
  await stepSimulation(page);
  await expect(page.locator(".trend-legend")).toContainText("out: 2");
  await expect(page.locator(".trend-legend")).toContainText("out_second: 2");

  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export macro", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("Rate-limiter.bms-macro.json");
  const bundle = readFileSync((await file.path())!);
  const document = JSON.parse(bundle.toString());
  expect(document.format).toBe("bms-macro-library/1");
  expect(document.library.definitions).toHaveLength(1);
  expect(document.library.definitions[0].program.nodes).toHaveLength(3);
  expect(
    document.library.definitions[0].program.nodes.find(
      (node: any) => node.id === "rate",
    ).params.rate,
  ).toBe(2);
  await page.screenshot({
    path: "test-results/studio-macros.png",
    fullPage: true,
  });

  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await expect(page.locator(".macro-count")).toHaveText("0 definitions");
  await page
    .getByLabel("Import macro bundle file", { exact: true })
    .setInputFiles({
      name: "Rate-limiter.bms-macro.json",
      mimeType: "application/json",
      buffer: bundle,
    });
  await expect(page.locator(".macro-count")).toHaveText("1 definition");
  await expect(page.locator(".macro-inspection")).toContainText("Slew");
  await expect(
    page.getByRole("button", { name: "Delete unused", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Delete unused", exact: true })
    .click();
  await expect(page.locator(".macro-count")).toHaveText("0 definitions");
});
