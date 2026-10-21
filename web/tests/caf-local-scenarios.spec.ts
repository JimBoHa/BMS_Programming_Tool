import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
const first = "8-1/526_1::simulationProperty:3113";
const second = "8-1/530_3::simulationProperty:3113";
function synthetic() {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_simulation import make_caf; import sys; sys.stdout.buffer.write(make_caf())",
    ],
    { cwd: root },
  );
}
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "CAF simulation", exact: true })
    .click();
  await page.getByLabel("Simulation CAF file", { exact: true }).setInputFiles({
    name: "authored.caf",
    mimeType: "application/octet-stream",
    buffer: synthetic(),
  });
  await expect(
    page.getByRole("region", { name: "Local CAF input scenarios" }),
  ).toContainText("2 supported inputs");
  return page.getByRole("region", { name: "Local CAF input scenarios" });
}
async function event(
  page: Page,
  time: string,
  input: string,
  value: string,
  quality = "good",
) {
  await page.getByLabel("Local event time", { exact: true }).fill(time);
  await page
    .getByLabel("Local event input", { exact: true })
    .selectOption(input);
  await page.getByLabel("Local event value", { exact: true }).fill(value);
  await page
    .getByLabel("Local event quality", { exact: true })
    .selectOption(quality);
  await page
    .getByRole("button", { name: "Add or replace input event", exact: true })
    .click();
}

test("named scenarios persist across page reopen, exchange exact-source JSON and preview faults without native execution", async ({
  page,
}) => {
  let panel = await open(page);
  await page
    .getByLabel("Local scenario name")
    .fill("Authored local fault recovery");
  await page
    .getByLabel("Local scenario description")
    .fill("Explicit local stimulus quality; no native CAF execution.");
  await page.getByLabel("Local scenario duration").fill("2");
  await event(page, "0", first, "-5.25");
  await event(page, "0.25", second, "true", "open-circuit");
  await event(page, "1", second, "false");
  await expect(
    page
      .getByRole("table", { name: "Local scenario events" })
      .locator("tbody tr"),
  ).toHaveCount(3);
  await page
    .getByRole("button", { name: "Save local scenario", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("revision 1");
  const pendingJson = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export local scenario JSON", exact: true })
    .click();
  const exported = JSON.parse(
    readFileSync((await (await pendingJson).path())!, "utf8"),
  );
  expect(exported.format).toBe("bms.caf-local-input-scenario");
  expect(
    exported.inputs.map((row: { class_id: string }) => row.class_id),
  ).toEqual(["526", "530"]);
  expect(exported.events[1]).toEqual({
    time: 0.25,
    values: { [second]: { value: "true", quality: "open-circuit" } },
  });
  expect(exported.inputs[0].unit_status).toBe("unknown");
  await page.reload();
  panel = await open(page);
  await page
    .getByLabel("Saved local input scenarios")
    .selectOption({ label: "Authored local fault recovery · revision 1" });
  await page
    .getByRole("button", { name: "Reopen local scenario", exact: true })
    .click();
  await expect(page.getByLabel("Local scenario name")).toHaveValue(
    "Authored local fault recovery",
  );
  await expect(
    page
      .getByRole("table", { name: "Local scenario events" })
      .locator("tbody tr"),
  ).toHaveCount(3);
  await page
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  const preview = page.getByRole("region", { name: "Input stimulus preview" });
  await expect(preview).toContainText("controller outputs are not executed");
  await page
    .getByLabel("Input stimulus frame")
    .selectOption({ label: "0.25 seconds" });
  await expect(preview).toContainText("open-circuit");
  await expect(
    preview.getByRole("button", { name: "Export startup CAF at preview time" }),
  ).toBeDisabled();
  const pendingPreview = page.waitForEvent("download");
  await preview
    .getByRole("button", { name: "Export input preview JSON" })
    .click();
  const trace = JSON.parse(
    readFileSync((await (await pendingPreview).path())!, "utf8"),
  );
  expect(trace.format).toBe("bms.caf-local-input-preview");
  expect(trace.scenario_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(trace.frames.map((row: { time: number }) => row.time)).toEqual([
    0, 0.25, 1, 2,
  ]);
  expect(trace.frames[1].inputs[second].quality).toBe("open-circuit");
  expect(trace.frames[0]).not.toHaveProperty("outputs");
  await page
    .getByLabel("Input stimulus frame")
    .selectOption({ label: "2 seconds" });
  const pendingCaf = page.waitForEvent("download");
  await preview
    .getByRole("button", { name: "Export startup CAF at preview time" })
    .click();
  const startup = await pendingCaf;
  const values = JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "import sys,json; from pathlib import Path; from bms_tool.caf_simulation import CafSimulationProfile; print(json.dumps([r['old'] for r in CafSimulationProfile(Path(sys.argv[1]).read_bytes()).summary()['records']]))",
        (await startup.path())!,
      ],
      { cwd: root },
    ).toString(),
  );
  expect(values).toEqual(["-5.25", "25.000", "false", "1", null]);
  await expect(panel.getByRole("status")).toContainText(
    "CCT/PCT acceptance remains unverified",
  );
  await page
    .getByRole("button", { name: "New local scenario", exact: true })
    .click();
  await page
    .getByLabel("Local input scenario JSON", { exact: true })
    .setInputFiles({
      name: "scenario.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(exported)),
    });
  await expect(page.getByLabel("Local scenario name")).toHaveValue(
    "Authored local fault recovery",
  );
  await expect(panel.getByRole("status")).toContainText("Save locally");
  await page
    .getByRole("button", { name: "Save local scenario", exact: true })
    .click();
  await expect(panel).toContainText("saved revision 1");
  const options = page
    .getByLabel("Saved local input scenarios")
    .locator("option");
  const beforeCopy = await options.count();
  await page
    .getByRole("button", { name: "Save local copy", exact: true })
    .click();
  await expect(options).toHaveCount(beforeCopy + 1);
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Delete saved scenario", exact: true })
    .click();
  await expect(options).toHaveCount(beforeCopy);
  await expect(panel.getByRole("status")).toContainText(
    "Draft remains available",
  );
  await expect(
    page
      .getByRole("table", { name: "Local scenario events" })
      .locator("tbody tr"),
  ).toHaveCount(3);
});

