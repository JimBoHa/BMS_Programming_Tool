import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
async function open(page: Page, product = "CCT", version = "18.0") {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const buffer = execFileSync(
    python,
    [
      "-c",
      "from tests.test_jci_preflight import application;import sys;sys.stdout.buffer.write(application().original)",
    ],
    { cwd: root },
  );
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name: "authored.caf",
    mimeType: "application/octet-stream",
    buffer,
  });
  const panel = page.getByRole("region", {
    name: "JCI target readiness",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Run target preflight", exact: true }),
  ).toBeEnabled();
  await panel
    .getByText("Edit toolchain and package inventory JSON", { exact: true })
    .click();
  const manifest = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from tests.test_jci_preflight import inventory;import json;print(json.dumps(inventory()))",
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  manifest.toolchain.product = product;
  manifest.toolchain.version = version;
  await panel
    .getByLabel("Inventory JSON text", { exact: true })
    .fill(JSON.stringify(manifest));
  await panel
    .getByLabel("Include documented release-rule review", { exact: true })
    .check();
  await panel
    .getByLabel("Source application tool product", { exact: true })
    .selectOption(product);
  await panel
    .getByLabel("Source application tool release", { exact: true })
    .fill("10.2");
  return { panel, manifest };
}
async function run(page: Page) {
  const panel = page.getByRole("region", {
    name: "JCI target readiness",
    exact: true,
  });
  await panel
    .getByRole("button", { name: "Run target preflight", exact: true })
    .click();
  const result = page.getByRole("region", {
    name: "Documented release-rule results",
    exact: true,
  });
  await expect(result).toBeVisible();
  return result;
}

