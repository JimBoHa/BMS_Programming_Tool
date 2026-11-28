import { type Page } from "@playwright/test";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTool,
} from "./workspace-navigation";

/** Exercise the current workspace navigation rather than historical feature tiles. */
export async function openCommunicationTool(page: Page, name: string) {
  await chooseWorkspaceSurface(page, "Settings");
  await chooseWorkspaceTool(page, "Communications & network", "settings tools");
  await chooseWorkspaceTool(page, name, "Controller task tools");
}

export async function openConnectionDetails(page: Page) {
  await openCommunicationTool(page, "BACnet/IP connection");
  const summary = page.getByText("Advanced connection settings", {
    exact: true,
  });
  if ((await summary.locator("..").getAttribute("open")) === null)
    await summary.click();
}
