import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { python } from "./caf-native-fixture";
import { source as cafSource } from "./caf-constant-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

const ref = "controller/575_1",
  a = ref + ".2_10",
  b = ref + ".2_11",
  c = ref + ".2_12";
let ids: Record<string, string> | undefined;
function seed() {
  return (ids ??= JSON.parse(
    python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_native_wire_compiler import wire_files
from tests.test_native_default_wire import IDENTITY
s=ApplicationStore(Store(sys.argv[1]));f=wire_files()
a=retained(s,f,identity=IDENTITY)
b=retained(s,f,identity=IDENTITY,connector_config={'transport':'mstp','serial_port':'/dev/authored'},target={'address':'7','router':None,'dnet':None})
f[11],f[12]=b'Unknown selectors',b'Opaque saved values'
unknown=retained(s,f,identity=IDENTITY)
print(json.dumps({'a':a['id'],'b':b['id'],'unknown':unknown['id']}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
    ),
  ));
}
const compiler = (page: Page) =>
  page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
const combined = (page: Page) =>
  compiler(page).getByLabel("Combined native default and connection", {
    exact: true,
  });
const reviewed = (copy: Locator) =>
  copy.getByRole("region", {
    name: "Reviewed combined native compilation",
    exact: true,
  });
async function expand(copy: Locator) {
  if ((await copy.getAttribute("open")) === null)
    await copy.locator(":scope > summary").click();
}
async function load(copy: Locator) {
  await expand(copy);
  await copy
    .getByRole("button", { name: "Open combined compiler", exact: true })
    .click();
  await expect(
    copy.getByLabel("Combined native diagram", { exact: true }),
  ).toHaveValue(ref);
  await copy
    .getByRole("button", { name: "Inspect combined connection", exact: true })
    .click();
  await expect(
    copy.getByLabel("Combined replacement source", { exact: true }),
  ).toBeVisible();
}
async function choose(page: Page, id: string) {
  const parent = compiler(page);
  await parent
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  await parent
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await parent
    .getByLabel("Native Real default", { exact: true })
    .selectOption(c);
  return parent;
}
async function enter(page: Page, id = seed().a, caf = false) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "authored-combined.caf",
      mimeType: "application/octet-stream",
      buffer: cafSource(),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-combined.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openNativeCompiler(page);
  const parent = await choose(page, id);
  await parent
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("0.1");
  const copy = combined(page);
  await load(copy);
  await copy
    .getByLabel("Combined replacement source", { exact: true })
    .selectOption(b);
  return { parent, copy };
}
async function review(copy: Locator) {
  await copy
    .getByRole("button", {
      name: "Review combined native compilation",
      exact: true,
    })
    .click();
  await expect(reviewed(copy)).toBeVisible();
  return reviewed(copy);
}
async function delayed(page: Page, suffix: string) {
  let release!: () => void, start!: () => void, finished!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    received = new Promise<void>((r) => (start = r)),
    complete = new Promise<void>((r) => (finished = r));
  await page.route(
    "**/inspection/default-wire/" + suffix,
    async (route) => {
      try {
        const response = await route.fetch({ maxRetries: 0 });
        start();
        await gate;
        await route.fulfill({ response });
      } finally {
        finished();
      }
    },
    { times: 1 },
  );
  return { release, received, complete };
}
const calls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  seed();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const list: string[] = [];
  calls.set(page, list);
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/api\/bacnet\//.test(r.url()) &&
      !/\/inspection\//.test(r.url()) &&
      !/\/signal-default\/(source|sources)/.test(r.url())
    )
      list.push(r.url());
  });
});

