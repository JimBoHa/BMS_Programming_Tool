import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { openSimulation, value, python } from "./caf-simulation-fixture";
async function exported(page: import("@playwright/test").Page) {
  const wait = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  return await wait;
}
test("an earlier self-consistent same-source export cannot satisfy different requested simulation values", async ({
  page,
}, info) => {
  await openSimulation(page);
  await value(page).fill("2");
  let earlier: { body: Buffer; headers: Record<string, string> } | null = null;
  await page.route("**/api/caf/*/simulation", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    if (earlier) {
      await route.fulfill({
        status: 200,
        headers: earlier.headers,
        body: earlier.body,
      });
      return;
    }
    const response = await route.fetch({ maxRetries: 0 });
    earlier = { body: await response.body(), headers: response.headers() };
    await route.fulfill({ response, body: earlier.body });
  });
  const first = await exported(page);
  expect(
    python(
      "from pathlib import Path;from bms_tool.caf_simulation import CafSimulationProfile;import sys;print(CafSimulationProfile(Path(sys.argv[1]).read_bytes(),profile_version=2).export_profile()['entries'][3]['old'])",
      (await first.path())!,
    )
      .toString()
      .trim(),
  ).toBe("2");
  await info.attach("earlier-source-version-artifact-proof", {
    body: JSON.stringify(earlier!.headers),
    contentType: "application/json",
  });
  await value(page).fill("3");
  let downloads = 0;
  const retained: Promise<void>[] = [];
  page.on("download", (download) => {
    downloads++;
    retained.push(
      download.saveAs(info.outputPath(`unwanted-download-${downloads}.caf`)),
    );
  });
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  try {
    await expect(
      page.locator(".caf-simulation").getByRole("alert"),
    ).toContainText("requested simulation values");
  } finally {
    await Promise.all(retained);
  }
  await expect(value(page)).toHaveValue("3");
  await expect(
    page.getByRole("region", { name: "Simulation file summary" }),
  ).toContainText("unexported");
  expect(downloads).toBe(0);
});
for (const fault of ["missing", "wrong"])
  test(`${fault} request proof cannot acknowledge a correct artifact`, async ({
    page,
  }) => {
    await openSimulation(page);
    await value(page).fill("256");
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/api/caf/*/simulation", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const response = await route.fetch({ maxRetries: 0 }),
        body = await response.body(),
        headers = { ...response.headers() };
      if (fault === "missing")
        delete headers["x-studio-simulation-request-sha256"];
      else headers["x-studio-simulation-request-sha256"] = "0".repeat(64);
      await route.fulfill({ response, body, headers });
    });
    await page
      .getByRole("button", { name: "Export simulation CAF", exact: true })
      .click();
    await expect(
      page.locator(".caf-simulation").getByRole("alert"),
    ).toContainText("requested simulation values");
    await expect(value(page)).toHaveValue("256");
    expect(downloads).toBe(0);
  });
test("fresh matching request proof permits no-op and changed copies with distinct proposal hashes", async ({
  page,
}) => {
  await openSimulation(page);
  const responses: Record<string, string>[] = [];
  page.on("response", (r) => {
    if (r.request().method() === "POST" && /\/simulation$/.test(r.url()))
      responses.push(r.headers());
  });
  const original = await exported(page);
  await value(page).fill("65536");
  const changed = await exported(page);
  expect(readFileSync((await original.path())!)).not.toEqual(
    readFileSync((await changed.path())!),
  );
  expect(responses).toHaveLength(2);
  expect(responses[0]["x-studio-simulation-request-sha256"]).toMatch(
    /^[a-f0-9]{64}$/,
  );
  expect(responses[0]["x-studio-simulation-request-sha256"]).not.toBe(
    responses[1]["x-studio-simulation-request-sha256"],
  );
  await expect(
    page.locator(".caf-simulation").getByRole("status"),
  ).toContainText("JCI execution remains unverified");
});
