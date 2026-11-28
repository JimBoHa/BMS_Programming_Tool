import { expect, type Page } from "@playwright/test";

export async function openCurrentGraph(page: Page) {
  await page.goto("/");
  await page
    .getByRole("region", { name: "Continue local work" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
}

export async function importGraphFile(
  page: Page,
  file: {
    name: string;
    mimeType: string;
    buffer: Buffer;
  },
) {
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  const receipt = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/import" &&
      r.request().method() === "POST",
  );
  await (await choosing).setFiles(file);
  expect((await receipt).status()).toBe(200);
}

export async function closeBlockProperties(page: Page) {
  const close = page.getByRole("button", {
    name: "Close block properties",
    exact: true,
  });
  if (await close.isVisible()) await close.click();
}

export async function showBlockProperties(page: Page) {
  const open = page.getByRole("button", {
    name: "Open block properties",
    exact: true,
  });
  if (
    (await open.isVisible()) &&
    !(await page
      .getByRole("dialog", { name: "Block properties", exact: true })
      .isVisible())
  )
    await open.click();
}

export async function graphSimulation(page: Page) {
  await closeBlockProperties(page);
  const mode = page.getByRole("button", { name: "Simulate", exact: true });
  await mode.click();
  await expect(mode).toHaveAttribute("aria-pressed", "true");
}

export async function openBlockLibrary(page: Page) {
  const open = page.getByRole("button", {
    name: "Open block library",
    exact: true,
  });
  if (await open.isVisible()) await open.click();
}
