import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  openNativeCompiler,
  chooseWorkspaceSurface,
} from "./workspace-navigation";

const root = path.resolve("..");
function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [
          process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
          root,
        ].join(path.delimiter),
      },
      encoding: "utf8",
    },
  );
}
function seed(directory: string) {
  return JSON.parse(
    python(
      `
import json,sys,base64
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity
from tests.test_moi_enum_defaults import enum_source
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]))
files={3:enum_source(),11:b'Opaque original static schema',12:b'Opaque original saved values'}
a=retained(s,files)
files[3]=enum_source(cid=529,compressed=False)
b=retained(s,files,target={'address':'10','router':'127.0.0.1:47919','dnet':200},source_identity_matches=False,source_identity_error='Authored incomplete acquisition identity')
print(json.dumps({'a':a['id'],'b':b['id'],'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
    ),
  );
}
async function inspect(compiler: Locator) {
  await compiler
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  const records = compiler.getByLabel("Captured native record explorer", {
    exact: true,
  });
  await records.locator(":scope > summary").click();
  return records;
}
async function record(records: Locator, ref = "controller/enum-1") {
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({ hasText: ref })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const copy = records.getByRole("region", {
    name: "Native Enum default archive copy",
    exact: true,
  });
  if (ref === "controller/enum-1") await expect(copy).toBeVisible();
  return copy;
}
async function enter(page: Page, id: string, caf = "") {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "authored-enum-context.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-enum-context.caf");
  } else
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
    .selectOption(id);
  const records = await inspect(compiler);
  return { compiler, records, copy: await record(records) };
}
async function review(copy: Locator, code = "4294967295") {
  await copy.getByLabel("Proposed Enum code", { exact: true }).fill(code);
  await copy
    .getByRole("button", { name: "Review Enum copy", exact: true })
    .click();
  const result = copy.getByRole("region", {
    name: "Reviewed Enum archive copy",
    exact: true,
  });
  await expect(result).toContainText(`copy code ${Number(code)}`);
  return result;
}
const digest = (body: Buffer) =>
  createHash("sha256").update(body).digest("hex");

test("connected routed entry keeps Enum copying local and retires review after a controller change", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
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
    await openNativeCompiler(page);
    const compiler = page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    });
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(ids.a);
    return record(await inspect(compiler));
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
    const copy = await select(true),
      before = await peer.command("stats");
    await review(copy, "256");
    const pending = page.waitForEvent("download");
    await copy
      .getByRole("button", { name: "Save Enum file copy", exact: true })
      .click();
    await pending;
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    const changed = await select(false);
    await expect(
      changed.getByLabel("Proposed Enum code", { exact: true }),
    ).toHaveValue("256");
    await expect(
      changed.getByRole("region", {
        name: "Reviewed Enum archive copy",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    peer.close();
  }
});

for (const caf of [false, true]) {
  test(`${caf ? "CAF" : "new application"} entry saves exact Enum review and native copy without a field connection`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const ids = seed(nativeScheduleWriteServer.directory);
    const { copy } = await enter(page, caf ? ids.b : ids.a, caf ? ids.caf : "");
    let original = Buffer.alloc(0);
    const before = python(
      `
import json,sys,hashlib
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
s=ApplicationStore(Store(sys.argv[1]));m,f=s.load(sys.argv[2]);print(json.dumps({'manifest':m,'files':{i:hashlib.sha256(v).hexdigest() for i,v in f.items()}} ,sort_keys=True))
`,
      nativeScheduleWriteServer.directory,
      caf ? ids.b : ids.a,
    );
    await page.route("**/inspection/enum-default/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      original = await response.body();
      await route.fulfill({ response });
    });
    const prepared = await review(copy);
    await expect(copy.locator("button.primary")).toHaveCount(1);
    await expect(
      copy.getByRole("button", { name: "Save Enum file copy", exact: true }),
    ).toHaveClass("primary");
    await copy.getByLabel("Proposed Enum code", { exact: true }).focus();
    await expect(
      copy.getByLabel("Proposed Enum code", { exact: true }),
    ).toBeFocused();
    const evidencePending = page.waitForEvent("download");
    await prepared
      .getByRole("button", { name: "Save Enum copy review", exact: true })
      .click();
    expect(readFileSync((await (await evidencePending).path())!)).toEqual(
      original,
    );
    const pending = page.waitForEvent("download");
    await prepared
      .getByRole("button", { name: "Save Enum file copy", exact: true })
      .click();
    const file = (await (await pending).path())!,
      data = JSON.parse(original.toString());
    expect(digest(readFileSync(file))).toBe(data.output_sha256);
    const proof = JSON.parse(
      python(
        `
import json,sys,hashlib
from pathlib import Path
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity
s=ApplicationStore(Store(sys.argv[1]));m,f=s.load(sys.argv[2]);a=MoiIdentity(Path(sys.argv[3]).read_bytes());r=a.reader.records['controller/enum-1'];p=r['properties'][3113];raw=a.data[p['value_start_offset']:p['value_end_offset']]
assert raw==b'\\x94\\xff\\xff\\xff\\xff\\x2f'
print(json.dumps({'code':a.reader.scalar(r,3113),'states':a.reader.scalar(r,931),'instance':a.instance,'receipts':len(s.receipts()),'original':json.dumps({'manifest':m,'files':{i:hashlib.sha256(v).hexdigest() for i,v in f.items()}},sort_keys=True)+'\\n'}))
`,
        nativeScheduleWriteServer.directory,
        caf ? ids.b : ids.a,
        file,
      ),
    );
    expect(proof).toEqual({
      code: 4294967295,
      states: 291,
      instance: 5136,
      receipts: 0,
      original: before,
    });
    expect(data.controller_write).toBe(false);
    expect(data.enum_semantics_verified).toBe(false);
    expect(data.field_transfer_enabled).toBe(false);
    expect(data.source_identity_matches).toBe(!caf);
    await expect(copy).toContainText(
      "membership and state meanings are unverified",
    );
    expect(
      await copy
        .getByLabel("Proposed Enum code", { exact: true })
        .evaluate((e) => Number.parseFloat(getComputedStyle(e).fontSize)),
    ).toBeGreaterThanOrEqual(14);
    await copy.scrollIntoViewIfNeeded();
    const bounds = await copy.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.width).toBeLessThanOrEqual(caf ? 390 : 1440);
    await page.screenshot({
      path: info.outputPath(
        caf ? "enum-copy-phone.png" : "enum-copy-desktop.png",
      ),
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
}

test("unfinished Enum codes survive record, task and source A B A navigation; reviews do not", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
    { compiler, records, copy } = await enter(page, ids.a);
  await review(copy);
  await copy.getByLabel("Proposed Enum code", { exact: true }).fill(" 1e-");
  await expect(
    copy.getByRole("region", {
      name: "Reviewed Enum archive copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await record(records, "controller/module-0");
  await record(records);
  await expect(
    copy.getByLabel("Proposed Enum code", { exact: true }),
  ).toHaveValue(" 1e-");
  await copy
    .getByRole("button", { name: "Review Enum copy", exact: true })
    .click();
  await expect(copy.getByRole("alert")).toContainText("decimal Enum code");
  const choices = compiler.getByLabel("Retained native backup", {
    exact: true,
  });
  await choices.selectOption(ids.b);
  const b = await record(await inspect(compiler));
  await b.getByLabel("Proposed Enum code", { exact: true }).fill("");
  await choices.selectOption(ids.a);
  const a = await record(await inspect(compiler));
  await expect(a.getByLabel("Proposed Enum code", { exact: true })).toHaveValue(
    " 1e-",
  );
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await openNativeCompiler(page);
  const again = await record(await inspect(compiler));
  await expect(
    again.getByLabel("Proposed Enum code", { exact: true }),
  ).toHaveValue(" 1e-");
  await again
    .getByRole("button", { name: "Discard local Enum draft", exact: true })
    .click();
  await expect(
    again.getByLabel("Proposed Enum code", { exact: true }),
  ).toHaveValue("1");
  await choices.selectOption(ids.b);
  await expect(
    (await record(await inspect(compiler))).getByLabel("Proposed Enum code", {
      exact: true,
    }),
  ).toHaveValue("");
});

for (const altered of ["source", "class", "code", "authority"]) {
  test(`substituted Enum review ${altered} cannot become export authority`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { copy } = await enter(page, ids.a);
    await page.route("**/inspection/enum-default/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (altered === "source") data.request.source_sha256 = "0".repeat(64);
      if (altered === "class") data.edit.class_id = 529;
      if (altered === "code") data.edit.after_value = 2;
      if (altered === "authority") data.controller_write = true;
      await route.fulfill({ response, json: data });
    });
    await copy.getByLabel("Proposed Enum code", { exact: true }).fill("256");
    await copy
      .getByRole("button", { name: "Review Enum copy", exact: true })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "differs from this exact captured field",
    );
    await expect(
      copy.getByRole("button", { name: "Save Enum file copy", exact: true }),
    ).toHaveCount(0);
  });
}

for (const altered of ["body", "artifact", "review", "snapshot"]) {
  test(`substituted Enum export ${altered} is refused with raw draft retained`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { copy } = await enter(page, ids.a);
    await review(copy, " 000256 ");
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/inspection/enum-default/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        headers = response.headers();
      if (altered !== "body")
        headers[`x-studio-${altered}-sha256`] = "0".repeat(64);
      await route.fulfill({
        response,
        headers,
        body:
          altered === "body"
            ? Buffer.from("substituted authored artifact")
            : await response.body(),
      });
    });
    await copy
      .getByRole("button", { name: "Save Enum file copy", exact: true })
      .click();
    await expect(copy.getByRole("alert")).toContainText(
      "differs from its original source or review",
    );
    expect(downloads).toBe(0);
    await expect(
      copy.getByLabel("Proposed Enum code", { exact: true }),
    ).toHaveValue(" 000256 ");
    await expect(
      copy.getByRole("region", {
        name: "Reviewed Enum archive copy",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

for (const phase of ["preview", "export"]) {
  for (const retire of ["edit", "source", "visibility", "pagehide"]) {
    test(`late Enum ${phase} after ${retire} cannot revive a review or download`, async ({
      page,
      nativeScheduleWriteServer,
    }) => {
      const ids = seed(nativeScheduleWriteServer.directory),
        { compiler, copy } = await enter(page, ids.a);
      if (phase === "export") await review(copy, "256");
      else
        await copy
          .getByLabel("Proposed Enum code", { exact: true })
          .fill("256");
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
      await page.route(`**/inspection/enum-default/${phase}`, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      });
      try {
        await copy
          .getByRole("button", {
            name:
              phase === "preview" ? "Review Enum copy" : "Save Enum file copy",
            exact: true,
          })
          .click();
        await received;
        if (retire === "edit")
          await copy
            .getByLabel("Proposed Enum code", { exact: true })
            .fill("1e");
        if (retire === "source") {
          const choices = compiler.getByLabel("Retained native backup", {
            exact: true,
          });
          await choices.selectOption(ids.b);
          await choices.selectOption(ids.a);
        }
        if (retire === "visibility")
          await page.evaluate(() =>
            document.dispatchEvent(new Event("visibilitychange")),
          );
        if (retire === "pagehide")
          await page.evaluate(() =>
            window.dispatchEvent(new Event("pagehide")),
          );
        const settled = page.waitForResponse((response) =>
          response.url().endsWith(`/enum-default/${phase}`),
        );
        release();
        await settled;
        // Wait for the response body/digest handler to release its local busy
        // state before checking that no late authority or download appeared.
        if (retire === "source") await page.waitForLoadState("networkidle");
        else
          await expect(
            copy.getByRole("button", { name: "Review Enum copy", exact: true }),
          ).toBeEnabled();
        if (retire === "source") await record(await inspect(compiler));
        await expect(
          copy.getByRole("region", {
            name: "Reviewed Enum archive copy",
            exact: true,
          }),
        ).toHaveCount(0);
        await expect(
          copy.getByLabel("Proposed Enum code", { exact: true }),
        ).toHaveValue(retire === "edit" ? "1e" : "256");
        expect(downloads).toBe(0);
      } finally {
        release();
      }
    });
  }
}
