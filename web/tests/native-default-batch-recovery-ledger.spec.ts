import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedBatchRecoveryLedger } from "./native-default-batch-recovery-ledger-fixture";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";

async function open(page: Page, data: any, entry: string) {
  await page.goto("/");
  if (entry === "CAF") {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "recorded-batch-recovery.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(data.caf, "base64"),
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("recorded-batch-recovery.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  if (entry === "History") {
    await chooseWorkspaceSurface(page, "History");
    const tools = page.getByRole("navigation", {
        name: "history tools",
        exact: true,
      }),
      select = tools.getByRole("combobox");
    if (await select.isVisible())
      await select.selectOption({ label: "Recorded changes" });
    else
      await tools
        .getByRole("button", { name: "Recorded changes", exact: true })
        .click();
  } else await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  await page
    .getByRole("button", { name: "Details for native " + data.id, exact: true })
    .click();
}
for (const entry of ["Changes", "CAF", "History"])
  for (const phone of [false, true])
    test(`${entry} ${phone ? "phone" : "desktop"} shows recorded typed recovery and parent search without field access`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, testInfo) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
      const data = seedBatchRecoveryLedger(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(r.url());
      });
      await open(page, data, entry);
      const detail = page.getByRole("region", {
        name: "Recorded previous batch recovery",
        exact: true,
      });
      await expect(detail.getByRole("heading")).toHaveText(
        "Recorded previous batch recovery",
      );
      await expect(detail).toContainText(data.parent);
      await expect(detail).toContainText(
        "grants no recovery or transfer authority",
      );
      await expect(detail.getByRole("table").getByRole("row")).toHaveCount(5);
      await expect(
        detail.getByRole("table").getByRole("row").nth(2),
      ).toContainText("-0");
      if (phone) {
        const viewport = detail.getByRole("region", {
          name: "Recorded batch recovery values viewport",
          exact: true,
        });
        expect(
          await viewport.evaluate((el) => el.scrollWidth > el.clientWidth),
        ).toBe(true);
        await viewport.focus();
        await viewport.press("ArrowRight");
        expect(await viewport.evaluate((el) => el.scrollLeft)).toBeGreaterThan(
          0,
        );
      }
      const original = await request.get(
        "/api/bacnet/controller/native-application/receipts/" + data.id,
      );
      const download = page.waitForEvent("download");
      await page
        .getByRole("region", { name: "Change evidence", exact: true })
        .getByRole("button", { name: "Download evidence JSON", exact: true })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(
        await original.body(),
      );
      await page.screenshot({
        path: testInfo.outputPath("recorded-batch-recovery.png"),
        fullPage: true,
      });
      await detail
        .getByRole("button", {
          name: "Find original batch receipt",
          exact: true,
        })
        .click();
      await expect(
        page.getByLabel("Search recorded changes", { exact: true }),
      ).toHaveValue(data.parent);
      await expect(
        page.getByRole("button", {
          name: "Details for native " + data.parent,
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: "Details for native " + data.id,
          exact: true,
        }),
      ).toBeVisible();
      expect(calls).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      if (entry === "CAF")
        await expect(
          page.getByLabel("Working context", { exact: true }),
        ).toContainText("recorded-batch-recovery.caf");
    });
for (const mode of ["uncertain", "later-unknown"])
  test(`${mode} receipt keeps its own outcome while displaying recorded lineage`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchRecoveryLedger(
      nativeScheduleWriteServer.directory,
      mode,
    );
    await open(page, data, "History");
    await expect(
      page.getByRole("region", {
        name: "Recorded previous batch recovery",
        exact: true,
      }),
    ).toContainText("Recorded previous batch recovery");
    const report = await (
      await request.post("/api/changes/query", {
        headers: {
          "X-Studio-Token": (await (await request.get("/api/session")).json())
            .token,
        },
        data: { source: "native", text: data.id },
      })
    ).json();
    const row = report.rows.find((r: any) => r.id === data.id);
    expect(row.state).toBe("unknown");
    expect(row.pending).toBe(mode === "uncertain");
    expect(row.native_default_batch_recovery.current_device_verified).toBe(
      false,
    );
  });
test("altered browser lineage hides recorded values and native program handoff", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchRecoveryLedger(nativeScheduleWriteServer.directory);
  await page.route("**/api/changes/query", async (route) => {
    const response = await route.fetch(),
      body = await response.json();
    for (const row of body.rows)
      if (row.id === data.id)
        row.native_default_batch_recovery.field_authority = true;
    await route.fulfill({ response, json: body });
  });
  await open(page, data, "History");
  const detail = page.getByRole("region", {
    name: "Recorded previous batch recovery",
    exact: true,
  });
  await expect(detail).toContainText("Batch recovery metadata unavailable");
  await expect(detail.getByRole("table")).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Open native program tools",
      exact: true,
    }),
  ).toHaveCount(0);
});
