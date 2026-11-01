import { test, expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { openNativeCompiler } from "./workspace-navigation";

const root = path.resolve("..");
const endpoint = "/api/bacnet/controller/native-application/inspection/compare";
function seed() {
  const state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state) throw new Error("An isolated state directory is required.");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json,struct
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained,signal_files
from tests.test_native_backup_comparison import archive,record,source
from tests.test_controller_application import encoded
from bacpypes3.primitivedata import Unsigned
s=ApplicationStore(Store(sys.argv[1]));a=retained(s,signal_files(compressed=False))
files=signal_files(compressed=False);before=b'\\x44'+struct.pack('>f',23.5)+b'\\x2f';assert files[3].count(before)==1
files[3]=files[3].replace(before,b'\\x44'+struct.pack('>f',-0.0)+b'\\x2f')
b=retained(s,files,target={'address':'3001:8','router':'127.0.0.1:49000','dnet':3001})
c=source(s,b'Opaque comparable native File3')
da=source(s,archive(record(properties=[(65000+i,encoded(Unsigned(i))) for i in range(41)])))
db=source(s,archive(record(properties=[(65000+i,encoded(Unsigned(i+1))) for i in range(41)])))
print(json.dumps({'a':a['id'],'b':b['id'],'opaque':c['capture_id'],'manyA':da['capture_id'],'manyB':db['capture_id']}))
`,
        state,
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
}
async function enter(page: Page, left: string, right: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(left);
  const panel = compiler.getByLabel("Retained native backup comparison", {
    exact: true,
  });
  await panel.locator(":scope > summary").click();
  await panel
    .getByLabel("Right native backup", { exact: true })
    .selectOption(right);
  return { compiler, panel };
}
async function compare(panel: Locator) {
  await panel
    .getByRole("button", { name: "Compare original backups", exact: true })
    .click();
  await expect(
    panel.getByRole("region", {
      name: "Native backup comparison results",
      exact: true,
    }),
  ).toBeVisible();
}
async function hold(page: Page) {
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const entered = new Promise<void>((resolve) => {
    seen = resolve;
  });
  await page.route("**" + endpoint, async (route) => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    seen();
    await gate;
    await route.fulfill({ response });
  });
  return {
    entered,
    async finish() {
      const done = page.waitForResponse((r) => r.url().endsWith(endpoint));
      release();
      await (await done).finished();
      await page.unroute("**" + endpoint);
    },
    release,
  };
}
async function cleared(panel: Locator) {
  await expect(
    panel.getByRole("region", {
      name: "Native backup comparison results",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", {
      name: "Download comparison JSON",
      exact: true,
    }),
  ).toBeDisabled();
}

test("offline comparison retains both routes, original JSON numbers and hashes without field requests", async ({
  page,
  request,
}) => {
  const ids = seed();
  const forbidden: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      r.url().includes("/api/bacnet/") &&
      !r.url().endsWith(endpoint)
    )
      forbidden.push(r.url());
  });
  const { panel } = await enter(page, ids.a, ids.b);
  let original!: Buffer;
  await page.route("**" + endpoint, async (route) => {
    const r = await route.fetch();
    expect(r.ok()).toBe(true);
    original = await r.body();
    await route.fulfill({ response: r });
  });
  await compare(panel);
  await expect(panel).toContainText("Real · -0.0");
  await expect(
    panel.getByLabel("right compared backup", { exact: true }),
  ).toContainText("3001:8 via 127.0.0.1:49000 / DNET 3001");
  const download = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download comparison JSON", exact: true })
    .click();
  const file = (await (await download).path())!;
  expect(readFileSync(file).equals(original)).toBe(true);
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `
import hashlib,json,math,sys
raw=open(sys.argv[1],'rb').read();r=json.loads(raw)
seal=r.pop('evidence_sha256');assert hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest()==seal
values=[x['right']['scalar']['value'] for x in r['rows'] if x['property']==3113]
assert any(type(x) is float and x==0 and math.copysign(1,x)==-1 for x in values)
assert not r['controller_queries'] and not r['field_actions'] and not r['restore_plan'] and not r['semantics_verified']
`,
      file,
    ],
    { cwd: root },
  );
  expect(forbidden).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("opaque sources retain byte comparisons and explicit unavailable structured coverage", async ({
  page,
}) => {
  const ids = seed();
  const { panel } = await enter(page, ids.a, ids.opaque);
  await compare(panel);
  await expect(panel).toContainText("Structured record comparison unavailable");
  await expect(
    panel
      .getByRole("table", { name: "Original native backup files", exact: true })
      .getByRole("row"),
  ).toHaveCount(4);
  await expect(
    panel.getByRole("table", {
      name: "Native record and property differences",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("paging and query keep bounded differences and retire old pages immediately", async ({
  page,
}) => {
  const ids = seed();
  const { panel } = await enter(page, ids.manyA, ids.manyB);
  await compare(panel);
  const table = panel.getByRole("table", {
    name: "Native record and property differences",
    exact: true,
  });
  await expect(table.locator("tbody tr")).toHaveCount(32);
  await panel
    .getByRole("button", { name: "Next comparison page", exact: true })
    .click();
  await expect(table.locator("tbody tr")).toHaveCount(10);
  await panel
    .getByLabel("Search native comparison", { exact: true })
    .fill("65040");
  await cleared(panel);
  await compare(panel);
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table).toContainText("65040");
});

test("a comparison naming another snapshot is refused before display or download", async ({
  page,
}) => {
  const ids = seed();
  const { panel } = await enter(page, ids.a, ids.b);
  await page.route("**" + endpoint, async (route) => {
    const r = await route.fetch();
    const data = await r.json();
    data.right.capture_id = ids.a;
    await route.fulfill({ response: r, json: data });
  });
  await panel
    .getByRole("button", { name: "Compare original backups", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("does not match");
  await cleared(panel);
});

for (const change of ["left", "right", "query", "disclosure"] as const) {
  test(`pending comparison retires through ${change} changes including source ABA`, async ({
    page,
  }) => {
    const ids = seed();
    const { panel, compiler } = await enter(page, ids.a, ids.b);
    const held = await hold(page);
    try {
      await panel
        .getByRole("button", { name: "Compare original backups", exact: true })
        .click();
      await held.entered;
      if (change === "left") {
        const select = compiler.getByLabel("Retained native backup", {
          exact: true,
        });
        await select.selectOption(ids.b);
        await select.selectOption(ids.a);
      }
      if (change === "right") {
        const select = panel.getByLabel("Right native backup", { exact: true });
        await select.selectOption(ids.a);
        await select.selectOption(ids.b);
      }
      if (change === "query") {
        const input = panel.getByLabel("Search native comparison", {
          exact: true,
        });
        await input.fill("65000");
        await input.fill("");
      }
      if (change === "disclosure") {
        await panel.locator(":scope > summary").click();
        await panel.locator(":scope > summary").click();
      }
      await held.finish();
      await cleared(panel);
    } finally {
      held.release();
    }
  });
}

test("task navigation cannot revive a late comparison when the retained compiler returns", async ({
  page,
}) => {
  const ids = seed();
  const { panel } = await enter(page, ids.a, ids.b);
  const held = await hold(page);
  try {
    await panel
      .getByRole("button", { name: "Compare original backups", exact: true })
      .click();
    await held.entered;
    await page
      .getByRole("navigation", { name: "Main navigation", exact: true })
      .getByRole("button", { name: "Help", exact: true })
      .click();
    await held.finish();
    await page
      .getByRole("navigation", { name: "Main navigation", exact: true })
      .getByRole("button", { name: "Workspace", exact: true })
      .click();
    await openNativeCompiler(page);
    await cleared(panel);
  } finally {
    held.release();
  }
});

test("phone comparison keeps readable context and table overflow inside the engineering table", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 900 });
  const ids = seed();
  const { panel } = await enter(page, ids.a, ids.b);
  await compare(panel);
  const summary = panel.locator(":scope > summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(panel).not.toHaveAttribute("open");
  await page.keyboard.press("Enter");
  await compare(panel);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  const scroll = panel.getByLabel("Original file comparison scroll area", {
    exact: true,
  });
  expect(await scroll.evaluate((e) => e.scrollWidth > e.clientWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("phone-comparison.png"),
    fullPage: true,
  });
  await scroll.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("phone-files.png"),
    fullPage: true,
  });
});