test("review actual operation rules, separate observed version, invalidate edits and verify exported seal", async ({
  page,
}) => {
  const { panel } = await open(page);
  let result = await run(page);
  await expect(
    result
      .locator("article")
      .filter({ hasText: "cct.earlier-open-commission" }),
  ).toContainText("condition-met");
  await expect(result).toContainText("Native execution: unavailable");
  await panel
    .getByLabel("Planned native operation", { exact: true })
    .selectOption("simulate");
  await panel.getByLabel("CAF release mode", { exact: true }).fill("10.2");
  await panel
    .getByLabel("Active tool release mode", { exact: true })
    .fill("10.4");
  await expect(
    panel.getByRole("button", {
      name: "Export target readiness report",
      exact: true,
    }),
  ).toBeDisabled();
  result = await run(page);
  await expect(result.getByRole("heading", { level: 3 })).toContainText(
    "documented-conflict",
  );
  await expect(result).toContainText("Observed CAF Appl SW Version: 10.2");
  await panel
    .getByLabel("Active tool release mode", { exact: true })
    .fill("10.2");
  result = await run(page);
  await expect(result.getByRole("heading", { level: 3 })).toContainText(
    "documented-conditions-only",
  );
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Export target readiness report",
      exact: true,
    })
    .click();
  const filename = (await (await pending).path())!;
  execFileSync(
    python,
    [
      "-c",
      "import json,sys;from tests.test_jci_release_rules import verify_seal;r=json.load(open(sys.argv[1]));v=r['release_review'];verify_seal(v);assert v['source']['declarations']['operation']=='simulate';assert v['source']['declarations']['caf_release_mode']=='10.2';assert v['source']['observed_appl_sw_version']=='10.2';assert not v['can_deploy'] and not v['can_execute_native']",
      filename,
    ],
    { cwd: root },
  );
});
test("source-qualified upgrade exception and package boundary are genuine predicates", async ({
  page,
}) => {
  const { panel, manifest } = await open(page);
  await panel
    .getByLabel("Planned native operation", { exact: true })
    .selectOption("upgrade-caf");
  await panel
    .getByLabel("Source application release channel", { exact: true })
    .selectOption("alpha");
  await panel.getByLabel("CAF release mode", { exact: true }).fill("10.2");
  await panel
    .getByLabel("Active tool release mode", { exact: true })
    .fill("10.4");
  await panel
    .getByLabel("CAF device-family identifier", { exact: true })
    .fill("declared-family");
  await panel
    .getByLabel("Active mode device-family identifier", { exact: true })
    .fill("declared-family");
  let result = await run(page);
  await expect(
    result.locator("article").filter({ hasText: "cct.prerelease-upgrade" }),
  ).toContainText("alpha/beta application does not automatically upgrade");
  await expect(
    result.locator("article").filter({ hasText: "cct18.upgrade-mode-family" }),
  ).toContainText("condition-met");
  await panel
    .getByLabel("Planned native operation", { exact: true })
    .selectOption("define-hardware");
  await panel
    .getByLabel("Controller package security generation", { exact: true })
    .selectOption("pre-16-only");
  await panel
    .getByLabel("Package generation evidence", { exact: true })
    .fill("Authored package provenance; no installer execution");
  manifest.packages[0].license_status = "missing";
  await panel
    .getByLabel("Inventory JSON text", { exact: true })
    .fill(JSON.stringify(manifest));
  result = await run(page);
  await expect(
    result.locator("article").filter({ hasText: "cct16.package-security" }),
  ).toContainText("conflict");
  await expect(
    result.locator("article").filter({ hasText: "cct18.package-license" }),
  ).toContainText("conflict");
});
test("PCT historical modes never borrow CCT compatibility or future releases", async ({
  page,
}) => {
  const { panel, manifest } = await open(page, "PCT", "10.3");
  await panel
    .getByLabel("Planned native operation", { exact: true })
    .selectOption("simulate");
  await panel.getByLabel("CAF release mode", { exact: true }).fill("10.2");
  await panel
    .getByLabel("Active tool release mode", { exact: true })
    .fill("10.2");
  let result = await run(page);
  await expect(
    result.locator("article").filter({ hasText: "pct103.release-modes" }),
  ).toContainText("condition-met");
  await panel
    .getByLabel("Source application tool product", { exact: true })
    .selectOption("CCT");
  result = await run(page);
  await expect(
    result.locator("article").filter({ hasText: "pct-cct.not-equivalent" }),
  ).toContainText("unknown");
  manifest.toolchain.product = "CCT";
  manifest.toolchain.version = "19.0";
  await panel
    .getByLabel("Inventory JSON text", { exact: true })
    .fill(JSON.stringify(manifest));
  result = await run(page);
  await expect(
    result.locator("article").filter({ hasText: "cct18.mode-operation" }),
  ).toContainText("unknown");
});
for (const mode of [
  "wrong-caf",
  "wrong-operation",
  "wrong-ruleset",
  "bad-shape",
]) {
  test(`reject ${mode} response and clear previous evidence`, async ({
    page,
  }) => {
    await open(page);
    await run(page);
    await page.route("**/api/caf/*/preflight", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      const response = await route.fetch(),
        value = await response.json();
      if (mode === "wrong-caf")
        value.release_review.source.caf_sha256 = "0".repeat(64);
      if (mode === "wrong-operation")
        value.release_review.source.declarations.operation =
          "transfer-to-device";
      if (mode === "wrong-ruleset")
        value.release_review.ruleset_sha256 = "0".repeat(64);
      if (mode === "bad-shape") value.release_review.findings = [{}];
      await route.fulfill({ response, json: value });
    });
    await page
      .getByRole("button", { name: "Run target preflight", exact: true })
      .click();
    await expect(
      page
        .getByRole("region", { name: "JCI target readiness", exact: true })
        .getByRole("alert"),
    ).toContainText("does not match this exact request");
    await expect(
      page.getByRole("region", {
        name: "Documented release-rule results",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: "Export target readiness report",
        exact: true,
      }),
    ).toBeDisabled();
  });
}
test("hidden CAF workspace retires delayed review and cannot revive it on return", async ({
  page,
}) => {
  await open(page);
  let seen!: () => void, release!: () => void, done!: () => void;
  const requested = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    completed = new Promise<void>((r) => (done = r));
  await page.route("**/api/caf/*/preflight", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
    done();
  });
  await page
    .getByRole("button", { name: "Run target preflight", exact: true })
    .click();
  await requested;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  release();
  await completed;
  await expect(
    page.getByRole("button", { name: "Run target preflight", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("region", {
      name: "Documented release-rule results",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Export target readiness report",
      exact: true,
    }),
  ).toBeDisabled();
});

for (const mode of ["99.0", "10.99", "18.0"]) {
  test(`matching unreviewed mode ${mode} stays unknown in UI and independently sealed export`, async ({
    page,
  }) => {
    const { panel } = await open(page);
    await panel
      .getByLabel("Planned native operation", { exact: true })
      .selectOption("simulate");
    await panel.getByLabel("CAF release mode", { exact: true }).fill(mode);
    await panel
      .getByLabel("Active tool release mode", { exact: true })
      .fill(mode);
    const result = await run(page);
    await expect(result.getByRole("heading", { level: 3 })).toContainText(
      "needs-evidence",
    );
    await expect(
      result.locator("article").filter({ hasText: "cct18.mode-operation" }),
    ).toContainText("condition-met");
    await expect(
      result
        .locator("article")
        .filter({ hasText: "cct18.mode-reference-coverage" }),
    ).toContainText("unknown");
    const pending = page.waitForEvent("download");
    await panel
      .getByRole("button", {
        name: "Export target readiness report",
        exact: true,
      })
      .click();
    const filename = (await (await pending).path())!;
    execFileSync(
      python,
      [
        "-c",
        "import json,sys;from tests.test_jci_release_rules import verify_seal;r=json.load(open(sys.argv[1]));v=r['release_review'];verify_seal(v);assert v['source']['declarations']['caf_release_mode']==sys.argv[2];assert v['source']['declarations']['active_release_mode']==sys.argv[2];assert v['source']['declarations']['operation']=='simulate';assert v['source']['destination_tool']['version']=='18.0';assert v['source']['observed_appl_sw_version']=='10.2';assert v['status']=='needs-evidence';assert v['source']['caf_sha256']==r['source']['caf_sha256'];assert {f['rule_id']:f['status'] for f in v['findings']}['cct18.mode-reference-coverage']=='unknown';assert not v['can_deploy'] and not v['can_execute_native']",
        filename,
        mode,
      ],
      { cwd: root },
    );
  });
}
