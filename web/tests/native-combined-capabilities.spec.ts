import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import {
  seedCombinedCapabilities,
  inspect,
  analyze,
} from "./native-combined-capability-fixture";
import { openNativeCompiler } from "./workspace-navigation";

const checkbox = (panel: Locator) =>
  panel.getByLabel(
    "Include combined default/connection and terminal operation support",
    { exact: true },
  );
const tableFor = (panel: Locator) =>
  panel.getByRole("table", { name: "Native backup operations", exact: true });
async function enter(page: Page, data: any, variant = "valid", caf = false) {
  await page.goto("/");
  if (caf) {
    const selecting = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await selecting
    ).setFiles({
      name: "combined-support.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("combined-support.caf");
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
    .selectOption(data.cases[variant].id);
  return { compiler, support: await inspect(compiler) };
}
async function include(panel: Locator) {
  await analyze(panel);
  await checkbox(panel).check();
  await expect(tableFor(panel).getByRole("row")).toHaveCount(37);
  return tableFor(panel);
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} source-specific combined support keeps the draft and downloads exact evidence`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const data = seedCombinedCapabilities(nativeScheduleWriteServer.directory),
      { compiler, support } = await enter(page, data, "valid", caf);
    const draft = compiler.getByLabel("Proposed native Real default", {
      exact: true,
    });
    await compiler
      .getByRole("button", { name: "Open retained backup", exact: true })
      .click();
    await compiler
      .getByLabel("Native Real default", { exact: true })
      .selectOption("controller/575_1.2_12");
    await draft.fill("12.");
    await analyze(support);
    let received!: (body: Buffer) => void;
    const response = new Promise<Buffer>((resolve) => (received = resolve));
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/19"))
        return route.continue();
      const original = await route.fetch(),
        body = await original.body();
      received(body);
      await route.fulfill({ response: original, body });
    });
    await checkbox(support).check();
    const body = await response,
      table = tableFor(support);
    expect(body.byteLength).toBeGreaterThan(0);
    await expect(table.getByRole("row")).toHaveCount(37);
    await expect(
      table.locator('[data-operation="combined-default-wire-compile"]'),
    ).toContainText("source qualified");
    await expect(
      table.locator('[data-operation="combined-default-wire-transfer"]'),
    ).toContainText("preflight required");
    await expect(draft).toHaveValue("12.");
    await expect(support.getByRole("button", { name: /Apply/ })).toHaveCount(0);
    const downloading = page.waitForEvent("download");
    await support
      .getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      })
      .click();
    const download = await downloading;
    expect((await readFile((await download.path())!)).equals(body)).toBe(true);
    await checkbox(support).focus();
    await expect(checkbox(support)).toBeFocused();
    await table
      .locator('[data-operation="combined-default-wire-compile"]')
      .scrollIntoViewIfNeeded();
    const viewport = support.getByRole("region", {
      name: "Native backup operation table viewport",
      exact: true,
    });
    await viewport.focus();
    await expect(viewport).toBeFocused();
    if (caf) {
      await page.keyboard.press("ArrowRight");
      await expect
        .poll(() => viewport.evaluate((element) => element.scrollLeft))
        .toBeGreaterThan(0);
      await page.keyboard.press("ArrowLeft");
      await expect
        .poll(() => viewport.evaluate((element) => element.scrollLeft))
        .toBe(0);
    }
    await page.screenshot({
      path: info.outputPath(
        caf
          ? "combined-capability-phone.png"
          : "combined-capability-desktop.png",
      ),
    });
    await checkbox(support).uncheck();
    await expect(tableFor(support).getByRole("row")).toHaveCount(28);
    await expect(draft).toHaveValue("12.");
    expect(
      (
        await (
          await request.get(nativeScheduleWriteServer.url + "/api/session")
        ).json()
      ).field_network_open,
    ).toBe(false);
  });
for (const kind of ["unknown", "serial"])
  test(`combined ${kind} support separates readable source from field preflight`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedCombinedCapabilities(nativeScheduleWriteServer.directory),
      { support } = await enter(page, data, kind),
      table = await include(support);
    await expect(
      table.locator('[data-operation="archive-read"]'),
    ).toContainText("source qualified");
    await expect(
      table.locator('[data-operation="combined-default-wire-compile"]'),
    ).toContainText(
      kind === "unknown" ? "unsupported source" : "source qualified",
    );
    await expect(
      table.locator('[data-operation="combined-default-wire-transfer"]'),
    ).toContainText(
      kind === "unknown" ? "unsupported source" : "transport unavailable",
    );
  });
for (const kind of ["witness", "prefix", "authority"])
  test(`altered combined ${kind} response cannot replace the source table`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedCombinedCapabilities(nativeScheduleWriteServer.directory);
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/19"))
        return route.continue();
      const response = await route.fetch(),
        value = await response.json();
      if (kind === "witness")
        value.qualification.combined_default_wire.witness.compilation.both_orders_identical = false;
      if (kind === "prefix") value.operations[0].id = "substituted";
      if (kind === "authority") value.can_apply = true;
      await route.fulfill({ response, json: value });
    });
    const { support } = await enter(page, data);
    await analyze(support);
    await checkbox(support).check();
    await expect(support.getByRole("alert")).toContainText(
      "differs from the selected source",
    );
    await expect(tableFor(support)).toHaveCount(0);
    await expect(
      support.getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      }),
    ).toHaveCount(0);
    await checkbox(support).uncheck();
    await expect(tableFor(support).getByRole("row")).toHaveCount(28);
  });
test("coalesced analysis mode A B A retires an old download before paint", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedCombinedCapabilities(nativeScheduleWriteServer.directory),
    { support } = await enter(page, data);
  await analyze(support);
  const button = await support
    .getByRole("button", { name: "Save exact operation analysis", exact: true })
    .elementHandle();
  let downloads = 0;
  page.on("download", () => downloads++);
  await checkbox(support).evaluate((element, button) => {
    (element as HTMLInputElement).click();
    (element as HTMLInputElement).click();
    (button as HTMLElement).click();
  }, button);
  await expect(checkbox(support)).not.toBeChecked();
  await expect(tableFor(support).getByRole("row")).toHaveCount(28);
  expect(downloads).toBe(0);
});
test("a held retired combined result cannot replace a newer mode A B A analysis", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedCombinedCapabilities(nativeScheduleWriteServer.directory);
  let release!: () => void,
    held = false;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/inspection/capabilities", async (route) => {
    if (
      !route.request().postDataJSON().capability_profile.endsWith("/19") ||
      held
    )
      return route.continue();
    held = true;
    const response = await route.fetch(),
      value = await response.json();
    value.operations.at(-2).basis = "Retired combined request marker";
    await gate;
    await route.fulfill({ response, json: value });
  });
  const { support } = await enter(page, data);
  await analyze(support);
  await checkbox(support).check();
  await expect.poll(() => held).toBe(true);
  await checkbox(support).uncheck();
  await expect(tableFor(support).getByRole("row")).toHaveCount(28);
  await checkbox(support).check();
  await expect(tableFor(support).getByRole("row")).toHaveCount(37);
  const old = page.waitForResponse(
    (r) =>
      r.url().endsWith("/inspection/capabilities") &&
      r.request().postDataJSON().capability_profile.endsWith("/19"),
  );
  release();
  await old;
  await expect(tableFor(support)).not.toContainText(
    "Retired combined request marker",
  );
});
