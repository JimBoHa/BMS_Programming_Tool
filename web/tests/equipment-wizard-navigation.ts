import { expect, type Page } from "@playwright/test";
import { chooseWorkspaceSurface } from "./workspace-navigation";

export async function openEquipmentWizard(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  // Start with an existing graph for the wizard's replace-or-cancel tests.
  await page
    .getByLabel("Choose VAV template", { exact: true })
    .selectOption({ index: 1 });
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
}

export async function reopenWizardProject(page: Page, projectId: string) {
  await page.reload();
  await expect(
    page.getByRole("button", { name: "New application", exact: true }),
  ).toBeVisible();
  await chooseWorkspaceSurface(page, "Workspace");
  await page
    .getByLabel("Open saved project", { exact: true })
    .selectOption(projectId);
}
