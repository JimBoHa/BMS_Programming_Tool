import { test, expect } from "@playwright/test";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";

const statement =
  "File data flushed; namespace/power-loss durability unverified on Windows.";

test("capture durability profiles stay visible without opening a field interface", async ({
  page,
}) => {
  const mutations: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/bacnet/") && request.method() !== "GET")
      mutations.push(request.url());
  });
  await page.route("**/api/bacnet/history/status", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      json: {
        ...(await response.json()),
        storage: {
          platform: "nt",
          directory_flush: false,
          durability: statement,
        },
      },
    });
  });
  await page.route("**/api/bacnet/files/status", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      json: {
        ...(await response.json()),
        storage: {
          platform: "nt",
          directory_flush: false,
          durability: statement,
        },
      },
    });
  });
  await page.goto("/");
  await chooseWorkspaceSurface(page, "History");
  await chooseWorkspaceTool(page, "Controller history", "history tools");
  await expect(page.getByLabel("History storage durability")).toContainText(
    statement,
  );
  await chooseWorkspaceSurface(page, "Workspace");
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "Controller changes");
  await chooseWorkspaceTool(page, "File captures", "Controller task tools");
  await expect(
    page.getByLabel("File capture storage durability"),
  ).toContainText(statement);
  await expect(
    page.getByRole("button", { name: "Inspect advertised files" }),
  ).toBeDisabled();
  expect(mutations).toEqual([]);
});
