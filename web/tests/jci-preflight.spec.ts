import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");
const fixture = (expression: string) =>
  execFileSync(python, ["-c", expression], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
  });
const caf = () =>
  fixture(
    "from tests.test_jci_preflight import application; import sys; sys.stdout.buffer.write(application().original)",
  );
const hardware = () =>
  fixture(
    "from tests.test_jci_hardware import definition; import sys; sys.stdout.buffer.write(definition())",
  );
const sha = (value: Buffer) => createHash("sha256").update(value).digest("hex");

async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const original = caf();
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name: "authored-target.caf",
    mimeType: "application/octet-stream",
    buffer: original,
  });
  const panel = page.getByRole("region", {
    name: "JCI target readiness",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Run target preflight", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByRole("status", { name: "Preflight result", exact: true }),
  ).toContainText("Current report: needs-evidence");
  return { panel, original };
}

test("CAF target preflight compares inventory, hardware provenance and Bluetooth limits and exports evidence", async ({
  page,
}) => {
  const { panel, original } = await open(page);
  await expect(panel).toContainText("Appl SW Version: 10.2");
  await expect(panel).toContainText("Recorded firmware: 6.2");
  await panel
    .getByLabel("Target controller model", { exact: true })
    .fill("MS-VMA1630-0");
  await panel
    .getByLabel("Target controller firmware", { exact: true })
    .fill("6.2");
  await panel
    .getByLabel("Planned connection", { exact: true })
    .selectOption("btcvt");
  const xml = hardware();
  await panel
    .getByLabel("JCI preflight hardware XML", { exact: true })
    .setInputFiles({
      name: "authored-hardware.xml",
      mimeType: "application/xml",
      buffer: xml,
    });
  await expect(panel).toContainText("Attached: authored-hardware.xml");
  const inventory = JSON.parse(
    fixture(
      "from tests.test_jci_preflight import inventory; import json; print(json.dumps(inventory()))",
    ).toString(),
  );
  inventory.toolchain.version = "18.0.2.6";
  inventory.hardware_definition_sha256 = sha(xml);
  const text = JSON.stringify(inventory, null, 2) + "\n";
  await panel.getByLabel("JCI inventory JSON", { exact: true }).setInputFiles({
    name: "authored-inventory.json",
    mimeType: "application/json",
    buffer: Buffer.from(text),
  });
  await panel
    .getByRole("button", { name: "Run target preflight", exact: true })
    .click();
  await expect(
    panel.getByRole("status", { name: "Preflight result", exact: true }),
  ).toContainText("Current report: blocked");
  await panel.getByText(/^Review readiness checks/).click();
  const row = (name: string) =>
    panel
      .locator("tbody tr")
      .filter({ has: page.getByText(name, { exact: true }) });
  await expect(row("Controller model")).toContainText("match");
  await expect(row("Controller firmware")).toContainText("match");
  await expect(row("BTCVT tool restriction")).toContainText("blocked");
  await expect(row("BTCVT firmware restriction")).toContainText("match");
  await expect(row("Native hardware definition hash")).toContainText("match");
  await expect(
    row("Validated native compiler/transfer integration"),
  ).toContainText("unknown");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Export target readiness report",
      exact: true,
    })
    .click();
  const exported = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  expect(exported.can_deploy).toBe(false);
  expect(exported.source.caf_sha256).toBe(sha(original));
  expect(exported.source.inventory_text).toBe(text);
  expect(exported.source.inventory_utf8_sha256).toBe(sha(Buffer.from(text)));
  expect(exported.source.hardware.sha256).toBe(sha(xml));
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await panel
    .getByLabel("Target controller model", { exact: true })
    .fill("FX-PCV1630-0");
  await expect(
    panel.getByRole("button", {
      name: "Export target readiness report",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(panel).toContainText("Inputs changed. Run preflight");
  await panel
    .getByRole("button", { name: "Run target preflight", exact: true })
    .click();
  await expect(row("Controller model")).toContainText("blocked");
  await page.screenshot({
    path: "test-results/jci-target-preflight.png",
    fullPage: true,
  });
});

test("inventory template stays unknown and invalid inventory cannot replace checked evidence", async ({
  page,
}) => {
  const { panel } = await open(page);
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download inventory template", exact: true })
    .click();
  const template = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  expect(template.toolchain.installed).toBeNull();
  expect(template.packages[0].license_status).toBe("unknown");
  await panel.getByLabel("JCI inventory JSON", { exact: true }).setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from('{"toolchain":{"installed":"true"}}'),
  });
  await panel
    .getByRole("button", { name: "Run target preflight", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("valid boolean");
  await expect(
    panel.getByRole("button", {
      name: "Export target readiness report",
      exact: true,
    }),
  ).toBeDisabled();
  await panel.getByLabel("JCI inventory JSON", { exact: true }).setInputFiles({
    name: "not-utf8.json",
    mimeType: "application/json",
    buffer: Buffer.from([0xff, 0xfe, 0xfd]),
  });
  await expect(panel.getByRole("alert")).toContainText("readable UTF-8");
});
