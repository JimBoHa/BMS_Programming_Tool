import { test, expect, type Page, type Locator } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

const root = fileURLToPath(new URL("../..", import.meta.url));
function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      encoding: "utf8",
    },
  );
}
function seed(direct = "127.0.0.1:47918", router = "127.0.0.1:47919") {
  return JSON.parse(
    python(
      `
import json,sys,base64
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained,signal_files
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]))
a=retained(s,target={'address':sys.argv[2],'router':None,'dnet':None})
b=retained(s,target={'address':'3001:7','router':sys.argv[3],'dnet':3001})
files=signal_files();files[11]=b'Unknown saved selectors';files[12]=b'Opaque saved values'
unknown=retained(s,files)
print(json.dumps({'a':a['id'],'b':b['id'],'unknown':unknown['id'],
'caf':base64.b64encode(caf_source().original).decode(),
'other':base64.b64encode(caf_source(model='Another model').original).decode()}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
      direct,
      router,
    ),
  );
}
function panel(page: Page) {
  return page.getByRole("region", {
    name: "CAF/native source comparison",
    exact: true,
  });
}
async function compatibility(page: Page) {
  await page
    .getByRole("navigation", { name: "CAF application tasks", exact: true })
    .getByRole("button", { name: "Compatibility", exact: true })
    .click();
  const result = panel(page),
    disclosure = result.locator(":scope > details");
  if ((await disclosure.getAttribute("open")) === null)
    await disclosure.locator(":scope > summary").click();
  return result;
}
async function chooseFile(page: Page, encoded: string, name = "authored.caf") {
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: Buffer.from(encoded, "base64"),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText(name);
}
async function open(page: Page, ids: any) {
  await page.goto("/");
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name: "authored.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(ids.caf, "base64"),
  });
  const p = await compatibility(page);
  await p
    .getByLabel("Native backup for CAF comparison", { exact: true })
    .selectOption(ids.a);
  return p;
}
async function compare(p: Locator) {
  await p
    .getByRole("button", {
      name: "Compare original CAF and native archive",
      exact: true,
    })
    .click();
  const result = p.getByRole("region", {
    name: "CAF/native comparison result",
    exact: true,
  });
  await expect(result).toContainText(
    "Recorded identities equal within the checked scope",
  );
  return result;
}
const fieldCalls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const calls: string[] = [];
  fieldCalls.set(page, calls);
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      calls.push(r.url());
  });
});

test("offline comparison retains exact report bytes, literal scope, keyboard access and narrow layout", async ({
  page,
  request,
}, info) => {
  const ids = seed();
  await page.setViewportSize({ width: 820, height: 1100 });
  const p = await open(page, ids);
  expect(
    (await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .boundingBox())!.height,
  ).toBeGreaterThanOrEqual(36);
  expect(
    await p
      .locator(".card-body > p")
      .first()
      .evaluate((node) => getComputedStyle(node).fontSize),
  ).toBe("14px");
  let original = Buffer.alloc(0);
  await page.route("**/native-correlation", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    original = await response.body();
    await route.fulfill({ response });
  });
  await p.getByLabel("Find comparison records", { exact: true }).press("Enter");
  const result = p.getByRole("region", {
    name: "CAF/native comparison result",
    exact: true,
  });
  await expect(result).toContainText(
    "8 CAF objects · 8 native engineering records · 1 native metadata records",
  );
  await expect(result).toContainText(
    "Full program match, compiler compatibility and a live application association remain unverified.",
  );
  await expect(
    result
      .getByRole("table", {
        name: "CAF/native record identity observations",
        exact: true,
      })
      .getByRole("row"),
  ).toHaveCount(9);
  const download = page.waitForEvent("download");
  await result
    .getByRole("button", { name: "Save exact source comparison", exact: true })
    .click();
  expect(readFileSync((await (await download).path())!)).toEqual(original);
  const data = JSON.parse(original.toString());
  expect(data.request.capture_id).toBe(ids.a);
  expect(data.application_association_granted).toBe(false);
  await p.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("caf-native-comparison-820.png"),
  });
  expect(fieldCalls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("Unicode reference limits count actual characters rather than UTF16 code units", async ({
  page,
}) => {
  const ids = JSON.parse(
    python(
      `
import sys,json,base64
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import unicode_files,caf_source,UNICODE_ROOT
s=ApplicationStore(Store(sys.argv[1]));a=retained(s,unicode_files())
print(json.dumps({'a':a['id'],'caf':base64.b64encode(caf_source(root=UNICODE_ROOT).original).decode()}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
    ),
  );
  const p = await open(page, ids),
    result = await compare(p);
  await expect(
    result
      .getByRole("table", {
        name: "CAF/native record identity observations",
        exact: true,
      })
      .getByRole("row"),
  ).toHaveCount(9);
  expect(fieldCalls.get(page)).toEqual([]);
});

test("original CAF proposals and comparison query survive workspace navigation without implying draft comparison", async ({
  page,
}) => {
  const ids = seed();
  const p = await open(page, ids);
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await page
    .locator(".caf-layout tbody tr")
    .filter({ hasText: "Authored controller" })
    .click();
  await page
    .getByLabel("CAF property 2390", { exact: true })
    .fill("Unexported local name");
  await compatibility(page);
  await expect(p).toContainText("Local CAF proposals are excluded");
  await p.getByLabel("Find comparison records", { exact: true }).fill("signal");
  const result = await compare(p);
  await expect(result).toContainText("2 matching references");
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await compatibility(page);
  await expect(
    p.getByRole("region", {
      name: "CAF/native comparison result",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    p.getByLabel("Find comparison records", { exact: true }),
  ).toHaveValue("signal");
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await expect(
    page.getByLabel("CAF property 2390", { exact: true }),
  ).toHaveValue("Unexported local name");
  expect(fieldCalls.get(page)).toEqual([]);
});

test("source A B A cannot revive a delayed comparison", async ({ page }) => {
  const ids = seed(),
    p = await open(page, ids);
  let release = () => {},
    started!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    received = new Promise<void>((resolve) => {
      started = resolve;
    });
  await page.route(
    "**/native-correlation",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await p
      .getByRole("button", {
        name: "Compare original CAF and native archive",
        exact: true,
      })
      .click();
    await received;
    await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .selectOption(ids.b);
    await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .selectOption(ids.a);
    release();
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toHaveCount(0);
    await compare(p);
    expect(fieldCalls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("replacing the opened CAF retires pending comparison and requires explicit source selection", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  let release = () => {},
    started!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    received = new Promise<void>((resolve) => {
      started = resolve;
    });
  await page.route(
    "**/native-correlation",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await p
      .getByRole("button", {
        name: "Compare original CAF and native archive",
        exact: true,
      })
      .click();
    await received;
    await chooseFile(page, ids.other, "other.caf");
    await compatibility(page);
    release();
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      p.getByLabel("Native backup for CAF comparison", { exact: true }),
    ).toHaveValue("");
    await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .selectOption(ids.a);
    await p
      .getByRole("button", {
        name: "Compare original CAF and native archive",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toContainText("Recorded identity differences found");
    expect(fieldCalls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("unknown saved schema remains readable as original-archive comparison", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  await p
    .getByLabel("Native backup for CAF comparison", { exact: true })
    .selectOption(ids.unknown);
  await compare(p);
  expect(fieldCalls.get(page)).toEqual([]);
});

for (const fault of ["caf", "capture", "station", "grant", "digest"]) {
  test(`altered ${fault} comparison cannot become retained evidence`, async ({
    page,
  }) => {
    const ids = seed(),
      p = await open(page, ids);
    await page.route("**/native-correlation", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      const data = await response.json();
      if (fault === "caf") data.caf.sha256 = "0".repeat(64);
      if (fault === "capture") data.native_backup.capture_id = "a".repeat(32);
      if (fault === "station")
        data.native_backup.target.address = "127.0.0.1:47999";
      if (fault === "grant") data.application_association_granted = true;
      const body = JSON.stringify(data),
        headers = { ...response.headers() };
      headers["x-studio-artifact-sha256"] =
        fault === "digest"
          ? "0".repeat(64)
          : createHash("sha256").update(body).digest("hex");
      await route.fulfill({ response, body, headers });
    });
    await p
      .getByRole("button", {
        name: "Compare original CAF and native archive",
        exact: true,
      })
      .click();
    await expect(p.getByRole("alert")).toContainText(
      "Comparison evidence does not match",
    );
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      p.getByRole("button", {
        name: "Save exact source comparison",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(fieldCalls.get(page)).toEqual([]);
  });
}

test("connected routed station propagates into CAF context and comparison adds zero BACnet requests", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer();
  try {
    const ids = seed(peer.direct, peer.router);
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
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview", exact: true }),
    ).toContainText("Authored controller");
    await chooseFile(page, ids.caf);
    const p = await compatibility(page);
    await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .selectOption(ids.b);
    await expect(
      p.getByLabel("Comparison workspace relation", { exact: true }),
    ).toContainText("same station");
    const before = await peer.command("stats");
    await compare(p);
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    expect(
      after.events.filter(
        (row: any[]) =>
          row[0] === "write" ||
          (row[0] === "state" && row[1].includes("restore")),
      ),
    ).toEqual([]);
    await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .selectOption(ids.a);
    await expect(
      p.getByLabel("Comparison workspace relation", { exact: true }),
    ).toContainText("different station");
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    peer.close();
  }
});
