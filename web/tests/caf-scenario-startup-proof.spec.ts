import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { openSimulation, python } from "./caf-simulation-fixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";
const scenarios = (page: Page) =>
  page.getByRole("region", { name: "Local CAF input scenarios", exact: true });
async function open(page: Page) {
  await openSimulation(page, { cafEntry: true });
  await expect(scenarios(page)).toContainText("2 supported inputs");
  await scenarios(page)
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Input stimulus preview" }),
  ).toBeVisible();
}
const startup = (page: Page) =>
  page.getByRole("button", {
    name: "Export startup CAF at preview time",
    exact: true,
  });
test("a valid native profile for wrong startup values cannot replace the selected scenario frame", async ({
  page,
}, info) => {
  await open(page);
  let downloads = 0;
  const retained: Promise<void>[] = [];
  page.on("download", (d) => {
    downloads++;
    retained.push(
      d.saveAs(info.outputPath(`unwanted-startup-${downloads}.caf`)),
    );
  });
  await page.route("**/local-scenarios/startup-profile", async (route) => {
    const response = await route.fetch({ maxRetries: 0 }),
      result = await response.json();
    result.profile.entries[0].value = "73.25";
    await route.fulfill({ response, json: result });
  });
  await startup(page).click();
  try {
    await expect(scenarios(page).getByRole("alert")).toContainText(
      "selected scenario frame",
    );
  } finally {
    await Promise.all(retained);
  }
  expect(downloads).toBe(0);
  await expect(page.getByLabel("Local scenario name")).toHaveValue(
    "New input scenario",
  );
});

for (const fault of ["output", "Boolean", "source", "version"])
  test(`prepared ${fault} changes are refused before a native-copy request`, async ({
    page,
  }) => {
    await open(page);
    let copies = 0;
    await page.route("**/api/caf/*/simulation", async (route) => {
      if (route.request().method() === "POST") copies++;
      await route.continue();
    });
    await page.route("**/local-scenarios/startup-profile", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        result = await response.json();
      if (fault === "output") result.profile.entries[1].value = "26";
      if (fault === "Boolean") result.profile.entries[2].value = "true";
      if (fault === "source") result.profile.source_sha256 = "0".repeat(64);
      if (fault === "version") result.profile.version = 2;
      await route.fulfill({ response, json: result });
    });
    await startup(page).click();
    await expect(scenarios(page).getByRole("alert")).toContainText(
      /selected scenario frame|exact CAF SHA-256/,
    );
    expect(copies).toBe(0);
  });
for (const fault of [
  "source",
  "version",
  "request",
  "digest",
  "body",
  "missing",
])
  test(`startup export refuses altered ${fault} artifact proof`, async ({
    page,
  }) => {
    await open(page);
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/api/caf/*/simulation", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const response = await route.fetch({ maxRetries: 0 }),
        headers = { ...response.headers() };
      let body = await response.body();
      if (fault === "source")
        headers["x-studio-source-sha256"] = "0".repeat(64);
      if (fault === "version") headers["x-studio-simulation-version"] = "2";
      if (fault === "request")
        headers["x-studio-simulation-request-sha256"] = "0".repeat(64);
      if (fault === "digest")
        headers["x-studio-artifact-sha256"] = "0".repeat(64);
      if (fault === "missing")
        delete headers["x-studio-simulation-request-sha256"];
      if (fault === "body") body = Buffer.from("other");
      await route.fulfill({ response, headers, body });
    });
    await startup(page).click();
    await expect(scenarios(page).getByRole("alert")).toContainText(
      "artifact digest",
    );
    expect(downloads).toBe(0);
    await expect(startup(page)).toBeEnabled();
  });
for (const stage of ["prepare", "copy"])
  for (const lifecycle of ["navigation", "pagehide", "visibility"])
    test(`${lifecycle} permanently retires a delayed startup ${stage} response`, async ({
      page,
    }) => {
      await open(page);
      let release!: () => void, seen!: () => void;
      const hold = new Promise<void>((r) => (release = r)),
        started = new Promise<void>((r) => (seen = r));
      let downloads = 0,
        copies = 0;
      page.on("download", () => downloads++);
      await page.route("**/api/caf/*/simulation", async (route) => {
        if (route.request().method() !== "POST") return route.continue();
        copies++;
        const response = await route.fetch({ maxRetries: 0 }),
          body = await response.body();
        if (stage === "copy") {
          seen();
          await hold;
        }
        await route.fulfill({ response, body });
      });
      if (stage === "prepare")
        await page.route(
          "**/local-scenarios/startup-profile",
          async (route) => {
            const response = await route.fetch({ maxRetries: 0 }),
              body = await response.body();
            seen();
            await hold;
            await route.fulfill({ response, body });
          },
        );
      await startup(page).click();
      await started;
      if (lifecycle === "navigation") {
        await chooseWorkspaceSurface(page, "Library");
        await chooseWorkspaceSurface(page, "Workspace");
        const { simulation } = await import("./caf-simulation-fixture");
        await simulation(page);
      } else
        await page.evaluate((kind) => {
          if (kind === "pagehide") window.dispatchEvent(new Event("pagehide"));
          else {
            Object.defineProperty(document, "hidden", {
              configurable: true,
              value: true,
            });
            document.dispatchEvent(new Event("visibilitychange"));
            Object.defineProperty(document, "hidden", {
              configurable: true,
              value: false,
            });
            document.dispatchEvent(new Event("visibilitychange"));
          }
        }, lifecycle);
      release();
      await page.unrouteAll({ behavior: "wait" });
      await expect(startup(page)).toBeEnabled();
      expect(downloads).toBe(0);
      expect(copies).toBe(stage === "copy" ? 1 : 0);
      await expect(scenarios(page).getByRole("alert")).toHaveCount(0);
      const next = page.waitForEvent("download");
      await startup(page).click();
      await next;
      expect(downloads).toBe(1);
    });
