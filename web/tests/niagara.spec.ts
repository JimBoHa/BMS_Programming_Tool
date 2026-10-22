import { test, expect } from "./simulationFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");
function fixture(expression: string) {
  return execFileSync(python, ["-c", expression], { cwd: root });
}

test("native Niagara BOG export and import retain the editable graph", async ({
  page,
}) => {
  await page.goto("/");
  const source = fixture(
    "from tests.test_native_format_api import primitive; print(primitive().model_dump_json())",
  );
  const input = page.locator('input[type=file][accept*=".bog"]');
  await input.setInputFiles({
    name: "native.bms.json",
    mimeType: "application/json",
    buffer: source,
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await page.getByLabel("Export format").selectOption("bog");
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await event;
  expect(file.suggestedFilename()).toMatch(/\.bog$/);
  const content = readFileSync((await file.path())!);
  expect(content.subarray(0, 2).toString()).toBe("PK");
  await expect(
    page.getByText("Exported native Niagara BOG primitives.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
  await input.setInputFiles({
    name: "native.bog",
    mimeType: "application/zip",
    buffer: content,
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("result: 42");
});

test("foreign BOG conversion requires visible semantics review and rejects unknown native logic", async ({
  page,
}) => {
  await page.goto("/");
  const source = fixture(
    "from bms_tool.niagara import SOURCE,NiagaraArchive,export_bog; from tests.test_native_format_api import primitive; import sys; sys.stdout.buffer.write(SOURCE.sub(b'',NiagaraArchive(export_bog(primitive())).xml))",
  );
  const input = page.locator('input[type=file][accept*=".bog"]');
  await input.setInputFiles({
    name: "foreign.bog",
    mimeType: "application/xml",
    buffer: source,
  });
  const report = page.locator(".conversion-report");
  await expect(report).toBeVisible();
  await expect(report).toContainText("Niagara links update on events");
  await expect(report).toContainText("Native station/Workbench acceptance");
  await page.screenshot({
    path: "test-results/studio-niagara-review.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Close settings", exact: true })
    .click();
  const before = await page.locator(".react-flow__node").count();
  await input.setInputFiles({
    name: "unsupported.bog",
    mimeType: "application/xml",
    buffer: Buffer.from(
      source
        .toString()
        .replace("kitControl:Add", "kitControl:UnknownNativeLogic"),
    ),
  });
  await expect(
    page.getByText("No semantic Niagara mapping", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(before);
  await input.setInputFiles({
    name: "ignored-compact-status.bog",
    mimeType: "application/xml",
    buffer: Buffer.from(
      '<bajaObjectGraph version="4.0"><p h="1" n="Value" m="k=kitControl" t="k:NumericConst"><p n="out" v="7"/></p></bajaObjectGraph>',
    ),
  });
  await expect(
    page.getByText("compact scalar is ignored", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(before);
});
