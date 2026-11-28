import type { Page } from "@playwright/test";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";

/** Reach the existing monitoring tasks through the controller-workspace shell. */
export async function openMonitoring(
  page: Page,
  tool: "Field recording" | "Controller history",
) {
  await chooseWorkspaceSurface(page, "Workspace");
  await chooseWorkspaceTask(page, "Trends & Alarms");
  await chooseWorkspaceTool(page, tool);
}
