import { test, expect, type Page } from "./simulationFixture";
import {
  sourceFixtureData,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function parameters(page: Page, flow = true) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Equipment and sequence wizard",
    exact: true,
  });
  await dialog
    .getByLabel("Wizard project name", { exact: true })
    .fill("Dual-deck browser authoring");
  await dialog
    .getByLabel("VAV equipment", { exact: true })
    .selectOption("dual-duct");
  await dialog
    .getByRole("button", { name: "Next: parameters", exact: true })
    .click();
  if (flow)
    await dialog
      .getByLabel("Damper control strategy", { exact: true })
      .selectOption("flow-feedback");
  return dialog;
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
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  const response = await arrived;
  expect(response.ok()).toBe(true);
  const report = sourceFixtureData(await response.json());
  await expect(
    dialog.getByRole("heading", {
      name: "Dual-deck browser authoring",
      exact: true,
    }),
  ).toBeVisible();
  return { dialog, report };
}

for (const layout of ["hot-cold", "hot-total", "cold-total"]) {
  test(`author ${layout} pickups, actual graph simulation, saved revision and independently verified export`, async ({
    page,
  }) => {
    let dialog = await parameters(page);
    await dialog
      .getByLabel("Dual-duct airflow pickup layout", { exact: true })
      .selectOption(layout);
    const reviewed = await preview(page);
    dialog = reviewed.dialog;
    await expect(
      dialog.getByRole("region", { name: "Wizard preview", exact: true }),
    ).toContainText("Cold-deck logical damper command");
    await expect(dialog).toContainText("Hot-deck logical damper command");
    await expect(dialog).toContainText("Nonnegative airflow arithmetic only");
    page.once("dialog", (d) => d.accept());
    await dialog
      .getByRole("button", { name: "Create editable project", exact: true })
      .click();
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
    await page
      .getByLabel("Export format", { exact: true })
      .selectOption("json");
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const file = (await (await downloaded).path())!;
    const root = path.resolve("..");
    const proof = JSON.parse(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          `
import json,sys
from bms_tool.models import Program
from bms_tool.engine import Engine
p=Program.model_validate(json.load(open(sys.argv[1])))
assert p.revision==1 and p.target.physical_inputs is None
assert not p.metadata['native_deployment_verified']
w=p.metadata['equipment_wizard'];assert w['source']['pdf_pages']==[594,595,596]
assert w['choices']['dual_duct']['layout']==sys.argv[2]
assert {n.id for n in p.nodes if n.kind=='Input'}=={'zone'}|{x+'_airflow' for x in sys.argv[2].split('-')}
r=Engine(p).step()['outputs'];assert r['control_permitted'] and r['airflow_consistent']
assert abs(r['cold_damper']-12.2816)<1e-9 and r['hot_damper']==0
assert r['hot_flow']==200 and r['cold_flow']==400 and r['total_flow']==600
p.revision=0;print(json.dumps({'program_sha256':p.digest(),'profile_sha256':w['profile_sha256'],'choices_sha256':w['choices_sha256']}))
`,
          file,
          layout,
        ],
        { cwd: root, encoding: "utf8" },
      ),
    );
    expect(proof.program_sha256).toBe(reviewed.report.program_sha256);
    expect(proof.profile_sha256).toBe(reviewed.report.profile_sha256);
    expect(proof.choices_sha256).toBe(reviewed.report.choices_sha256);
    await page.reload();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Dual-deck browser authoring",
    );
    await expect(
      page.locator('.react-flow__node[data-id="cold_flow_loop"]'),
    ).toBeVisible();
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });
}

test("explicit no-pickup position layout retains declared simultaneous minima and changing strategy requires new layout", async ({
  page,
}) => {
  const dialog = await parameters(page, false);
  await expect(
    dialog.getByLabel("Dual-duct airflow pickup layout", { exact: true }),
  ).toHaveValue("");
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
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .selectOption("none");
  await dialog
    .getByLabel("Hot-deck minimum damper position (%)", { exact: true })
    .fill("10");
  await preview(page);
  await expect(
    dialog.getByRole("region", { name: "Wizard preview", exact: true }),
  ).not.toContainText("Measured total airflow");
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await expect(dialog).toContainText("simultaneous minimum flow");
  await dialog
    .getByLabel("Damper control strategy", { exact: true })
    .selectOption("flow-feedback");
  await expect(
    dialog.getByLabel("Dual-duct airflow pickup layout", { exact: true }),
  ).toHaveValue("");
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  const options = dialog
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .locator("option");
  await expect(options).toHaveCount(4);
  await expect(options).not.toContainText(["Total flow only"]);
});

test("unit changes preserve both deck defaults and inverse gains before the generated metric simulation", async ({
  page,
}) => {
  const dialog = await parameters(page);
  await dialog
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .selectOption("hot-total");
  await dialog
    .getByLabel("Wizard temperature units", { exact: true })
    .selectOption("degC");
  await expect(
    dialog.getByLabel("Zone proportional gain (%/delta-degC)", { exact: true }),
  ).toHaveValue("36");
  await dialog
    .getByLabel("Wizard airflow units", { exact: true })
    .selectOption("L/s");
  await expect(
    dialog.getByLabel("Cold-deck minimum declared airflow (L/s)", {
      exact: true,
    }),
  ).toHaveValue("94.38948864");
  await expect(
    dialog.getByLabel("Hot-deck minimum declared airflow (L/s)", {
      exact: true,
    }),
  ).toHaveValue("47.19474432");
  await expect(
    dialog.getByLabel("Measured total airflow input default (L/s)", {
      exact: true,
    }),
  ).toHaveValue("283.16846592");
  await expect(
    dialog.getByLabel("Measured cold-deck airflow input default (L/s)", {
      exact: true,
    }),
  ).toHaveCount(0);
  await preview(page);
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", { name: "Create editable project", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
});

test("inconsistent declared total default is refused and a corrected pickup selection previews without stale authority", async ({
  page,
}) => {
  const dialog = await parameters(page);
  await dialog
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .selectOption("hot-total");
  await dialog
    .getByLabel("Measured total airflow input default (cfm)", { exact: true })
    .fill("100");
  await dialog
    .getByRole("button", { name: "Preview VAV project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Total default airflow cannot be below",
  );
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  await dialog
    .getByLabel("Measured total airflow input default (cfm)", { exact: true })
    .fill("600");
  await preview(page);
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .selectOption("cold-total");
  await expect(
    dialog.getByRole("button", {
      name: "Create editable project",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    dialog.getByLabel("Measured hot-deck airflow input default (cfm)", {
      exact: true,
    }),
  ).toHaveCount(0);
  await preview(page);
});

test("a legacy profile cannot authorize a dual-deck preview", async ({
  page,
}) => {
  const dialog = await parameters(page);
  await dialog
    .getByLabel("Dual-duct airflow pickup layout", { exact: true })
    .selectOption("hot-cold");
  const catalog = await (
    await page.request.get("/api/equipment-wizard/catalog")
  ).json();
  await page.route("**/api/equipment-wizard/preview", async (route) => {
    const response = await route.fetch(),
      envelope = await response.json(),
      value = sourceFixtureData(envelope);
    value.profile_sha256 = catalog.profile_sha256;
    value.profile = catalog.profile;
    await route.fulfill({
      response,
      json: resealSourceFixture(envelope, value),
    });
  });
  await dialog
    .getByRole("button", { name: "Preview VAV project", exact: true })
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
