import { createHash } from "node:crypto";
import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFile } from "node:fs/promises";
import { seedOrderRecoveryProposal } from "./native-order-recovery-proposal-fixture";
import { openOrder } from "./native-execution-order-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { connectionSeal } from "../src/nativeConnectionContract";
const endpoint = "**/execution-order/recovery/prepare";
const panel = (page: Page) =>
  page.getByLabel("Previous execution-order proposal", { exact: true });
const result = (page: Page) =>
  page.getByRole("region", {
    name: "Prepared previous execution order",
    exact: true,
  });
async function enter(page: Page, f: any, caf = false, withDraft = false) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "previous-order-source.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(f.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("previous-order-source.caf");
  } else {
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Preserved previous-order graph");
  }
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTool(page, "Graph editor");
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Preserved previous-order graph");
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.id);
  const opened = await openOrder(page, compiler);
  if (withDraft) {
    await opened.panel
      .getByRole("combobox", {
        name: "Native execution-order block",
        exact: true,
      })
      .selectOption("2");
    await opened.panel
      .getByRole("button", { name: "Move native block later", exact: true })
      .click();
  }
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
  const comparison = page.getByLabel(
    "Retained execution-order result comparison",
    { exact: true },
  );
  await comparison.locator(":scope > summary").click();
  await comparison
    .getByRole("button", {
      name: "Compare retained source with recorded execution order",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("region", {
      name: "Retained execution-order comparison result",
      exact: true,
    }),
  ).toBeVisible();
  await panel(page).locator(":scope > summary").click();
  return {
    ...opened,
    compiler,
    transfer,
    comparison,
    prepare: panel(page).getByRole("button", {
      name: "Prepare previous order proposal",
      exact: true,
    }),
  };
}
for (const caf of [false, true])
  for (const compact of [false, true])
    test(`${caf ? "CAF" : "graph"} ${compact ? "compact" : "desktop"} prepares actual inverse and exports exact original report`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }) => {
      if (compact) await page.setViewportSize({ width: 390, height: 844 });
      const f = seedOrderRecoveryProposal(nativeScheduleWriteServer.directory),
        opened = await enter(page, f, caf);
      const draft = opened.panel.getByRole("table", {
        name: "Proposed native execution order",
        exact: true,
      });
      const originalDraft = await draft.textContent();
      let received: Buffer | undefined;
      const posts: string[] = [];
      page.on("request", (r) => {
        if (r.method() === "POST") posts.push(new URL(r.url()).pathname);
      });
      await page.route(endpoint, async (route) => {
        const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
        received = await response.body();
        await route.fulfill({ response, body: received });
      });
      await opened.prepare.click();
      await expect(result(page)).toBeVisible();
      await expect(
        result(page).getByLabel("Previous order indices", { exact: true }),
      ).toHaveValue("0, 1, 2, 3");
      await expect(result(page)).toContainText(
        "Current controller state remains unverified",
      );
      await expect(result(page)).toContainText("separate review");
      await expect(draft).toHaveText(originalDraft!);
      const downloaded = page.waitForEvent("download");
      await result(page)
        .getByRole("button", {
          name: "Save exact previous-order proposal",
          exact: true,
        })
        .click();
      const bytes = await readFile((await (await downloaded).path())!);
      expect(received).toBeDefined();
      expect(bytes.equals(received!)).toBe(true);
      const report = JSON.parse(bytes.toString());
      expect(report).toEqual(f.proposal);
      expect(report.can_apply).toBe(false);
      expect(report.recovery_lineage_recorded).toBe(false);
      if (compact) {
        const box = (await result(page).boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(390);
      }
      expect(posts).toEqual([
        "/api/bacnet/controller/native-application/execution-order/recovery/prepare",
      ]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      await result(page)
        .getByRole("button", {
          name: "Replace local order proposal with previous order",
          exact: true,
        })
        .click();
      await expect(draft).not.toHaveText(originalDraft!);
      await opened.panel
        .getByLabel("Native execution-order destination", { exact: true })
        .selectOption("file");
      const reviewed = page.waitForRequest((r) =>
        new URL(r.url()).pathname.endsWith("/execution-order/preview"),
      );
      await opened.panel
        .getByRole("button", {
          name: "Review native execution-order compilation",
          exact: true,
        })
        .click();
      expect((await reviewed).postDataJSON().proposed_order).toEqual([
        0, 1, 2, 3,
      ]);
      const copied = page.waitForEvent("download");
      await opened.panel
        .getByRole("button", {
          name: "Save native execution-order copy",
          exact: true,
        })
        .click();
      const nativeBytes = await readFile((await (await copied).path())!);
      expect(createHash("sha256").update(nativeBytes).digest("hex")).toBe(
        f.proposal.preview.output_sha256,
      );
      expect(
        posts.some((p) =>
          /\/transfer\/(preview|review|apply|reconcile)$/.test(p),
        ),
      ).toBe(false);
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTool(page, "Graph editor");
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue("Preserved previous-order graph");
      if (caf) await chooseWorkspaceTool(page, "CAF file");
      if (caf)
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("previous-order-source.caf");
    });

test("replacing a different unfinished order requires confirmation and leaves a separate local review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedOrderRecoveryProposal(nativeScheduleWriteServer.directory),
    opened = await enter(page, f, false, true);
  const table = opened.panel.getByRole("table", {
      name: "Proposed native execution order",
      exact: true,
    }),
    before = await table.textContent();
  await opened.prepare.click();
  await expect(result(page)).toBeVisible();
  page.once("dialog", (d) => d.dismiss());
  await result(page)
    .getByRole("button", {
      name: "Replace local order proposal with previous order",
      exact: true,
    })
    .click();
  await expect(table).toHaveText(before!);
  await expect(result(page)).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await result(page)
    .getByRole("button", {
      name: "Replace local order proposal with previous order",
      exact: true,
    })
    .click();
  await expect(table).not.toHaveText(before!);
  await opened.panel
    .getByLabel("Native execution-order destination", { exact: true })
    .selectOption("file");
  const review = page.waitForRequest((r) =>
    new URL(r.url()).pathname.endsWith("/execution-order/preview"),
  );
  await opened.panel
    .getByRole("button", {
      name: "Review native execution-order compilation",
      exact: true,
    })
    .click();
  expect((await review).postDataJSON().proposed_order).toEqual([0, 1, 2, 3]);
});

