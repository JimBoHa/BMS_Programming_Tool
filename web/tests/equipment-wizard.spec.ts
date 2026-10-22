import {
  sourceFixtureData,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { test, expect, type Page } from "./simulationFixture";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Equipment and sequence wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Wizard project name", { exact: true }),
  ).toBeVisible();
  return dialog;
}
async function params(page: Page) {
  const dialog = await open(page);
  await dialog
    .getByLabel("Wizard project name", { exact: true })
    .fill("Wizard browser authoring");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  return dialog;
}
async function review(page: Page) {
  const dialog = page.getByRole("dialog", {
    name: "Equipment and sequence wizard",
    exact: true,
  });
  await dialog
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  await expect(
    dialog.getByRole("heading", {
      name: "Wizard browser authoring",
      exact: true,
    }),
  ).toBeVisible();
  return dialog;
}

test("author measured-airflow project, preview actual signals, protect current draft, simulate save reopen and export", async ({
  page,
}) => {
  let dialog = await open(page);
  const originalName = await page
    .getByLabel("Program name", { exact: true })
    .inputValue();
  await dialog
    .getByLabel("Wizard project name", { exact: true })
    .fill("Wizard browser authoring");
  await dialog
    .getByLabel("VAV equipment", { exact: true })
    .selectOption("parallel-fan-reheat");
  await dialog
    .getByLabel("Declared controller family", { exact: true })
    .selectOption("johnson-fx");
  await dialog
    .getByLabel("Declared controller model", { exact: true })
    .fill("FX-PCV1630-0");
  await dialog
    .getByLabel("Declared controller firmware", { exact: true })
    .fill("declared-6.2");
  await dialog
    .getByLabel("Declared CAF release mode", { exact: true })
    .fill("declared-10.2");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  await dialog
    .getByLabel("Damper control strategy", { exact: true })
    .selectOption("flow-feedback");
  let preview: any;
  page.on("response", async (response) => {
    if (
      response.url().endsWith("/api/equipment-wizard/preview") &&
      response.ok()
    )
      preview = sourceFixtureData(await response.json());
  });
  dialog = await review(page);
  await expect(
    dialog.getByRole("region", { name: "Wizard preview", exact: true }),
  ).toContainText("Measured airflow input");
  await expect(dialog).toContainText("Airflow setpoint");
  await expect(dialog).toContainText("no physical/native allocation");
  page.once("dialog", (d) => d.dismiss());
  await dialog
    .getByRole("button", { name: "Create editable project", exact: true })
    .click();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    originalName,
  );
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", { name: "Create editable project", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", {
      name: "Equipment and sequence wizard",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Wizard browser authoring",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByLabel("Last saved revision", { exact: true }),
  ).toContainText("r1");
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = (await (await event).path())!;
  const inspected = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "import json,sys;from bms_tool.models import Program;from bms_tool.engine import Engine;p=Program.model_validate(json.load(open(sys.argv[1])));assert p.revision==1;assert p.target.model=='FX-PCV1630-0';assert p.target.physical_inputs is None;assert not p.metadata['native_deployment_verified'];r=Engine(p).step()['outputs'];assert abs(r['damper']-12.2816)<1e-8;assert abs(r['flow_setpoint']-521.6)<1e-8;p.revision=0;print(json.dumps({'id':p.id,'hash':p.digest(),'choice_hash':p.metadata['equipment_wizard']['choices_sha256']}))",
        file,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  expect(inspected.id).toBe(preview.program.id);
  expect(inspected.hash).toBe(preview.program_sha256);
  expect(inspected.choice_hash).toBe(preview.choices_sha256);
  await page.reload();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Wizard browser authoring",
  );
  await expect(
    page.locator('.react-flow__node[data-id="flow_loop"]'),
  ).toBeVisible();
});
test("unit changes convert defaults and inverse gains without changing simulated physical behavior", async ({
  page,
}) => {
  const dialog = await params(page);
  await dialog
    .getByLabel("Damper control strategy", { exact: true })
    .selectOption("flow-feedback");
  await dialog
    .getByLabel("Wizard temperature units", { exact: true })
    .selectOption("degC");
  await expect(
    dialog.getByLabel("Zone proportional gain (%/delta-degC)", { exact: true }),
  ).toHaveValue("36");
  await expect(
    dialog.getByLabel("Zone integral gain (%/delta-degC/s)", { exact: true }),
  ).toHaveValue("0.18");
  await dialog
    .getByLabel("Wizard airflow units", { exact: true })
    .selectOption("L/s");
  await expect(
    dialog.getByLabel("Minimum declared airflow (L/s)", { exact: true }),
  ).toHaveValue("94.38948864");
  await review(page);
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", { name: "Create editable project", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
});
test("position mapping and P-only strategy preview no flow sensor and stale parameter edits require fresh review", async ({
  page,
}) => {
  const dialog = await params(page);
  await dialog
    .getByLabel("Zone loop strategy", { exact: true })
    .selectOption("P");
  await dialog
    .getByLabel("Minimum damper position (%)", { exact: true })
    .fill("30");
  await review(page);
  await expect(dialog).toContainText("Damper position mapping");
  await expect(dialog.getByRole("table")).not.toContainText("airflow");
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog
    .getByLabel("Minimum damper position (%)", { exact: true })
    .fill("40");
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  await review(page);
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", { name: "Create editable project", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
});
test("closed wizard retires delayed preview without replacing current project", async ({
  page,
}) => {
  const dialog = await params(page);
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
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  await requested;
  await dialog
    .getByRole("button", { name: "Cancel wizard", exact: true })
    .click();
  release();
  await completed;
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
  await expect(
    page.getByRole("dialog", {
      name: "Equipment and sequence wizard",
      exact: true,
    }),
  ).toHaveCount(0);
});
for (const mode of [
  "wrong-choice",
  "wrong-profile",
  "wrong-profile-body",
  "wrapper",
]) {
  test(`refuse ${mode} preview`, async ({ page }) => {
    const dialog = await params(page);
    await page.route("**/api/equipment-wizard/preview", async (route) => {
      const response = await route.fetch(),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (mode === "wrong-choice") value.choices.name = "Different source";
      if (mode === "wrong-profile") value.profile_sha256 = "0".repeat(64);
      if (mode === "wrong-profile-body") value.profile.gaps = [];
      await route.fulfill({
        response,
        json:
          mode === "wrapper"
            ? { preview: "unexpected wrapper" }
            : resealSourceFixture(envelope, value),
      });
    });
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
  });
}

test("changed editor source retires a pending preview and blocks stale replacement", async ({
  page,
}) => {
  const dialog = await params(page);
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
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  await requested;
  await page
    .getByLabel("Program name", { exact: true })
    .fill("New editor source during preview");
  release();
  await completed;
  await expect(dialog.getByRole("alert")).toContainText(
    "Current editor changed",
  );
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "New editor source during preview",
  );
});

test("unit response must refer to exact source choices", async ({ page }) => {
  const dialog = await params(page);
  await page.route("**/api/equipment-wizard/units", async (route) => {
    const response = await route.fetch(),
      value = await response.json();
    value.source_choices.project_id = "another-project";
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
    dialog.getByLabel("Zone proportional gain (%/delta-degF)", { exact: true }),
  ).toHaveValue("20");
});

test("invalid equipment parameter constraints block generation without replacing source", async ({
  page,
}) => {
  const dialog = await params(page),
    original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
  await dialog
    .getByLabel("Minimum damper position (%)", { exact: true })
    .fill("100");
  await dialog
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Minimum damper position",
  );
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});
