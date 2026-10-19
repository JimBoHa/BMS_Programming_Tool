import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("inspect unknown protected BOG resources and export every original byte", async ({
  page,
}) => {
  const root = path.resolve("..");
  const original = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_niagara_api import opaque_archive; import sys; sys.stdout.buffer.write(opaque_archive())",
    ],
    { cwd: root },
  );
  await page.goto("/");
  await page.getByRole("button", { name: "BOG files", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Niagara BOG archive inspector",
    exact: true,
  });
  await panel.locator('input[type=file][accept=".bog,.xml"]').setInputFiles({
    name: "protected-native.bog",
    mimeType: "application/octet-stream",
    buffer: original,
  });
  await expect(
    panel.getByRole("region", { name: "BOG archive metadata", exact: true }),
  ).toContainText("Protected content is retained");
  await panel
    .getByText("Inspect preserved archive members", { exact: true })
    .click();
  await expect(panel.locator(".niagara-members")).toContainText("unknown.bin");
  await expect(
    panel.getByRole("region", {
      name: "Unmodeled native records",
      exact: true,
    }),
  ).toContainText("vendor:HiddenProgram");
  await panel
    .getByLabel("Search BOG components", { exact: true })
    .fill("CustomProgram");
  await expect(panel.locator(".niagara-component-table tbody tr")).toHaveCount(
    1,
  );
  await expect(panel.locator(".niagara-component-table")).toContainText(
    "PrivateLogic",
  );
  await panel
    .getByLabel("Search BOG links", { exact: true })
    .fill("PrivateLogic");
  await expect(panel.locator(".niagara-link-table tbody tr")).toHaveCount(1);
  await expect(panel.locator(".niagara-link-table")).toContainText(
    "Resolved locally",
  );
  await panel
    .getByRole("button", { name: "Reload archive details", exact: true })
    .click();
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export original BOG bytes", exact: true })
    .click();
  const file = await pending;
  expect(file.suggestedFilename()).toBe("original-protected-native.bog");
  expect(
    execFileSync("/bin/cat", [(await file.path())!]).equals(original),
  ).toBe(true);
  await expect(panel.getByRole("status")).toContainText(
    "protected content are preserved",
  );
  await page.screenshot({
    path: "test-results/studio-niagara-inspector.png",
    fullPage: true,
  });
});

test("inspect an unresolved native XML link without opening a station connection", async ({
  page,
  request,
}) => {
  const original = Buffer.from(
    '<bajaObjectGraph version="4.0"><p h="1" n="ExternalResult" m="b=baja" t="control:NumericWritable"><p n="Link" t="b:Link"><p n="sourceOrd" v="foxs://192.0.2.1/slot:/RemotePoint"/><p n="sourceSlotName" v="out"/><p n="targetSlotName" v="in16"/></p></p></bajaObjectGraph>',
  );
  await page.goto("/");
  await page.getByRole("button", { name: "BOG files", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Niagara BOG archive inspector",
    exact: true,
  });
  await panel.locator('input[type=file][accept=".bog,.xml"]').setInputFiles({
    name: "unresolved.xml",
    mimeType: "application/xml",
    buffer: original,
  });
  await expect(panel.locator(".stat-grid")).toContainText("Raw XML");
  await panel
    .getByLabel("Search BOG links", { exact: true })
    .fill("unresolved");
  await expect(panel.locator(".niagara-link-table")).toContainText(
    "Unresolved · retained",
  );
  await expect(panel.locator(".niagara-link-table")).toContainText(
    "foxs://192.0.2.1/slot:/RemotePoint",
  );
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export original BOG bytes", exact: true })
    .click();
  const file = await pending;
  expect(file.suggestedFilename()).toBe("original-unresolved.xml");
  expect(
    execFileSync("/bin/cat", [(await file.path())!]).equals(original),
  ).toBe(true);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