test("input guards, bad scalar types and optimistic saves refuse stale or unsafe scenarios", async ({
  page,
}) => {
  const panel = await open(page);
  await event(page, "0", first, "NaN");
  await page
    .getByRole("button", { name: "Save local scenario", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("finite decimal");
  await page
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Input stimulus preview" }),
  ).toHaveCount(0);
  await event(page, "0", first, "0");
  await page
    .getByRole("button", { name: "Save local scenario", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("revision 1");
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export local scenario JSON", exact: true })
    .click();
  const original = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  for (const wrong of [
    { ...original, source_sha256: "0".repeat(64) },
    {
      ...original,
      inputs: original.inputs.map((row: object, i: number) =>
        i ? row : { ...row, units_native: { text: "degF" } },
      ),
    },
  ]) {
    await page
      .getByLabel("Local input scenario JSON", { exact: true })
      .setInputFiles({
        name: "stale.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(wrong)),
      });
    await expect(panel.getByRole("alert")).toContainText("input guards");
    await expect(
      page
        .getByRole("table", { name: "Local scenario events" })
        .locator("tbody tr"),
    ).toHaveCount(1);
  }
  // Another client saves the same persisted record; UI's stale revision cannot overwrite it.
  await page.evaluate(async () => {
    const token = (await (await fetch("/api/session")).json()).token;
    const caf = document
      .querySelector(".caf-simulation-summary code")!
      .getAttribute("title")!;
    const base = `/api/caf/${caf}/local-scenarios`;
    const saved = (await (await fetch(base)).json()).saved[0];
    const item = await (await fetch(`${base}/${saved.id}`)).json();
    await fetch(base + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Studio-Token": token },
      body: JSON.stringify({
        id: item.id,
        scenario: item.scenario,
        expected_revision: item.revision,
      }),
    });
  });
  await page.getByLabel("Local scenario name").fill("Stale browser draft");
  await page
    .getByRole("button", { name: "Save local scenario", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("revision changed");
  await expect(page.getByLabel("Local scenario name")).toHaveValue(
    "Stale browser draft",
  );
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByLabel("Simulation CAF file", { exact: true }).setInputFiles({
    name: "replacement.caf",
    mimeType: "application/octet-stream",
    buffer: synthetic(),
  });
  await expect(page.getByLabel("Local scenario name")).toHaveValue(
    "Stale browser draft",
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByLabel("Simulation CAF file", { exact: true }).setInputFiles({
    name: "replacement.caf",
    mimeType: "application/octet-stream",
    buffer: synthetic(),
  });
  await expect(page.getByLabel("Local scenario name")).toHaveValue(
    "New input scenario",
  );
  await expect(
    page
      .getByRole("table", { name: "Local scenario events" })
      .locator("tbody tr"),
  ).toHaveCount(0);
});

test("hidden workspace suppresses a late startup CAF download and leaves the scenario reusable", async ({
  page,
}) => {
  const panel = await open(page);
  await page
    .getByRole("button", { name: "Preview input stimuli", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Input stimulus preview" }),
  ).toBeVisible();
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let seen!: () => void;
  const requestSeen = new Promise<void>((resolve) => {
    seen = resolve;
  });
  await page.route("**/local-scenarios/startup-profile", async (route) => {
    seen();
    await held;
    await route.continue();
  });
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  await page
    .getByRole("button", { name: "Export startup CAF at preview time" })
    .click();
  await requestSeen;
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  release();
  await page.unrouteAll({ behavior: "wait" });
  await page
    .getByRole("button", { name: "CAF simulation", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Save local scenario", exact: true }),
  ).toBeEnabled();
  expect(downloads).toEqual([]);
  await expect(
    page.getByRole("region", { name: "Input stimulus preview" }),
  ).toBeVisible();
});
