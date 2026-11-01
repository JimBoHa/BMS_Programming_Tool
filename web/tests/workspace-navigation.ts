import { expect, type Page } from "@playwright/test";

/** Use the visible desktop or compact control for the same workspace action. */
export async function chooseWorkspaceTask(page: Page, label: string) {
  const navigation = page.getByRole("navigation", {
    name: "Workspace tasks",
    exact: true,
  });
  const select = navigation.getByRole("combobox", {
    name: "Workspace task",
    exact: true,
  });
  if (await select.isVisible()) await select.selectOption({ label });
  else
    await navigation.getByRole("button", { name: label, exact: true }).click();
}

export async function chooseWorkspaceTool(page: Page, label: string) {
  const navigation = page.getByRole("navigation", {
    name: "Current task tools",
    exact: true,
  });
  const select = navigation.getByRole("combobox", {
    name: "Current task tools",
    exact: true,
  });
  if (await select.isVisible()) await select.selectOption({ label });
  else
    await navigation.getByRole("button", { name: label, exact: true }).click();
}

export async function openNativeCompiler(page: Page) {
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTool(page, "Native backup defaults");
}

export async function expectWorkspaceNavigationLocked(page: Page) {
  await expect(
    page
      .getByRole("navigation", {
        name: "Main navigation",
        exact: true,
        includeHidden: true,
      })
      .getByRole("button", {
        name: "Library",
        exact: true,
        includeHidden: true,
      }),
  ).toBeDisabled();
  const menu = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await menu.isVisible()) await expect(menu).toBeDisabled();
  for (const name of ["Workspace task", "Current task tools"]) {
    const select = page.getByRole("combobox", { name, exact: true });
    if (await select.isVisible()) await expect(select).toBeDisabled();
  }
}
