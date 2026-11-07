import {
  test,
  expect,
  simulationServerResponseJSON,
  type Page,
} from "./simulationFixture";
import { sourceStringify } from "../src/programSource";
import {
  sourceFixtureData,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
const title = "Declared VAV guard browser project";
const dialogFor = (page: Page) =>
  page.getByRole("dialog", {
    name: "Equipment and sequence wizard",
    exact: true,
  });
const guardFor = (page: Page) =>
  dialogFor(page).getByLabel("VAV runtime setpoint guard", { exact: true });
async function parameters(
  page: Page,
  family = "parallel-fan-reheat",
  caf = false,
) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "guard-source.caf",
      mimeType: "application/octet-stream",
      buffer: execFileSync(
        python,
        [
          "-c",
          "from tests.test_caf_graph import make_graph;import sys;sys.stdout.buffer.write(make_graph())",
        ],
        { cwd: root },
      ),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("guard-source.caf");
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTool(page, "Graph editor");
  } else {
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  }
  await page
    .getByLabel("Choose VAV template", { exact: true })
    .selectOption({ index: 1 });
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Preserved local graph draft");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  const dialog = dialogFor(page);
  await dialog.getByLabel("Wizard project name", { exact: true }).fill(title);
  await dialog
    .getByLabel("VAV equipment", { exact: true })
    .selectOption(family);
  await dialog
    .getByLabel("Declared controller family", { exact: true })
    .selectOption(caf ? "johnson-fx" : "johnson-metasys");
  await dialog
    .getByLabel("Declared controller model", { exact: true })
    .fill(caf ? "FX-PCV1630-0" : "VMA1630-0");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  return dialog;
}
async function enable(page: Page) {
  const dialog = dialogFor(page),
    guard = guardFor(page);
  await guard.locator(":scope > summary").click();
  await expect(guard.getByRole("checkbox")).not.toBeChecked();
  await guard.getByRole("checkbox").check();
  await expect(
    guard.getByLabel("Minimum permitted setpoint (degF)", { exact: true }),
  ).toHaveValue("50");
  await dialog
    .getByLabel("Cooling setpoint (degF)", { exact: true })
    .fill("73");
  await dialog
    .getByLabel("Setpoint sources", { exact: true })
    .selectOption("inputs");
  await dialog
    .getByLabel("Zone loop strategy", { exact: true })
    .selectOption("P");
  return guard;
}
async function preview(page: Page) {
  const arrived = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/equipment-wizard/preview",
  );
  await dialogFor(page)
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  const response = await arrived;
  expect(response.status()).toBe(200);
  const report = JSON.parse(
    sourceStringify(sourceFixtureData(await response.json())),
  );
  await expect(
    dialogFor(page).getByRole("region", {
      name: "Wizard preview",
      exact: true,
    }),
  ).toBeVisible();
  return report;
}
for (const family of ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
  for (const compact of [false, true])
    test(`${family} ${compact ? "compact CAF" : "desktop new"} author simulate save reopen and exact JSON export`, async ({
      page,
      request,
    }, testInfo) => {
      if (compact) await page.setViewportSize({ width: 390, height: 844 });
      const dialog = await parameters(page, family, compact);
      await enable(page);
      const report = await preview(page);
      expect(report.profile.profile).toBe(
        "studio-vav-selection-with-setpoint-guard/1",
      );
      expect(report.native_compile).toBe(false);
      expect(report.controller_writes).toBe(false);
      expect(
        report.program.metadata.equipment_wizard.setpoint_guard.choices,
      ).toEqual({ minimum: 50, maximum: 90, minimum_deadband: 5 });
      await expect(
        dialog.getByRole("region", { name: "Wizard preview", exact: true }),
      ).toContainText("Runtime setpoint guard: 50 to 90 degF");
      await expect(dialog).toContainText("no physical/native allocation");
      if (compact) {
        await page.screenshot({
          path: testInfo.outputPath("guard-preview.png"),
        });
        const box = (await dialog.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(390);
        expect(
          await dialog.evaluate(
            (element) => element.scrollWidth <= element.clientWidth,
          ),
        ).toBe(true);
      }
      page.once("dialog", (d) => d.dismiss());
      await dialog
        .getByRole("button", { name: "Create editable project", exact: true })
        .click();
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue("Preserved local graph draft");
      page.once("dialog", (d) => d.accept());
      await dialog
        .getByRole("button", { name: "Create editable project", exact: true })
        .click();
      await expect(dialog).toHaveCount(0);
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(title);
      await page.getByRole("button", { name: "Simulate", exact: true }).click();
      const stepped = page.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/simulation/step",
      );
      await page
        .getByRole("button", { name: "Step simulation", exact: true })
        .click();
      const out = simulationServerResponseJSON(await stepped).history.at(
        -1,
      ).outputs;
      expect(out.spguard_configuration_valid).toBe(true);
      expect(out.spguard_cool_permitted_output).toBe(true);
      expect(out.damper).toBeCloseTo(36, 10);
      if (family !== "cooling-only") expect(out.reheat).toBe(0);
      if (family === "parallel-fan-reheat") expect(out.fan).toBe(false);
      await page
        .getByRole("button", { name: "Save project", exact: true })
        .click();
      await expect(
        page.getByLabel("Last saved revision", { exact: true }),
      ).toContainText("r1");
      await page
        .getByLabel("Export format", { exact: true })
        .selectOption("json");
      const download = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const bytes = await readFile((await (await download).path())!);
      const exported = JSON.parse(bytes.toString());
      expect(exported.metadata).toEqual(report.program.metadata);
      expect(exported.nodes).toEqual(report.program.nodes);
      expect(exported.edges).toEqual(report.program.edges);
      expect(exported.revision).toBe(1);
      expect(exported.target.physical_inputs).toBeNull();
      const saved = await (
        await request.get("/api/projects/" + report.program.id)
      ).json();
      expect(exported).toEqual(saved);
      await chooseWorkspaceSurface(page, "Library");
      await chooseWorkspaceSurface(page, "Workspace");
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTool(page, "Graph editor");
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(title);
      await page.reload();
      await page
        .getByRole("region", { name: "Continue local work", exact: true })
        .getByRole("button", { name: "Program", exact: true })
        .click();
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(title);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });

for (const family of ["cooling-only", "inline-reheat", "parallel-fan-reheat"])
  for (const sources of ["fixed", "inputs"])
    test(`legacy ${family} ${sources} retains original authoring and simulated values`, async ({
      page,
    }) => {
      const dialog = await parameters(page, family);
      await dialog
        .getByLabel("Setpoint sources", { exact: true })
        .selectOption(sources);
      const report = await preview(page);
      expect(report.choices).not.toHaveProperty("setpoint_guard");
      expect(report.program.metadata.equipment_wizard).not.toHaveProperty(
        "setpoint_guard",
      );
      expect(report.profile.profile).toBe("studio-vav-selection/1");
      expect(
        report.program.nodes.some((n: any) => n.id.startsWith("spguard_")),
      ).toBe(false);
      page.once("dialog", (d) => d.accept());
      await dialog
        .getByRole("button", { name: "Create editable project", exact: true })
        .click();
      await page.getByRole("button", { name: "Simulate", exact: true }).click();
      const stepped = page.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/simulation/step",
      );
      await page
        .getByRole("button", { name: "Step simulation", exact: true })
        .click();
      const out = simulationServerResponseJSON(await stepped).history.at(
        -1,
      ).outputs;
      expect(out.damper).toBeCloseTo(52.16, 10);
      if (family !== "cooling-only") expect(out.reheat).toBe(0);
      if (family === "parallel-fan-reheat") expect(out.fan).toBe(false);
    });

