import { test, expect, type Page, type TestInfo } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const profile = "studio-iec-symbols/1";
const hash = (bytes: Buffer | string) =>
  createHash("sha256").update(bytes).digest("hex");
const canonical = (value: any): string => {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + canonical(value[key]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
};
const nodes = [
  { id: "x", kind: "Input", unit: "degC", params: { default: 12.5 } },
  { id: "x_valid", kind: "Output", unit: "degC" },
  { id: "a-b", kind: "Input", params: { default: 3 } },
  { id: "a_b", kind: "Output" },
  {
    id: "Case",
    kind: "Input",
    value_type: "boolean",
    params: { default: true },
  },
  { id: "case", kind: "Output", value_type: "boolean" },
  { id: "held", kind: "Delay", unit: "degC", params: { initial: 0 } },
  { id: "held_memory", kind: "Output", unit: "degC" },
];
const graph = (id = "symbol-browser") => ({
  id,
  name: "Compiler symbol collisions",
  scan_seconds: 1,
  nodes,
  edges: [
    ["x", "x_valid"],
    ["a-b", "a_b"],
    ["Case", "case"],
    ["x", "held"],
    ["held", "held_memory"],
  ].map(([source, target], index) => ({ id: "wire" + index, source, target })),
});
async function load(page: Page, id?: string) {
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "symbols.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(graph(id))),
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function retain(info: TestInfo, name: string, bytes: Buffer) {
  await info.attach(name, { body: bytes, contentType: "application/json" });
}
function inspectTable(table: any) {
  expect(table.profile.id).toBe(profile);
  const { sha256, ...document } = table;
  expect(hash(canonical(document))).toBe(sha256);
  expect(table.nodes.map((node: any) => node.id)).toEqual(
    nodes.map((node) => node.id).sort(),
  );
  const byId = Object.fromEntries(
    table.nodes.map((node: any) => [node.id, node]),
  );
  expect(byId.x.roles.valid.symbol).not.toBe(byId.x_valid.roles.value.symbol);
  expect(byId["a-b"].roles.value.symbol).not.toBe(byId.a_b.roles.value.symbol);
  expect(byId.Case.roles.value.symbol.toLowerCase()).not.toBe(
    byId.case.roles.value.symbol.toLowerCase(),
  );
  expect(byId.held.roles.memory.symbol).not.toBe(
    byId.held_memory.roles.value.symbol,
  );
  expect(byId.held.roles.memory.state_label).toBe("n_held_memory");
  const names = [
    ...table.globals.map((row: any) => row.symbol),
    ...table.nodes.flatMap((node: any) =>
      Object.values(node.roles).map((row: any) => row.symbol),
    ),
  ];
  expect(new Set(names.map((name) => name.toLowerCase())).size).toBe(
    names.length,
  );
}

test("colliding graph names compile and verify with original evidence and stale-result clearing", async ({
  page,
}, info) => {
  // Retain the browser's actual Response clone. The initial Chromium protocol
  // observation returned an empty body despite a rendered successful response.
  // This observer adds work; it never sends, changes or repeats a request.
  await page.addInitScript(() => {
    const state = window as typeof window & {
      __iecOriginalBodies?: Record<string, { status: number; bytes: number[] }>;
    };
    state.__iecOriginalBodies = {};
    const fetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await fetch(...args);
      const path = new URL(response.url).pathname;
      if (["/api/iec/compile", "/api/iec/verify"].includes(path)) {
        void response.clone().arrayBuffer().then((buffer) => {
          state.__iecOriginalBodies![path] = {
            status: response.status,
            bytes: Array.from(new Uint8Array(buffer)),
          };
        });
      }
      return response;
    };
  });
  async function originalBody(path: string) {
    await page.waitForFunction((path) => (window as any).__iecOriginalBodies[path], path);
    const observed = await page.evaluate((path) => (window as any).__iecOriginalBodies[path], path);
    expect(observed.status).toBe(200);
    return Buffer.from(observed.bytes);
  }
  await load(page);
  await page.getByRole("button", { name: "IEC native", exact: true }).click();
  await expect(
    page.getByText("MatIEC compiler available", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Compiler provenance and scope", { exact: true })
    .click();
  await expect(page.locator("details[open]")).toContainText(profile);
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/iec/compile") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Compile native IEC", exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const original = await originalBody("/api/iec/compile"),
    compiled = JSON.parse(original.toString());
  expect(original.length).toBe(Number(response.headers()["content-length"]));
  await retain(info, "original-compile-response", original);
  inspectTable(compiled.symbol_table);
  // Native compilation deliberately omits the editable export's embedded IR.
  for (const node of compiled.symbol_table.nodes)
    for (const role of Object.values(node.roles) as { symbol: string }[])
      expect(compiled.source_st).toContain(role.symbol + " :");
  const mapping = page.getByRole("region", {
    name: "IEC symbol mapping",
    exact: true,
  });
  await expect(mapping).toContainText(compiled.symbol_table.sha256);
  await mapping
    .getByText("Show allocated compiler names", { exact: true })
    .click();
  await expect(mapping.locator("tbody")).toContainText("held_memory");
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download compilation evidence", exact: true })
    .click();
  const downloaded = readFileSync((await (await pending).path())!);
  expect(downloaded.equals(original)).toBe(true);
  await retain(info, "original-compile-download", downloaded);
  await page.getByLabel("IEC scan count", { exact: true }).fill("3");
  const verifiedPromise = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/iec/verify") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run IEC verification", exact: true })
    .click();
  const verifiedResponse = await verifiedPromise;
  expect(verifiedResponse.status()).toBe(200);
  const verifiedRaw = await originalBody("/api/iec/verify"),
    verified = JSON.parse(verifiedRaw.toString());
  await retain(info, "original-verification-response", verifiedRaw);
  inspectTable(verified.symbol_table);
  expect(verified.symbol_table).toEqual(compiled.symbol_table);
  expect(verified.program_sha256).toBe(compiled.program_sha256);
  expect(verified.matches_reference).toBe(true);
  expect(verified.rows.map((row: any) => row.outputs)).toEqual(
    [0, 12.5, 12.5].map((held) => ({
      x_valid: 12.5,
      a_b: 3,
      case: true,
      held_memory: held,
    })),
  );
  expect(
    verified.rows.every((row: any) => row.matches_reference && !row.fault),
  ).toBe(true);
  const tracePending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download full IEC trace", exact: true })
    .click();
  const traceDownload = readFileSync((await (await tracePending).path())!);
  expect(traceDownload.equals(verifiedRaw)).toBe(true);
  await retain(info, "original-verification-download", traceDownload);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page
    .locator('input[type=file][accept*=".st"]')
    .setInputFiles({
      name: "replacement.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(graph("replacement"))),
    });
  await expect(page.locator(".toast")).toContainText("Imported as a new local project");
  await page.getByRole("button", { name: "IEC native", exact: true }).click();
  await expect(mapping).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Compiled IEC artifacts", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "IEC verification results", exact: true }),
  ).toHaveCount(0);
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("conversion review exposes IEC symbol provenance without changing Sedona policy", async ({
  page,
}, info) => {
  await load(page);
  const review = page.getByRole("region", {
    name: "Conversion review",
    exact: true,
  });
  const responsePromise = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/conversion/preview") &&
      r.request().method() === "POST",
  );
  await review
    .getByRole("button", { name: "Review conversion formats", exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const raw = await response.body(),
    document = JSON.parse(raw.toString());
  await retain(info, "original-conversion-preview", raw);
  for (const format of ["st", "plcopen"]) {
    const target = document.targets.find((row: any) => row.format === format);
    expect(target.symbol_generator.id).toBe(profile);
    expect(target.editable_round_trip.exact).toBe(true);
    const row = review.locator(`tr[data-format="${format}"]`);
    await expect(row).toContainText(profile);
    await row
      .getByText("Differences and requirements", { exact: true })
      .click();
    await expect(row).toContainText(target.symbol_generator.rules_sha256);
  }
  expect(
    document.targets.find((row: any) => row.format === "sedona")
      .symbol_generator,
  ).toBeUndefined();
  await expect(review.locator('tr[data-format="sedona"]')).not.toContainText(
    "Symbol profile:",
  );
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
