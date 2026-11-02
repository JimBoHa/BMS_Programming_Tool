import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  python,
  seed,
  inspect,
  record,
  enter,
  review,
} from "./native-boolean-fixture";

test.beforeEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
});

test("offline Boolean archive copy changes one actual byte, preserves other archive settings and exact review JSON", async ({
  page,
  nativeScheduleWriteServer,
  request,
}, info) => {
  await page.setViewportSize({ width: 820, height: 1100 });
  const ids = seed(nativeScheduleWriteServer.directory),
    { copy } = await enter(page, ids.a);
  let originalReview = Buffer.alloc(0);
  await page.route("**/inspection/boolean-default/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    originalReview = await response.body();
    await route.fulfill({ response });
  });
  const reviewed = await review(copy);
  const pendingReview = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save Boolean copy review JSON", exact: true })
    .click();
  const evidence = await pendingReview;
  expect(readFileSync((await evidence.path())!)).toEqual(originalReview);
  const pending = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save Boolean archive copy", exact: true })
    .click();
  const file = await pending,
    filename = (await file.path())!;
  const data = JSON.parse(originalReview.toString());
  expect(
    createHash("sha256").update(readFileSync(filename)).digest("hex"),
  ).toBe(data.output_sha256);
  const proof = JSON.parse(
    python(
      `
import json,sys
from pathlib import Path
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
from bms_tool.moi_identity import MoiIdentity
s=ApplicationStore(Store(sys.argv[1]));original=MoiIdentity(s.load(sys.argv[2])[1][3]);actual=MoiIdentity(Path(sys.argv[3]).read_bytes())
differences=[i for i,(a,b) in enumerate(zip(original.data,actual.data,strict=True)) if a!=b]
print(json.dumps({'differences':differences,'before':original.reader.scalar(original.reader.records['controller/boolean-20'],3113),'after':actual.reader.scalar(actual.reader.records['controller/boolean-20'],3113),'other':actual.reader.scalar(actual.reader.records['controller/boolean-21'],3113),'archive_root':actual.reader.scalar(actual.root,900),'archive_real':actual.reader.scalar(actual.reader.records['controller/signal-10'],3113)}))
`,
      nativeScheduleWriteServer.directory,
      ids.a,
      filename,
    ),
  );
  expect(proof).toEqual({
    differences: [data.edit.native_byte_offset],
    before: false,
    after: true,
    other: true,
    archive_root: 1.25,
    archive_real: 23.5,
  });
  await copy.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-boolean-archive-copy-820.png"),
  });
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("Boolean drafts stay with their record and capture through selection and navigation; reviews retire", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
    { compiler, records, copy } = await enter(page, ids.a);
  await review(copy);
  const other = await record(records, "controller/boolean-21");
  await other
    .getByLabel("Proposed Boolean archive default", { exact: true })
    .uncheck();
  const first = await record(records);
  await expect(
    first.getByLabel("Proposed Boolean archive default", { exact: true }),
  ).toBeChecked();
  await expect(
    first.getByRole("region", {
      name: "Reviewed Boolean archive copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.b);
  let current = await inspect(compiler),
    panel = await record(current.records);
  await expect(
    panel.getByLabel("Proposed Boolean archive default", { exact: true }),
  ).not.toBeChecked();
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.a);
  current = await inspect(compiler);
  panel = await record(current.records);
  await expect(
    panel.getByLabel("Proposed Boolean archive default", { exact: true }),
  ).toBeChecked();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Library", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  current = await inspect(compiler);
  panel = await record(current.records);
  await expect(
    panel.getByLabel("Proposed Boolean archive default", { exact: true }),
  ).toBeChecked();
  await expect(
    panel.getByRole("region", {
      name: "Reviewed Boolean archive copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await panel
    .getByRole("button", { name: "Discard Boolean copy draft", exact: true })
    .click();
  await expect(
    panel.getByLabel("Proposed Boolean archive default", { exact: true }),
  ).not.toBeChecked();
});

test("unverified source and unknown saved format remain archive-copyable without enabling transfer", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
    { inspection, copy } = await enter(page, ids.unknown);
  await expect(inspection).toContainText("Authored identity mismatch");
  await review(copy);
  await expect(
    copy.getByRole("button", { name: "Apply to controller", exact: true }),
  ).toHaveCount(0);
  await expect(copy).toContainText("Saved settings are not merged");
});

for (const altered of ["station", "field", "value", "transfer"]) {
  test(`altered Boolean review ${altered} cannot become a saved-copy review`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { copy } = await enter(page, ids.a);
    await page.route("**/inspection/boolean-default/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = JSON.parse((await response.body()).toString());
      if (altered === "station") data.target.address = "127.0.0.1:47999";
      if (altered === "field") data.edit.encoded_sha256 = "0".repeat(64);
      if (altered === "value") data.edit.after_value = false;
      if (altered === "transfer") data.field_transfer_enabled = true;
      await route.fulfill({ response, json: data });
    });
    await copy
      .getByLabel("Proposed Boolean archive default", { exact: true })
      .check();
    await copy
      .getByRole("button", { name: "Review Boolean archive copy", exact: true })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "differs from the selected source or proposal",
    );
    await expect(
      copy.getByRole("region", {
        name: "Reviewed Boolean archive copy",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

for (const altered of ["bytes", "header"]) {
  test(`substituted export ${altered} cannot download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { copy } = await enter(page, ids.a),
      reviewed = await review(copy);
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/inspection/boolean-default/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      if (altered === "header")
        await route.fulfill({
          response,
          headers: {
            ...response.headers(),
            "x-studio-artifact-sha256": "0".repeat(64),
          },
        });
      else
        await route.fulfill({
          response,
          body: Buffer.from("substituted bytes"),
          headers: { ...response.headers(), "content-length": "17" },
        });
    });
    await reviewed
      .getByRole("button", { name: "Save Boolean archive copy", exact: true })
      .click();
    await expect(copy.getByRole("alert")).toContainText("byte-digest check");
    expect(downloads).toBe(0);
  });
}

test("export delivered after source A B A cannot download or revive its review; draft survives", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
    { compiler, copy } = await enter(page, ids.a),
    reviewed = await review(copy);
  let release!: () => void,
    started!: () => void,
    downloads = 0;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    started = resolve;
  });
  page.on("download", () => downloads++);
  await page.route("**/inspection/boolean-default/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await reviewed
      .getByRole("button", { name: "Save Boolean archive copy", exact: true })
      .click();
    await received;
    const choices = compiler.getByLabel("Retained native backup", {
      exact: true,
    });
    await choices.selectOption(ids.b);
    await choices.selectOption(ids.a);
    release();
    await page.waitForLoadState("networkidle");
    expect(downloads).toBe(0);
    const current = await inspect(compiler),
      panel = await record(current.records);
    await expect(
      panel.getByLabel("Proposed Boolean archive default", { exact: true }),
    ).toBeChecked();
    await expect(
      panel.getByRole("region", {
        name: "Reviewed Boolean archive copy",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    release();
  }
});
