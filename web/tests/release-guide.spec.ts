import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

test("illustrated guide uses a fresh offline workspace and an authored CAF", async ({
  page,
  request,
}, info) => {
  const directory = process.env.BMS_DOC_SCREENSHOTS || info.outputDir;
  mkdirSync(directory, { recursive: true });
  const calls: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/api/bacnet/"))
      calls.push(req.url());
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: /^Connect to a controller/ }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(directory, "start.png"),
    fullPage: true,
  });
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await chooser
  ).setFiles({
    name: "Example-application.caf",
    mimeType: "application/octet-stream",
    buffer,
  });
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Logic", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Native CAF graph", exact: true }),
  ).toContainText("4 blocks · 2 connections");
  await page
    .getByRole("button", { name: "Expand logic view", exact: true })
    .click();
  await page.getByRole("button", { name: "Fit diagram", exact: true }).click();
  await expect(page.locator(".engineering-node").first()).toBeVisible();
  await page.screenshot({
    path: path.join(directory, "offline-caf.png"),
    fullPage: true,
  });
  expect(calls).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
