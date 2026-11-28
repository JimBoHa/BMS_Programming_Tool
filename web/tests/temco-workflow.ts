import { expect, type Page } from "@playwright/test";
import { chooseWorkspaceTool } from "./workspace-navigation";

export async function openTemcoProgram(
  page: Page,
  name: string,
  buffer: Buffer,
) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await (
    await chooser
  ).setFiles({ name, mimeType: "application/json", buffer });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Untitled program",
  );
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await chooseWorkspaceTool(page, "Temco");
}
