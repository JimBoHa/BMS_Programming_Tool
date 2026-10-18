import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("simulation runs real blocks and refuses open-circuit inputs", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Step simulation" }),
  ).toBeVisible();
  await page.getByLabel("Simulate zone", { exact: true }).fill("80");
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await expect(page.locator(".trend-legend")).toContainText(
    "Damper command: 100",
  );
  await page
    .getByLabel("Quality zone", { exact: true })
    .selectOption("open-circuit");
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".simulation .inline-error")).toContainText(
    "open-circuit",
  );
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await page.screenshot({
    path: "test-results/studio-editor.png",
    fullPage: true,
  });
});

test("drag blocks, wire pins, edit values and undo", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  const before = await page.locator(".react-flow__node").count();
  const constant = page
    .locator(".palette-block")
    .filter({ hasText: "Constant" });
  await constant.dragTo(page.locator(".canvas"), {
    targetPosition: { x: 220, y: 180 },
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(before + 1);
  await page.locator(".palette-block").filter({ hasText: "Output" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^value$/ })
    .locator("input")
    .fill("37.5");
  const source = page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .locator(".react-flow__handle-right");
  const target = page
    .locator(".react-flow__node")
    .filter({ hasText: "Output" })
    .locator(".react-flow__handle-left");
  const s = await source.boundingBox(),
    t = await target.boundingBox();
  await page.mouse.move(s!.x + s!.width / 2, s!.y + s!.height / 2);
  await page.mouse.down();
  await page.mouse.move(t!.x + t!.width / 2, t!.y + t!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".trend-legend")).not.toBeEmpty();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
});

test("save, export and import a graph through the GUI", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Program name")).toBeVisible();
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-inline-reheat");
  await page
    .getByLabel("Program name")
    .fill("Browser acceptance " + Date.now());
  await page.getByRole("button", { name: "Save revision" }).click();
  await expect(page.locator(".toast")).toContainText("Saved revision 1");
  await page.getByLabel("Export format").selectOption("plcopen");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await downloadEvent;
  await expect(file.suggestedFilename()).toMatch(/\.xml$/);
  const saved = await file.path();
  expect(saved).toBeTruthy();
  await page
    .locator('input[type=file][accept=".json,.st,.xml,.graphml"]')
    .setInputFiles({
      name: "program.xml",
      mimeType: "application/xml",
      buffer: execFileSync("/bin/cat", [saved!]),
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(8);
});

test("inspect and patch a synthetic CAF without changing its model", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_formats_caf import make_caf; import sys; sys.stdout.buffer.write(make_caf())",
    ],
    { cwd: root },
  );
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name: "synthetic.caf",
    mimeType: "application/octet-stream",
    buffer,
  });
  await expect(page.locator(".stat-grid")).toContainText("MS-VMA1630-0");
  await page.getByRole("row").filter({ hasText: "Example" }).click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("75");
  await expect(page.locator(".export-strip")).toContainText(
    "1 proposed scalar changes",
  );
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CAF copy" }).click();
  expect((await event).suggestedFilename()).toBe("edited-copy.caf");
  await page.screenshot({
    path: "test-results/studio-caf.png",
    fullPage: true,
  });
});

test("apply an online sandbox revision and roll back", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Runtime", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate and preview deployment" })
    .click();
  await page.getByRole("button", { name: "Apply to sandbox runtime" }).click();
  await expect(page.locator(".stat-grid")).toContainText("Cooling Only");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator(".palette-block").filter({ hasText: /Input/ }).click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^Label$/ })
    .locator("input")
    .fill("Unused test input");
  await page.getByRole("button", { name: "Runtime", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate and preview deployment" })
    .click();
  await expect(page.locator(".diff-summary")).toContainText("+1 added");
  await page.getByRole("button", { name: "Apply to sandbox runtime" }).click();
  await expect(
    page.getByRole("button", { name: "Roll back" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Roll back" }).last().click();
  const state = await page.request.get("/api/runtime");
  expect((await state.json()).program.nodes).toHaveLength(5);
  await page.screenshot({
    path: "test-results/studio-runtime.png",
    fullPage: true,
  });
});

test("capabilities disclose native and hardware gaps", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reference", exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "Native vendor formats" }),
  ).toContainText("pending");
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "BTCVT Bluetooth and direct MS/TP" }),
  ).toContainText("pending");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.locator(".connection-badge")).toContainText(
    "No BACnet interface open",
  );
  await expect(
    page.getByText("ADAPTER REQUIRED", { exact: true }),
  ).toBeVisible();
});