test("file replacement retires an earlier startup preparation without changing the new source", async ({
  page,
}) => {
  await open(page);
  let release!: () => void, seen!: () => void;
  const hold = new Promise<void>((r) => (release = r)),
    started = new Promise<void>((r) => (seen = r));
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route("**/local-scenarios/startup-profile", async (route) => {
    const response = await route.fetch({ maxRetries: 0 }),
      body = await response.body();
    seen();
    await hold;
    await route.fulfill({ response, body });
  });
  await startup(page).click();
  await started;
  const { synthetic } = await import("./caf-simulation-fixture");
  await page
    .getByLabel("Simulation CAF file", { exact: true })
    .setInputFiles({
      name: "current.caf",
      mimeType: "application/octet-stream",
      buffer: synthetic("529"),
    });
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("current.caf");
  release();
  await page.unrouteAll({ behavior: "wait" });
  expect(downloads).toBe(0);
  await expect(scenarios(page).getByRole("alert")).toHaveCount(0);
});
test("decimal frame export copies exact held input text and preserves unselected values", async ({
  page,
}) => {
  await open(page);
  await page.getByLabel("Local scenario duration", { exact: true }).fill("1");
  await page.getByLabel("Local scenario interval", { exact: true }).fill("0.1");
  for (const [time, input, value] of [
    ["0", "8-1/526_1::simulationProperty:3113", "-0.0"],
    ["0.3", "8-1/526_1::simulationProperty:3113", "+7.25e1"],
    ["0.3", "8-1/530_3::simulationProperty:3113", "false"],
  ]) {
    await page.getByLabel("Local event time", { exact: true }).fill(time);
    await page
      .getByLabel("Local event input", { exact: true })
      .selectOption(input);
    await page.getByLabel("Local event value", { exact: true }).fill(value);
    await page
      .getByRole("button", { name: "Add or replace input event", exact: true })
      .click();
  }
  await scenarios(page)
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await page
    .getByLabel("Input stimulus frame", { exact: true })
    .selectOption({ label: "0.3 seconds" });
  const wait = page.waitForEvent("download");
  await startup(page).click();
  const download = await wait;
  expect(download.suggestedFilename()).toBe("authored-startup-0.3s.caf");
  expect(
    JSON.parse(
      python(
        "from pathlib import Path;from bms_tool.caf_simulation import CafSimulationProfile;import sys,json;print(json.dumps([r['old'] for r in CafSimulationProfile(Path(sys.argv[1]).read_bytes()).export_profile()['entries']]))",
        (await download.path())!,
      ).toString(),
    ),
  ).toEqual(["+7.25e1", "25.000", "false", "1", null]);
});
