import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { openSimulation, python } from "./caf-simulation-fixture";
const input = "8-1/528_4::simulationProperty:3113";
const active = (page: Page) => page.locator(".caf-local-scenarios:visible");
const selectVersion = (page: Page, value: string) =>
  page
    .getByLabel("Local scenario input profile", { exact: true })
    .selectOption(value);
async function open(page: Page) {
  await openSimulation(page, { cafEntry: true });
  await expect(active(page)).toContainText("2 supported inputs");
  await selectVersion(page, "2");
  await expect(active(page)).toContainText("3 supported inputs");
  return active(page);
}
async function event(page: Page, quality = "good", value = "2") {
  const p = active(page);
  await p.getByLabel("Local event input", { exact: true }).selectOption(input);
  await p.getByLabel("Local event time", { exact: true }).fill("0");
  await p.getByLabel("Local event value", { exact: true }).fill(value);
  await p
    .getByLabel("Local event quality", { exact: true })
    .selectOption(quality);
  await p
    .getByRole("button", { name: "Add or replace input event", exact: true })
    .click();
}
for (const width of [1440, 390])
  test(`${width} opt-in Enum scenario saves, exports and produces the exact selected startup leaf`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const p = await open(page);
    await event(page);
    await p
      .getByLabel("Local scenario name", { exact: true })
      .fill("Numeric Enum input");
    await p
      .getByRole("button", { name: "Save local scenario", exact: true })
      .click();
    await expect(p.getByRole("status")).toContainText("revision 1");
    const jsonDownload = page.waitForEvent("download");
    await p
      .getByRole("button", { name: "Export local scenario JSON", exact: true })
      .click();
    const scenario = JSON.parse(
      readFileSync((await (await jsonDownload).path())!, "utf8"),
    );
    expect(scenario.version).toBe(2);
    expect(scenario.inputs.map((r: any) => r.class_id)).toEqual([
      "526",
      "530",
      "528",
    ]);
    expect(scenario.inputs[2].enum_representation).toEqual({
      attributes: { set: "113" },
      maximum_code: 4294967295,
      enum_semantics_verified: false,
    });
    await p
      .getByRole("button", { name: "Preview input stimuli", exact: true })
      .click();
    await expect(
      p.getByRole("region", { name: "Input stimulus preview" }),
    ).toBeVisible();
    const downloading = page.waitForEvent("download");
    await p
      .getByRole("button", {
        name: "Export startup CAF at preview time",
        exact: true,
      })
      .click();
    const download = await downloading;
    const exact = python(
      `
from pathlib import Path
from bms_tool.caf import CafArchive
from tests.test_caf_enum_simulation import source
import sys
a=CafArchive(source());b=CafArchive(Path(sys.argv[1]).read_bytes())
print(b.xml==a.xml.replace(b'<enum set="113">1</enum>',b'<enum set="113">2</enum>'))
`,
      (await download.path())!,
    )
      .toString()
      .trim();
    expect(exact).toBe("True");
    await selectVersion(page, "1");
    await expect(
      active(page)
        .getByLabel("Saved local input scenarios", { exact: true })
        .locator("option"),
    ).toHaveCount(1);
    await selectVersion(page, "2");
    await expect(
      active(page).getByLabel("Local scenario name", { exact: true }),
    ).toHaveValue("Numeric Enum input");
    if (width === 390) {
      await page
        .getByLabel("Local scenario input profile", { exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: test.info().outputPath("enum-scenario-profile-phone.png"),
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  });
test("switching versions retains both unsaved drafts and refuses implicit version import", async ({
  page,
}) => {
  await open(page);
  await active(page)
    .getByLabel("Local scenario name", { exact: true })
    .fill("Enum draft");
  await event(page);
  const downloading = page.waitForEvent("download");
  await active(page)
    .getByRole("button", { name: "Export local scenario JSON", exact: true })
    .click();
  const file = await (await downloading).path();
  await selectVersion(page, "1");
  await active(page)
    .getByLabel("Local scenario name", { exact: true })
    .fill("Float draft");
  const choosing = page.waitForEvent("filechooser");
  await active(page)
    .getByRole("button", { name: "Import local scenario JSON", exact: true })
    .click();
  page.once("dialog", (dialog) => dialog.accept());
  await (await choosing).setFiles(file!);
  await expect(active(page).getByRole("alert")).toBeVisible();
  await expect(
    active(page).getByLabel("Local scenario name", { exact: true }),
  ).toHaveValue("Float draft");
  await selectVersion(page, "2");
  await expect(
    active(page).getByLabel("Local scenario name", { exact: true }),
  ).toHaveValue("Enum draft");
  await expect(
    active(page)
      .getByRole("table", { name: "Local scenario events" })
      .locator("tbody tr"),
  ).toHaveCount(1);
});
test("Enum quality is local and faulty frames cannot produce startup copies", async ({
  page,
}) => {
  const p = await open(page);
  await event(page, "open-circuit");
  await p
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await expect(
    p.getByRole("region", { name: "Input stimulus preview" }),
  ).toContainText("open-circuit");
  let downloads = 0;
  page.on("download", () => downloads++);
  await expect(
    p.getByRole("button", {
      name: "Export startup CAF at preview time",
      exact: true,
    }),
  ).toBeDisabled();
  expect(downloads).toBe(0);
});
test("profile switching retires held startup output even after returning to version2", async ({
  page,
}) => {
  const p = await open(page);
  await event(page);
  await p
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await expect(
    p.getByRole("region", { name: "Input stimulus preview" }),
  ).toBeVisible();
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    sent = new Promise<void>((r) => (arrived = r));
  await page.route(
    "**/local-scenarios/startup-profile?scenario_version=2",
    async (route) => {
      arrived();
      await held;
      await route.continue();
    },
  );
  let downloads = 0;
  page.on("download", () => downloads++);
  await p
    .getByRole("button", {
      name: "Export startup CAF at preview time",
      exact: true,
    })
    .click();
  await sent;
  await page
    .getByLabel("Local scenario input profile", { exact: true })
    .evaluate((select) => {
      const node = select as HTMLSelectElement;
      node.value = "1";
      node.dispatchEvent(new Event("change", { bubbles: true }));
      node.value = "2";
      node.dispatchEvent(new Event("change", { bubbles: true }));
    });
  const returned = page.waitForResponse((r) =>
    r.url().includes("/local-scenarios/startup-profile?scenario_version=2"),
  );
  release();
  await returned;
  await expect(
    active(page).getByLabel("Local scenario name", { exact: true }),
  ).toBeEnabled();
  expect(downloads).toBe(0);
  await expect(
    active(page)
      .getByRole("table", { name: "Local scenario events" })
      .locator("tbody tr"),
  ).toHaveCount(1);
});
