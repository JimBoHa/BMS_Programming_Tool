import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { python, simulation, value } from "./caf-simulation-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
function source(kind: string) {
  return python(
    "from tests.test_caf_zip_attributes import repack,original;import sys;sys.stdout.buffer.write(repack(original(sys.argv[1])))",
    kind,
  );
}
function inspect(file: string) {
  return JSON.parse(
    python(
      "from pathlib import Path;from bms_tool.caf import CafArchive;import sys,json;from bms_tool.caf_simulation import CafSimulationProfile;a=CafArchive(Path(sys.argv[1]).read_bytes());print(json.dumps({'external_attr':a.info.external_attr,'create_system':a.info.create_system,'comment':a.comment.decode(),'simulation':[r['old'] for r in CafSimulationProfile(a).export_profile()['entries']]}))",
      file,
    ).toString(),
  );
}
async function open(page: Page, kind: string) {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "zero-attributes.caf",
      mimeType: "application/octet-stream",
      buffer: source(kind),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("zero-attributes.caf");
}
test("ordinary Enum CAF copy retains actual zero attributes through the existing source/request/artifact download checks", async ({
  page,
  request,
}) => {
  await open(page, "enum");
  await page
    .locator(".caf-layout tbody tr")
    .filter({ has: page.getByText("ENUM_CMD", { exact: true }) })
    .click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("256");
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "CAF changes");
  const pending = page.waitForEvent("download");
  await page
    .locator(".export-strip:visible")
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .click();
  const file = (await (await pending).path())!;
  expect(inspect(file)).toMatchObject({
    external_attr: 0,
    create_system: 0,
    comment: "preserved archive comment",
  });
  expect(
    python(
      "from pathlib import Path;from bms_tool.caf import CafArchive;import sys;print(next(p for p in CafArchive(Path(sys.argv[1]).read_bytes()).properties('controller/enum') if p['id']=='3113')['scalar']['text'])",
      file,
    )
      .toString()
      .trim(),
  ).toBe("256");
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
test("version2 and scenario startup version1 retain zero attributes while preserving their separate source values", async ({
  page,
}) => {
  await open(page, "simulation1");
  await simulation(page);
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("4 editable");
  await value(page).fill("256");
  let pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  let file = (await (await pending).path())!;
  expect(inspect(file)).toMatchObject({
    external_attr: 0,
    create_system: 0,
    simulation: ["70.000", "25.000", "0", "256", null],
  });
  await page.getByLabel("Local event time", { exact: true }).fill("0");
  await page
    .getByLabel("Local event input", { exact: true })
    .selectOption("8-1/526_1::simulationProperty:3113");
  await page.getByLabel("Local event value", { exact: true }).fill("73.25");
  await page
    .getByRole("button", { name: "Add or replace input event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Input stimulus preview" }),
  ).toBeVisible();
  pending = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: "Export startup CAF at preview time",
      exact: true,
    })
    .click();
  file = (await (await pending).path())!;
  expect(inspect(file)).toMatchObject({
    external_attr: 0,
    create_system: 0,
    comment: "preserved archive comment",
    simulation: ["73.25", "25.000", "0", "1", null],
  });
});
