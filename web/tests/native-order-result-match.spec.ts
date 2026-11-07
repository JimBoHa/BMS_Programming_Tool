import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { seedOrderResultMatch } from "./native-order-result-match-fixture";
import { openOrder } from "./native-execution-order-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { connectionSeal } from "../src/nativeConnectionContract";
const endpoint = "**/execution-order/result/compare";
const comparison = (page: Page) =>
  page.getByLabel("Retained execution-order result comparison", {
    exact: true,
  });
const result = (page: Page) =>
  page.getByRole("region", {
    name: "Retained execution-order comparison result",
    exact: true,
  });
async function enter(page: Page, f: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "retained-order-source.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(f.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("retained-order-source.caf");
  } else {
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Preserved order comparison graph");
  }
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.id);
  const opened = await openOrder(page, compiler);
  await opened.panel
    .getByLabel("Native execution-order destination", { exact: true })
    .selectOption("controller");
  const transfer = page.getByRole("region", {
    name: "Native execution-order controller transfer",
    exact: true,
  });
  await transfer
    .getByText("Retained execution-order receipts", { exact: true })
    .click();
  await transfer
    .getByLabel("Execution-order receipt", { exact: true })
    .selectOption(f.receipt.intent.id);
  await transfer
    .getByRole("button", { name: "Load execution-order receipt", exact: true })
    .click();
  await comparison(page).locator(":scope > summary").click();
  const compare = comparison(page).getByRole("button", {
    name: "Compare retained source with recorded execution order",
    exact: true,
  });
  await expect(compare).toBeEnabled();
  return { ...opened, transfer, compare };
}
for (const caf of [false, true])
  for (const phone of [false, true])
    test(`${caf ? "CAF" : "graph"} ${phone ? "compact" : "desktop"} compares offline retained order and saves exact evidence`, async ({
      page,
      nativeScheduleWriteServer,
    }) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
      const f = seedOrderResultMatch(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      let bytes!: Buffer;
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      const { compare } = await enter(page, f, caf);
      calls.length = 0;
      await page.route(endpoint, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        bytes = await response.body();
        expect(bytes.length).toBeGreaterThan(0);
        await route.fulfill({ response, body: bytes });
      });
      await compare.click();
      await expect(result(page)).toContainText("match the recorded result");
      await expect(
        result(page).getByRole("table", {
          name: "Recorded and retained execution order",
          exact: true,
        }),
      ).toContainText("1:");
      const download = page.waitForEvent("download");
      await result(page)
        .getByRole("button", {
          name: "Save exact execution-order comparison",
          exact: true,
        })
        .click();
      expect(await readFile((await (await download).path())!)).toEqual(bytes);
      expect(calls).toEqual([
        "/api/bacnet/controller/native-application/execution-order/result/compare",
      ]);
      await chooseWorkspaceTask(page, "Program");
      if (caf)
        await expect(
          page.getByLabel("Working context", { exact: true }),
        ).toContainText("retained-order-source.caf");
      else {
        await chooseWorkspaceTool(page, "Graph editor");
        await expect(
          page.getByLabel("Program name", { exact: true }),
        ).toHaveValue("Preserved order comparison graph");
      }
    });
for (const kind of ["historical", "saved", "order", "routed", "reencoded"])
  test(`actual ${kind} source retains separate historical order comparison`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderResultMatch(nativeScheduleWriteServer.directory, kind);
    const { compare } = await enter(page, f);
    await compare.click();
    await expect(result(page)).toContainText(
      kind === "historical" || kind === "reencoded"
        ? "match the recorded result"
        : "differs from the recorded",
    );
    await expect(result(page)).toContainText(f.report.verified_proof.kind);
    if (kind === "routed") await expect(result(page)).toContainText("3001:7");
  });
