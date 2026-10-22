import { test, expect } from "@playwright/test";

const statement =
  "File data flushed; namespace/power-loss durability unverified on Windows.";

test("capture durability profiles stay visible without opening a field interface", async ({ page }) => {
  const mutations: string[] = [];
  page.on("request", request => {
    if (request.url().includes("/api/bacnet/") && request.method() !== "GET")
      mutations.push(request.url());
  });
  await page.route("**/api/bacnet/history/status", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), storage: {
      platform: "nt", directory_flush: false, durability: statement,
    } } });
  });
  await page.route("**/api/bacnet/files/status", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), storage: {
      platform: "nt", directory_flush: false, durability: statement,
    } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Device history", exact: true }).click();
  await expect(page.getByLabel("History storage durability")).toContainText(statement);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByLabel("File capture storage durability")).toContainText(statement);
  expect(mutations).toEqual([]);
});
