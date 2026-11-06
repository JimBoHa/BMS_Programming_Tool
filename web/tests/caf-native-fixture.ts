import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../..", import.meta.url));

export function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      encoding: "utf8",
    },
  );
}

export function panel(page: Page) {
  return page.getByRole("region", {
    name: "CAF/native source comparison",
    exact: true,
  });
}

export async function compatibility(page: Page) {
  await page
    .getByRole("navigation", { name: "CAF application tasks", exact: true })
    .waitFor({ state: "visible" });
  const compact = page.getByRole("combobox", {
    name: "CAF application tasks",
    exact: true,
  });
  if (await compact.isVisible())
    await compact.selectOption({ label: "Compatibility" });
  else
    await page
      .getByRole("navigation", { name: "CAF application tasks", exact: true })
      .getByRole("button", { name: "Compatibility", exact: true })
      .click();
  const result = panel(page),
    disclosure = result.locator(":scope > details");
  if ((await disclosure.getAttribute("open")) === null)
    await disclosure.locator(":scope > summary").click();
  return result;
}

export async function chooseFile(
  page: Page,
  encoded: string,
  name = "authored.caf",
) {
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: Buffer.from(encoded, "base64"),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText(name);
}

export async function enterCafComparison(page: Page, encoded: string) {
  await page.goto("/");
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name: "authored.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(encoded, "base64"),
  });
  const p = await compatibility(page);
  return p;
}
