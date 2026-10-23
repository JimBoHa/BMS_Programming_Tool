import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");
const profile = "studio-literals/2";
const rules =
  "be014ca51c1d3e42538d607d698b8ddacd164b2e0ddfb821c433329b99050493";

async function loadMidpoint(page: Page) {
  const program = execFileSync(
    python,
    [
      "-c",
      "import math; from tests.test_executable_numbers import passthrough; print(passthrough(value=math.nextafter(1.0+2**-24, math.inf), kind='Constant').model_dump_json())",
    ],
    { cwd: root },
  );
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "literal-midpoint.json",
    mimeType: "application/json",
    buffer: program,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}

test("profile review and actual ST/XML downloads retain source identity", async ({
  page,
}) => {
  await loadMidpoint(page);
  const review = page.getByRole("region", { name: "Conversion review" });
  await review
    .getByRole("button", { name: "Review conversion formats" })
    .click();
  await expect(review.locator('tr[data-format="st"]')).toContainText(profile);
  const sourceHash = await review.locator("code").first().textContent();
  expect(sourceHash).toMatch(/^[0-9a-f]{64}$/);
  for (const format of ["st", "plcopen", "sedona"]) {
    const row = review.locator(`tr[data-format="${format}"]`);
    await expect(row).toContainText(profile);
    await row
      .getByText("Differences and requirements", { exact: true })
      .click();
    await expect(row).toContainText(rules);
  }
  for (const format of ["json", "graphml", "bog"]) {
    await expect(
      review.locator(`tr[data-format="${format}"]`),
    ).not.toContainText("Literal profile");
  }
  for (const [format, filename] of [
    ["st", "download.st"],
    ["plcopen", "download.xml"],
  ]) {
    await page
      .getByLabel("Export format", { exact: true })
      .selectOption(format);
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const downloaded = await pending;
    const bytes = readFileSync((await downloaded.path())!);
    expect(bytes.toString()).toContain("1.000000059604645");
    const digest = execFileSync(
      python,
      [
        "-c",
        "import sys; from bms_tool.formats import import_program; print(import_program(sys.stdin.buffer.read(),sys.argv[1]).digest())",
        filename,
      ],
      { cwd: root, input: bytes },
    )
      .toString()
      .trim();
    expect(digest).toBe(sourceHash);
    if (format === "st") expect(bytes.toString()).toContain("BMS_STUDIO_IR_V3");
    else expect(bytes.toString()).toContain(`sourceProfile="${profile}"`);
  }
  await page.screenshot({
    path: "test-results/literal-profile-review.png",
    fullPage: true,
  });
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("owned native compiler and simulator show actual literal provenance", async ({
  page,
}) => {
  test.setTimeout(60000);
  await loadMidpoint(page);
  await page.getByRole("button", { name: "IEC native", exact: true }).click();
  await page
    .getByText("Compiler provenance and scope", { exact: true })
    .click();
  await expect(
    page.getByText("Literal profile:", { exact: false }),
  ).toContainText(profile);
  await expect(page.locator("details[open]")).toContainText(rules);
  await page.getByRole("button", { name: "Native sim", exact: true }).click();
  try {
    await page
      .getByRole("button", { name: "Compile and start", exact: true })
      .click();
    const toolbar = page.locator(".native-toolbar").filter({
      has: page.getByRole("button", { name: "Compile and start", exact: true }),
    });
    await expect(toolbar).toContainText(profile);
    await toolbar.getByText("Literal rules SHA-256", { exact: true }).click();
    await expect(toolbar).toContainText(rules);
    await page
      .getByRole("button", { name: "Step native controller", exact: true })
      .click();
    await expect(page.locator(".native-trace tbody")).toContainText("Match");
    const status = await (await page.request.get("/api/native/status")).json();
    expect(status.source_generator).toEqual({
      id: profile,
      rules_sha256: rules,
    });
    const value = status.history.at(-1).outputs.out;
    const encoded = Buffer.alloc(4);
    encoded.writeFloatBE(value);
    expect(encoded.toString("hex")).toBe("3f800001");
    await page.screenshot({
      path: "test-results/literal-profile-native.png",
      fullPage: true,
    });
  } finally {
    const session = await (await page.request.get("/api/session")).json();
    await page.request.post("/api/native/stop", {
      headers: { "X-Studio-Token": session.token },
      data: {},
    });
    expect(session.field_network_open).toBe(false);
  }
});
