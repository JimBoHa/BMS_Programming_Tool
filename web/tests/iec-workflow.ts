import { expect, type Page } from "@playwright/test";
import { chooseWorkspaceTool } from "./workspace-navigation";

export async function startGraphImport(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
}

export async function importGraphFile(
  page: Page,
  name: string,
  buffer: Buffer,
) {
  const file = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  const imported = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/import") &&
      response.request().method() === "POST",
  );
  await (await file).setFiles({ name, mimeType: "application/json", buffer });
  expect((await imported).status()).toBe(200);
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}

export async function showIecVerification(page: Page) {
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await chooseWorkspaceTool(page, "IEC verification");
}
