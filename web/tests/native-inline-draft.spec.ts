import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { python } from "./native-connection-fixture";
import { openNativeCompiler } from "./workspace-navigation";

function seed(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys,pytest
from contextlib import aclosing
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_inline_monitor import observation_peer
from tests.test_native_inline_sequence import authored_source
from tests.test_native_inline_activity_drawing import drawing_source
async def main():
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1]),patch)) as fixture:
   peer,_,_,service,target=await anext(fixture)
   observation_peer(peer,"")
   peer.files=authored_source(catalog=True,wide=True)
   donor=await service.capture(**target,operation_id="capture-primitives")
   peer.files=drawing_source()
   source=await service.capture(**target,operation_id="capture-inline-source")
   print(json.dumps({"source":source["id"],"donor":donor["id"]}))
asyncio.run(main())
`,
      directory,
    )
      .trim()
      .split("\n")
      .at(-1)!,
  );
}
async function openDraft(page: Page, directory: string) {
  const data = seed(directory);
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  const panel = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await panel
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.source);
  await panel
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  await panel
    .getByText("Draft an inline reheat program", { exact: true })
    .click();
  await panel
    .getByLabel("Logic block source", { exact: true })
    .selectOption(data.donor);
  await panel
    .getByLabel("First new object instance", { exact: true })
    .fill("200");
  return { panel, data };
}
test("review and save a grouped native control draft with the field connection closed", async ({
  page,
  nativeScheduleWriteServer,
}, testInfo) => {
  const { panel } = await openDraft(page, nativeScheduleWriteServer.directory);
  await panel
    .getByLabel("Program purpose", { exact: true })
    .selectOption("control");
  const review = page.waitForResponse(
    (r) =>
      r.url().endsWith("/inline-sequence/draft/review") &&
      r.request().method() === "POST",
  );
  const button = panel.getByRole("button", {
    name: "Review local program",
    exact: true,
  });
  await button.focus();
  await page.keyboard.press("Enter");
  const response = await review;
  expect(response.status()).toBe(200);
  const r = await response.json();
  expect(r.sampling).toBe("clock-edge");
  expect(r.production_transfer_qualified).toBe(false);
  expect(r.controller_queries).toBe(false);
  await expect(
    panel
      .getByRole("status")
      .filter({ hasText: "verified signal connections" }),
  ).toContainText("protected heat command");
  const image = testInfo.outputPath("reviewed-inline-draft.png");
  await page.screenshot({ path: image });
  await testInfo.attach("Reviewed inline draft", {
    path: image,
    contentType: "image/png",
  });
  const file = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Save reviewed program file", exact: true })
    .click();
  const dl = await file;
  expect(dl.suggestedFilename()).toBe("inline-reheat-control.moi");
  expect(
    createHash("sha256")
      .update(await readFile((await dl.path())!))
      .digest("hex"),
  ).toBe(r.compilation.candidate_sha256);
  await expect(
    panel.getByText("Saved the reviewed local program file.", { exact: true }),
  ).toBeVisible();
  await panel
    .getByLabel("Airflow sampling", { exact: true })
    .selectOption("paired");
  await expect(
    panel.getByRole("button", {
      name: "Save reviewed program file",
      exact: true,
    }),
  ).toHaveCount(0);
  const priorReview = page.waitForResponse(
    (response) =>
      response.url().endsWith("/inline-sequence/draft/review") &&
      response.request().method() === "POST",
  );
  await panel
    .getByRole("button", { name: "Review local program", exact: true })
    .click();
  const prior = await (await priorReview).json();
  expect(prior.sampling).toBeUndefined();
  expect(prior.compilation.candidate_sha256).not.toBe(
    r.compilation.candidate_sha256,
  );
  await expect(
    panel.getByRole("button", {
      name: "Save reviewed program file",
      exact: true,
    }),
  ).toBeEnabled();
  await panel
    .getByLabel("Drawing layout", { exact: true })
    .selectOption("flat");
  await expect(
    panel.getByRole("button", { name: "Review local program", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByRole("button", {
      name: "Save reviewed program file",
      exact: true,
    }),
  ).toHaveCount(0);
});
test("a late draft review cannot save after editing the sample allocation", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const { panel } = await openDraft(page, nativeScheduleWriteServer.directory);
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>((r) => (release = r)),
    got = new Promise<void>((r) => (started = r));
  const route = "**/inline-sequence/draft/review";
  await page.route(route, async (r) => {
    const response = await r.fetch();
    started();
    await wait;
    await r.fulfill({ response });
  });
  await panel
    .getByRole("button", { name: "Review local program", exact: true })
    .click();
  await got;
  await panel
    .getByLabel("First new object instance", { exact: true })
    .fill("201");
  const late = page.waitForResponse((r) =>
    r.url().endsWith("/inline-sequence/draft/review"),
  );
  release();
  await late;
  await expect(
    panel.getByRole("button", {
      name: "Save reviewed program file",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Review local program", exact: true }),
  ).toBeEnabled();
  await page.unroute(route);
  await panel
    .getByLabel("First new object instance", { exact: true })
    .fill("4194303");
  await expect(
    panel.getByRole("button", { name: "Review local program", exact: true }),
  ).toBeDisabled();
});