test("offline combined export preserves exact review, literal native edits and saved values", async ({
  page,
  request,
}, info) => {
  const { copy } = await enter(page);
  let raw = Buffer.alloc(0);
  await page.route("**/inspection/default-wire/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    raw = await response.body();
    await route.fulfill({ response });
  });
  const result = await review(copy),
    data = JSON.parse(raw.toString());
  const report = page.waitForEvent("download");
  await result
    .getByRole("button", { name: "Export exact combined review", exact: true })
    .click();
  expect(readFileSync((await (await report).path())!)).toEqual(raw);
  const downloading = page.waitForEvent("download");
  await result
    .getByRole("button", {
      name: "Save compiled default and connection",
      exact: true,
    })
    .click();
  const file = (await (await downloading).path())!;
  expect(createHash("sha256").update(readFileSync(file)).digest("hex")).toBe(
    data.output_sha256,
  );
  const proof = JSON.parse(
    python(
      `
import json,sys,struct
from pathlib import Path
from tests.test_native_wire_compiler import wire_files,BOOLEAN
from tests.test_moi_wire_sources import REF,A,B,C
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.moi_identity import MoiIdentity
f=wire_files();merged,_=ParameterApplication(f[3],f[11],f[12]).compile()
before=MoiIdentity(merged);after=MoiIdentity(Path(sys.argv[1]).read_bytes());expected=bytearray(before.data)
p=before.reader.records[C]['properties'][3113]['value_start_offset']+1
w=before.reader.records[REF]['properties'][3118]['value_start_offset']+2
expected[p:p+4]=struct.pack('>f',0.1);expected[w]=1
print(json.dumps({'literal_bytes_exact':after.data==bytes(expected),'source':after.reader.diagram(REF)['connections'][0]['source_ref'],'saved_a':after.reader.scalar(after.reader.records[A],3113),'saved_b':after.reader.scalar(after.reader.records[B],3113),'saved_boolean':after.reader.scalar(after.reader.records[BOOLEAN],3113)}))
`,
      file,
    ),
  );
  expect(proof).toEqual({
    literal_bytes_exact: true,
    source: b,
    saved_a: 42,
    saved_b: 17,
    saved_boolean: true,
  });
  await expect(copy.getByRole("status")).toContainText(
    "Saved reviewed combined native copy.",
  );
  await copy.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("combined-native-desktop.png"),
  });
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("CAF entry retains its original file and readable keyboard-accessible combined review on a phone", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 412, height: 915 });
  const { copy } = await enter(page, seed().a, true);
  await review(copy);
  const table = copy.getByRole("region", {
    name: "Combined native proposal table",
    exact: true,
  });
  await table.focus();
  await expect(table).toBeFocused();
  expect(
    await table.evaluate((e) => e.getBoundingClientRect().width),
  ).toBeLessThan(412);
  await copy.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("combined-native-phone.png") });
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-combined.caf");
  expect(calls.get(page)).toEqual([]);
});

test("navigation retains ordinary raw text and the separate combined connection draft while retiring review", async ({
  page,
}) => {
  const { parent, copy } = await enter(page);
  await review(copy);
  await parent
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("1e-");
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await openNativeCompiler(page);
  await expect(
    parent.getByLabel("Proposed native Real default", { exact: true }),
  ).toHaveValue("1e-");
  await expand(copy);
  await expect(
    copy.getByLabel("Combined replacement source", { exact: true }),
  ).toHaveValue(b);
  await expect(reviewed(copy)).toHaveCount(0);
  await copy
    .getByRole("button", {
      name: "Review combined native compilation",
      exact: true,
    })
    .click();
  await expect(copy.getByRole("alert")).toContainText("finite decimal");
  await parent
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("0.1");
  await review(copy);
  expect(calls.get(page)).toEqual([]);
});

