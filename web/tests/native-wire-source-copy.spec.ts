import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { python } from "./caf-native-fixture";
import { inspect } from "./native-boolean-fixture";
import { rememberWireDraft } from "../src/nativeWireDrafts";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

test("wire draft capacity refuses new entries without evicting earlier proposals", () => {
  const drafts = new Map<string, string>();
  for (let index = 0; index < 256; index++)
    expect(
      rememberWireDraft(drafts, `source-${index}`, `proposal-${index}`),
    ).toBe(true);
  const original = [...drafts];
  expect(rememberWireDraft(drafts, "another-source", "new proposal")).toBe(
    false,
  );
  expect([...drafts]).toEqual(original);
  expect(rememberWireDraft(drafts, "source-255", "revised proposal")).toBe(
    true,
  );
  expect(drafts.get("source-0")).toBe("proposal-0");
  drafts.delete("source-255");
  expect(rememberWireDraft(drafts, "another-source", "new proposal")).toBe(
    true,
  );
  expect(drafts.size).toBe(256);
});

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
from tests.test_moi_wire_sources import source
s=ApplicationStore(Store(sys.argv[1]))
def capture(**kwargs):
 return retained(s,{3:source(**kwargs),11:b'Unknown saved selectors',12:b'Opaque saved values'},
  identity={'object-name':'Authored native wire controller','model-name':'UNLISTED-MODEL','vendor-identifier':5})
