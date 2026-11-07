import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import {
  seedOrderCapabilities,
  inspect,
  analyze,
} from "./native-order-capability-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

const table = (p: Locator) =>
  p.getByRole("table", { name: "Native backup operations", exact: true });
const choice = (p: Locator) =>
  p.getByLabel("Include native execution-order support", { exact: true });
async function enter(page: Page, data: any, kind = "valid", caf = false) {
  await page.goto("/");
  if (caf) {
    const selecting = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await selecting
    ).setFiles({
      name: "order-support.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("order-support.caf");
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
  const support = await inspect(compiler);
  await analyze(support);
  return { compiler, support };
}
for (const kind of [
  "valid",
  "serial",
  "bbmd",
  "chain",
  "unknown",
  "unverified",
  "large",
  "refused",
])
  test(`actual ${kind} order source separates local support and field prerequisites`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seedOrderCapabilities(nativeScheduleWriteServer.directory);
    if (kind === "refused")
      await page.route("**/inspection/capabilities", async (route) => {
        if (!route.request().postDataJSON().capability_profile.endsWith("/22"))
          return route.continue();
        const response = await route.fetch({ maxRetries: 0 });
        await route.fulfill({ response, json: data.cases.refused.report });
      });
    const { support } = await enter(page, data, kind);
    // Keep the original case/assertion budgets, but start checking the large
    // report after its actual analysis response rather than while CPU work runs.
    const largeAnalysis =
      kind === "large"
        ? page.waitForResponse(
            (response) =>
              response.url().endsWith("/inspection/capabilities") &&
              response.request().method() === "POST" &&
              response.request().postDataJSON().capability_profile ===
                "native-backup-operation-capabilities/22",
          )
        : null;
    await choice(support).check();
    if (largeAnalysis) {
      const response = await largeAnalysis;
      expect(response.ok()).toBe(true);
      expect(await response.finished()).toBeNull();
    }
    await expect(table(support).getByRole("row")).toHaveCount(30);
    const report = data.cases[kind].report;
    for (const r of report.operations.slice(-2))
      await expect(
        table(support).locator(`[data-operation="${r.id}"]`),
      ).toContainText(r.status.replaceAll("-", " "));
    await expect(
      support.getByRole("button", { name: /Apply|Read back/ }),
    ).toHaveCount(0);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

for (const caf of [false, true])
  test(`${caf ? "CAF" : "new application"} entry preserves exact read-only order analysis`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedOrderCapabilities(nativeScheduleWriteServer.directory);
    let bytes: Buffer | undefined;
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/22"))
        return route.continue();
      const response = await route.fetch({ maxRetries: 0 });
      bytes = await response.body();
      await route.fulfill({ response, body: bytes });
    });
    const { support } = await enter(page, data, "valid", caf);
    await choice(support).check();
    await expect(table(support).getByRole("row")).toHaveCount(30);
    const saved = page.waitForEvent("download");
    await support
      .getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      })
      .click();
    expect(await readFile((await (await saved).path())!)).toEqual(bytes);
    if (caf)
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("order-support.caf");
  });

for (const changed of ["witness", "prefix", "authority"])
  test(`altered ${changed} order capability response grants no interpreted table`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedOrderCapabilities(nativeScheduleWriteServer.directory);
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/22"))
        return route.continue();
      const response = await route.fetch({ maxRetries: 0 }),
        value = await response.json();
      if (changed === "witness")
        value.qualification.execution_order.witness.request.proposed_order = [
          0, 1, 2, 3,
        ];
      if (changed === "prefix") value.operations[0].id = "substituted";
      if (changed === "authority") value.can_apply = true;
      await route.fulfill({ response, json: value });
    });
    const { support } = await enter(page, data);
    await choice(support).check();
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

for (const change of ["source", "task", "mode"])
  test(`held order analysis retires after ${change} changes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedOrderCapabilities(nativeScheduleWriteServer.directory);
    let release = () => {},
      held = false;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**/inspection/capabilities", async (route) => {
      if (!route.request().postDataJSON().capability_profile.endsWith("/22"))
        return route.continue();
      const response = await route.fetch({ maxRetries: 0 }),
        value = await response.json();
      value.operations.at(-1).basis = "Retired order analysis";
      held = true;
      await gate;
      await route.fulfill({ response, json: value });
    });
    try {
      const { compiler, support } = await enter(page, data);
      await choice(support).check();
      await expect.poll(() => held).toBe(true);
      if (change === "source")
        await compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(data.cases.serial.id);
      else if (change === "task") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
      } else await choice(support).uncheck();
      const late = page.waitForResponse(
        (r) =>
          r.url().endsWith("/inspection/capabilities") &&
          r.request().postDataJSON().capability_profile.endsWith("/22"),
      );
      release();
      await (await late).finished();
      await expect(compiler).not.toContainText("Retired order analysis");
      if (change === "mode")
        await expect(table(support).getByRole("row")).toHaveCount(28);
      else await expect(table(compiler)).toHaveCount(0);
    } finally {
      release();
    }
  });

test("coalesced order mode switches reject a cached export handler", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedOrderCapabilities(nativeScheduleWriteServer.directory),
    { support } = await enter(page, data);
  await choice(support).check();
  await expect(table(support).getByRole("row")).toHaveCount(30);
  const old = await support
    .getByRole("button", { name: "Save exact operation analysis", exact: true })
    .elementHandle();
  let downloads = 0;
  page.on("download", () => downloads++);
  await choice(support).evaluate((input, old) => {
    (input as HTMLInputElement).click();
    (input as HTMLInputElement).click();
    (old as HTMLElement).click();
  }, old);
  await expect(table(support).getByRole("row")).toHaveCount(30);
  expect(downloads).toBe(0);
});
