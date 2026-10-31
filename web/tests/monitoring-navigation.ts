import type { Page } from "@playwright/test";

/** Reach the existing monitoring tasks through the controller-workspace shell. */
export async function openMonitoring(
  page: Page,
  tool: "Field recording" | "Controller history",
) {
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Trends & Alarms", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: tool, exact: true })
    .click();
}
