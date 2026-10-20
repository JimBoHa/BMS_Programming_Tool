import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
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

async function open(page: import("@playwright/test").Page) {
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
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("3 editable");
}

test("native CAF simulation profile edits save real simulation leaves and ordinary properties stay exact", async ({
  page,
}) => {
  await open(page);
  await expect(page.locator(".caf-simulation-table tbody tr")).toHaveCount(5);
  await expect(page.locator(".caf-simulation-table")).toContainText("set 113");
  await page
    .getByLabel("Simulation value 8-1/526_1", { exact: true })
    .fill("73.25");
  await page
    .getByLabel("Simulation value 8-1/530_3", { exact: true })
    .fill("true");
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("2 draft changes");
  const pendingProfile = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export profile JSON", exact: true })
    .click();
  const profileFile = await pendingProfile;
  const profile = JSON.parse(readFileSync((await profileFile.path())!, "utf8"));
  expect(profile.format).toBe("bms.caf-simulation-profile");
  expect(profile.entries[0].value).toBe("73.25");
  expect(profile.entries[3].editable).toBe(false);
  const pendingNative = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  const file = await pendingNative;
  expect(file.suggestedFilename()).toBe("authored-simulation.caf");
  const result = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from pathlib import Path; import sys,json; from bms_tool.caf import CafArchive; from bms_tool.caf_simulation import CafSimulationProfile; a=CafArchive(Path(sys.argv[1]).read_bytes()); print(json.dumps({'ordinary_unchanged':a.xml.count(b'<float>111.000</float>')==5,'values':[r['old'] for r in CafSimulationProfile(a).summary()['records']]}))",
      (await file.path())!,
    ],
    { cwd: root },
  );
  expect(JSON.parse(result.toString())).toEqual({
    ordinary_unchanged: true,
    values: ["73.25", "25.000", "true", "1", null],
  });
  await expect(page.getByRole("status")).toContainText(
    "JCI execution remains unverified",
  );
  await page
    .getByLabel("Search simulation records", { exact: true })
    .fill("enum");
  await expect(page.locator(".caf-simulation-table tbody tr")).toHaveCount(1);
  await page.screenshot({
    path: "test-results/studio-caf-simulation.png",
    fullPage: true,
  });
});

test("profile import guards, invalid scalar refusal and explicit draft discard retain work", async ({
  page,
}) => {
  await open(page);
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export profile JSON", exact: true })
    .click();
  const baseline = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  const uploadProfile = async (profile: unknown) => {
    await page
      .getByLabel("Simulation profile JSON", { exact: true })
      .setInputFiles({
        name: "scenario.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(profile)),
      });
  };
  await uploadProfile({ ...baseline, source_sha256: "0".repeat(64) });
  await expect(page.getByRole("alert")).toContainText("exact CAF SHA-256");
  const readOnly = structuredClone(baseline);
  readOnly.entries[3].value = "2";
  await uploadProfile(readOnly);
  await expect(page.getByRole("alert")).toContainText(
    "read-only native record",
  );
  const good = structuredClone(baseline);
  good.entries[0].value = "75.5";
  await uploadProfile(good);
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("75.5");
  await page
    .getByLabel("Simulation value 8-1/526_1", { exact: true })
    .fill("NaN");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "finite decimal native text",
  );
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByRole("button", { name: "Reset simulation draft", exact: true })
    .click();
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("NaN");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByLabel("Simulation CAF file", { exact: true })
    .setInputFiles({
      name: "other.caf",
      mimeType: "application/octet-stream",
      buffer: synthetic(),
    });
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("authored.caf");
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("NaN");
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Reset simulation draft", exact: true })
    .click();
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("70.000");
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("0 draft changes");
});

test("leaving simulation workspace suppresses a late native download", async ({
  page,
}) => {
  await open(page);
  let release: (() => void) | undefined;
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/caf/*/simulation", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    await hold;
    await route.fulfill({ response });
  });
  const downloads: unknown[] = [];
  page.on("download", (item) => downloads.push(item));
  await page
    .getByLabel("Simulation value 8-1/526_1", { exact: true })
    .fill("77");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Validating copy…", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Program", exact: true }).click();
  release!();
  await expect(
    page
      .locator(".caf-simulation button")
      .filter({ hasText: "Export simulation CAF" }),
  ).toHaveCount(1);
  await page
    .getByRole("button", { name: "CAF simulation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Export simulation CAF", exact: true }),
  ).toBeEnabled();
  expect(downloads).toHaveLength(0);
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("77");
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("unexported");
});
