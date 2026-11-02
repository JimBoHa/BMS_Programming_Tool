import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  python,
  enter,
  inspect,
  effective,
  load,
} from "./native-effective-enum-fixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  chooseWorkspaceTask,
  openNativeCompiler,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";

const base = "/api/bacnet/controller/native-application";
const preparePath = base + "/enum-default/recovery/prepare";
const host = (page: Page) =>
  page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
const transfer = (editor: Locator) =>
  editor.getByRole("region", {
    name: "Native Enum default controller transfer",
    exact: true,
  });
const prepared = (page: Page) =>
  page.getByRole("region", {
    name: "Prepared previous Enum default",
    exact: true,
  });
const mutations = (events: any[]) =>
  events.filter(
    (row) =>
      row[0] === "write" || (row[0] === "state" && row[1].includes("restore")),
  );
function seed(directory: string, already = false) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys,pytest,base64
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_enum_recovery_transfer import recovery_review
from tests.test_native_enum_transfer import enum_slot
from tests.test_caf_native_correlation import caf_source
from bms_tool.native_enum_compiler import EffectiveEnumService
from bms_tool.native_backup_records import NativeBackupRecords
async def main():
 patch=pytest.MonkeyPatch();generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator)
 try:
  peer,_,_,service,target=link
  parent,capture,report,_,_=await recovery_review(link,previous=0)
  if sys.argv[2]=='already':
   enum_slot(peer.files,0);capture=await service.capture(**target,operation_id='enum-already-source')
  request=dict(receipt_id=parent['intent']['id'],capture_id=capture['id'],snapshot_sha256=capture['snapshot_evidence_sha256'])
  source=EffectiveEnumService(NativeBackupRecords(service.storage)).source({k:request[k] for k in ('capture_id','snapshot_sha256')})
  print(json.dumps(dict(a=capture['id'],before=parent['intent']['backup_id'],parent=parent,request=request,source=source,report=service.enum_recovery.prepare(request),caf=base64.b64encode(caf_source().original).decode())))
 finally:await generator.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
      already ? "already" : "after",
    ),
  );
}
async function receipt(panel: Locator, id: string) {
  const summary = panel
    .locator("summary")
    .filter({ hasText: /^Retained native default transfers/ });
  if ((await summary.locator("..").getAttribute("open")) === null)
    await summary.click();
  await panel
    .getByRole("button", {
      name: "Open receipt " + id.slice(0, 8),
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("region", {
      name: "Native default transfer outcome",
      exact: true,
    }),
  ).toBeVisible();
}
async function openField(compiler: Locator, value: string) {
  await inspect(compiler);
  const editor = await effective(compiler);
  await load(editor, value);
  return {
    editor,
    panel: transfer(editor),
    input: editor.getByLabel("Proposed effective Enum code", { exact: true }),
  };
}
for (const caf of [false, true]) {
  test(`${caf ? "CAF phone" : "offline"} previous Enum proposal preserves raw drafts, exact JSON and source ownership`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const data = seed(nativeScheduleWriteServer.directory);
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const view = await enter(page, data, "a", caf);
    await load(view.panel, "65535");
    const panel = transfer(view.panel),
      input = view.panel.getByLabel("Proposed effective Enum code", {
        exact: true,
      });
    await input.fill("01 unfinished");
    await receipt(panel, data.request.receipt_id);
    let exact = Buffer.alloc(0);
    await page.route("**/enum-default/recovery/prepare", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    });
    const fieldRequests: string[] = [];
    page.on("request", (r) => {
      if (/\/(connect|capture|transfer\/(preview|apply)|write)$/.test(r.url()))
        fieldRequests.push(r.url());
    });
    await panel
      .getByRole("button", {
        name: "Prepare previous Enum default",
        exact: true,
      })
      .click();
    await expect(prepared(page)).toContainText("65535 to 0");
    await expect(prepared(page)).toBeFocused();
    await expect(input).toHaveValue("0");
    await expect(input).toBeDisabled();
    await expect(
      panel.getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    const downloaded = page.waitForEvent("download");
    await prepared(page)
      .getByRole("button", {
        name: "Export exact previous Enum proposal",
        exact: true,
      })
      .click();
    const download = await downloaded;
    expect(readFileSync((await download.path())!)).toEqual(exact);
    expect(JSON.parse(exact.toString()).origin.previous_encoding_hex).toBe(
      "91002f",
    );
    expect(JSON.parse(exact.toString()).origin.proposal_encoding_hex).toBe(
      "9200002f",
    );
    expect(fieldRequests).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    await page.screenshot({
      path: info.outputPath(
        caf ? "enum-recovery-phone.png" : "enum-recovery-desktop.png",
      ),
      fullPage: true,
    });
    await view.compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(data.before);
    await openField(view.compiler, "0");
    await expect(prepared(page)).toHaveCount(0);
    await view.compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(data.a);
    const returned = await openField(view.compiler, "0");
    await expect(prepared(page)).toContainText(data.request.receipt_id);
    await returned.editor
      .getByRole("button", {
        name: "Discard previous Enum proposal",
        exact: true,
      })
      .click();
    await expect(returned.input).toHaveValue("01 unfinished");
    await expect(returned.input).toBeEnabled();
    await chooseWorkspaceTask(page, "Overview");
    await openNativeCompiler(page);
    const reopened = await openField(host(page), "01 unfinished");
    await expect(prepared(page)).toHaveCount(0);
    await reopened.editor
      .getByRole("button", {
        name: "Discard effective Enum draft",
        exact: true,
      })
      .click();
    await expect(reopened.input).toHaveValue("65535");
  });
}
test("already-previous Enum source reports evidence without creating an Apply proposal", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, true),
    view = await enter(page, data);
  await load(view.panel, "0");
  await receipt(transfer(view.panel), data.request.receipt_id);
  await transfer(view.panel)
    .getByRole("button", { name: "Prepare previous Enum default", exact: true })
    .click();
  await expect(prepared(page)).toContainText(
    "Previous Enum code already recorded in this backup",
  );
  await expect(prepared(page)).toContainText(
    "No transfer proposal was created",
  );
  await expect(
    view.panel.getByLabel("Proposed effective Enum code", { exact: true }),
  ).toBeEnabled();
});
for (const mutation of ["state metadata", "equal-code encoding"]) {
  test(`changed ${mutation} preparation is rejected while ordinary invalid text survives`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory),
      view = await enter(page, data);
    await load(view.panel, "65535");
    const panel = transfer(view.panel),
      input = view.panel.getByLabel("Proposed effective Enum code", {
        exact: true,
      });
    await input.fill("not a code");
    await receipt(panel, data.request.receipt_id);
    await page.route("**/enum-default/recovery/prepare", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        body = await response.json();
      if (mutation === "state metadata")
        body.origin.states_text_encoded_sha256 = "0".repeat(64);
      else body.origin.proposal_encoding_hex = "91002f";
      await route.fulfill({ response, json: body });
    });
    await panel
      .getByRole("button", {
        name: "Prepare previous Enum default",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "does not match this receipt",
    );
    await expect(prepared(page)).toHaveCount(0);
    await expect(input).toHaveValue("not a code");
  });
}
test("a late preparation after page lifecycle retirement cannot restore a proposal", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory),
    view = await enter(page, data);
  await load(view.panel, "65535");
  const panel = transfer(view.panel);
  await receipt(panel, data.request.receipt_id);
  let release = () => {},
    reached = () => {};
  const held = new Promise<void>((resolve) => (release = resolve)),
    intercepted = new Promise<void>((resolve) => (reached = resolve));
  await page.route("**/enum-default/recovery/prepare", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    reached();
    await held;
    await route.fulfill({ response });
  });
  try {
    await panel
      .getByRole("button", {
        name: "Prepare previous Enum default",
        exact: true,
      })
      .click();
    await intercepted;
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    const ended = page.waitForResponse((r) => r.url().endsWith(preparePath));
    release();
    await (await ended).finished();
    await expect(
      panel.getByRole("button", {
        name: "Prepare previous Enum default",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(prepared(page)).toHaveCount(0);
  } finally {
    release();
  }
});

async function connect(page: Page, endpoint: string, routed: boolean) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
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
    .fill(routed ? "3001:7" : endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page
    .getByLabel("Known router", { exact: true })
    .fill(routed ? endpoint : "");
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
  const compiler = host(page),
    shared = compiler.getByRole("region", {
      name: "Native default controller transfer",
      exact: true,
    });
  await shared
    .getByText("Native backup and restore credentials", { exact: true })
    .click();
  await shared
    .getByLabel("Native backup credential", { exact: true })
    .fill("authored-backup");
  await shared
    .getByLabel("Native restore credential", { exact: true })
    .fill("authored-restore");
  await shared
    .getByRole("button", {
      name: "Save native transfer credentials",
      exact: true,
    })
    .click();
  await expect(
    shared.getByLabel("Native backup credential", { exact: true }),
  ).toHaveValue("");
  await capture(page, shared);
  return { compiler, shared, ...(await openField(compiler, "513")) };
}
async function capture(page: Page, panel: Locator) {
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith(base + "/capture") && r.request().method() === "POST",
  );
  await panel
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  const data = await (await response).json();
  await expect(
    host(page).getByLabel("Retained native backup", { exact: true }),
  ).toHaveValue(data.id);
}
async function review(panel: Locator, before: number, after: number) {
  await panel
    .getByRole("button", {
      name: "Review controller default transfer",
      exact: true,
    })
    .click();
  const plan = panel.getByRole("region", {
    name: "Reviewed controller default transfer",
    exact: true,
  });
  await expect(plan).toContainText(
    `${before} → ${after} · stored value ${after}`,
  );
  const apply = plan.getByRole("button", {
    name: "Apply native default to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native Enum code and its intended meaning.",
      exact: true,
    })
    .check();
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the application transfer and controller interruption.",
      exact: true,
    })
    .check();
  return { plan, apply };
}
async function apply(
  page: Page,
  button: Locator,
  during?: () => Promise<void>,
) {
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/enum-default/transfer/apply") &&
      r.request().method() === "POST",
  );
  await button.click();
  if (during) await during();
  const result = await response;
  await result.finished();
  expect(result.ok()).toBe(true);
}
for (const variant of ["direct", "routed-phone", "routed-lost-ack"]) {
  test(`${variant} previous Enum code uses a fresh confirmed transfer and preserves unrelated live settings`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    test.setTimeout(60000);
    const peer = await nativeDefaultPeer("consume", "enum", true);
    let headers: any;
    try {
      if (variant === "routed-phone")
        await page.setViewportSize({ width: 390, height: 844 });
      const routed = variant !== "direct",
        view = await connect(page, routed ? peer.router : peer.direct, routed);
      headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      await view.input.fill("65535");
      await apply(page, (await review(view.panel, 513, 65535)).apply);
      await expect(
        view.panel.getByRole("heading", {
          name: "Verified native default transfer",
          exact: true,
        }),
      ).toBeVisible();
      const records = (
        await (await request.get(base + "/status")).json()
      ).receipts.filter((r: any) => r.change_kind === "enum-default");
      expect(records).toHaveLength(1);
      const parentId = records[0].id;
      const parent = await (
        await request.get(base + "/receipts/" + parentId)
      ).json();
      await capture(page, view.shared);
      const current = await openField(view.compiler, "65535");
      await current.input.fill("ordinary invalid draft");
      await receipt(current.panel, parentId);
      await current.panel
        .getByRole("button", {
          name: "Prepare previous Enum default",
          exact: true,
        })
        .click();
      await expect(prepared(page)).toContainText("65535 to 513");
      const first = await review(current.panel, 65535, 513);
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      await expect(first.plan).toHaveCount(0);
      const second = await review(current.panel, 65535, 513);
      await peer.command("enum-other9");
      await peer.command("enum-restore-513");
      if (variant === "routed-lost-ack") await peer.command("mode drop-end");
      const before = mutations((await peer.command("stats")).events);
      await apply(page, second.apply, () =>
        expectWorkspaceNavigationLocked(page),
      );
      const result = current.panel.getByRole("region", {
        name: "Native default transfer outcome",
        exact: true,
      });
      if (variant === "routed-lost-ack") {
        await expect(
          result.getByRole("heading", {
            name: "Native default transfer outcome uncertain",
            exact: true,
          }),
        ).toBeVisible();
        const changed = mutations((await peer.command("stats")).events);
        await peer.command("mode normal");
        const readback = page.waitForResponse(
          (r) =>
            r.url().endsWith(base + "/readback") &&
            r.request().method() === "POST",
        );
        await result
          .getByRole("button", {
            name: "Read back native default transfer",
            exact: true,
          })
          .click();
        await (await readback).finished();
        await expect(
          result.getByRole("heading", {
            name: "Verified native default transfer",
            exact: true,
          }),
        ).toBeVisible();
        expect(mutations((await peer.command("stats")).events)).toEqual(
          changed,
        );
      } else
        await expect(
          result.getByRole("heading", {
            name: "Verified native default transfer",
            exact: true,
          }),
        ).toBeVisible();
      const after = await peer.command("stats"),
        changes = mutations(after.events).slice(before.length);
      expect(
        changes.filter(
          (r: any) => r[0] === "state" && r[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        changes.filter((r: any) => r[0] === "state" && r[1] === "end-restore"),
      ).toHaveLength(1);
      expect(after.enum_effective_code).toBe(513);
      expect(after.router_errors).toEqual([]);
      const currentReceipts = (
        await (await request.get(base + "/status")).json()
      ).receipts.filter((r: any) => r.change_kind === "enum-default");
      expect(currentReceipts).toHaveLength(2);
      const id = currentReceipts.find((r: any) => r.id !== parentId).id;
      const child = await (await request.get(base + "/receipts/" + id)).json();
      expect(child.intent.recovery_origin.parent_receipt_id).toBe(parentId);
      expect(child.intent.recovery_origin.current_capture_id).toBe(
        await view.compiler
          .getByLabel("Retained native backup", { exact: true })
          .inputValue(),
      );
      const observed = child.latest_readback ?? child.result;
      const currentReal = JSON.parse(
        python(
          `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity
_,files=ApplicationStore(Store(sys.argv[1])).load(sys.argv[2]);image=MoiIdentity(files[3])
print(json.dumps(image.reader.scalar(image.root,900)))
`,
          nativeScheduleWriteServer.directory,
          observed.verification_capture_id,
        ),
      );
      expect(currentReal).toBe(9.25);
      expect(
        await (await request.get(base + "/receipts/" + parentId)).json(),
      ).toEqual(parent);
      await current.editor
        .getByRole("button", {
          name: "Discard previous Enum proposal",
          exact: true,
        })
        .click();
      await expect(current.input).toHaveValue("ordinary invalid draft");
    } finally {
      if (headers)
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
      peer.close();
    }
  });
}