a=capture();b=capture(config=True);empty=capture(empty=True)
print(json.dumps({'a':a['id'],'b':b['id'],'empty':empty['id']}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
    ),
  );
}
async function record(page: Page, compiler: Locator, expectedWire = true) {
  const { records } = await inspect(compiler, 8);
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", {
        name: ref + " engineering",
        exact: true,
      }),
    })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const editor = records.getByLabel("Native archive wire source copy", {
    exact: true,
  });
  await editor.locator(":scope > summary").click();
  await editor
    .getByRole("button", { name: "Open native wire sources", exact: true })
    .click();
  if (expectedWire)
    await expect(
      editor.getByLabel("Replacement native source", { exact: true }),
    ).toBeVisible();
  else
    await expect(editor).toContainText(
      "No existing native connection is recorded",
    );
  return editor;
}
async function enter(page: Page, id: string, expectedWire = true) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  return { compiler, editor: await record(page, compiler, expectedWire) };
}
async function prepare(editor: Locator) {
  await editor
    .getByRole("button", { name: "Review native wire copy", exact: true })
    .click();
  const review = editor.getByRole("region", {
    name: "Reviewed native wire copy",
    exact: true,
  });
  await expect(review).toContainText("0, 85, 2, 7000 → 1, 85, 2, 7000");
  return review;
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

test("native wire review exports exact one-byte source copy and original review with readable controls", async ({
  page,
  request,
}, info) => {
  const ids = seed();
  await page.setViewportSize({ width: 820, height: 1100 });
  const { editor } = await enter(page, ids.a);
  for (const name of [
    "Existing native connection",
    "Replacement native source",
  ])
    expect(
      (await editor.getByLabel(name, { exact: true }).boundingBox())!.height,
    ).toBeGreaterThanOrEqual(36);
  await editor
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  let original = Buffer.alloc(0);
  await page.route("**/wire-source/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    original = await response.body();
    await route.fulfill({ response });
  });
  const review = await prepare(editor),
    data = JSON.parse(original.toString());
  expect(data.field_transfer_enabled).toBe(false);
  expect(data.compilation.other_expanded_bytes_preserved).toBe(true);
  const evidence = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save exact native wire review", exact: true })
    .click();
  expect(readFileSync((await (await evidence).path())!)).toEqual(original);
  const download = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save native wire copy", exact: true })
    .click();
  const path = (await (await download).path())!;
  expect(createHash("sha256").update(readFileSync(path)).digest("hex")).toBe(
    data.output_sha256,
  );
  const proof = JSON.parse(
    python(
      `
import sys,json
from pathlib import Path
from bms_tool.moi_identity import MoiIdentity
from tests.test_moi_wire_sources import source,REF
old=MoiIdentity(source());new=MoiIdentity(Path(sys.argv[1]).read_bytes())
diff=[i for i,(a,b) in enumerate(zip(old.data,new.data,strict=True)) if a!=b]
print(json.dumps({'differences':diff,'source':new.reader.diagram(REF)['connections'][0]['source_ref']}))
`,
      path,
    ),
  );
  expect(proof.differences).toEqual([data.compilation.source_index_offset]);
  expect(proof.source).toBe(b);
  await expect(editor.getByRole("status")).toContainText(
    "Saved reviewed native wire source copy",
  );
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("native-wire-copy-820.png") });
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("wire proposal survives navigation in its original graph while review retires", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, editor } = await enter(page, ids.a);
  await editor
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  await prepare(editor);
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
  const reopened = await record(page, compiler);
  await expect(
    reopened.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(b);
  await expect(
    reopened.getByRole("region", {
      name: "Reviewed native wire copy",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("native wire source and proposal A B A cannot revive a delayed review", async ({
  page,
}) => {
  const ids = seed(),
    { editor } = await enter(page, ids.a);
  await editor
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  let release = () => {},
    started!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    received = new Promise<void>((resolve) => {
      started = resolve;
    });
  await page.route(
    "**/wire-source/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await editor
      .getByRole("button", { name: "Review native wire copy", exact: true })
      .click();
    await received;
    await editor
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(a);
    await editor
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(b);
    release();
    await expect(
      editor.getByRole("region", {
        name: "Reviewed native wire copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await prepare(editor);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("copy from a different retained snapshot cannot inherit another graph's proposal", async ({
  page,
}) => {
  const ids = seed(),
    { compiler, editor } = await enter(page, ids.a);
  await editor
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  await prepare(editor);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.b);
  const other = await record(page, compiler);
  await expect(
    other.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(a);
  await expect(other).toContainText("No alternate source passes");
  await expect(
    other
      .getByLabel("Replacement native source", { exact: true })
      .locator("option"),
  ).toHaveCount(1);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.a);
  const back = await record(page, compiler);
  await expect(
    back.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(b);
  await expect(
    back.getByRole("region", {
      name: "Reviewed native wire copy",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

for (const fault of ["tuple", "source", "preservation"]) {
  test(`altered native wire review ${fault} is rejected`, async ({ page }) => {
    const ids = seed(),
      { editor } = await enter(page, ids.a);
    await editor
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(b);
    await page.route("**/wire-source/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (fault === "tuple") data.compilation.new[0] = 0;
      if (fault === "source") data.snapshot_sha256 = "0".repeat(64);
      if (fault === "preservation")
        data.compilation.other_expanded_bytes_preserved = false;
      await route.fulfill({ response, body: JSON.stringify(data) });
    });
    await editor
      .getByRole("button", { name: "Review native wire copy", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "Native wire review differs",
    );
    await expect(
      editor.getByRole("button", {
        name: "Save native wire copy",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });
}

test("late or substituted native wire output cannot download after the proposal changes", async ({
  page,
}) => {
  const ids = seed(),
    { editor } = await enter(page, ids.a);
  await editor
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(b);
  const review = await prepare(editor);
  let release = () => {},
    started!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    received = new Promise<void>((resolve) => {
      started = resolve;
    });
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  await page.route(
    "**/wire-source/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await review
      .getByRole("button", { name: "Save native wire copy", exact: true })
      .click();
    await received;
    await editor
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(a);
    release();
    await expect(
      editor.getByRole("region", {
        name: "Reviewed native wire copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await editor
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(b);
    const next = await prepare(editor);
    await page.route(
      "**/wire-source/export",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        await route.fulfill({
          response,
          body: Buffer.from("Substituted bytes"),
        });
      },
      { times: 1 },
    );
    await next
      .getByRole("button", { name: "Save native wire copy", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "output bytes differ",
    );
    expect(downloads).toEqual([]);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("empty native graph stays inspectable without creating a connection", async ({
  page,
}) => {
  const ids = seed(),
    { editor } = await enter(page, ids.empty, false);
  await expect(
    editor.getByLabel("Replacement native source", { exact: true }),
  ).toHaveCount(0);
  await expect(
    editor.getByRole("button", {
      name: "Review native wire copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    editor.getByRole("button", { name: "Save native wire copy", exact: true }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("wire switching retains each original proposal and retires the earlier review", async ({
  page,
}) => {
  const ids = seed(),
    { editor } = await enter(page, ids.a);
  const connection = editor.getByLabel("Existing native connection", {
    exact: true,
  });
  const candidate = editor.getByLabel("Replacement native source", {
    exact: true,
  });
  await candidate.selectOption(b);
  await prepare(editor);
  await connection.selectOption("1");
  await expect(candidate).toHaveValue(b);
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native wire copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await candidate.selectOption(a);
  await connection.selectOption("0");
  await expect(candidate).toHaveValue(b);
  await connection.selectOption("1");
  await expect(candidate).toHaveValue(a);
  await editor
    .getByRole("button", { name: "Discard native wire draft", exact: true })
    .click();
  await expect(candidate).toHaveValue(b);
  expect(calls.get(page)).toEqual([]);
});

test("unchanged wire review exports the exact original archive through keyboard controls", async ({
  page,
  browserName,
}) => {
  const ids = seed(),
    { editor } = await enter(page, ids.a);
  const candidate = editor.getByLabel("Replacement native source", {
    exact: true,
  });
  await candidate.focus();
  // WebKit's default Tab skips buttons on this host; Option-Tab includes them.
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  const reviewButton = editor.getByRole("button", {
    name: "Review native wire copy",
    exact: true,
  });
  await expect(reviewButton).toBeFocused();
  await page.keyboard.press("Enter");
  const review = editor.getByRole("region", {
    name: "Reviewed native wire copy",
    exact: true,
  });
  await expect(review).toContainText(
    "No wire change; the original archive bytes are retained",
  );
  const downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save native wire copy", exact: true })
    .click();
  const path = (await (await downloading).path())!;
  expect(
    python(
      `from pathlib import Path\nimport sys\nfrom tests.test_moi_wire_sources import source\nassert Path(sys.argv[1]).read_bytes()==source()\nprint('exact original archive')`,
      path,
    ).trim(),
  ).toBe("exact original archive");
  expect(calls.get(page)).toEqual([]);
});

test("source read failure preserves the wire draft and supports explicit retry", async ({
  page,
}) => {
  const ids = seed(),
    { editor } = await enter(page, ids.a);
  const candidate = editor.getByLabel("Replacement native source", {
    exact: true,
  });
  await candidate.selectOption(b);
  await prepare(editor);
  await page.route(
    "**/wire-source/source",
    (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Authored source integrity failure" }),
      }),
    { times: 1 },
  );
  await editor
    .getByRole("button", { name: "Open native wire sources", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "Authored source integrity failure",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native wire copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(candidate).toHaveValue(b);
  await editor
    .getByRole("button", { name: "Open native wire sources", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toHaveCount(0);
  await expect(candidate).toHaveValue(b);
  await prepare(editor);
  expect(calls.get(page)).toEqual([]);
});

test("connected routed entry keeps archive copying local and route changes retire review without losing its draft", async ({
  page,
}) => {
  const ids = seed(),
    peer = await nativeDefaultPeer();
  async function select(routed: boolean) {
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill(routed ? "3001:7" : peer.direct);
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page
      .getByLabel("Known router", { exact: true })
      .fill(routed ? peer.router : "");
    await page
      .getByLabel("Known network", { exact: true })
      .fill(routed ? "3001" : "");
    await page
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview", exact: true }),
    ).toContainText("Authored controller");
    await page
      .getByRole("navigation", { name: "Workspace tasks", exact: true })
      .getByRole("button", { name: "Program", exact: true })
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
      .selectOption(ids.a);
    return record(page, compiler);
  }
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    const editor = await select(true);
    await editor
      .getByLabel("Replacement native source", { exact: true })
      .selectOption(b);
    const before = await peer.command("stats");
    const review = await prepare(editor);
    const downloading = page.waitForEvent("download");
    await review
      .getByRole("button", { name: "Save native wire copy", exact: true })
      .click();
    await downloading;
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    const changed = await select(false);
    await expect(
      changed.getByLabel("Replacement native source", { exact: true }),
    ).toHaveValue(b);
    await expect(
      changed.getByRole("region", {
        name: "Reviewed native wire copy",
        exact: true,
      }),
    ).toHaveCount(0);
    const final = await peer.command("stats");
    expect(
      final.events.filter(
        (row: any[]) => row[0] === "write" || row[0] === "state",
      ),
    ).toEqual([]);
  } finally {
    peer.close();
  }
});
