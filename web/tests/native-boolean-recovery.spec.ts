import {
  test,
  expect,
  type Page,
  type Locator,
  type APIRequestContext,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { inspect } from "./native-boolean-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";
import { previousBooleanDefaultMatches } from "../src/nativeBooleanRecoveryContract";

const root = path.resolve("..");
const base = "/api/bacnet/controller/native-application";
const preparePath = base + "/boolean-default/recovery/prepare";
function seed(already = false, ref = "controller/boolean-20") {
  const state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state) throw new Error("An isolated state directory is required.");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json
from pathlib import Path
from tests.test_native_boolean_recovery import setup,current_source
from tests.test_native_boolean_transfer import boolean_slot
from tests.test_native_boolean_copies import FIRST
from bms_tool.native_boolean_compiler import EffectiveBooleanService
from bms_tool.native_backup_records import NativeBackupRecords
s,service,request,before,files=setup(Path(sys.argv[1]),ref=sys.argv[3])
if sys.argv[2]=='already':
 boolean_slot(files,sys.argv[3],service.prepare(request)['previous_effective_value']);request=current_source(s,request,files)
src=EffectiveBooleanService(NativeBackupRecords(s)).source({k:request[k] for k in ('capture_id','snapshot_sha256')})
print(json.dumps({'request':request,'before':before['id'],'source':src,'receipt':s.receipt(request['receipt_id']),'report':service.prepare(request)}))
`,
        state,
        already ? "already" : "changed",
        ref,
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
const compiler = (page: Page) =>
  page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
const prepared = (page: Page) =>
  page.getByRole("region", {
    name: "Prepared previous Boolean default",
    exact: true,
  });
async function field(page: Page, ref = "controller/boolean-20") {
  const host = compiler(page);
  let records = host.getByLabel("Captured native record explorer", {
    exact: true,
  });
  if (!(await records.isVisible())) records = (await inspect(host)).records;
  else if ((await records.getAttribute("open")) === null)
    await records.locator(":scope > summary").click();
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({ hasText: ref })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("effective");
  const open = records.getByRole("button", {
    name: "Open saved Boolean defaults",
    exact: true,
  });
  if (await open.isVisible()) await open.click();
  const editor = records.getByLabel("Effective Boolean default compilation", {
    exact: true,
  });
  await expect(editor).toBeVisible();
  const panel = editor.getByRole("region", {
    name: "Native Boolean default controller transfer",
    exact: true,
  });
  return { host, records, editor, panel };
}
async function receipt(panel: Locator, id: string) {
  const summary = panel
    .locator("summary")
    .filter({ hasText: /^Retained native default transfers/ });
  const details = summary.locator("..");
  if ((await details.getAttribute("open")) === null) await summary.click();
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
async function offline(
  page: Page,
  data: ReturnType<typeof seed>,
  ref = "controller/boolean-20",
) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  await compiler(page)
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.request.capture_id);
  const p = await field(page, ref);
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
  ).toContainText("Authored controller");
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
  ).toContainText("11 saved application parameters");
  return field(page);
}
async function confirm(panel: Locator, before: boolean, after: boolean) {
  await panel
    .getByRole("button", {
      name: "Review controller default transfer",
      exact: true,
    })
    .click();
  const review = panel.getByRole("region", {
    name: "Reviewed controller default transfer",
    exact: true,
  });
  await expect(review).toContainText(
    `${before} → ${after} · stored value ${after}`,
  );
  const apply = review.getByRole("button", {
    name: "Apply native default to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await review
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native default and proposed value.",
      exact: true,
    })
    .check();
  await expect(apply).toBeDisabled();
  await review
    .getByRole("checkbox", {
      name: "I confirm the application transfer and controller interruption.",
      exact: true,
    })
    .check();
  await expect(apply).toBeEnabled();
  return { review, apply };
}
async function apply(page: Page, panel: Locator, button: Locator) {
  const response = page.waitForResponse((r) =>
    r.url().endsWith("/boolean-default/transfer/apply"),
  );
  await button.click();
  expect((await response).ok()).toBe(true);
  await expect(
    panel.getByRole("heading", {
      name: "Verified native default transfer",
      exact: true,
    }),
  ).toBeVisible();
}

for (const routed of [false, true]) {
  test(`previous Boolean ${routed ? "routed compact" : "direct"} uses a new verified transfer and recorded lineage`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000);
    const headers = await reset(request),
      peer = await nativeDefaultPeer("consume", "boolean");
    const originalIds = new Set(
      (await (await request.get(base + "/status")).json()).receipts.map(
        (r: any) => r.id,
      ),
    );
    try {
      if (routed) await page.setViewportSize({ width: 820, height: 1100 });
      let p = await connect(page, routed ? peer.router : peer.direct, routed);
      await p.editor
        .getByLabel("Proposed effective Boolean default", { exact: true })
        .uncheck();
      await apply(page, p.panel, (await confirm(p.panel, true, false)).apply);
      const parents = (
        await (await request.get(base + "/status")).json()
      ).receipts.filter(
        (r: any) =>
          r.change_kind === "boolean-default" && !originalIds.has(r.id),
      );
      expect(parents).toHaveLength(1);
      const parent = parents[0];
      const original = await (
        await request.get(base + "/receipts/" + parent.id)
      ).json();
      const oldCapture = await compiler(page)
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
      ).not.toHaveValue(oldCapture);
      p = await field(page);
      await receipt(p.panel, parent.id);
      await p.editor
        .getByLabel("Proposed effective Boolean default", { exact: true })
        .check();
      const before = (await peer.command("stats")).events;
      let exact: Buffer | undefined;
      await page.route("**" + preparePath, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        exact = await response.body();
        await route.fulfill({ response });
      });
      await p.panel
        .getByRole("button", {
          name: "Prepare previous Boolean default",
          exact: true,
        })
        .click();
      await expect(prepared(page)).toContainText(
        "Previous effective Boolean value prepared locally",
      );
      await expect(prepared(page)).toBeFocused();
      await expect(prepared(page)).toBeInViewport();
      await expect(
        p.editor.getByLabel("Proposed effective Boolean default", {
          exact: true,
        }),
      ).toBeChecked();
      await expect(
        p.editor.getByLabel("Proposed effective Boolean default", {
          exact: true,
        }),
      ).toBeDisabled();
      expect((await peer.command("stats")).events).toEqual(before);
      const download = page.waitForEvent("download");
      await prepared(page)
        .getByRole("button", {
          name: "Export exact previous Boolean proposal",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(exact);
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
      if (!(await p.editor.isVisible())) p = await field(page);
      await expect(prepared(page)).toBeVisible();
      await p.editor
        .getByRole("button", {
          name: "Discard previous Boolean proposal",
          exact: true,
        })
        .click();
      await expect(
        p.editor.getByLabel("Proposed effective Boolean default", {
          exact: true,
        }),
      ).toBeChecked();
      await expect(
        p.editor.getByLabel("Proposed effective Boolean default", {
          exact: true,
        }),
      ).toBeEnabled();
      await receipt(p.panel, parent.id);
      await p.panel
        .getByRole("button", {
          name: "Prepare previous Boolean default",
          exact: true,
        })
        .click();
      await expect(prepared(page)).toBeFocused();
      await peer.command("boolean-restore-true");
      await peer.command("boolean-second-true");
      const start = (await peer.command("stats")).events.length;
      await apply(page, p.panel, (await confirm(p.panel, false, true)).apply);
      const rows = (await (await request.get(base + "/status")).json())
        .receipts;
      const children = rows.filter(
        (r: any) =>
          !originalIds.has(r.id) &&
          r.id !== parent.id &&
          r.change_kind === "boolean-default",
      );
      expect(children).toHaveLength(1);
      const child = children[0];
      const result = await (
        await request.get(base + "/receipts/" + child.id)
      ).json();
      expect(result.intent.recovery_origin.parent_receipt_id).toBe(parent.id);
      expect(result.intent.recovery_origin_sha256).toBe(
        JSON.parse(exact!.toString()).origin_sha256,
      );
      expect(result.result.preservation.selected_default.effective_value).toBe(
        true,
      );
      expect(
        await (await request.get(base + "/receipts/" + parent.id)).json(),
      ).toEqual(original);
      const stats = await peer.command("stats"),
        changes = stats.events
          .slice(start)
          .filter(
            (r: any[]) =>
              r[0] === "write" ||
              (r[0] === "state" && r[1].includes("restore")),
          );
      expect(
        changes.filter(
          (r: any[]) => r[0] === "state" && r[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        changes.filter(
          (r: any[]) => r[0] === "state" && r[1] === "end-restore",
        ),
      ).toHaveLength(1);
      expect(stats.router_errors).toEqual([]);
      await chooseWorkspaceTask(page, "Changes");
      const ledger = page.getByRole("region", {
        name: "Change ledger",
        exact: true,
      });
      const detailButton = ledger.getByRole("button", {
        name: "Details for native " + child.id,
        exact: true,
      });
      expect(
        await detailButton.evaluate((button) => {
          const text = document.createRange();
          text.selectNodeContents(button);
          return text.getClientRects().length;
        }),
      ).toBe(1);
      await ledger
        .getByRole("button", {
          name: "Details for native " + child.id,
          exact: true,
        })
        .click();
      const origin = ledger.getByRole("region", {
        name: "Recorded native recovery lineage",
        exact: true,
      });
      await expect(origin).toContainText("Recorded Boolean change");
      await expect(origin).toContainText("false to true · tags 10 to 11");
      await expect(origin).toContainText(parent.id);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("boolean-recovery-verified.png"),
        fullPage: true,
      });
    } finally {
      await request
        .post("/api/bacnet/disconnect", { headers, data: {} })
        .catch(() => {});
      await peer.close();
    }
  });
}

for (const width of [1440, 390]) {
  test(`offline Boolean recovery retains ordinary draft and exact evidence at ${width}px`, async ({
    page,
    request,
  }, info) => {
    await reset(request);
    const data = seed();
    await page.setViewportSize({ width, height: 1100 });
    let p = await offline(page, data);
    await p.editor
      .getByLabel("Proposed effective Boolean default", { exact: true })
      .check();
    await p.panel
      .getByRole("button", {
        name: "Prepare previous Boolean default",
        exact: true,
      })
      .click();
    await expect(prepared(page)).toBeFocused();
    await expect(prepared(page)).toBeInViewport();
    await expect(
      p.editor.getByLabel("Proposed effective Boolean default", {
        exact: true,
      }),
    ).toBeChecked();
    await expect(
      p.editor.getByLabel("Proposed effective Boolean default", {
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      p.panel.getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    const download = page.waitForEvent("download");
    await prepared(page)
      .getByRole("button", {
        name: "Export exact previous Boolean proposal",
        exact: true,
      })
      .click();
    expect(
      JSON.parse(readFileSync((await (await download).path())!, "utf8")),
    ).toEqual(data.report);
    await chooseWorkspaceTask(page, "Overview");
    await openNativeCompiler(page);
    if (!(await p.editor.isVisible())) p = await field(page);
    await expect(prepared(page)).toBeVisible();
    await page.screenshot({
      path: info.outputPath("boolean-recovery-offline.png"),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await p.editor
      .getByRole("button", {
        name: "Discard previous Boolean proposal",
        exact: true,
      })
      .click();
    await expect(prepared(page)).toHaveCount(0);
    await expect(
      p.editor.getByLabel("Proposed effective Boolean default", {
        exact: true,
      }),
    ).toBeChecked();
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
}

test("Boolean preparation requires the original selected field", async ({
  page,
  request,
}) => {
  await reset(request);
  const data = seed(),
    p = await offline(page, data, "controller/boolean-21");
  await expect(
    p.panel.getByRole("button", {
      name: "Prepare previous Boolean default",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(p.panel).toContainText(
    "Open its recorded Boolean field controller/boolean-20",
  );
  await expect(prepared(page)).toHaveCount(0);
});

test("already recorded Boolean value creates no transfer or live-state claim", async ({
  page,
  request,
}) => {
  await reset(request);
  const data = seed(true),
    p = await offline(page, data);
  await p.editor
    .getByLabel("Proposed effective Boolean default", { exact: true })
    .uncheck();
  await p.panel
    .getByRole("button", {
      name: "Prepare previous Boolean default",
      exact: true,
    })
    .click();
  await expect(prepared(page)).toContainText(
    "Previous Boolean value already recorded in this backup",
  );
  await expect(prepared(page)).toContainText(
    "does not establish current live state",
  );
  await expect(
    p.editor.getByLabel("Proposed effective Boolean default", { exact: true }),
  ).not.toBeChecked();
  await expect(
    p.editor.getByLabel("Proposed effective Boolean default", { exact: true }),
  ).toBeEnabled();
});

for (const change of ["task-aba", "draft-aba"]) {
  test(`late Boolean proposal retires after ${change}`, async ({
    page,
    request,
  }) => {
    await reset(request);
    const data = seed();
    let p = await offline(page, data);
    let release!: () => void, entered!: () => void;
    const gate = new Promise<void>((r) => {
        release = r;
      }),
      seen = new Promise<void>((r) => {
        entered = r;
      });
    await page.route("**" + preparePath, async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      expect(response.ok()).toBe(true);
      entered();
      await gate;
      await route.fulfill({ response });
    });
    try {
      await p.panel
        .getByRole("button", {
          name: "Prepare previous Boolean default",
          exact: true,
        })
        .click();
      await seen;
      if (change === "task-aba") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
      } else {
        const checkbox = p.editor.getByLabel(
          "Proposed effective Boolean default",
          { exact: true },
        );
        await checkbox.check();
        await checkbox.uncheck();
      }
      const finished = page.waitForResponse((r) =>
        r.url().endsWith(preparePath),
      );
      release();
      await (await finished).finished();
      await expect(prepared(page)).toHaveCount(0);
    } finally {
      release();
    }
  });
}

test("Boolean report contract rejects numeric aliases and mismatched tags/proof", () => {
  const data = seed(),
    selected = data.source.fields.find(
      (r: any) => r.ref === "controller/boolean-20",
    );
  expect(
    previousBooleanDefaultMatches(
      data.report,
      data.source,
      data.receipt,
      selected,
    ),
  ).toBe(true);
  for (const mutate of [
    (r: any) => {
      r.proposal.value = 1;
    },
    (r: any) => {
      r.origin.current_effective_value = 0;
    },
    (r: any) => {
      r.origin.previous_tag = "10";
    },
    (r: any) => {
      r.origin.class_id = 526;
    },
    (r: any) => {
      r.origin.verified_proof.sha256 = "0".repeat(64);
    },
  ]) {
    const copy = structuredClone(data.report);
    mutate(copy);
    expect(
      previousBooleanDefaultMatches(copy, data.source, data.receipt, selected),
    ).toBeFalsy();
  }
});

test("a false Boolean proposal remains active and preserves an ordinary false draft", async ({
  page,
  request,
}) => {
  await reset(request);
  const ref = "controller/boolean-21",
    data = seed(false, ref),
    p = await offline(page, data, ref);
  const checkbox = p.editor.getByLabel("Proposed effective Boolean default", {
    exact: true,
  });
  await checkbox.uncheck();
  await p.panel
    .getByRole("button", {
      name: "Prepare previous Boolean default",
      exact: true,
    })
    .click();
  await expect(prepared(page)).toBeFocused();
  await expect(prepared(page)).toContainText(
    "controller/boolean-21 · true to false",
  );
  await expect(checkbox).not.toBeChecked();
  await expect(checkbox).toBeDisabled();
  const download = page.waitForEvent("download");
  await prepared(page)
    .getByRole("button", {
      name: "Export exact previous Boolean proposal",
      exact: true,
    })
    .click();
  const report = JSON.parse(
    readFileSync((await (await download).path())!, "utf8"),
  );
  expect(report.proposal.value).toBe(false);
  expect(report.origin.previous_tag).toBe("10");
  await p.editor
    .getByRole("button", {
      name: "Discard previous Boolean proposal",
      exact: true,
    })
    .click();
  await expect(prepared(page)).toHaveCount(0);
  await expect(checkbox).not.toBeChecked();
  await expect(checkbox).toBeEnabled();
});
