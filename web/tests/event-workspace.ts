import { expect, type Page } from "@playwright/test";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { freePort } from "./workflow-peer";

export async function showControllerMonitor(
  page: Page,
  label: "Controller events" | "Live COV monitor",
) {
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
  if (await select.isVisible()) await select.selectOption({ label });
  else await tools.getByRole("button", { name: label, exact: true }).click();
}

export async function showControllerEvents(page: Page) {
  await showControllerMonitor(page, "Controller events");
  return page.getByRole("region", { name: "BACnet field events", exact: true });
}

export async function selectKnownMonitoringController(
  page: Page,
  address: string,
  device: string,
  router = "",
  network = "",
) {
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
  await form.getByLabel("Known Device object", { exact: true }).fill(device);
  await form.getByLabel("Known router", { exact: true }).fill(router);
  await form.getByLabel("Known network", { exact: true }).fill(network);
  await form
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toBeVisible();
  await expect(page.getByLabel("Working context")).toContainText(address);
}

export async function selectEventController(page: Page, port: number) {
  await selectKnownMonitoringController(
    page,
    `127.0.0.1:${port}`,
    "device,4190096",
  );
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored event peer");
  const panel = await showControllerEvents(page);
  await expect(
    panel.getByRole("button", { name: "Query device events", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByLabel("Event device address", { exact: true }),
  ).toHaveCount(0);
  return panel;
}

export async function openMonitoringInterface(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  const bbmd = page.getByLabel("BBMD address / UDP port (optional)", {
    exact: true,
  });
  if (!(await bbmd.isVisible())) {
    await page
      .getByText("Advanced connection settings", { exact: true })
      .click();
  }
  // A previous foreign-device or routed connection can be saved across browser contexts.
  await bbmd.fill("");
  await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
  await page
    .getByLabel("MS/TP destination network (optional)", { exact: true })
    .fill("");
  const opening = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/bacnet/connect") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  expect((await opening).ok()).toBe(true);
  await expect(
    page.getByRole("button", { name: "Known controller address", exact: true }),
  ).toBeEnabled();
}

export async function openEventController(page: Page, port: number) {
  await openMonitoringInterface(page);
  return selectEventController(page, port);
}
