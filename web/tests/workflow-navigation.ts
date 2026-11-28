import { expect, type Page } from "@playwright/test";
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

export async function selectKnownController(
  page: Page,
  address: string,
  device: string,
  route?: { router: string; dnet: number },
) {
  await chooseWorkspaceSurface(page, "Start");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  const form = page.getByRole("region", {
    name: "Known controller connection",
  });
  await form
    .getByLabel("Known controller address", { exact: true })
    .fill(address);
  await form.getByLabel("Known Device object", { exact: true }).fill(device);
  if (route) {
    await form.getByLabel("Known router", { exact: true }).fill(route.router);
    await form
      .getByLabel("Known network", { exact: true })
      .fill(String(route.dnet));
  }
  await form
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText(device);
}
