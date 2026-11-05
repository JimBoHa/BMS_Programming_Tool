import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { python, d } from "./native-connection-fixture";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";

function seed(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys
from pathlib import Path
from contextlib import aclosing
import pytest
from tests.test_native_applications import native_link
from tests.test_native_connection_transfer import connection_review,applying
from tests.test_caf_graph import make_graph
import base64
async def main():
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1]),patch)) as generator:
   link=await anext(generator)
   _,review=await connection_review(link)
   receipt=await link[3].apply_connection(**applying(review))
   assert receipt['result']['status']=='verified',receipt
   print(json.dumps(dict(id=receipt['intent']['id'],caf=base64.b64encode(make_graph()).decode())))
asyncio.run(main())
`,
      directory,
    ),
  );
}
async function open(page: Page, data: any, entry: string) {
  await page.goto("/");
  if (entry === "CAF") {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "recorded-connection.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(data.caf, "base64"),
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("recorded-connection.caf");
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
  test(`recorded matching connection through ${entry} retains original evidence without field authority`, async ({
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
      name: "Recorded native matching connection",
      exact: true,
    });
    await expect(detail).toContainText("Recorded matching connection");
    await expect(detail).toContainText(d);
    await expect(detail).toContainText("No original-backup revalidation");
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
      ).toContainText("recorded-connection.caf");
  });
}
for (const mode of ["extra-field", "future-profile"]) {
  test(`${mode} matching connection metadata keeps raw evidence and withholds program action`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory);
    await page.route("**/api/changes/query", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      const body = await response.json();
      for (const row of body.rows)
        if (row.id === data.id) {
          if (mode === "extra-field") row.native_connection.unqualified = true;
          else
            row.native_connection.profile =
              "native-effective-matching-connection-transfer/999";
        }
      await route.fulfill({ response, json: body });
    });
    await open(page, data, "History");
    await expect(
      page.getByRole("region", {
        name: "Recorded native matching connection",
        exact: true,
      }),
    ).toContainText("Connection metadata unavailable");
    await expect(
      page.getByRole("button", {
        name: "Open native program tools",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Download evidence JSON", exact: true }),
    ).toBeVisible();
  });
}
