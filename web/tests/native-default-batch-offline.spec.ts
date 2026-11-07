import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { seedDefaultBatch } from "./native-default-batch-fixture";
import { openNativeCompiler } from "./workspace-navigation";
async function enter(page: Page, data: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "typed-default-batch.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.id);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/575_1.2_12");
  return compiler;
}
async function expand(compiler: Locator) {
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(
    batch
      .getByRole("table", { name: "Native batch default fields", exact: true })
      .getByRole("row"),
  ).toHaveCount(6);
  return batch;
}
async function propose(batch: Locator, data: any) {
  for (const change of data.body.changes) {
    await batch
      .getByLabel(`Include ${change.record_ref} in batch`, { exact: true })
      .check();
    if (change.kind === "boolean")
      await batch
        .getByLabel(`Proposed Boolean for ${change.record_ref}`, {
          exact: true,
        })
        .setChecked(change.value);
    else
      await batch
        .getByLabel(`Proposed ${change.kind} value for ${change.record_ref}`, {
          exact: true,
        })
        .fill(
          change.kind === "real" ? change.value_text : String(change.value),
        );
  }
}

for (const caf of [false, true])
  test(`${caf ? "CAF" : "new application"} keeps batch compilation offline while controller Apply stays unavailable`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      calls: string[] = [];
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        /native-application\/(capture|readback|default-batch\/transfer)/.test(
          r.url(),
        )
      )
        calls.push(r.url());
    });
    const compiler = await enter(page, data, caf),
      batch = await expand(compiler);
    await propose(batch, data);
    const field = batch.getByLabel("Default batch field workflow", {
      exact: true,
    });
    await field.locator(":scope > summary").click();
    await expect(field).toContainText("Open and verify a controller");
    await expect(
      field.getByRole("button", {
        name: "Review default batch transfer",
        exact: true,
      }),
    ).toBeDisabled();
    await batch
      .getByRole("button", { name: "Review local default batch", exact: true })
      .click();
    await expect(
      batch.getByRole("region", {
        name: "Reviewed native default batch",
        exact: true,
      }),
    ).toBeVisible();
    expect(calls).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
