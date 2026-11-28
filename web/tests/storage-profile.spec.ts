import { test, expect, type Page } from "@playwright/test";
import { chooseWorkspaceSurface } from "./workspace-navigation";

async function chooseHistoryTool(page: Page, name: string) {
  const tools = page.getByRole("navigation", { name: "history tools", exact: true });
  await expect(tools).toBeVisible();
  const choice = tools.getByRole("combobox");
  if (await choice.isVisible()) await choice.selectOption({ label: name });
  else await tools.getByRole("button", { name, exact: true }).click();
}

const statement =
  "File data flushed; namespace/power-loss durability unverified on Windows.";

test("capture durability profiles stay visible without opening a field interface", async ({ page, request }) => {
  const nonGet: string[] = [];
  const listPath = "/api/bacnet/controller/native-application/backup-library/list";
  page.on("request", request => {
    if (request.url().includes("/api/bacnet/") && request.method() !== "GET")
      nonGet.push(new URL(request.url()).pathname);
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
  await chooseWorkspaceSurface(page, "History");
  await chooseHistoryTool(page, "Controller history");
  await expect(page.getByLabel("History storage durability")).toContainText(statement);
  const listing = page.waitForResponse(r => new URL(r.url()).pathname === listPath);
  await chooseHistoryTool(page, "Native backups");
  expect((await (await listing).json()).read_only).toBe(true);
  await page.getByText("Saved BACnet file captures", { exact: true }).click();
  await expect(page.getByLabel("File capture storage durability")).toContainText(statement);
  await expect(page.getByRole("button", { name: "Inspect advertised files" })).toHaveCount(0);
  expect(nonGet).toEqual([listPath]);
  expect((await (await request.get("/api/bacnet/status")).json()).connected).toBe(false);
});