test("snapshot and connection selectors retain independent drafts without reusing either review", async ({
  page,
}) => {
  const { copy } = await enter(page);
  await review(copy);
  await copy
    .getByLabel("Combined native connection", { exact: true })
    .selectOption("1");
  await copy
    .getByRole("button", { name: "Inspect combined connection", exact: true })
    .click();
  await copy
    .getByLabel("Combined replacement source", { exact: true })
    .selectOption(a);
  await review(copy);
  await copy
    .getByLabel("Combined native connection", { exact: true })
    .selectOption("0");
  await copy
    .getByRole("button", { name: "Inspect combined connection", exact: true })
    .click();
  await expect(
    copy.getByLabel("Combined replacement source", { exact: true }),
  ).toHaveValue(b);
  await expect(reviewed(copy)).toHaveCount(0);
  await choose(page, seed().b);
  await load(combined(page));
  await expect(
    combined(page).getByLabel("Combined replacement source", { exact: true }),
  ).toHaveValue(a);
  await expect(combined(page)).toContainText("device,5136 at 7");
  await choose(page, seed().a);
  await load(combined(page));
  await expect(
    combined(page).getByLabel("Combined replacement source", { exact: true }),
  ).toHaveValue(b);
  await expect(reviewed(combined(page))).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

for (const transition of ["raw-default", "replacement", "disclosure"])
  test(`delayed review cannot survive ${transition} A B A`, async ({
    page,
  }) => {
    const { parent, copy } = await enter(page),
      gate = await delayed(page, "preview");
    try {
      await copy
        .getByRole("button", {
          name: "Review combined native compilation",
          exact: true,
        })
        .click();
      await gate.received;
      if (transition === "raw-default")
        await parent
          .getByLabel("Proposed native Real default", { exact: true })
          .evaluate((e: HTMLInputElement) => {
            const set = Object.getOwnPropertyDescriptor(
              HTMLInputElement.prototype,
              "value",
            )!.set!;
            for (const value of ["2", "0.1"]) {
              set.call(e, value);
              e.dispatchEvent(new Event("input", { bubbles: true }));
            }
          });
      else if (transition === "replacement")
        await copy
          .getByLabel("Combined replacement source", { exact: true })
          .evaluate(
            (e: HTMLSelectElement, values: string[]) => {
              for (const value of values) {
                e.value = value;
                e.dispatchEvent(new Event("change", { bubbles: true }));
              }
            },
            [a, b],
          );
      else {
        await copy.locator(":scope > summary").click();
        await copy.locator(":scope > summary").click();
      }
      gate.release();
      await gate.complete;
      await expect(reviewed(copy)).toHaveCount(0);
      await review(copy);
      expect(calls.get(page)).toEqual([]);
    } finally {
      gate.release();
    }
  });

test("retired delayed download cannot save after navigation or restore its review", async ({
  page,
}) => {
  const { copy } = await enter(page);
  const result = await review(copy),
    gate = await delayed(page, "export");
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  try {
    await result
      .getByRole("button", {
        name: "Save compiled default and connection",
        exact: true,
      })
      .click();
    await gate.received;
    await chooseWorkspaceSurface(page, "Library");
    gate.release();
    await gate.complete;
    await chooseWorkspaceSurface(page, "Workspace");
    await openNativeCompiler(page);
    await expand(copy);
    await expect(reviewed(copy)).toHaveCount(0);
    expect(downloads).toEqual([]);
    await review(copy);
  } finally {
    gate.release();
  }
});

for (const fault of ["preservation", "intermediate", "route"])
  test(`substituted ${fault} review remains unavailable in the browser`, async ({
    page,
  }) => {
    const { copy } = await enter(page);
    await page.route("**/inspection/default-wire/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (fault === "preservation")
        data.compilation.other_merged_bytes_preserved = false;
      if (fault === "intermediate")
        data.compilation.default_then_wire.intermediate_sha256 = "0".repeat(64);
      if (fault === "route") data.target.address = "127.0.0.1:47999";
      await route.fulfill({ response, body: JSON.stringify(data) });
    });
    await copy
      .getByRole("button", {
        name: "Review combined native compilation",
        exact: true,
      })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "Combined native review differs",
    );
    await expect(reviewed(copy)).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });

for (const fault of ["bytes", "snapshot", "review"])
  test(`substituted ${fault} export cannot download`, async ({ page }) => {
    const { copy } = await enter(page);
    const result = await review(copy),
      downloads: string[] = [];
    page.on("download", (d) => downloads.push(d.suggestedFilename()));
    await page.route("**/inspection/default-wire/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        headers = response.headers();
      if (fault !== "bytes")
        headers[`x-studio-${fault}-sha256`] = "0".repeat(64);
      await route.fulfill({
        response,
        headers,
        ...(fault === "bytes"
          ? { body: Buffer.from("Substituted compiled bytes") }
          : {}),
      });
    });
    await result
      .getByRole("button", {
        name: "Save compiled default and connection",
        exact: true,
      })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "Combined native output bytes differ",
    );
    expect(downloads).toEqual([]);
  });

