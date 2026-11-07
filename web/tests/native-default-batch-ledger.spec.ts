import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedBatchTransfer as seed } from "./native-default-batch-transfer-fixture";
const ref = "controller/575_1.2_12";
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
        name: "recorded-default-batch.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(data.caf, "base64"),
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("recorded-default-batch.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  if (entry === "History") {
    await chooseWorkspaceSurface(page, "History");
    const tools = page.getByRole("navigation", {
      name: "history tools",
      exact: true,
    });
    const select = tools.getByRole("combobox");
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

for (const entry of ["Changes", "CAF", "History"]) {
  test(`recorded typed defaults through ${entry} retains original evidence without field authority`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory),
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
      name: "Recorded typed default batch",
      exact: true,
    });
    await expect(detail).toContainText("Recorded typed defaults");
    await expect(detail).toContainText(ref);
    await expect(detail).toContainText("grants no transfer authority");
    const original = await request.get(
      "/api/bacnet/controller/native-application/receipts/" + data.id,
    );
    const evidence = page.getByRole("region", {
      name: "Change evidence",
      exact: true,
    });
    const download = page.waitForEvent("download");
    await evidence
      .getByRole("button", { name: "Download evidence JSON", exact: true })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(
      await original.body(),
    );
    await evidence
      .getByRole("button", { name: "Open native program tools", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Native backup default compiler",
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
      ).toContainText("recorded-default-batch.caf");
  });
}
