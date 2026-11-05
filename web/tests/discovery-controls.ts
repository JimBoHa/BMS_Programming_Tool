import type { Locator } from "@playwright/test";

/** Advanced protocol controls stay available without crowding the normal flow. */
export async function openDiscoveryDetails(panel: Locator, name: string) {
  const summary = panel.getByText(name, { exact: true });
  const details = summary.locator("..");
  if ((await details.getAttribute("open")) === null) await summary.click();
}