test("discarding the combined connection draft preserves the ordinary Real draft and compiler", async ({
  page,
}) => {
  const { parent, copy } = await enter(page);
  await review(copy);
  await copy
    .getByRole("button", {
      name: "Discard combined connection draft",
      exact: true,
    })
    .click();
  await expect(
    copy.getByLabel("Combined replacement source", { exact: true }),
  ).toHaveValue(a);
  await expect(
    parent.getByLabel("Proposed native Real default", { exact: true }),
  ).toHaveValue("0.1");
  await expect(reviewed(copy)).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
  await parent
    .getByRole("button", { name: "Review native compilation", exact: true })
    .click();
  await expect(
    parent.getByRole("region", {
      name: "Reviewed native compilation",
      exact: true,
    }),
  ).toBeVisible();
  expect(calls.get(page)).toEqual([
    new URL(
      "/api/bacnet/controller/native-application/signal-default/preview",
      page.url(),
    ).href,
  ]);
});

test("unknown saved parameter storage refuses both effective compilers without changing original inspection", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  const parent = compiler(page);
  await parent
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(seed().unknown);
  await parent
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await expect(parent.getByRole("alert")).toBeVisible();
  await expect(combined(page)).toHaveCount(0);
  await parent
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  await expect(
    parent.getByLabel("Native archive inspection source", { exact: true }),
  ).toContainText(
    `Archive ${seed().unknown.slice(0, 8)} · device,5136 at 127.0.0.1:47819`,
  );
  await expect(
    parent.getByRole("region", {
      name: "Retained native backup inspection",
      exact: true,
    }),
  ).toContainText("7 indexed engineering records · 1 metadata records");
  expect(calls.get(page)).toEqual([]);
});

test("connected authored routed capture compiles locally without new peer traffic or writes", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-wire");
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
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill("3001:7");
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill(peer.router);
    await page.getByLabel("Known network", { exact: true }).fill("3001");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored native wire controller");
    await openNativeCompiler(page);
    const transfer = page.getByRole("region", {
      name: "Native default controller transfer",
      exact: true,
    });
    await transfer
      .getByText("Native backup and restore credentials", { exact: true })
      .click();
    await transfer
      .getByLabel("Native backup credential", { exact: true })
      .fill("authored-backup");
    await transfer
      .getByLabel("Native restore credential", { exact: true })
      .fill("authored-restore");
    await transfer
      .getByRole("button", {
        name: "Save native transfer credentials",
        exact: true,
      })
      .click();
    await transfer
      .getByRole("button", { name: "Read current native backup", exact: true })
      .click();
    const parent = compiler(page);
    await expect(
      parent.getByLabel("Native compiler snapshot source", { exact: true }),
    ).toContainText("3 saved application parameters");
    await parent
      .getByLabel("Native Real default", { exact: true })
      .selectOption(c);
    await parent
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("-0");
    const before = await peer.command("stats");
    calls.get(page)!.length = 0;
    const copy = combined(page);
    await load(copy);
    await copy
      .getByLabel("Combined replacement source", { exact: true })
      .selectOption(b);
    const result = await review(copy),
      downloading = page.waitForEvent("download");
    await result
      .getByRole("button", {
        name: "Save compiled default and connection",
        exact: true,
      })
      .click();
    await downloading;
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    expect(after.router_errors).toEqual([]);
    expect(calls.get(page)).toEqual([]);
    await expect(copy).toContainText(
      `device,5136 at 3001:7 via ${peer.router} / DNET 3001`,
    );
    await expect(
      copy.getByRole("button", { name: /Apply.*controller/ }),
    ).toHaveCount(0);
  } finally {
    peer.close();
  }
});