for (const fault of ["source", "order", "authority"])
  test(`changed ${fault} response cannot display order correlation`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderResultMatch(nativeScheduleWriteServer.directory),
      { compare } = await enter(page, f);
    await page.route(endpoint, async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        v = await response.json();
      if (fault === "source") v.source.capture_id = "f".repeat(32);
      else if (fault === "order")
        v.expected_selection.original_order = [0, 1, 2, 3];
      else v.can_apply = true;
      const { evidence_sha256, ...body } = v;
      v.evidence_sha256 = await connectionSeal(body);
      await route.fulfill({ response, json: v });
    });
    await compare.click();
    await expect(comparison(page).getByRole("alert")).toContainText(
      "does not match this retained source",
    );
    await expect(result(page)).toHaveCount(0);
  });

async function holdComparison(page: Page) {
  let release = () => {},
    started!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    arrived = new Promise<void>((resolve) => (started = resolve));
  await page.route(
    endpoint,
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        body = await response.body();
      started();
      await gate;
      await route.fulfill({ response, body });
    },
    { times: 1 },
  );
  return { arrived, release };
}
for (const change of [
  "cancel",
  "task",
  "source",
  "receipt",
  "mode",
  "pagehide",
])
  test(`held comparison retires on ${change} without importing an old result`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderResultMatch(nativeScheduleWriteServer.directory),
      opened = await enter(page, f),
      held = await holdComparison(page);
    try {
      await opened.compare.click();
      await held.arrived;
      if (change === "cancel")
        await comparison(page)
          .getByRole("button", {
            name: "Cancel order result comparison",
            exact: true,
          })
          .click();
      else if (change === "task") await chooseWorkspaceTask(page, "Changes");
      else if (change === "source")
        await opened.compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(f.receipt.intent.backup_id);
      else if (change === "receipt")
        await opened.transfer
          .getByRole("button", {
            name: "Load execution-order receipt",
            exact: true,
          })
          .click();
      else if (change === "mode")
        await opened.panel
          .getByLabel("Native execution-order destination", { exact: true })
          .selectOption("file");
      else
        await page.evaluate(() => {
          window.dispatchEvent(new Event("pagehide"));
          window.dispatchEvent(new Event("pageshow"));
        });
      held.release();
      await expect(
        page.getByRole("region", {
          name: "Retained execution-order comparison result",
          exact: true,
          includeHidden: true,
        }),
      ).toHaveCount(0);
      if (change === "cancel" || change === "pagehide") {
        await opened.compare.click();
        await expect(result(page)).toContainText("match the recorded result");
      }
    } finally {
      held.release();
    }
  });
for (const change of ["disclosure", "pagehide"])
  test(`cached export callback retires with ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderResultMatch(nativeScheduleWriteServer.directory),
      { compare } = await enter(page, f);
    await compare.click();
    await expect(result(page)).toBeVisible();
    const cached = await result(page)
      .getByRole("button", {
        name: "Save exact execution-order comparison",
        exact: true,
      })
      .evaluateHandle(
        (element: any) =>
          element[
            Object.keys(element).find((k) => k.startsWith("__reactProps"))!
          ].onClick,
      );
    let downloads = 0;
    page.on("download", () => downloads++);
    if (change === "disclosure")
      await comparison(page)
        .locator(":scope > summary")
        .evaluate((element: HTMLElement) => {
          element.click();
          element.click();
        });
    else
      await page.evaluate(() => {
        window.dispatchEvent(new Event("pagehide"));
        window.dispatchEvent(new Event("pageshow"));
      });
    await cached.evaluate((callback: any) => callback());
    await expect(result(page)).toHaveCount(0);
    expect(downloads).toBe(0);
  });
test("comparison preserves the unfinished proposed order independently of retained values", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedOrderResultMatch(nativeScheduleWriteServer.directory),
    opened = await enter(page, f);
  await opened.panel
    .getByRole("button", { name: "Move native block earlier", exact: true })
    .click();
  const table = opened.panel.getByRole("table", {
      name: "Proposed native execution order",
      exact: true,
    }),
    draft = await table.textContent();
  await opened.compare.click();
  await expect(result(page)).toContainText("match the recorded result");
  await expect(table).toHaveText(draft!);
});
