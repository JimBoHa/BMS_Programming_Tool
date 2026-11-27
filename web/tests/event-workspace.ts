import { expect, type Page } from "@playwright/test";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { freePort } from "./workflow-peer";

export async function showControllerEvents(page: Page) {
  await chooseWorkspaceTask(page, "Trends & Alarms");
  await chooseWorkspaceTool(page, "Controller monitoring");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  const select = tools.getByRole("combobox", {
    name: "Controller task tools",
    exact: true,
  });
  if (await select.isVisible())
    await select.selectOption({ label: "Controller events" });
  else
    await tools
      .getByRole("button", { name: "Controller events", exact: true })
      .click();
  return page.getByRole("region", { name: "BACnet field events", exact: true });
}

export async function selectEventController(page: Page, port: number) {
  const address = `127.0.0.1:${port}`;
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  const form = page.getByRole("region", {
    name: "Known controller connection",
    exact: true,
  });
  await form
    .getByLabel("Known controller address", { exact: true })
    .fill(address);
  await form
    .getByLabel("Known Device object", { exact: true })
    .fill("device,4190096");
  await form.getByLabel("Known router", { exact: true }).fill("");
  await form.getByLabel("Known network", { exact: true }).fill("");
  await form
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored event peer");
  await expect(page.getByLabel("Working context")).toContainText(address);
  const panel = await showControllerEvents(page);
  await expect(
    panel.getByRole("button", { name: "Query device events", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByLabel("Event device address", { exact: true }),
  ).toHaveCount(0);
  return panel;
}

export async function openEventController(page: Page, port: number) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  return selectEventController(page, port);
}