test("nominal deadband and range errors refuse preview until the operator repairs them", async ({
  page,
}) => {
  const dialog = await parameters(page);
  await enable(page);
  for (const [label, value] of [
    ["Cooling setpoint (degF)", "72"],
    ["Minimum permitted setpoint (degF)", "80"],
  ]) {
    await dialog.getByLabel(label, { exact: true }).fill(value);
    await dialog
      .getByRole("button", { name: "Preview VAV project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable project",
        exact: true,
      }),
    ).toHaveCount(0);
    await dialog
      .getByLabel("Cooling setpoint (degF)", { exact: true })
      .fill("73");
    await guardFor(page)
      .getByLabel("Minimum permitted setpoint (degF)", { exact: true })
      .fill("50");
  }
  await preview(page);
});

test("absolute range and delta deadband convert together and return without losing source choices", async ({
  page,
}) => {
  const dialog = await parameters(page);
  await enable(page);
  await dialog
    .getByLabel("Wizard temperature units", { exact: true })
    .selectOption("degC");
  await expect(
    guardFor(page).getByLabel("Minimum permitted setpoint (degC)", {
      exact: true,
    }),
  ).toHaveValue("10");
  expect(
    Number(
      await guardFor(page)
        .getByLabel("Maximum permitted setpoint (degC)", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(290 / 9, 10);
  expect(
    Number(
      await guardFor(page)
        .getByLabel("Minimum heating/cooling deadband (delta-degC)", {
          exact: true,
        })
        .inputValue(),
    ),
  ).toBeCloseTo(25 / 9, 10);
  const report = await preview(page);
  expect(report.choices.temperature_unit).toBe("degC");
  expect(report.choices.setpoint_guard.minimum_deadband).toBeCloseTo(
    25 / 9,
    10,
  );
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog
    .getByLabel("Wizard temperature units", { exact: true })
    .selectOption("degF");
  await expect(
    guardFor(page).getByLabel("Minimum heating/cooling deadband (delta-degF)", {
      exact: true,
    }),
  ).toHaveValue("5");
});

test("disabling guard restores absent legacy choices and profile", async ({
  page,
}) => {
  await parameters(page);
  const guard = await enable(page);
  await guard.getByRole("checkbox").uncheck();
  const report = await preview(page);
  expect(report.choices).not.toHaveProperty("setpoint_guard");
  expect(report.program.metadata.equipment_wizard).not.toHaveProperty(
    "setpoint_guard",
  );
  expect(report.profile.profile).toBe("studio-vav-selection/1");
  expect(
    report.program.nodes.some((n: any) => n.id.startsWith("spguard_")),
  ).toBe(false);
});

for (const family of ["dual-duct", "fan-coil"])
  test(`${family} selection removes the single-duct guard`, async ({
    page,
  }) => {
    const dialog = await parameters(page);
    await enable(page);
    await dialog.getByRole("button", { name: "Back", exact: true }).click();
    await dialog
      .getByLabel("VAV equipment", { exact: true })
      .selectOption(family);
    await dialog
      .getByRole("button", { name: "Next: parameters", exact: true })
      .click();
    await expect(guardFor(page)).toHaveCount(0);
    await dialog.getByRole("button", { name: "Back", exact: true }).click();
    await dialog
      .getByLabel("VAV equipment", { exact: true })
      .selectOption("inline-reheat");
    await dialog
      .getByRole("button", { name: "Next: parameters", exact: true })
      .click();
    await guardFor(page).locator(":scope > summary").click();
    await expect(guardFor(page).getByRole("checkbox")).not.toBeChecked();
  });

for (const mutation of [
  "choices",
  "rules",
  "rule-seal",
  "profile",
  "authority",
])
  test(`refuse mismatched guard ${mutation} response`, async ({ page }) => {
    const dialog = await parameters(page);
    await enable(page);
    await page.route("**/api/equipment-wizard/preview", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      const guard = value.program.metadata.equipment_wizard.setpoint_guard;
      if (mutation === "choices") guard.choices.minimum = 49;
      if (mutation === "rules") guard.rules.integral = "Altered policy";
      if (mutation === "rule-seal") guard.rules_sha256 = "0".repeat(64);
      if (mutation === "profile")
        value.profile.profile = "studio-vav-selection/1";
      if (mutation === "authority") value.controller_writes = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", { name: "Preview VAV project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toContainText("does not match");
    await expect(
      dialog.getByRole("button", {
        name: "Create editable project",
        exact: true,
      }),
    ).toHaveCount(0);
  });

for (const mutation of ["missing", "bounds", "deadband", "profile"])
  test(`refuse unit conversion that changes guard ${mutation}`, async ({
    page,
  }) => {
    const dialog = await parameters(page);
    await enable(page);
    await page.route("**/api/equipment-wizard/units", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
        value = await response.json();
      if (mutation === "missing") delete value.choices.setpoint_guard;
      if (mutation === "bounds") value.choices.setpoint_guard.minimum = 0;
      if (mutation === "deadband")
        value.choices.setpoint_guard.minimum_deadband = 0;
      if (mutation === "profile") value.profile_sha256 = "0".repeat(64);
      await route.fulfill({ response, json: value });
    });
    await dialog
      .getByLabel("Wizard temperature units", { exact: true })
      .selectOption("degC");
    await expect(dialog.getByRole("alert")).toContainText(
      "Unit conversion profile does not match",
    );
    await expect(
      dialog.getByLabel("Wizard temperature units", { exact: true }),
    ).toHaveValue("degF");
    await expect(
      guardFor(page).getByLabel("Minimum permitted setpoint (degF)", {
        exact: true,
      }),
    ).toHaveValue("50");
    await expect(
      guardFor(page).getByLabel(
        "Minimum heating/cooling deadband (delta-degF)",
        { exact: true },
      ),
    ).toHaveValue("5");
  });

for (const change of ["close", "source", "reopen"])
  test(`late guarded preview cannot survive ${change} retirement`, async ({
    page,
  }) => {
    const dialog = await parameters(page);
    await enable(page);
    let seen!: () => void, release!: () => void, done!: () => void;
    const arrived = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      delivered = new Promise<void>((r) => (done = r));
    await page.route("**/api/equipment-wizard/preview", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      seen();
      await gate;
      await route.fulfill({ response });
      done();
    });
    await dialog
      .getByRole("button", { name: "Preview VAV project", exact: true })
      .click();
    await arrived;
    if (change === "close")
      await dialog
        .getByRole("button", { name: "Cancel wizard", exact: true })
        .click();
    if (change === "source")
      await page
        .getByLabel("Program name", { exact: true })
        .fill("Revised underlying source");
    if (change === "reopen") {
      await dialog
        .getByRole("button", { name: "Cancel wizard", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Equipment wizard", exact: true })
        .click();
      await expect(
        dialog.getByLabel("Wizard project name", { exact: true }),
      ).toBeVisible();
    }
    release();
    await delivered;
    await expect(
      dialog.getByRole("button", {
        name: "Create editable project",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      change === "source"
        ? "Revised underlying source"
        : "Preserved local graph draft",
    );
  });
