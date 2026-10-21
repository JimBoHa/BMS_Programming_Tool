import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const program = {
  schema_version: 1,
  id: "conversion-browser",
  name: "OA sample",
  description: "",
  revision: 0,
  scan_seconds: 1,
  target: {
    family: "universal-runtime",
    model: "",
    firmware: "",
    release_mode: "",
    max_nodes: 2000,
    physical_inputs: null,
    physical_outputs: null,
  },
  nodes: [
    {
      id: "sensor",
      kind: "Input",
      label: "OA temperature",
      x: 0,
      y: 0,
      params: { default: 12.5 },
      unit: "degC",
      value_type: "number",
    },
    {
      id: "out",
      kind: "Output",
      label: "Output",
      x: 250,
      y: 0,
      params: {},
      unit: "degC",
      value_type: "number",
    },
  ],
  edges: [
    {
      id: "wire",
      source: "sensor",
      target: "out",
      source_port: "out",
      target_port: "in",
    },
  ],
  metadata: {},
};

async function load(page: Page) {
  await page.goto("/");
  await page.locator('input[type="file"][accept*=".graphml"]').setInputFiles({
    name: "conversion-browser.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(program)),
  });
  await expect(
    page.locator('.react-flow__node[data-id="sensor"]'),
  ).toBeVisible();
}

async function editSource(page: Page, label: string) {
  await page.locator('.react-flow__node[data-id="sensor"]').click();
  await page
    .locator(".inspector")
    .getByLabel("Label", { exact: true })
    .fill(label);
}

test("conversion review uses actual encoders, exports evidence and invalidates after edits", async ({
  page,
}) => {
  await load(page);
  const review = page.getByRole("region", { name: "Conversion review" });
  await review
    .getByRole("button", { name: "Review conversion formats" })
    .click();
  await expect(review.locator('tr[data-format="st"]')).toContainText(
    "source-generated",
  );
  await expect(review.locator('tr[data-format="st"]')).toContainText(
    "Exact project digest",
  );
  await expect(review.locator('tr[data-format="temco-bas"]')).toContainText(
    "Authoring fields changed:",
  );
  await expect(review.locator('tr[data-format="jci-caf"]')).toContainText(
    "no-verified-encoder",
  );
  await review
    .locator('tr[data-format="st"]')
    .getByText("Differences and requirements", { exact: true })
    .click();
  await expect(review.locator('tr[data-format="st"]')).toContainText(
    "32-bit precision",
  );
  const download = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Export conversion report" })
    .click();
  const file = await download;
  const report = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(report.targets).toHaveLength(10);
  expect(
    report.targets.find((t: any) => t.format === "jci-caf").artifact,
  ).toBeNull();
  expect(
    report.targets.find((t: any) => t.format === "sedona").native_compilation,
  ).toBe("not-run");
  await editSource(page, "Revised OA sensor");
  await expect(
    review.getByText("Program changed. Review the current source again."),
  ).toBeVisible();
  await expect(
    review.getByRole("button", { name: "Export conversion report" }),
  ).toHaveCount(0);
  await review
    .getByRole("button", { name: "Review conversion formats" })
    .click();
  await expect(review.getByText("Source SHA-256:")).toBeVisible();
  await expect(review.locator("code").first()).not.toHaveText(
    report.program.sha256,
  );
  const state = await (await page.request.get("/api/session")).json();
  expect(state.field_network_open).toBe(false);
});

test("a late conversion response cannot label an edited source", async ({
  page,
}) => {
  await load(page);
  let release!: () => void;
  let arrived!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  await page.route("**/api/conversion/preview", async (route) => {
    const response = await route.fetch();
    arrived();
    await held;
    await route.fulfill({ response });
  });
  const review = page.getByRole("region", { name: "Conversion review" });
  await review
    .getByRole("button", { name: "Review conversion formats" })
    .click();
  await received;
  await editSource(page, "Edited while checking");
  release();
  await expect(
    review.getByRole("button", { name: "Review conversion formats" }),
  ).toBeEnabled();
  await expect(review.locator("tbody")).toHaveCount(0);
  await expect(
    review.getByText("Program changed. Review the current source again."),
  ).toBeVisible();
});