for (const change of ["collapse", "mode", "pagehide"])
  test(`completed previous-order export retires on ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderRecoveryProposal(nativeScheduleWriteServer.directory),
      opened = await enter(page, f);
    await opened.prepare.click();
    await expect(result(page)).toBeVisible();
    if (change === "collapse")
      await panel(page).locator(":scope > summary").click();
    if (change === "mode")
      await opened.panel
        .getByLabel("Native execution-order destination", { exact: true })
        .selectOption("file");
    if (change === "pagehide")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    await expect(result(page)).toHaveCount(0);
    if (change === "collapse")
      await panel(page).locator(":scope > summary").click();
    if (change === "mode")
      await opened.panel
        .getByLabel("Native execution-order destination", { exact: true })
        .selectOption("controller");
    if (change === "pagehide") {
      await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
      await openOrder(page, opened.compiler);
    }
    await expect(result(page)).toHaveCount(0);
  });

test("same-turn page exit retires local draft replacement before asynchronous validation completes", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedOrderRecoveryProposal(nativeScheduleWriteServer.directory),
    opened = await enter(page, f, false, true);
  const table = opened.panel.getByRole("table", {
      name: "Proposed native execution order",
      exact: true,
    }),
    before = await table.textContent();
  await opened.prepare.click();
  await expect(result(page)).toBeVisible();
  let dialogs = 0;
  page.on("dialog", async (d) => {
    dialogs++;
    await d.dismiss();
  });
  await result(page)
    .getByRole("button", {
      name: "Replace local order proposal with previous order",
      exact: true,
    })
    .evaluate((button) => {
      (button as HTMLButtonElement).click();
      window.dispatchEvent(new Event("pagehide"));
    });
  await expect(result(page)).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
  await openOrder(page, opened.compiler);
  await expect(table).toHaveText(before!);
  expect(dialogs).toBe(0);
});

test("immutable historical readback stays usable after later unknown observations", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedOrderRecoveryProposal(
      nativeScheduleWriteServer.directory,
      "historical",
    ),
    opened = await enter(page, f);
  await opened.prepare.click();
  await expect(result(page)).toContainText("readback-event");
  await expect(
    result(page).getByLabel("Previous order indices", { exact: true }),
  ).toHaveValue("0, 1, 2, 3");
});
for (const kind of ["saved", "order", "routed"])
  test(`${kind} retained difference cannot prepare previous order`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderRecoveryProposal(
        nativeScheduleWriteServer.directory,
        kind,
      ),
      opened = await enter(page, f);
    await expect(opened.prepare).toBeDisabled();
    await expect(result(page)).toHaveCount(0);
  });
for (const mutation of ["parent", "proposal", "live", "compilation", "extra"])
  test(`reject resealed previous-order ${mutation} response`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderRecoveryProposal(nativeScheduleWriteServer.directory),
      opened = await enter(page, f);
    await page.route(endpoint, async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        v = await response.json();
      if (mutation === "parent") v.origin.parent_receipt_id = "f".repeat(32);
      if (mutation === "proposal") v.proposal.proposed_order = [1, 0, 2, 3];
      if (mutation === "live") v.current_device_verified = true;
      if (mutation === "compilation")
        v.preview.compilation.other_merged_bytes_preserved = false;
      if (mutation === "extra") v.token = "unexpected";
      const { evidence_sha256, ...body } = v;
      v.evidence_sha256 = await connectionSeal(body);
      await route.fulfill({ response, json: v });
    });
    await opened.prepare.click();
    await expect(panel(page).getByRole("alert")).toContainText(
      "does not match",
    );
    await expect(result(page)).toHaveCount(0);
  });
for (const change of [
  "cancel",
  "task",
  "source",
  "receipt",
  "mode",
  "pagehide",
  "collapse",
])
  test(`held previous-order preparation retires on ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedOrderRecoveryProposal(nativeScheduleWriteServer.directory),
      opened = await enter(page, f, false, true);
    const draft = await opened.panel
      .getByRole("table", {
        name: "Proposed native execution order",
        exact: true,
      })
      .textContent();
    let release!: () => void, seen!: () => void, done!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      arrived = new Promise<void>((r) => (seen = r)),
      delivered = new Promise<void>((r) => (done = r));
    await page.route(endpoint, async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
        body = await response.body();
      seen();
      await gate;
      await route.fulfill({ response, body });
      done();
    });
    try {
      await opened.prepare.click();
      await arrived;
      if (change === "cancel")
        await panel(page)
          .getByRole("button", {
            name: "Cancel previous order proposal",
            exact: true,
          })
          .click();
      if (change === "task") await chooseWorkspaceTask(page, "Changes");
      if (change === "source")
        await opened.compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(f.receipt.intent.backup_id);
      if (change === "receipt")
        await opened.transfer
          .getByRole("button", {
            name: "Load execution-order receipt",
            exact: true,
          })
          .click();
      if (change === "mode")
        await opened.panel
          .getByLabel("Native execution-order destination", { exact: true })
          .selectOption("file");
      if (change === "pagehide")
        await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      if (change === "collapse")
        await panel(page).locator(":scope > summary").click();
      release();
      await delivered;
      await expect(result(page)).toHaveCount(0);
      if (change === "pagehide")
        await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
      if (change === "task") {
        await chooseWorkspaceTask(page, "Program");
        await chooseWorkspaceTool(page, "Native backup defaults");
      }
      if (change === "mode")
        await opened.panel
          .getByLabel("Native execution-order destination", { exact: true })
          .selectOption("controller");
      if (change === "collapse")
        await panel(page).locator(":scope > summary").click();
      await expect(result(page)).toHaveCount(0);
      if (change === "task" || change === "pagehide")
        await openOrder(page, opened.compiler);
      if (change !== "source")
        await expect(
          opened.panel.getByRole("table", {
            name: "Proposed native execution order",
            exact: true,
          }),
        ).toHaveText(draft!);
    } finally {
      release();
    }
  });
