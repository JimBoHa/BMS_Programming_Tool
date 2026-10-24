import {
  test,
  expect,
  simulationServerResponseJSON,
  type Page,
} from "./simulationFixture";
import {
  sourceFixtureData,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
const title = "Fan-coil browser foundation";
async function parameters(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Equipment and sequence wizard",
    exact: true,
  });
  await dialog.getByLabel("Wizard project name", { exact: true }).fill(title);
  await dialog
    .getByLabel("VAV equipment", { exact: true })
    .selectOption("fan-coil");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  return dialog;
}
async function declare(
  dialog: ReturnType<Page["getByRole"]>,
  fan = "variable-speed",
  policy = "continuous-occupied",
  condensate = "none",
) {
  await dialog
    .getByLabel("Fan-coil coil arrangement", { exact: true })
    .selectOption("separate-modulating");
  await dialog
    .getByLabel("Fan-coil fan type", { exact: true })
    .selectOption(fan);
  await dialog
    .getByLabel("Fan-coil occupied fan policy", { exact: true })
    .selectOption(policy);
  await dialog
    .getByLabel("Fan-coil condensate policy", { exact: true })
    .selectOption(condensate);
}
async function preview(page: Page) {
  const dialog = page.getByRole("dialog", {
    name: "Equipment and sequence wizard",
    exact: true,
  });
  const arrived = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/equipment-wizard/preview",
  );
  await dialog
    .getByRole("button", { name: "Preview fan-coil project", exact: true })
    .click();
  const response = await arrived;
  expect(response.ok()).toBe(true);
  const envelope = await response.json(),
    report = sourceFixtureData(envelope);
  await expect(
    dialog.getByRole("region", { name: "Wizard preview", exact: true }),
  ).toBeVisible();
  return { dialog, report, envelope };
}
async function create(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", { name: "Create editable project", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
}
async function step(page: Page) {
  const arrived = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await arrived;
  expect(response.ok()).toBe(true);
  return simulationServerResponseJSON(response).history.at(-1).outputs;
}
for (const fan of ["single-speed", "variable-speed"])
  for (const policy of ["continuous-occupied", "cycle-on-demand"]) {
    test(`${fan} ${policy} creates actual editable graph, simulates, saves and exports exact source`, async ({
      page,
    }) => {
      const dialog = await parameters(page);
      await declare(dialog, fan, policy);
      const { report } = await preview(page);
      await expect(dialog).toContainText(
        "Logical portable signal; no physical/native allocation",
      );
      await expect(dialog).toContainText(
        "unoccupied setbacks/frost protection",
      );
      expect(report.choices.control).toBe("not-applicable");
      expect(report.choices.fan_coil.fan).toBe(fan);
      expect(report.profile.profile).toBe("studio-fan-coil-selection/1");
      await create(page, dialog);
      const values = await step(page);
      expect(values.cooling_valve).toBeCloseTo(40.2, 10);
      expect(values.heating_valve).toBe(0);
      expect(values.fan_enable).toBe(true);
      if (fan === "variable-speed")
        expect(values.fan_speed).toBeCloseTo(52.16, 10);
      else expect(values).not.toHaveProperty("fan_speed");
      await page
        .getByRole("button", { name: "Save revision", exact: true })
        .click();
      await expect(
        page.getByLabel("Last saved revision", { exact: true }),
      ).toContainText("r1");
      await page
        .getByLabel("Export format", { exact: true })
        .selectOption("json");
      const pending = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const file = (await (await pending).path())!;
      const proof = JSON.parse(
        execFileSync(
          python,
          [
            "-c",
            `
import json,sys
from bms_tool.models import Program
from bms_tool.engine import Engine
p=Program.model_validate(json.load(open(sys.argv[1])));w=p.metadata['equipment_wizard']
assert p.revision==1 and p.target.physical_inputs is None and p.target.physical_outputs is None
assert w['source']['pdf_pages']==[479,480,481,482,483] and not p.metadata['native_deployment_verified']
assert w['choices']['fan_coil']['fan']==sys.argv[2] and w['choices']['fan_coil']['fan_policy']==sys.argv[3]
assert 'dual_duct' not in w['choices'] and w['choices']['control']=='not-applicable'
a=Engine(p).step()['outputs'];assert abs(a['cooling_valve']-40.2)<1e-10 and a['heating_valve']==0 and a['fan_enable'] is True
n=Engine(p).step({'zone':70.0})['outputs'];assert n['cooling_valve']==n['heating_valve']==0
assert n['fan_enable'] is (sys.argv[3]=='continuous-occupied')
if sys.argv[2]=='variable-speed': assert abs(a['fan_speed']-52.16)<1e-10 and n['fan_speed']==(20 if n['fan_enable'] else 0)
else: assert 'fan_speed' not in a
p.revision=0;print(json.dumps({'program_sha256':p.digest(),'choices_sha256':w['choices_sha256'],'profile_sha256':w['profile_sha256']}))
`,
            file,
            fan,
            policy,
          ],
          { cwd: root, encoding: "utf8" },
        ),
      );
      expect(proof.program_sha256).toBe(report.program_sha256);
      expect(proof.choices_sha256).toBe(report.choices_sha256);
      expect(proof.profile_sha256).toBe(report.profile_sha256);
      await page.reload();
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(title);
      expect(
        (await (await page.request.get("/api/session")).json())
          .field_network_open,
      ).toBe(false);
    });
  }

