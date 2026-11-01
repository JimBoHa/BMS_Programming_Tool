import {
  test,
  expect,
  type Page,
  type Locator,
  type APIRequestContext,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { inspect } from "./native-boolean-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";
import { previousWireSourceMatches } from "../src/nativeWireRecoveryContract";

const root = path.resolve(".."),
  base = "/api/bacnet/controller/native-application",
  preparePath = base + "/wire-source/recovery/prepare",
  ref = "controller/575_1",
  prior = ref + ".2_10",
  after = ref + ".2_11";
const compiler = (page: Page) =>
  page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
const prepared = (page: Page) =>
  page.getByRole("region", {
    name: "Prepared previous wire source",
    exact: true,
  });
function seed(already = false, diagramClass = 575) {
  const state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state) throw new Error("An isolated test state is required.");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json
from pathlib import Path
from tests.test_native_wire_recovery import setup,current_source,FANOUT
from bms_tool.native_historical_wire_recovery import NativeHistoricalWireRecovery
from tests.test_native_wire_compiler import query
from bms_tool.moi_effective_wire import EffectiveWireCompiler
from bms_tool.native_wire_compiler import EffectiveWireService
from bms_tool.native_backup_records import NativeBackupRecords
s,ordinary,request,before,files=setup(Path(sys.argv[1]),wires=FANOUT[:2],diagram_class=int(sys.argv[3]));service=NativeHistoricalWireRecovery(ordinary.records)
if sys.argv[2]=='already':
 files[3]=EffectiveWireCompiler(s.load(before['id'])[1]).merged;request=current_source(s,request,files)
snap=s.load(request['capture_id'])[0];src=EffectiveWireService(NativeBackupRecords(s));source=src.source(query(src,snap))
source['device']=snap['device']
print(json.dumps({'request':request,'before':before['id'],'source':source,'receipt':s.receipt(request['receipt_id']),'report':service.prepare(request)}))
`,
        state,
        already ? "already" : "changed",
        String(diagramClass),
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
}
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  return headers;
}
async function field(page: Page) {
  const host = compiler(page);
  let records = host.getByLabel("Captured native record explorer", {
    exact: true,
  });
  if (!(await records.isVisible())) records = (await inspect(host, 9)).records;
  else if ((await records.getAttribute("open")) === null)
    await records.locator(":scope > summary").click();
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", { name: ref + " engineering", exact: true }),
    })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const editor = records.getByLabel(
    /^(Native archive wire source copy|Effective native wire compilation)$/,
  );
  if ((await editor.getAttribute("open")) === null)
    await editor.locator(":scope > summary").click();
  await editor
    .getByLabel("Native wire source basis", { exact: true })
    .selectOption("effective");
  await editor
    .getByRole("button", { name: "Open saved wire sources", exact: true })
    .click();
  await expect(
    editor.getByLabel("Replacement native source", { exact: true }),
  ).toBeVisible();
  return {
    host,
    records,
    editor,
    panel: editor.getByRole("region", {
      name: "Native wire source controller transfer",
      exact: true,
    }),
  };
}
async function receipt(panel: Locator, id: string) {
  const summary = panel
      .locator("summary")
      .filter({ hasText: /^Retained native wire transfers/ }),
    details = summary.locator("..");
  if ((await details.getAttribute("open")) === null) await summary.click();
  await panel
    .getByRole("button", {
      name: "Open receipt " + id.slice(0, 8),
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("region", {
      name: "Native wire transfer outcome",
      exact: true,
    }),
  ).toBeVisible();
}
async function offline(page: Page, data: ReturnType<typeof seed>) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  await compiler(page)
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.request.capture_id);
  const p = await field(page);
  await receipt(p.panel, data.request.receipt_id);
  return p;
}
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
  ).toContainText("Authored native wire controller");
  await openNativeCompiler(page);
  const shared = compiler(page).getByRole("region", {
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
  await shared
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  await expect(
    compiler(page).getByLabel("Native compiler snapshot source", {
      exact: true,
    }),
  ).toContainText("3 saved application parameters");
  return field(page);
}
async function confirm(panel: Locator, from: string, to: string) {
  await panel
    .getByRole("button", {
      name: "Review controller wire transfer",
      exact: true,
    })
    .click();
  const plan = panel.getByRole("region", {
    name: "Reviewed controller wire transfer",
    exact: true,
  });
  await expect(plan).toContainText(from + " → " + to);
  const apply = plan.getByRole("button", {
    name: "Apply native wire to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native connection and proposed wire source.",
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
  await expect(apply).toBeEnabled();
  return { plan, apply };
}
async function apply(page: Page, panel: Locator, button: Locator) {
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/wire-source/transfer/apply") &&
      r.request().method() === "POST",
  );
  await button.click();
  expect((await response).ok()).toBe(true);
  await expect(
    panel.getByRole("region", {
      name: "Native wire transfer outcome",
      exact: true,
    }),
  ).toContainText("Verified native wire transfer");
}
const mutations = (rows: any[]) =>
  rows.filter(
    (r) => r[0] === "write" || (r[0] === "state" && r[1].includes("restore")),
  );
for (const routed of [false, true]) {
  test(`original pin ${routed ? "routed" : "direct"} uses a new confirmed transfer and keeps other fresh settings`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000);
    await reset(request);
    const peer = await nativeDefaultPeer("consume", "wire");
    try {
      if (routed) await page.setViewportSize({ width: 820, height: 1100 });
      const originalIds = new Set(
        (await (await request.get(base + "/status")).json()).receipts.map(
          (r: any) => r.id,
        ),
      );
      let p = await connect(page, routed ? peer.router : peer.direct, routed);
      await p.editor
        .getByLabel("Replacement native source", { exact: true })
        .selectOption(after);
      await apply(page, p.panel, (await confirm(p.panel, prior, after)).apply);
      const parents = (
        await (await request.get(base + "/status")).json()
      ).receipts.filter(
        (r: any) => r.change_kind === "wire-source" && !originalIds.has(r.id),
      );
      expect(parents).toHaveLength(1);
      const parent = parents[0],
        original = await (
          await request.get(base + "/receipts/" + parent.id)
        ).json();
      const oldSource = await compiler(page)
        .getByLabel("Retained native backup", { exact: true })
        .inputValue();
      const captured = page.waitForResponse(
        (r) =>
          r.url().endsWith("/native-application/capture") &&
          r.request().method() === "POST",
      );
      await p.panel
        .getByRole("button", {
          name: "Read current native backup",
          exact: true,
        })
        .click();
      expect((await captured).ok()).toBe(true);
      await expect(
        compiler(page).getByLabel("Retained native backup", { exact: true }),
      ).not.toHaveValue(oldSource);
      p = await field(page);
      await receipt(p.panel, parent.id);
      // An ordinary unchanged-source draft must survive the active recovery overlay.
      await expect(
        p.editor.getByLabel("Replacement native source", { exact: true }),
      ).toHaveValue(after);
      const before = (await peer.command("stats")).events;
      let exact: Buffer | undefined;
      await page.route("**" + preparePath, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        exact = await response.body();
        await route.fulfill({ response });
      });
      await p.panel
        .getByRole("button", {
          name: "Prepare previous wire source",
          exact: true,
        })
        .click();
      await expect(prepared(page)).toContainText(
        "Previous wire source prepared locally",
      );
      await expect(prepared(page)).toContainText(
        "previous output pin comes from the verified original program",
      );
      await expect(prepared(page)).toBeFocused();
      await expect(prepared(page)).toBeInViewport();
      await expect(
        p.editor.getByLabel("Replacement native source", { exact: true }),
      ).toHaveValue(prior);
      await expect(
        p.editor.getByLabel("Replacement native source", { exact: true }),
      ).toBeDisabled();
      expect((await peer.command("stats")).events).toEqual(before);
      const download = page.waitForEvent("download");
      await prepared(page)
        .getByRole("button", {
          name: "Export exact previous wire proposal",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(exact);
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
      if (!(await p.editor.isVisible())) p = await field(page);
      await expect(prepared(page)).toBeVisible();
      await prepared(page)
        .getByRole("button", {
          name: "Discard wire recovery proposal",
          exact: true,
        })
        .click();
      await expect(
        p.editor.getByLabel("Replacement native source", { exact: true }),
      ).toHaveValue(after);
      await expect(
        p.editor.getByLabel("Replacement native source", { exact: true }),
      ).toBeEnabled();
      await receipt(p.panel, parent.id);
      await p.panel
        .getByRole("button", {
          name: "Prepare previous wire source",
          exact: true,
        })
        .click();
      await expect(prepared(page)).toContainText(
        "previous output pin comes from the verified original program",
      );
      await expect(prepared(page)).toBeFocused();
      await peer.command("wire-other-fresh");
      const start = (await peer.command("stats")).events.length;
      await apply(page, p.panel, (await confirm(p.panel, after, prior)).apply);
      const children = (
        await (await request.get(base + "/status")).json()
      ).receipts.filter(
        (r: any) =>
          r.change_kind === "wire-source" &&
          r.id !== parent.id &&
          !originalIds.has(r.id),
      );
      expect(children).toHaveLength(1);
      const result = await (
        await request.get(base + "/receipts/" + children[0].id)
      ).json();
      expect(result.intent.recovery_origin.parent_receipt_id).toBe(parent.id);
      expect(result.intent.recovery_origin_sha256).toBe(
        JSON.parse(exact!.toString()).origin_sha256,
      );
      expect(result.result.preservation.selected_wire.source_ref).toBe(prior);
      expect(
        result.result.preservation.selected_wire.effective_connection_verified,
      ).toBe(true);
      expect(
        await (await request.get(base + "/receipts/" + parent.id)).json(),
      ).toEqual(original);
      const changes = mutations(
        (await peer.command("stats")).events.slice(start),
      );
      expect(
        changes.filter((r) => r[0] === "state" && r[1] === "start-restore"),
      ).toHaveLength(1);
      expect(
        changes.filter((r) => r[0] === "state" && r[1] === "end-restore"),
      ).toHaveLength(1);
      expect(
        changes.filter((r) => r[0] === "write").every((r) => r[1] === 3),
      ).toBe(true);
      await chooseWorkspaceTask(page, "Changes");
      const ledger = page.getByRole("region", {
        name: "Change ledger",
        exact: true,
      });
      await ledger
        .getByRole("button", {
          name: "Details for native " + children[0].id,
          exact: true,
        })
        .click();
      const lineage = ledger.getByRole("region", {
        name: "Recorded native recovery lineage",
        exact: true,
      });
      await expect(lineage).toContainText("Recorded wire change");
      await expect(lineage).toContainText("Connection 1:");
      await expect(lineage).toContainText(parent.id);
      await expect(lineage).toContainText("Retained original output pin");
      await expect(lineage).toContainText("port 85");
      await lineage.scrollIntoViewIfNeeded();
      await expect(lineage).toBeInViewport();
      await page.screenshot({
        path: info.outputPath("wire-recovery-ledger.png"),
        fullPage: true,
      });
      expect((await peer.command("stats")).router_errors).toEqual([]);
    } finally {
      peer.close();
    }
  });
}
for (const width of [1440, 390]) {
  test(`offline original pin recovery ${width} retains its ordinary draft and exact local evidence`, async ({
    page,
    request,
  }, info) => {
    await reset(request);
    const data = seed(false, width === 390 ? 536 : 575);
    await page.setViewportSize({ width, height: 1000 });
    const p = await offline(page, data);
    await expect(
      p.panel.getByRole("button", {
        name: "Review controller wire transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    const before = await (await request.get(base + "/status")).json();
    await p.panel
      .getByRole("button", {
        name: "Prepare previous wire source",
        exact: true,
      })
      .click();
    await expect(prepared(page)).toBeFocused();
    await expect(prepared(page)).toBeInViewport();
    await expect(
      p.editor.getByLabel("Replacement native source", { exact: true }),
    ).toHaveValue(prior);
    await expect(prepared(page)).toContainText(
      "ordinary wire draft remains retained separately",
    );
    const download = page.waitForEvent("download");
    await prepared(page)
      .getByRole("button", {
        name: "Export exact previous wire proposal",
        exact: true,
      })
      .click();
    expect(
      JSON.parse(readFileSync((await (await download).path())!, "utf8")),
    ).toEqual(data.report);
    let copyRaw: Buffer | undefined;
    await page.route(
      "**/inspection/historical-wire-source/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        copyRaw = await response.body();
        await route.fulfill({ response });
      },
    );
    await p.editor
      .getByRole("button", {
        name: "Review effective wire compilation",
        exact: true,
      })
      .click();
    const reviewed = p.editor.getByRole("region", {
      name: "Reviewed effective native wire compilation",
      exact: true,
    });
    await expect(reviewed).toBeVisible();
    const copy = JSON.parse(copyRaw!.toString());
    expect(copy.recovery_origin_sha256).toBe(data.report.origin_sha256);
    expect(copy.compilation.historical_pin_evidence_sha256).toBe(
      data.report.origin.historical_pin_sha256,
    );
    const compiling = page.waitForEvent("download");
    await reviewed
      .getByRole("button", { name: "Save compiled native wire", exact: true })
      .click();
    const artifact = (await (await compiling).path())!;
    expect(
      createHash("sha256").update(readFileSync(artifact)).digest("hex"),
    ).toBe(copy.output_sha256);
    const independent = JSON.parse(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          `
import sys,json
from pathlib import Path
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
from bms_tool.moi_effective_wire import EffectiveWireCompiler
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_wire_sources import MoiWireSources
s=ApplicationStore(Store(sys.argv[2]));_,files=s.load(sys.argv[3]);before=EffectiveWireCompiler(files).effective.editor.data
wire=MoiWireSources(before).graph('controller/575_1')[3][0];offset,width=wire['source_index_offset'],wire['source_index_bytes'];actual=MoiIdentity(Path(sys.argv[1]).read_bytes())
assert actual.data==before[:offset]+bytes(width)+before[offset+width:]
assert actual.reader.diagram('controller/575_1')['connections'][0]['source_ref']=='controller/575_1.2_10'
print(json.dumps({'other_bytes_preserved':True,'source_restored':True}))
`,
          artifact,
          process.env.BMS_TEST_COMPILER_STATE!,
          data.request.capture_id,
        ],
        {
          cwd: root,
          env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
          encoding: "utf8",
        },
      ),
    );
    expect(independent).toEqual({
      other_bytes_preserved: true,
      source_restored: true,
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(
      (await (await request.get(base + "/status")).json()).receipts,
    ).toEqual(before.receipts);
    await page.screenshot({
      path: info.outputPath("wire-recovery-offline.png"),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await prepared(page)
      .getByRole("button", {
        name: "Discard wire recovery proposal",
        exact: true,
      })
      .click();
    await expect(
      p.editor.getByLabel("Replacement native source", { exact: true }),
    ).toHaveValue(after);
    await expect(
      p.editor.getByLabel("Replacement native source", { exact: true }),
    ).toBeEnabled();
  });
}
test("a wire receipt requires its original diagram and connection", async ({
  page,
  request,
}) => {
  await reset(request);
  const data = seed(),
    p = await offline(page, data);
  await p.editor
    .getByLabel("Existing native connection", { exact: true })
    .selectOption("1");
  await receipt(p.panel, data.request.receipt_id);
  await expect(
    p.panel.getByRole("button", {
      name: "Prepare previous wire source",
      exact: true,
    }),
  ).toBeDisabled();
  await p.editor
    .getByLabel("Existing native connection", { exact: true })
    .selectOption("0");
  await receipt(p.panel, data.request.receipt_id);
  await expect(
    p.panel.getByRole("button", {
      name: "Prepare previous wire source",
      exact: true,
    }),
  ).toBeEnabled();
});
test("already recorded exact previous wire image creates no transfer or live claim", async ({
  page,
  request,
}) => {
  await reset(request);
  const p = await offline(page, seed(true));
  await p.panel
    .getByRole("button", { name: "Prepare previous wire source", exact: true })
    .click();
  await expect(prepared(page)).toContainText(
    "Previous wire source already recorded",
  );
  await expect(prepared(page)).toContainText(
    "does not establish current live state",
  );
  await expect(
    p.editor.getByLabel("Replacement native source", { exact: true }),
  ).toBeEnabled();
  await expect(
    p.panel.getByRole("button", {
      name: "Review controller wire transfer",
      exact: true,
    }),
  ).toHaveCount(0);
});
for (const change of ["task-aba", "connection-aba"]) {
  test(`late original pin response retires on ${change}`, async ({
    page,
    request,
  }) => {
    await reset(request);
    const data = seed();
    let p = await offline(page, data);
    let release = () => {},
      started!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      received = new Promise<void>((r) => (started = r));
    try {
      await page.route("**" + preparePath, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      });
      const response = page.waitForResponse(
        (r) => r.url().endsWith(preparePath) && r.request().method() === "POST",
      );
      await p.panel
        .getByRole("button", {
          name: "Prepare previous wire source",
          exact: true,
        })
        .click();
      await received;
      if (change === "task-aba") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
        if (!(await p.editor.isVisible())) p = await field(page);
      } else {
        await p.editor
          .getByLabel("Existing native connection", { exact: true })
          .selectOption("1");
        await p.editor
          .getByLabel("Existing native connection", { exact: true })
          .selectOption("0");
      }
      release();
      await (await response).finished();
      await receipt(p.panel, data.request.receipt_id);
      await expect(
        p.panel.getByRole("button", {
          name: "Prepare previous wire source",
          exact: true,
        }),
      ).toBeEnabled();
      await expect(prepared(page)).toHaveCount(0);
      await expect(
        p.editor.getByLabel("Replacement native source", { exact: true }),
      ).toHaveValue(after);
    } finally {
      release();
    }
  });
}
test("original pin recovery report binds original/current images, source identity and pin tuple", () => {
  const data = seed(),
    selection = { diagram_ref: ref, wire_index: 0, class_id: 575 };
  expect(
    previousWireSourceMatches(
      data.report,
      data.source,
      data.receipt,
      selection,
    ),
  ).toBe(true);
  for (const change of [
    "index",
    "class",
    "alias",
    "source",
    "target",
    "proof",
    "hash",
    "capability",
    "pin-port",
    "pin-image",
    "pin-object",
  ]) {
    const d = structuredClone(data.report);
    if (change === "index") d.origin.wire_index = 1;
    else if (change === "class") d.origin.class_id = 536;
    else if (change === "alias") d.origin.previous_tuple[0] = false;
    else if (change === "source") d.proposal.source_ref = after;
    else if (change === "target") d.origin.target_ref = "unrelated";
    else if (change === "proof")
      d.origin.verified_proof.sha256 = "0".repeat(64);
    else if (change === "hash") d.proposal.property_sha256 = "0".repeat(64);
    else if (change === "pin-port") d.origin.historical_pin.old[1] = 86;
    else if (change === "pin-image")
      d.origin.historical_pin.after_native_sha256 = "0".repeat(64);
    else if (change === "pin-object")
      d.proposal_candidate.object = "analog-value,11";
    else d.can_apply = true;
    expect(
      previousWireSourceMatches(d, data.source, data.receipt, selection),
      change,
    ).toBe(false);
  }
});
