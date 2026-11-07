import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import {
  seedBatchTransferCapabilities as seedBatchCapabilities,
  inspect,
  analyze,
} from "./native-batch-transfer-capability-fixture";
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

for (const kind of [
  "serial",
  "bbmd",
  "unknown",
  "unverified",
  "empty",
  "large",
  "boolean",
  "enum",
  "unfixed",
  "refused",
])
  test(`actual ${kind} source reports precise batch transfer prerequisites`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
    if (kind === "refused")
      await page.route("**/inspection/capabilities", async (route) => {
        if (!route.request().postDataJSON().capability_profile.endsWith("/21"))
          return route.continue();
        const response = await route.fetch({ maxRetries: 0 });
        await route.fulfill({ response, json: data.cases.refused.report });
      });
    const { support } = await enter(page, data, kind);
    await include(support);
    const row = table(support).locator(
      '[data-operation="typed-default-batch-transfer-prerequisites"]',
    );
    await expect(row).toContainText(
      ["serial", "bbmd", "large", "boolean", "enum"].includes(kind)
        ? "source qualified"
        : kind === "refused"
          ? "not evaluated"
          : "unsupported source",
    );
    if (kind === "large")
      await expect(row).toContainText(
        "16 hypothetical changes among 24 candidate defaults (25 recorded)",
      );
    if (kind === "unfixed")
      await expect(row).toContainText(
        "No recorded default has this transfer profile's saved-storage prerequisites",
      );
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    await expect(support.getByRole("button", { name: /Apply/ })).toHaveCount(0);
  });

for (const kind of ["witness", "prefix", "authority"])
  test(`altered transfer preflight ${kind} response grants no interpreted table`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/21"))
        return route.continue();
      const response = await route.fetch({ maxRetries: 0 }),
        value = await response.json();
      if (kind === "witness")
        value.qualification.typed_default_batch_transfer.witness.compilation.batch_guard.fields[0].prior_bits =
          "00000000";
      if (kind === "prefix") value.operations[0].id = "substituted";
      if (kind === "authority") value.can_apply = true;
      await route.fulfill({ response, json: value });
    });
    const { support } = await enter(page, data);
    await analyze(support);
    await extended(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(37);
    await batch(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(38);
    await support
      .getByLabel("Include source prerequisites for typed batch transfer", {
        exact: true,
      })
      .check();
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
  });

test("selected unfixed Enum explains controller prerequisites while local compilation stays available", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchCapabilities(nativeScheduleWriteServer.directory),
    { compiler } = await enter(page, data);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  const editor = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await editor.locator(":scope > summary").click();
  await expect(
    editor.getByRole("table", {
      name: "Native batch default fields",
      exact: true,
    }),
  ).toBeVisible();
  await editor
    .getByLabel("Include controller/enum-1 in batch", { exact: true })
    .check();
  await editor
    .getByLabel("Proposed enum value for controller/enum-1", { exact: true })
    .fill("0");
  const field = editor.getByLabel("Default batch field workflow", {
    exact: true,
  });
  await field.locator(":scope > summary").click();
  await expect(field).toContainText("no captured fixed saved-value slot");
  await expect(
    field.getByRole("button", {
      name: "Review default batch transfer",
      exact: true,
    }),
  ).toBeDisabled();
  await editor
    .getByRole("button", { name: "Review local default batch", exact: true })
    .click();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native default batch",
      exact: true,
    }),
  ).toBeVisible();
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
const transfer = (p: Locator) =>
  p.getByLabel("Include source prerequisites for typed batch transfer", {
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
  await support
    .getByLabel("Include source prerequisites for typed batch transfer", {
      exact: true,
    })
    .check();
  await expect(table(support).getByRole("row")).toHaveCount(39);
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} transfer preflight preserves the raw draft and exact report`, async ({
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
      if (!route.request().postDataJSON().capability_profile.endsWith("/21"))
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
      '[data-operation="typed-default-batch-transfer-prerequisites"]',
    );
    await expect(row).toContainText("source qualified");
    await expect(row).toContainText(
      "4 hypothetical changes among 4 candidate defaults (5 recorded)",
    );
    await expect(row).toContainText("creates no draft");
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
    await support
      .getByLabel("Include source prerequisites for typed batch transfer", {
        exact: true,
      })
      .uncheck();
    await expect(table(support).getByRole("row")).toHaveCount(38);
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
test("coalesced transfer preflight mode A B A retires a prior exact download before paint", async ({
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
  await transfer(support).evaluate((element, button) => {
    (element as HTMLInputElement).click();
    (element as HTMLInputElement).click();
    (button as HTMLElement).click();
  }, button);
  await expect(transfer(support)).toBeChecked();
  await expect(table(support).getByRole("row")).toHaveCount(39);
  expect(downloads).toBe(0);
});
test("held transfer preflight response cannot replace a newer coalesced A B A report", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
  let release!: () => void,
    held = false,
    fresh!: Buffer;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/inspection/capabilities", async (route) => {
    if (!route.request().postDataJSON().capability_profile.endsWith("/21"))
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
  await expect(table(support).getByRole("row")).toHaveCount(38);
  await transfer(support).check();
  await expect.poll(() => held).toBe(true);
  await transfer(support).evaluate((element) => {
    (element as HTMLInputElement).click();
    (element as HTMLInputElement).click();
  });
  await expect(table(support).getByRole("row")).toHaveCount(39);
  const late = page.waitForResponse(
    (r) =>
      r.url().endsWith("/inspection/capabilities") &&
      r.request().postDataJSON().capability_profile.endsWith("/21"),
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
  test(`held transfer preflight result retires when its ${change} changes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchCapabilities(nativeScheduleWriteServer.directory);
    let release!: () => void,
      held = false;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/21"))
        return route.continue();
      const response = await route.fetch(),
        value = await response.json();
      value.operations.at(-1).basis =
        "Retired transfer preflight source/task result";
      held = true;
      await gate;
      await route.fulfill({ response, json: value });
    });
    const { compiler, support } = await enter(page, data);
    await analyze(support);
    await extended(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(37);
    await batch(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(38);
    await transfer(support).check();
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
        r.request().postDataJSON().capability_profile.endsWith("/21"),
    );
    release();
    await (await late).finished();
    await expect(table(compiler)).toHaveCount(0);
    const current = await inspect(compiler);
    await analyze(current);
    await expect(table(current).getByRole("row")).toHaveCount(28);
    await expect(compiler).not.toContainText(
      "Retired transfer preflight source/task result",
    );
  });
