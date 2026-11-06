import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import {
  seedBatchCapabilities,
  inspect,
  analyze,
} from "./native-batch-capability-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

const extended = (p: Locator) =>
  p.getByLabel(
    "Include combined default/connection and terminal operation support",
    { exact: true },
  );
const batch = (p: Locator) =>
  p.getByLabel("Include typed default batch compilation support", {
    exact: true,
  });
const table = (p: Locator) =>
  p.getByRole("table", { name: "Native backup operations", exact: true });
async function enter(page: Page, data: any, kind = "valid", caf = false) {
  await page.goto("/");
  if (caf) {
    const selecting = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await selecting
    ).setFiles({
      name: "batch-support.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("batch-support.caf");
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
    .selectOption(data.cases[kind].id);
  return { compiler, support: await inspect(compiler) };
}
async function include(support: Locator) {
  await analyze(support);
  await extended(support).check();
  await expect(table(support).getByRole("row")).toHaveCount(37);
  await batch(support).check();
  await expect(table(support).getByRole("row")).toHaveCount(38);
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} batch support preserves the raw draft and exact report`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory),
      { compiler, support } = await enter(page, data, "valid", caf);
    await compiler
      .getByRole("button", { name: "Open retained backup", exact: true })
      .click();
    await compiler
      .getByLabel("Native Real default", { exact: true })
      .selectOption("controller/575_1.2_12");
    const draft = compiler.getByLabel("Proposed native Real default", {
      exact: true,
    });
    await draft.fill("12.");
    let received!: (v: Buffer) => void;
    const response = new Promise<Buffer>((resolve) => (received = resolve));
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/20"))
        return route.continue();
      const original = await route.fetch(),
        bytes = await original.body();
      received(bytes);
      await route.fulfill({ response: original, body: bytes });
    });
    await include(support);
    const body = await response;
    expect(body.byteLength).toBeGreaterThan(0);
    const row = table(support).locator(
      '[data-operation="typed-default-batch-compile"]',
    );
    await expect(row).toContainText("source qualified");
    await expect(row).toContainText(
      "5 actual changes among 5 recorded defaults",
    );
    await expect(row).toContainText("Batch field deployment");
    await expect(draft).toHaveValue("12.");
    await expect(support.getByRole("button", { name: /Apply/ })).toHaveCount(0);
    const downloading = page.waitForEvent("download");
    await support
      .getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      })
      .click();
    expect(
      (await readFile((await (await downloading).path())!)).equals(body),
    ).toBe(true);
    await row.scrollIntoViewIfNeeded();
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
        caf ? "batch-capability-phone.png" : "batch-capability-desktop.png",
      ),
    });
    await batch(support).uncheck();
    await expect(table(support).getByRole("row")).toHaveCount(37);
    await extended(support).uncheck();
    await expect(table(support).getByRole("row")).toHaveCount(28);
    await expect(batch(support)).toHaveCount(0);
    await expect(draft).toHaveValue("12.");
    expect(
      (
        await (
          await request.get(nativeScheduleWriteServer.url + "/api/session")
        ).json()
      ).field_network_open,
    ).toBe(false);
  });
for (const kind of [
  "serial",
  "unknown",
  "unverified",
  "empty",
  "large",
  "boolean",
  "enum",
])
  test(`actual ${kind} source keeps batch support separate from field transport`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory),
      { support } = await enter(page, data, kind);
    await include(support);
    await expect(
      table(support).locator('[data-operation="archive-read"]'),
    ).toContainText("source qualified");
    await expect(
      table(support).locator('[data-operation="typed-default-batch-compile"]'),
    ).toContainText(
      ["serial", "large", "boolean", "enum"].includes(kind)
        ? "source qualified"
        : "unsupported source",
    );
    if (kind === "large")
      await expect(table(support)).toContainText(
        "16 actual changes among 25 recorded defaults",
      );
  });
for (const kind of ["witness", "prefix", "authority"])
  test(`altered batch ${kind} response cannot replace the source table`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/20"))
        return route.continue();
      const response = await route.fetch(),
        value = await response.json();
      if (kind === "witness")
        value.qualification.typed_default_batch.witness.compilation.both_orders_identical = false;
      if (kind === "prefix") value.operations[0].id = "substituted";
      if (kind === "authority") value.can_apply = true;
      await route.fulfill({ response, json: value });
    });
    const { support } = await enter(page, data);
    await analyze(support);
    await extended(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(37);
    await batch(support).check();
    await expect(support.getByRole("alert")).toContainText(
      "differs from the selected source",
    );
    await expect(table(support)).toHaveCount(0);
    await expect(
      support.getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      }),
    ).toHaveCount(0);
    await batch(support).uncheck();
    await expect(table(support).getByRole("row")).toHaveCount(37);
  });
test("coalesced batch mode A B A retires a prior exact download before paint", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchCapabilities(nativeScheduleWriteServer.directory),
    { support } = await enter(page, data);
  await include(support);
  const button = await support
    .getByRole("button", { name: "Save exact operation analysis", exact: true })
    .elementHandle();
  let downloads = 0;
  page.on("download", () => downloads++);
  await batch(support).evaluate((element, button) => {
    (element as HTMLInputElement).click();
    (element as HTMLInputElement).click();
    (button as HTMLElement).click();
  }, button);
  await expect(batch(support)).toBeChecked();
  await expect(table(support).getByRole("row")).toHaveCount(38);
  expect(downloads).toBe(0);
});
test("held batch response cannot replace a newer coalesced A B A report", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
  let release!: () => void,
    held = false,
    fresh!: Buffer;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/inspection/capabilities", async (route) => {
    if (!route.request().postDataJSON().capability_profile.endsWith("/20"))
      return route.continue();
    const original = await route.fetch(),
      body = await original.body();
    if (held) {
      fresh = body;
      return route.fulfill({ response: original, body });
    }
    held = true;
    await gate;
    await route.fulfill({
      response: original,
      body: Buffer.concat([body, Buffer.from("\n \n")]),
    });
  });
  const { support } = await enter(page, data);
  await analyze(support);
  await extended(support).check();
  await expect(table(support).getByRole("row")).toHaveCount(37);
  await batch(support).check();
  await expect.poll(() => held).toBe(true);
  await batch(support).evaluate((element) => {
    (element as HTMLInputElement).click();
    (element as HTMLInputElement).click();
  });
  await expect(table(support).getByRole("row")).toHaveCount(38);
  const late = page.waitForResponse(
    (r) =>
      r.url().endsWith("/inspection/capabilities") &&
      r.request().postDataJSON().capability_profile.endsWith("/20"),
  );
  release();
  await (await late).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  const downloading = page.waitForEvent("download");
  await support
    .getByRole("button", { name: "Save exact operation analysis", exact: true })
    .click();
  expect(
    (await readFile((await (await downloading).path())!)).equals(fresh),
  ).toBe(true);
});

for (const change of ["source", "task"])
  test(`held batch result retires when its ${change} changes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
    let release!: () => void,
      held = false;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/20"))
        return route.continue();
      const response = await route.fetch(),
        value = await response.json();
      value.operations.at(-1).basis = "Retired batch source/task result";
      held = true;
      await gate;
      await route.fulfill({ response, json: value });
    });
    const { compiler, support } = await enter(page, data);
    await analyze(support);
    await extended(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(37);
    await batch(support).check();
    await expect.poll(() => held).toBe(true);
    if (change === "source")
      await compiler
        .getByLabel("Retained native backup", { exact: true })
        .selectOption(data.cases.serial.id);
    else {
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
    }
    const late = page.waitForResponse(
      (r) =>
        r.url().endsWith("/inspection/capabilities") &&
        r.request().postDataJSON().capability_profile.endsWith("/20"),
    );
    release();
    await (await late).finished();
    await expect(table(compiler)).toHaveCount(0);
    const current = await inspect(compiler);
    await analyze(current);
    await expect(table(current).getByRole("row")).toHaveCount(28);
    await expect(compiler).not.toContainText(
      "Retired batch source/task result",
    );
  });
