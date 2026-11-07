import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { seedBatchResultMatch } from "./native-default-batch-result-match-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

async function enter(page: Page, data: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "batch-result-match.caf",
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
    .selectOption(data.opened.capture_id);
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
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(
    batch.getByRole("table", {
      name: "Native batch default fields",
      exact: true,
    }),
  ).toBeVisible();
  const field = batch.getByLabel("Default batch field workflow", {
    exact: true,
  });
  await field.locator(":scope > summary").click();
  const transfer = field.getByRole("region", {
    name: "Native default batch controller transfer",
    exact: true,
  });
  await transfer
    .getByText("Retained default-batch receipts", { exact: true })
    .click();
  await transfer
    .getByLabel("Typed default batch receipt", { exact: true })
    .selectOption(data.id);
  await transfer
    .getByRole("button", { name: "Load default batch receipt", exact: true })
    .click();
  const comparison = transfer.getByRole("region", {
      name: "Retained source result comparison",
      exact: true,
    }),
    compare = comparison.getByRole("button", {
      name: "Compare retained source with recorded result",
      exact: true,
    });
  await expect(compare).toBeVisible();
  return { compiler, batch, field, transfer, comparison, compare, draft };
}
for (const caf of [false, true])
  for (const phone of [false, true])
    test(`${caf ? "CAF" : "controller workspace"} ${phone ? "phone" : "desktop"} compares retained result offline and exports exact JSON`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, testInfo) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
      const data = seedBatchResultMatch(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      let original!: Buffer;
      // Retain actual HTTP bytes before browser consumption and blob download.
      await page.route("**/default-batch/result/compare", async (route) => {
        const response = await route.fetch();
        original = await response.body();
        expect(original.length).toBeGreaterThan(0);
        await route.fulfill({ response, body: original });
      });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      const { comparison, compare, draft } = await enter(page, data, caf),
        response = page.waitForResponse((r) =>
          r.url().endsWith("/default-batch/result/compare"),
        );
      await compare.click();
      const answer = await response;
      await answer.finished();
      await expect(comparison).toContainText(
        "Retained application and effective values match",
      );
      await expect(comparison.getByRole("table").getByRole("row")).toHaveCount(
        5,
      );
      await expect(
        comparison.getByRole("table").getByRole("row").nth(2),
      ).toContainText("-0");
      if (phone) {
        const view = comparison.getByRole("region", {
          name: "Recorded result comparison values viewport",
          exact: true,
        });
        await view.focus();
        await view.press("ArrowRight");
        expect(await view.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
      }
      await comparison.getByRole("table").scrollIntoViewIfNeeded();
      await page.screenshot({
        path: testInfo.outputPath("retained-result-match.png"),
        fullPage: true,
      });
      const download = page.waitForEvent("download");
      await comparison
        .getByRole("button", {
          name: "Save exact result comparison",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(original);
      await expect(draft).toHaveValue("12.");
      expect(calls).toEqual([
        "/api/bacnet/controller/native-application/signal-default/source",
        "/api/bacnet/controller/native-application/inspection/default-batch/source",
        "/api/bacnet/controller/native-application/default-batch/result/compare",
      ]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });
for (const kind of [
  "selected",
  "unselected",
  "historical",
  "recovery",
  "reencoded",
  "routed",
])
  test(`actual ${kind} source displays its independently qualified comparison`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchResultMatch(
        nativeScheduleWriteServer.directory,
        kind,
      ),
      { comparison, compare, draft } = await enter(page, data);
    await compare.click();
    await expect(comparison.getByRole("table")).toBeVisible();
    await expect(comparison).toContainText(
      ["selected", "unselected", "routed"].includes(kind)
        ? "The retained source differs"
        : "Retained application and effective values match",
    );
    await expect(draft).toHaveValue("12.");
  });
for (const change of ["task", "source", "same-receipt"])
  test(`late comparison cannot revive a retired ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchResultMatch(nativeScheduleWriteServer.directory);
    let release!: () => void,
      held = false;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**/default-batch/result/compare", async (route) => {
      const response = await route.fetch(),
        body = await response.body();
      held = true;
      await gate;
      await route.fulfill({ response, body });
    });
    const { compiler, transfer, compare, draft } = await enter(page, data);
    try {
      await compare.click();
      await expect.poll(() => held).toBe(true);
      if (change === "task") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
      } else if (change === "source") {
        await compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(data.receipt.intent.backup_id);
        await compiler
          .getByRole("button", { name: "Open retained backup", exact: true })
          .click();
      } else
        await transfer
          .getByRole("button", {
            name: "Load default batch receipt",
            exact: true,
          })
          .click();
      const late = page.waitForResponse((r) =>
        r.url().endsWith("/default-batch/result/compare"),
      );
      release();
      await (await late).finished();
      await expect(
        page.getByRole("table", {
          name: "Recorded result comparison values",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Save exact result comparison",
          exact: true,
        }),
      ).toHaveCount(0);
      if (change !== "source") await expect(draft).toHaveValue("12.");
    } finally {
      release();
    }
  });
test("coalesced field disclosure blocks the old compare callback before a request", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchResultMatch(nativeScheduleWriteServer.directory),
    { field, compare } = await enter(page, data);
  let calls = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/default-batch/result/compare")) calls++;
  });
  const button = await compare.elementHandle(),
    summary = await field.locator(":scope > summary").elementHandle();
  await page.evaluate(
    ({ button, summary }) => {
      (summary as HTMLElement).click();
      (summary as HTMLElement).click();
      (button as HTMLElement).click();
    },
    { button, summary },
  );
  expect(calls).toBe(0);
  await expect(
    page.getByRole("table", {
      name: "Recorded result comparison values",
      exact: true,
    }),
  ).toHaveCount(0);
});
for (const kind of ["pagehide", "visibility"])
  test(`${kind} retires a cached exact comparison download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchResultMatch(nativeScheduleWriteServer.directory),
      { comparison, compare } = await enter(page, data);
    await compare.click();
    const save = comparison.getByRole("button", {
      name: "Save exact result comparison",
      exact: true,
    });
    await expect(save).toBeVisible();
    const old = await save.elementHandle();
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.evaluate(
      ({ button, kind }) => {
        if (kind === "pagehide") window.dispatchEvent(new Event("pagehide"));
        else document.dispatchEvent(new Event("visibilitychange"));
        (button as HTMLElement).click();
      },
      { button: old, kind },
    );
    await expect(save).toHaveCount(0);
    expect(downloads).toBe(0);
  });
test("altered comparison flags cannot publish values or an exact export", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchResultMatch(nativeScheduleWriteServer.directory);
  await page.route("**/default-batch/result/compare", async (route) => {
    const response = await route.fetch(),
      body = await response.json();
    body.can_apply = true;
    await route.fulfill({ response, json: body });
  });
  const { comparison, compare } = await enter(page, data);
  await compare.click();
  await expect(comparison.getByRole("alert")).toContainText("does not match");
  await expect(comparison.getByRole("table")).toHaveCount(0);
  await expect(
    comparison.getByRole("button", {
      name: "Save exact result comparison",
      exact: true,
    }),
  ).toHaveCount(0);
});
test("no-dispatch receipt explains unavailable comparison without posting", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchResultMatch(nativeScheduleWriteServer.directory);
  let calls = 0;
  await page.route("**/receipts/" + data.id, async (route) => {
    const response = await route.fetch(),
      text = await response.text(),
      start = text.indexOf(',"result":'),
      end = text.indexOf(',"pending":', start);
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    const body =
      text.slice(0, start) +
      ',"result":' +
      JSON.stringify({
        status: "not_sent",
        may_have_applied: false,
        protocol_accepted: false,
      }) +
      text.slice(end);
    await route.fulfill({ status: 200, contentType: "application/json", body });
  });
  page.on("request", (r) => {
    if (r.url().endsWith("/default-batch/result/compare")) calls++;
  });
  const { comparison, compare } = await enter(page, data);
  await expect(compare).toBeDisabled();
  await expect(comparison).toContainText("no possible batch restore");
  await compare.evaluate((e) => (e as HTMLElement).click());
  expect(calls).toBe(0);
});