test("fan-coil requires all four explicit selections, validates speed limits and converts only applicable temperature quantities", async ({
  page,
}) => {
  const dialog = await parameters(page);
  for (const label of [
    "Fan-coil coil arrangement",
    "Fan-coil fan type",
    "Fan-coil occupied fan policy",
    "Fan-coil condensate policy",
  ])
    await expect(dialog.getByLabel(label, { exact: true })).toHaveValue("");
  for (const label of [
    "Damper control strategy",
    "Wizard airflow units",
    "Minimum damper position (%)",
    "Fan on heat-demand threshold (%)",
  ])
    await expect(dialog.getByLabel(label, { exact: true })).toHaveCount(0);
  await dialog
    .getByRole("button", { name: "Preview fan-coil project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  await declare(dialog);
  await dialog
    .getByLabel("Minimum logical fan speed (%)", { exact: true })
    .fill("100");
  await dialog
    .getByRole("button", { name: "Preview fan-coil project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "minimum speed must be below",
  );
  await dialog
    .getByLabel("Minimum logical fan speed (%)", { exact: true })
    .fill("20");
  await dialog
    .getByLabel("Wizard temperature units", { exact: true })
    .selectOption("degC");
  await expect(
    dialog.getByLabel("Zone proportional gain (%/delta-degC)", { exact: true }),
  ).toHaveValue("36");
  await expect(
    dialog.getByLabel("Zone integral gain (%/delta-degC/s)", { exact: true }),
  ).toHaveValue("0.18");
  await expect(
    dialog.getByLabel("Minimum logical fan speed (%)", { exact: true }),
  ).toHaveValue("20");
  await dialog
    .getByLabel("Fan-coil occupied input default", { exact: true })
    .uncheck();
  await dialog
    .getByLabel("Fan-coil energy-holdoff input default", { exact: true })
    .check();
  const { report } = await preview(page);
  expect(report.choices.fan_coil.occupied_default).toBe(false);
  expect(report.choices.fan_coil.energy_holdoff_default).toBe(true);
  expect(report.choices.temperature_unit).toBe("degC");
  await create(page, dialog);
  const values = await step(page);
  expect(values.fan_enable).toBe(false);
  expect(values.cooling_valve).toBe(0);
  expect(values.heating_valve).toBe(0);
  expect(values.fan_speed).toBe(0);
});

for (const condensate of ["disable-cooling", "shutdown-unit"])
  test(`declared ${condensate} keeps logical condensate permission distinct from physical fan proof`, async ({
    page,
  }) => {
    const dialog = await parameters(page);
    await declare(dialog, "variable-speed", "continuous-occupied", condensate);
    await dialog
      .getByLabel("Fan-coil condensate-alarm input default", { exact: true })
      .check();
    await preview(page);
    await create(page, dialog);
    const cooling = await step(page);
    expect(cooling.cooling_valve).toBe(0);
    expect(cooling.fan_enable).toBe(condensate === "disable-cooling");
    expect(cooling.fan_speed).toBe(condensate === "disable-cooling" ? 20 : 0);
    await page.getByLabel("Simulate zone", { exact: true }).fill("66");
    const heating = await step(page);
    expect(heating.heating_valve).toBeCloseTo(
      condensate === "disable-cooling" ? 40.2 : 0,
      10,
    );
    await page.getByLabel("Simulate occupied", { exact: true }).uncheck();
    const off = await step(page);
    expect(off.fan_enable).toBe(false);
    expect(off.cooling_valve).toBe(0);
    expect(off.heating_valve).toBe(0);
  });

test("switching equipment removes fan-only declarations and restores unchanged dual and single-duct profiles", async ({
  page,
}) => {
  const dialog = await parameters(page);
  await declare(dialog);
  await preview(page);
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog
    .getByLabel("VAV equipment", { exact: true })
    .selectOption("dual-duct");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  await expect(
    dialog.getByRole("region", { name: "Fan-coil declarations", exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByLabel("Damper control strategy", { exact: true }),
  ).toHaveValue("position");
  await dialog
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .selectOption("none");
  let pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/equipment-wizard/preview",
  );
  await dialog
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  let report = sourceFixtureData(await (await pending).json());
  expect(report.profile.profile).toBe("studio-vav-dual-duct/1");
  expect(report.choices).not.toHaveProperty("fan_coil");
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog
    .getByLabel("VAV equipment", { exact: true })
    .selectOption("cooling-only");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/equipment-wizard/preview",
  );
  await dialog
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  report = sourceFixtureData(await (await pending).json());
  expect(report.profile.profile).toBe("studio-vav-selection/1");
  expect(report.choices).not.toHaveProperty("fan_coil");
  expect(report.choices).not.toHaveProperty("dual_duct");
});

for (const changed of ["source", "close"])
  test(`held fan preview is retired after ${changed} ownership changes`, async ({
    page,
  }) => {
    const dialog = await parameters(page);
    await declare(dialog);
    const original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
    let seen!: () => void, release!: () => void, done!: () => void;
    const requested = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      completed = new Promise<void>((r) => (done = r));
    await page.route("**/api/equipment-wizard/preview", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill({ response });
      done();
    });
    await dialog
      .getByRole("button", { name: "Preview fan-coil project", exact: true })
      .click();
    await requested;
    if (changed === "source")
      await page
        .getByLabel("Program name", { exact: true })
        .fill("Changed while fan preview waits");
    else
      await dialog
        .getByRole("button", { name: "Cancel wizard", exact: true })
        .click();
    release();
    await completed;
    await expect(
      page.getByRole("button", {
        name: "Create editable project",
        exact: true,
      }),
    ).toHaveCount(0);
    if (changed === "source") {
      await expect(dialog.getByRole("alert")).toContainText(
        "Current editor changed",
      );
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue("Changed while fan preview waits");
    } else {
      await expect(dialog).toHaveCount(0);
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(original);
    }
  });

for (const profile of ["legacy", "dual"])
  test(`${profile} profile cannot authorize a fan-coil preview`, async ({
    page,
  }) => {
    const dialog = await parameters(page);
    await declare(dialog);
    const catalog = await (
      await page.request.get("/api/equipment-wizard/catalog")
    ).json();
    const alternative = profile === "dual" ? catalog.dual_duct : catalog;
    await page.route("**/api/equipment-wizard/preview", async (route) => {
      const response = await route.fetch(),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      value.profile = alternative.profile;
      value.profile_sha256 = alternative.profile_sha256;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", { name: "Preview fan-coil project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toContainText(
      "does not match these exact choices/profile",
    );
    await expect(
      dialog.getByRole("button", {
        name: "Create editable project",
        exact: true,
      }),
    ).toHaveCount(0);
  });
