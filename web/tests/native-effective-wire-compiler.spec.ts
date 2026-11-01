import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { python } from "./caf-native-fixture";
import { inspect } from "./native-boolean-fixture";
const ref = "controller/575_1",
  a = ref + ".2_10",
  b = ref + ".2_11";
function seed() {
  return JSON.parse(
    python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_native_wire_compiler import wire_files
s=ApplicationStore(Store(sys.argv[1]));files=wire_files(target_class=538)
identity={'object-name':'Authored native wire controller','model-name':'UNLISTED-MODEL','vendor-identifier':5}
a=retained(s,files,identity=identity)
b=retained(s,files,identity=identity,connector_config={'transport':'mstp','serial_port':'/dev/authored'},target={'address':'7','router':None,'dnet':None})
u=retained(s,files,identity=identity,source_identity_matches=False)
files[11],files[12]=b'Unknown selectors',b'Opaque saved values'
unknown=retained(s,files,identity=identity)
print(json.dumps({'a':a['id'],'b':b['id'],'unknown':unknown['id'],'unverified':u['id']}))`,
      process.env.BMS_TEST_COMPILER_STATE!,
    ),
  );
}
async function editor(
  page: Page,
  compiler: Locator,
  mode = "effective",
  loaded = true,
) {
  const { records } = await inspect(compiler, 9);
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", { name: ref + " engineering", exact: true }),
    })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const copy = records.getByLabel(
    /^(Native archive wire source copy|Effective native wire compilation)$/,
  );
  await copy.locator(":scope > summary").click();
  await copy
    .getByLabel("Native wire source basis", { exact: true })
    .selectOption(mode);
  if (loaded) await load(copy, mode);
  return copy;
}
async function load(copy: Locator, mode = "effective") {
  await copy
    .getByRole("button", {
      name:
        mode === "effective"
          ? "Open saved wire sources"
          : "Open native wire sources",
      exact: true,
    })
    .click();
  await expect(
    copy.getByLabel("Replacement native source", { exact: true }),
  ).toBeVisible();
}
async function enter(
  page: Page,
  id: string,
  mode = "effective",
  loaded = true,
) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools", exact: true })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  return { compiler, copy: await editor(page, compiler, mode, loaded) };
}
async function review(copy: Locator) {
  await copy
    .getByRole("button", {
      name: "Review effective wire compilation",
      exact: true,
    })
    .click();
  const result = copy.getByRole("region", {
    name: "Reviewed effective native wire compilation",
    exact: true,
  });
  await expect(result).toBeVisible();
  return result;
}
const calls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const rows: string[] = [];
  calls.set(page, rows);
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/api\/bacnet\//.test(r.url()) &&
      !/\/inspection\//.test(r.url()) &&
      !/\/signal-default\/(source|sources)/.test(r.url())
    )
      rows.push(r.url());
  });
});

test("effective native wire compilation exports exact merged output and original review offline", async ({
  page,
  request,
}, info) => {
  const ids = seed();
  await page.setViewportSize({ width: 820, height: 1100 });
  const { copy } = await enter(page, ids.a);
  await expect(copy).toContainText("3 saved application parameters merged");
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  let raw = Buffer.alloc(0);
  await page.route("**/effective-wire-source/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    raw = await response.body();
    await route.fulfill({ response });
  });
  const result = await review(copy),
    data = JSON.parse(raw.toString());
  expect(data.saved_settings_merged).toBe(true);
  expect(data.field_transfer_enabled).toBe(false);
  expect(data.compilation.other_merged_bytes_preserved).toBe(true);
  const evidence = page.waitForEvent("download");
  await result
    .getByRole("button", {
      name: "Save exact effective wire review",
      exact: true,
    })
    .click();
  expect(readFileSync((await (await evidence).path())!)).toEqual(raw);
  const downloading = page.waitForEvent("download");
  await result
    .getByRole("button", { name: "Save compiled native wire", exact: true })
    .click();
  const path = (await (await downloading).path())!;
  expect(createHash("sha256").update(readFileSync(path)).digest("hex")).toBe(
    data.output_sha256,
  );
  const proof = JSON.parse(
    python(
      `
import json,sys
from pathlib import Path
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from tests.test_native_wire_compiler import wire_files,BOOLEAN
from tests.test_moi_wire_sources import REF,A,B
f=wire_files(target_class=538);merged,_=ParameterApplication(f[3],f[11],f[12]).compile()
before=MoiIdentity(merged);after=MoiIdentity(Path(sys.argv[1]).read_bytes())
print(json.dumps({'differences':[i for i,(a,b) in enumerate(zip(before.data,after.data,strict=True)) if a!=b], 'source':after.reader.diagram(REF)['connections'][0]['source_ref'],'saved_a':after.reader.scalar(after.reader.records[A],3113),'saved_b':after.reader.scalar(after.reader.records[B],3113),'saved_boolean':after.reader.scalar(after.reader.records[BOOLEAN],3113)}))`,
      path,
    ),
  );
  expect(proof).toEqual({
    differences: [data.compilation.wire_edit.source_index_offset],
    source: b,
    saved_a: 42,
    saved_b: 17,
    saved_boolean: true,
  });
  await expect(
    copy
      .getByRole("status")
      .filter({ hasText: "Saved reviewed effective native wire compilation" }),
  ).toBeVisible();
  await copy.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-effective-wire-820.png"),
  });
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("archive and effective wire drafts remain independent while switching retires review", async ({
  page,
}) => {
  const ids = seed(),
    { copy } = await enter(page, ids.a, "archive");
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  await copy
    .getByRole("button", { name: "Review native wire copy", exact: true })
    .click();
  await expect(
    copy.getByRole("region", {
      name: "Reviewed native wire copy",
      exact: true,
    }),
  ).toBeVisible();
  await copy
    .getByLabel("Native wire source basis", { exact: true })
    .selectOption("effective");
  await load(copy);
  await expect(
    copy.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(a);
  await expect(
    copy.getByRole("region", {
      name: "Reviewed native wire copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await review(copy);
  await expect(
    copy.getByRole("region", {
      name: "Reviewed effective native wire compilation",
      exact: true,
    }),
  ).toContainText("No wire change; the merged snapshot bytes are retained");
  await copy
    .getByLabel("Native wire source basis", { exact: true })
    .selectOption("archive");
  await load(copy, "archive");
  await expect(
    copy.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(b);
  await copy
    .getByLabel("Native wire source basis", { exact: true })
    .selectOption("effective");
  await load(copy);
  await expect(
    copy.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(a);
  await expect(
    copy.getByRole("region", {
      name: "Reviewed effective native wire compilation",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("effective wire basis and draft survive navigation while the review retires", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, copy } = await enter(page, ids.a);
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  await review(copy);
  await page
    .getByRole("navigation", { name: "Main navigation", exact: true })
    .getByRole("button", { name: "Library", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation", exact: true })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools", exact: true })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const reopened = await editor(page, compiler);
  await expect(
    reopened.getByLabel("Native wire source basis", { exact: true }),
  ).toHaveValue("effective");
  await expect(
    reopened.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(b);
  await expect(
    reopened.getByRole("region", {
      name: "Reviewed effective native wire compilation",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

for (const variant of ["unknown", "unverified"]) {
  test(`effective ${variant} source refuses compilation while original archive copy stays available`, async ({
    page,
  }) => {
    const ids = seed(),
      { copy } = await enter(page, ids[variant], "effective", false);
    await copy
      .getByRole("button", { name: "Open saved wire sources", exact: true })
      .click();
    await expect(copy.getByRole("alert")).toBeVisible();
    await expect(
      copy.getByRole("button", {
        name: "Review effective wire compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    await copy
      .getByLabel("Native wire source basis", { exact: true })
      .selectOption("archive");
    await load(copy, "archive");
    await copy
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(b);
    await copy
      .getByRole("button", { name: "Review native wire copy", exact: true })
      .click();
    await expect(
      copy.getByRole("button", { name: "Save native wire copy", exact: true }),
    ).toBeVisible();
    expect(calls.get(page)).toEqual([]);
  });
}

test("a serial-recorded snapshot compiles offline without opening its transport", async ({
  page,
}) => {
  const ids = seed(),
    { copy } = await enter(page, ids.b);
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  await review(copy);
  await expect(
    page.getByLabel("Native archive inspection source", { exact: true }),
  ).toContainText("device,5136 at 7");
  expect(calls.get(page)).toEqual([]);
});

for (const changed of ["effective", "settings", "preservation", "wire"]) {
  test(`altered effective wire ${changed} review cannot produce a compiled download`, async ({
    page,
  }) => {
    const ids = seed(),
      { copy } = await enter(page, ids.a);
    await copy
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(b);
    await page.route("**/effective-wire-source/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (changed === "effective") data.effective_sha256 = "0".repeat(64);
      if (changed === "settings")
        data.compilation.files["11"].sha256 = "0".repeat(64);
      if (changed === "preservation")
        data.compilation.other_merged_bytes_preserved = false;
      if (changed === "wire") data.compilation.wire_edit.new[0] = 0;
      await route.fulfill({ response, body: JSON.stringify(data) });
    });
    await copy
      .getByRole("button", {
        name: "Review effective wire compilation",
        exact: true,
      })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "Native wire review differs",
    );
    await expect(
      copy.getByRole("button", {
        name: "Save compiled native wire",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });
}

test("mode A B A cannot revive a delayed effective wire review", async ({
  page,
}) => {
  const ids = seed(),
    { copy } = await enter(page, ids.a);
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  let release = () => {},
    start!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    received = new Promise<void>((r) => (start = r));
  await page.route(
    "**/effective-wire-source/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      start();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await copy
      .getByRole("button", {
        name: "Review effective wire compilation",
        exact: true,
      })
      .click();
    await received;
    await copy
      .getByLabel("Native wire source basis", { exact: true })
      .selectOption("archive");
    await load(copy, "archive");
    await copy
      .getByLabel("Native wire source basis", { exact: true })
      .selectOption("effective");
    await load(copy);
    release();
    await expect(
      copy.getByRole("region", {
        name: "Reviewed effective native wire compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    await review(copy);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("changing retained source keeps its effective proposal independent and retires the review", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, copy } = await enter(page, ids.a);
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  await review(copy);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.b);
  const other = await editor(page, compiler);
  await expect(
    other.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(a);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.a);
  const back = await editor(page, compiler);
  await expect(
    back.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(b);
  await expect(
    back.getByRole("region", {
      name: "Reviewed effective native wire compilation",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("late and substituted effective output cannot download or restore an old review", async ({
  page,
}) => {
  const ids = seed(),
    { copy } = await enter(page, ids.a);
  await copy
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  const plan = await review(copy);
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  let release = () => {},
    start!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    received = new Promise<void>((r) => (start = r));
  await page.route(
    "**/effective-wire-source/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      start();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await plan
      .getByRole("button", { name: "Save compiled native wire", exact: true })
      .click();
    await received;
    await copy
      .getByLabel("Native wire source basis", { exact: true })
      .selectOption("archive");
    await load(copy, "archive");
    release();
    await copy
      .getByLabel("Native wire source basis", { exact: true })
      .selectOption("effective");
    await load(copy);
    expect(downloads).toEqual([]);
    const current = await review(copy);
    await page.route("**/effective-wire-source/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      await route.fulfill({
        response,
        body: Buffer.from("Substituted output"),
      });
    });
    await current
      .getByRole("button", { name: "Save compiled native wire", exact: true })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "Native wire output bytes differ",
    );
    expect(downloads).toEqual([]);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});
