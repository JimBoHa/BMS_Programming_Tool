import { test, expect, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { seed, enter, inspect, record, python } from "./native-boolean-fixture";

async function effective(records: Locator) {
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("effective");
  const source = records.getByRole("region", {
    name: "Effective native Boolean source",
    exact: true,
  });
  await source
    .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
    .click();
  const editor = source.getByLabel("Effective Boolean default compilation", {
    exact: true,
  });
  await expect(
    editor.getByLabel("Proposed effective Boolean default", { exact: true }),
  ).toBeChecked();
  return { source, editor };
}
async function review(editor: Locator, value = false) {
  await editor
    .getByLabel("Proposed effective Boolean default", { exact: true })
    .setChecked(value);
  await editor
    .getByRole("button", {
      name: "Review effective Boolean compilation",
      exact: true,
    })
    .click();
  const reviewed = editor.getByRole("region", {
    name: "Reviewed effective Boolean compilation",
    exact: true,
  });
  await expect(reviewed).toContainText(
    `Retained effective default true · proposed ${String(value)}`,
  );
  return reviewed;
}
test.beforeEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
});

test("effective Boolean compilation preserves actual other saved values and original review bytes", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 820, height: 1100 });
  const ids = seed(),
    { records } = await enter(page, ids.a),
    { editor } = await effective(records);
  await expect(editor).toContainText(
    "Original archive default false · retained effective default true",
  );
  let originalReview = Buffer.alloc(0);
  await page.route("**/boolean-default-compiler/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    originalReview = await response.body();
    await route.fulfill({ response });
  });
  const reviewed = await review(editor);
  const evidencePending = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save Boolean copy review JSON", exact: true })
    .click();
  const evidence = await evidencePending;
  expect(readFileSync((await evidence.path())!)).toEqual(originalReview);
  const pending = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save compiled Boolean default", exact: true })
    .click();
  const file = await pending,
    filename = (await file.path())!,
    data = JSON.parse(originalReview.toString());
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
from bms_tool.moi_parameters import ParameterApplication
s=ApplicationStore(Store(sys.argv[1]));files=s.load(sys.argv[2])[1];merged=MoiIdentity(ParameterApplication(files[3],files[11],files[12]).compile()[0]);actual=MoiIdentity(Path(sys.argv[3]).read_bytes())
differences=[i for i,(a,b) in enumerate(zip(merged.data,actual.data,strict=True)) if a!=b]
print(json.dumps({'differences':differences,'after':actual.reader.scalar(actual.reader.records['controller/boolean-20'],3113),'other':actual.reader.scalar(actual.reader.records['controller/boolean-21'],3113),'saved_root':actual.reader.scalar(actual.root,900),'saved_real':actual.reader.scalar(actual.reader.records['controller/signal-10'],3113)}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
      ids.a,
      filename,
    ),
  );
  expect(proof).toEqual({
    differences: [data.edit.native_byte_offset],
    after: false,
    other: false,
    saved_root: 3.5,
    saved_real: 42,
  });
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-effective-boolean-820.png"),
  });
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("Boolean-only signal archive compiles independently of Real-default support", async ({
  page,
}) => {
  const id = JSON.parse(
    python(
      `
import json,sys
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
from tests.test_native_boolean_copies import boolean_files
from tests.test_native_signal_compiler import retained
s=ApplicationStore(Store(sys.argv[1]));print(json.dumps(retained(s,boolean_files(real_signals=False))['id']))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
    ),
  );
  const { records } = await enter(page, id, 10),
    { editor } = await effective(records);
  await expect(await review(editor)).toContainText(
    "One native tag byte changes",
  );
});

test("unchanged effective Boolean still exports other merged settings with an explicit no-op boundary", async ({
  page,
}) => {
  const ids = seed(),
    { records } = await enter(page, ids.a),
    { editor } = await effective(records);
  const reviewed = await review(editor, true);
  await expect(reviewed).toContainText(
    "Selected value unchanged; other retained saved settings remain merged",
  );
  await expect(reviewed).not.toContainText(
    "original archive bytes are preserved",
  );
  const pending = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save compiled Boolean default", exact: true })
    .click();
  const file = await pending;
  const proof = JSON.parse(
    python(
      `
from pathlib import Path
from bms_tool.moi_identity import MoiIdentity
import json,sys
a=MoiIdentity(Path(sys.argv[1]).read_bytes());print(json.dumps({'boolean':a.reader.scalar(a.reader.records['controller/boolean-20'],3113),'other':a.reader.scalar(a.reader.records['controller/boolean-21'],3113),'root':a.reader.scalar(a.root,900)}))
`,
      (await file.path())!,
    ),
  );
  expect(proof).toEqual({ boolean: true, other: false, root: 3.5 });
});

test("archive and effective drafts use distinct baselines and never resurrect mode-switch reviews", async ({
  page,
}) => {
  const ids = seed(),
    { records, copy } = await enter(page, ids.a);
  await copy
    .getByLabel("Proposed Boolean archive default", { exact: true })
    .check();
  let current = await effective(records);
  await review(current.editor, false);
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("archive");
  const archive = records.getByLabel("Native Boolean archive copy", {
    exact: true,
  });
  await archive.locator(":scope > summary").click();
  await expect(
    archive.getByLabel("Proposed Boolean archive default", { exact: true }),
  ).toBeChecked();
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("effective");
  const source = records.getByRole("region", {
    name: "Effective native Boolean source",
    exact: true,
  });
  await source
    .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
    .click();
  const editor = source.getByLabel("Effective Boolean default compilation", {
    exact: true,
  });
  await expect(
    editor.getByLabel("Proposed effective Boolean default", { exact: true }),
  ).not.toBeChecked();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed effective Boolean compilation",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("unknown saved format and unverified identity refuse effective compilation while archive copying stays available", async ({
  page,
}) => {
  const ids = seed(),
    { records } = await enter(page, ids.unknown);
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("effective");
  const source = records.getByRole("region", {
    name: "Effective native Boolean source",
    exact: true,
  });
  await source
    .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
    .click();
  await expect(source.getByRole("alert")).toContainText("identity-verified");
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("archive");
  const archive = records.getByLabel("Native Boolean archive copy", {
    exact: true,
  });
  await archive.locator(":scope > summary").click();
  await archive
    .getByLabel("Proposed Boolean archive default", { exact: true })
    .check();
  await archive
    .getByRole("button", { name: "Review Boolean archive copy", exact: true })
    .click();
  await expect(
    archive.getByRole("region", {
      name: "Reviewed Boolean archive copy",
      exact: true,
    }),
  ).toBeVisible();
});

for (const altered of ["manifest", "station", "baseline"]) {
  test(`altered effective Boolean source ${altered} cannot supply a compiler baseline`, async ({
    page,
  }) => {
    const ids = seed(),
      { records } = await enter(page, ids.a);
    await page.route("**/boolean-default-compiler/source", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = JSON.parse((await response.body()).toString());
      if (altered === "manifest") data.snapshot_sha256 = "0".repeat(64);
      if (altered === "station") data.target.address = "127.0.0.1:47999";
      if (altered === "baseline")
        data.fields.find(
          (row: any) => row.ref === "controller/boolean-20",
        ).archive_value = true;
      await route.fulfill({ response, json: data });
    });
    await records
      .getByLabel("Boolean default source", { exact: true })
      .selectOption("effective");
    const source = records.getByRole("region", {
      name: "Effective native Boolean source",
      exact: true,
    });
    await source
      .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
      .click();
    await expect(source.getByRole("alert")).toContainText(
      "differs from the selected retained archive field",
    );
    await expect(
      source.getByLabel("Proposed effective Boolean default", { exact: true }),
    ).toHaveCount(0);
  });
}

for (const altered of ["merged-source", "preservation"]) {
  test(`altered effective Boolean review ${altered} cannot become an export`, async ({
    page,
  }) => {
    const ids = seed(),
      { records } = await enter(page, ids.a),
      { editor } = await effective(records);
    await page.route("**/boolean-default-compiler/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = JSON.parse((await response.body()).toString());
      if (altered === "merged-source") data.effective_sha256 = "0".repeat(64);
      else data.compilation.other_merged_bytes_preserved = false;
      await route.fulfill({ response, json: data });
    });
    await editor
      .getByLabel("Proposed effective Boolean default", { exact: true })
      .uncheck();
    await editor
      .getByRole("button", {
        name: "Review effective Boolean compilation",
        exact: true,
      })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "differs from the selected source or proposal",
    );
    await expect(
      editor.getByRole("region", {
        name: "Reviewed effective Boolean compilation",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

test("a held effective source cannot return after mode archive effective archive selection", async ({
  page,
}) => {
  const ids = seed(),
    { records } = await enter(page, ids.a);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/boolean-default-compiler/source", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await records
      .getByLabel("Boolean default source", { exact: true })
      .selectOption("effective");
    await records
      .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
      .click();
    await received;
    await records
      .getByLabel("Boolean default source", { exact: true })
      .selectOption("archive");
    release();
    await records
      .getByLabel("Boolean default source", { exact: true })
      .selectOption("effective");
    await expect(
      records.getByRole("button", {
        name: "Open saved Boolean defaults",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      records.getByLabel("Proposed effective Boolean default", { exact: true }),
    ).toHaveCount(0);
  } finally {
    release();
  }
});

test("effective export arriving after capture A B A cannot download or restore a review", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, records } = await enter(page, ids.a),
    { editor } = await effective(records),
    reviewed = await review(editor);
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
  await page.route("**/boolean-default-compiler/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await reviewed
      .getByRole("button", {
        name: "Save compiled Boolean default",
        exact: true,
      })
      .click();
    await received;
    const selected = compiler.getByLabel("Retained native backup", {
      exact: true,
    });
    await selected.selectOption(ids.b);
    await selected.selectOption(ids.a);
    release();
    await page.waitForLoadState("networkidle");
    expect(downloads).toBe(0);
    const current = await inspect(compiler);
    await record(current.records);
    await current.records
      .getByLabel("Boolean default source", { exact: true })
      .selectOption("effective");
    await current.records
      .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
      .click();
    await expect(
      current.records.getByLabel("Proposed effective Boolean default", {
        exact: true,
      }),
    ).not.toBeChecked();
    await expect(
      current.records.getByRole("region", {
        name: "Reviewed effective Boolean compilation",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    release();
  }
});
