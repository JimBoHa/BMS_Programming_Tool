import { expect, type Page } from "@playwright/test";

/** Exercise the current workspace navigation rather than historical feature tiles. */
export async function openCommunicationTool(page: Page, name: string) {
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Settings", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Communications & network", exact: true })
    .click();
  const tools = page.getByRole("navigation", { name: "Controller task tools" });
  await expect(tools).toBeVisible();
  await tools.getByRole("button", { name, exact: true }).click();
}

export async function openConnectionDetails(page: Page) {
  await openCommunicationTool(page, "BACnet/IP connection");
  const summary = page.getByText("Advanced connection settings", {
    exact: true,
  });
  if ((await summary.locator("..").getAttribute("open")) === null)
    await summary.click();
}

