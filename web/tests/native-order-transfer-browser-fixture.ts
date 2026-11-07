import { expect, type Page } from "@playwright/test";
import { freePort } from "./workflow-peer";
import { openNativeCompiler } from "./workspace-navigation";
import { openOrder, stageOrder } from "./native-execution-order-fixture";

export async function openOrderTransfer(
  page: Page,
  endpoint: string,
  routed: boolean,
  resume?: string,
) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  if (!resume) {
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
  }
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(routed ? "3001:7" : endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page
    .getByLabel("Known router", { exact: true })
    .fill(routed ? endpoint : "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored native wire controller");
  await openNativeCompiler(page);
  const shared = page.getByRole("region", {
    name: "Native default controller transfer",
    exact: true,
  });
  if (!resume) {
    await shared
      .getByText("Native backup and restore credentials", { exact: true })
      .click();
    await shared
      .getByLabel("Native backup credential", { exact: true })
      .fill("authored-backup");
    await shared
      .getByLabel("Native restore credential", { exact: true })
      .fill("authored-restore");
    await shared
      .getByRole("button", {
        name: "Save native transfer credentials",
        exact: true,
      })
      .click();
    await expect(
      shared.getByLabel("Native backup credential", { exact: true }),
    ).toHaveValue("");
    await shared
      .getByRole("button", { name: "Read current native backup", exact: true })
      .click();
    await expect(
      page.getByLabel("Native compiler snapshot source", { exact: true }),
    ).toContainText("3 saved application parameters");
  }
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  if (resume)
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(resume);
  const { panel: editor } = await openOrder(page, compiler);
  await stageOrder(page);

  await editor
    .getByLabel("Native execution-order destination", { exact: true })
    .selectOption("controller");
  const transfer = editor.getByRole("region", {
    name: "Native execution-order controller transfer",
    exact: true,
  });
  await expect(
    transfer.getByRole("button", {
      name: "Review execution-order transfer",
      exact: true,
    }),
  )[resume ? "toBeDisabled" : "toBeEnabled"]();
  return { compiler, editor, transfer };
}
