import { test, expect, type Page, type Locator } from "./simulationFixture";
import { readFileSync } from "node:fs";

async function add(page: Page, title: string) {
  await page
    .getByRole("button", {
      name: new RegExp(`^[A-Z] ${title} (source|[0-9]+ inputs)$`),
    })
    .click();
  return page
    .locator(".inspector")
    .getByLabel("Identifier", { exact: true })
    .inputValue();
}
async function wire(page: Page, source: string, target: string, port: string) {
  const from = page.locator(
    `.react-flow__node[data-id="${source}"] .react-flow__handle[data-handleid="out"]`,
  );
  const to = page.locator(
    `.react-flow__node[data-id="${target}"] .react-flow__handle[data-handleid="${port}"]`,
  );
  const before = await page.locator(".react-flow__edge").count();
  const a = await from.boundingBox(),
    b = await to.boundingBox();
  expect(a).not.toBeNull();
  expect(b).not.toBeNull();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, {
    steps: 15,
  });
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(before + 1);
}
function parameter(inspector: Locator, key: string) {
  return inspector
    .locator("label")
    .filter({ hasText: new RegExp(`^${key}$`) })
    .locator("input");
}

test("palette creates explicit quantities with units/help, wires a difference and exports executable formats", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  const inspector = page.locator(".inspector");
  await add(page, "Temperature difference conversion");
  await expect(
    inspector.getByLabel("Engineering units", { exact: true }),
  ).toHaveValue("delta-degC");
  await parameter(inspector, "to").fill("delta-K");
  await expect(
    inspector.getByLabel("Engineering units", { exact: true }),
  ).toHaveValue("delta-K");
  await expect(inspector).toContainText("Zero stays zero");
  await add(page, "Temperature offset");
  await parameter(inspector, "unit").fill("degC");
  await expect(
    inspector.getByLabel("Engineering units", { exact: true }),
  ).toHaveValue("degC");
  await expect(inspector).toContainText(
    "difference is scaled without an absolute offset",
  );
  await page.getByRole("button", { name: "New program", exact: true }).click();
  const supply = await add(page, "Constant");
  await inspector.getByLabel("Engineering units", { exact: true }).fill("degF");
  await parameter(inspector, "value").fill("86");
  const returned = await add(page, "Constant");
  await inspector.getByLabel("Engineering units", { exact: true }).fill("degF");
  await parameter(inspector, "value").fill("68");
  const difference = await add(page, "Temperature difference");
  await expect(
    inspector.getByLabel("Engineering units", { exact: true }),
  ).toHaveValue("delta-degF");
  await expect(inspector).toContainText("a minus b");
  const out = await add(page, "Output");
  await inspector
    .getByLabel("Engineering units", { exact: true })
    .fill("delta-degF");
  await inspector
    .getByLabel("Label", { exact: true })
    .fill("Temperature change");
  await page.getByTitle("Fit view", { exact: true }).click();
  await page.waitForTimeout(300);
  await wire(page, supply, difference, "a");
  await wire(page, returned, difference, "b");
  await wire(page, difference, out, "in");
  await expect(page.locator(".validation-bar")).toContainText(
    "Graph checks passed",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText(
    "Temperature change: 18",
  );
  await expect(page.locator(".trend-legend")).toContainText("delta-degF");
  for (const format of [
    "json",
    "st",
    "plcopen",
    "graphml",
    "temco-bas",
    "bog",
  ]) {
    await page
      .getByLabel("Export format", { exact: true })
      .selectOption(format);
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const file = await pending;
    const bytes = readFileSync((await file.path())!);
    expect(bytes.length).toBeGreaterThan(100);
    if (format === "json") {
      const p = JSON.parse(bytes.toString());
      expect(
        p.nodes.find((n: any) => n.kind === "TemperatureDifference").unit,
      ).toBe("delta-degF");
    }
    if (format === "bog") expect(bytes.subarray(0, 2).toString()).toBe("PK");
  }
});

test("authored quantity chain simulates negative changes, retains quality faults and reopens typed exports", async ({
  page,
}) => {
  const program = {
    id: "temperature-browser",
    name: "Explicit temperature quantities",
    nodes: [
      {
        id: "a",
        kind: "Input",
        unit: "degF",
        params: { default: 86 },
        x: 0,
        y: 0,
      },
      {
        id: "b",
        kind: "Input",
        unit: "degF",
        params: { default: 68 },
        x: 0,
        y: 200,
      },
      {
        id: "base",
        kind: "Input",
        unit: "degC",
        params: { default: 20 },
        x: 0,
        y: 400,
      },
      {
        id: "difference",
        kind: "TemperatureDifference",
        unit: "delta-degF",
        params: { unit: "degF" },
        x: 280,
        y: 0,
      },
      {
        id: "delta",
        kind: "DeltaConvert",
        unit: "delta-degC",
        params: { from: "delta-degF", to: "delta-degC" },
        x: 560,
        y: 0,
      },
      {
        id: "offset",
        kind: "TemperatureOffset",
        unit: "degC",
        params: { unit: "degC", difference_unit: "delta-degC" },
        x: 840,
        y: 100,
      },
      { id: "absolute", kind: "Output", unit: "degC", x: 1120, y: 100 },
      { id: "change", kind: "Output", unit: "delta-degC", x: 1120, y: 300 },
    ],
    edges: [
      { id: "a", source: "a", target: "difference", target_port: "a" },
      { id: "b", source: "b", target: "difference", target_port: "b" },
      { id: "d", source: "difference", target: "delta" },
      { id: "base", source: "base", target: "offset", target_port: "base" },
      {
        id: "delta",
        source: "delta",
        target: "offset",
        target_port: "difference",
      },
      { id: "absolute", source: "offset", target: "absolute" },
      { id: "change", source: "delta", target: "change" },
    ],
  };
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "temperature.bms.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(program)),
  });
  await expect(page.locator(".validation-bar")).toContainText(
    "Graph checks passed",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("absolute: 30");
  await expect(page.locator(".trend-legend")).toContainText("change: 10");
  await page.getByLabel("Simulate a", { exact: true }).fill("32");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("absolute: 0");
  await expect(page.locator(".trend-legend")).toContainText("change: -20");
  await page
    .getByLabel("Quality a", { exact: true })
    .selectOption("open-circuit");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".simulation")).toContainText("open-circuit");
  await expect(page.locator(".elapsed")).toHaveText("2.0 s");
  await page.getByLabel("Quality a", { exact: true }).selectOption("good");
  await page.getByLabel("Export format", { exact: true }).selectOption("st");
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await pending;
  const bytes = readFileSync((await file.path())!);
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "temperature.st",
    mimeType: "text/plain",
    buffer: bytes,
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(8);
  await expect(
    page.locator('.react-flow__node[data-id="delta"]'),
  ).toContainText("delta-degC");
  await page.getByLabel("Simulate a", { exact: true }).fill("86");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("absolute: 30");
});
