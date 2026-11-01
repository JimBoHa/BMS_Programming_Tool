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
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";
import { previousRealDefaultMatches } from "../src/nativeDefaultRecoveryContract";

const base = "/api/bacnet/controller/native-application";
const preparePath = base + "/signal-default/recovery/prepare";
const root = path.resolve("..");
function seed(already = false) {
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
from tests.test_native_default_recovery import setup,current_source,set_saved
from bms_tool.native_signal_compiler import SignalCompilerService
s,service,request,before,files=setup(Path(sys.argv[1]))
if sys.argv[2]=='already':request=current_source(s,request,set_saved(files,42))
print(json.dumps({'request':request,'before':before['id'],'report':service.prepare(request),'source':SignalCompilerService(s).source(request['capture_id']),'receipt':s.receipt(request['receipt_id'])}))
`,
        state,
        already ? "already" : "changed",
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
function panels(page: Page) {
  return {
    compiler: page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    }),
    panel: page.getByRole("region", {
      name: "Native default controller transfer",
      exact: true,
    }),
    prepared: page.getByRole("region", {
      name: "Prepared previous Real default",
      exact: true,
    }),
  };
}
async function offline(page: Page, data: ReturnType<typeof seed>) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  const p = panels(page);
  await p.compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.request.capture_id);
  await p.compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await p.compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  await p.panel
    .locator("summary")
    .filter({ hasText: /^Retained native default transfers/ })
    .click();
  await p.panel
    .getByRole("button", {
      name: "Open receipt " + data.request.receipt_id.slice(0, 8),
      exact: true,
    })
    .click();
  await expect(
    p.panel.getByRole("region", {
      name: "Native default transfer outcome",
      exact: true,
    }),
  ).toBeVisible();
  return p;
}
async function confirm(panel: Locator, before: string, after: string) {
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
  await expect(review).toContainText(before + " → " + after);
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
  const p = panels(page);
  await p.panel
    .getByText("Native backup and restore credentials", { exact: true })
    .click();
  await p.panel
    .getByLabel("Native backup credential", { exact: true })
    .fill("authored-backup");
  await p.panel
    .getByLabel("Native restore credential", { exact: true })
    .fill("authored-restore");
  await p.panel
    .getByRole("button", {
      name: "Save native transfer credentials",
      exact: true,
    })
    .click();
  await expect(
    p.panel.getByLabel("Native backup credential", { exact: true }),
  ).toHaveValue("");
  await p.panel
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  await expect(
    p.compiler.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toContainText("9 saved application parameters");
  await p.compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  await p.compiler
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("0.1");
  return p;
}

for (const routed of [false, true]) {
  test(`previous Real default ${routed ? "routed compact" : "direct"} requires a new reviewed transfer`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000);
    const headers = await reset(request),
      peer = await nativeDefaultPeer();
    try {
      if (routed) await page.setViewportSize({ width: 820, height: 1100 });
      const p = await connect(page, routed ? peer.router : peer.direct, routed);
      const firstReview = await confirm(p.panel, "42280000", "3dcccccd");
      const firstApply = page.waitForResponse((response) =>
        response.url().endsWith("/signal-default/transfer/apply"),
      );
      await firstReview.apply.click();
      expect((await firstApply).ok()).toBe(true);
      await expect(
        p.panel.getByRole("heading", {
          name: "Verified native default transfer",
          exact: true,
        }),
      ).toBeVisible();
      const parent = (await (await request.get(base + "/status")).json())
        .receipts[0];
      const original = await (
        await request.get(base + "/receipts/" + parent.id)
      ).json();
      await p.panel
        .getByRole("button", {
          name: "Read current native backup",
          exact: true,
        })
        .click();
      await expect(
        p.compiler.getByLabel("Native Real default", { exact: true }),
      ).toHaveValue("");
      await p.compiler
        .getByLabel("Native Real default", { exact: true })
        .selectOption("controller/signal-11");
      await p.compiler
        .getByLabel("Proposed native Real default", { exact: true })
        .fill("77.");
      const before = (await peer.command("stats")).events;
      let exact: Buffer | undefined;
      await page.route("**" + preparePath, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        exact = await response.body();
        await route.fulfill({ response });
      });
      await p.panel
        .getByRole("button", {
          name: "Prepare previous Real default",
          exact: true,
        })
        .click();
      await expect(p.prepared).toContainText(
        "Previous effective value prepared locally",
      );
      await expect(p.prepared).toBeFocused();
      await expect(p.prepared).toBeInViewport();
      await expect(
        p.compiler.getByLabel("Native Real default", { exact: true }),
      ).toHaveValue("controller/signal-10");
      await expect(
        p.compiler.getByLabel("Proposed native Real default", { exact: true }),
      ).toHaveValue("42.0");
      await expect(
        p.compiler.getByLabel("Proposed native Real default", { exact: true }),
      ).toHaveAttribute("readonly", "");
      expect((await peer.command("stats")).events).toEqual(before);
      const download = page.waitForEvent("download");
      await p.prepared
        .getByRole("button", {
          name: "Export exact previous-value proposal",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(exact);
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
      await expect(p.prepared).toBeVisible();
      await p.compiler
        .getByLabel("Native Real default", { exact: true })
        .selectOption("controller/signal-11");
      await expect(
        p.compiler.getByLabel("Proposed native Real default", { exact: true }),
      ).toHaveValue("77.");
      await p.compiler
        .getByLabel("Native Real default", { exact: true })
        .selectOption("controller/signal-10");
      await peer.command("restore42");
      await peer.command("second17");
      const start = (await peer.command("stats")).events.length;
      const reviewed = await confirm(p.panel, "3dcccccd", "42280000");
      const secondApply = page.waitForResponse((response) =>
        response.url().endsWith("/signal-default/transfer/apply"),
      );
      await reviewed.apply.click();
      expect((await secondApply).ok()).toBe(true);
      await expect(
        p.panel.getByRole("heading", {
          name: "Verified native default transfer",
          exact: true,
        }),
      ).toBeVisible();
      const receipts = (await (await request.get(base + "/status")).json())
        .receipts;
      const child = receipts.find((row: any) => row.id !== parent.id);
      const result = await (
        await request.get(base + "/receipts/" + child.id)
      ).json();
      expect(result.intent.recovery_origin.parent_receipt_id).toBe(parent.id);
      expect(result.intent.recovery_origin_sha256).toBe(
        JSON.parse(exact!.toString()).origin_sha256,
      );
      expect(result.result.preservation.selected_default.effective_bits).toBe(
        "42280000",
      );
      expect(
        await (await request.get(base + "/receipts/" + parent.id)).json(),
      ).toEqual(original);
      const sourceResponse = await request.post(
        base + "/signal-default/source",
        {
          headers,
          data: { capture_id: result.result.verification_capture_id },
        },
      );
      expect(sourceResponse.ok()).toBe(true);
      const source = await sourceResponse.json();
      expect(
        source.fields.find((row: any) => row.ref === "controller/signal-11")
          .effective_value,
      ).toBe(17.5);
      const stats = await peer.command("stats"),
        mutations = stats.events
          .slice(start)
          .filter(
            (row: any[]) =>
              row[0] === "write" ||
              (row[0] === "state" && row[1].includes("restore")),
          );
      expect(
        mutations.filter(
          (row: any[]) => row[0] === "state" && row[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        mutations.filter(
          (row: any[]) => row[0] === "state" && row[1] === "end-restore",
        ),
      ).toHaveLength(1);
      expect(stats.router_errors).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("previous-real-default-verified.png"),
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

for (const width of [1440, 820, 390]) {
  test(`offline previous-value proposal preserves ordinary drafts and exact evidence at ${width}px`, async ({
    page,
    request,
  }, info) => {
    await reset(request);
    const data = seed();
    await page.setViewportSize({ width, height: 1000 });
    const p = await offline(page, data);
    await p.compiler
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("18.");
    await p.panel
      .getByRole("button", {
        name: "Prepare previous Real default",
        exact: true,
      })
      .click();
    await expect(p.prepared).toContainText(
      "Previous effective value prepared locally",
    );
    await expect(p.prepared).toBeFocused();
    await expect(p.prepared).toBeInViewport();
    await expect(
      p.compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("42.0");
    await expect(
      p.panel.getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await chooseWorkspaceTask(page, "Changes");
    await openNativeCompiler(page);
    await expect(p.prepared).toBeVisible();
    await expect(
      p.compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("42.0");
    const download = page.waitForEvent("download");
    await p.prepared
      .getByRole("button", {
        name: "Export exact previous-value proposal",
        exact: true,
      })
      .click();
    const exported = JSON.parse(
      readFileSync((await (await download).path())!, "utf8"),
    );
    expect(
      previousRealDefaultMatches(exported, data.source, data.receipt),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("previous-real-default-offline.png"),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await p.compiler
      .getByRole("button", {
        name: "Discard previous-value proposal",
        exact: true,
      })
      .click();
    await expect(p.prepared).toHaveCount(0);
    await expect(
      p.compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("18.");
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
}

for (const change of ["source-aba", "task-aba"]) {
  test(`late previous-value response retires after ${change}`, async ({
    page,
    request,
  }) => {
    await reset(request);
    const data = seed(),
      p = await offline(page, data);
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const entered = new Promise<void>((resolve) => {
      seen = resolve;
    });
    await page.route("**" + preparePath, async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      expect(response.ok()).toBe(true);
      seen();
      await gate;
      await route.fulfill({ response });
    });
    try {
      await p.panel
        .getByRole("button", {
          name: "Prepare previous Real default",
          exact: true,
        })
        .click();
      await entered;
      if (change === "source-aba") {
        await p.compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(data.before);
        await p.compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(data.request.capture_id);
      } else if (change === "task-aba") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
      }
      const finished = page.waitForResponse((response) =>
        response.url().endsWith(preparePath),
      );
      release();
      await (await finished).finished();
      await expect(p.prepared).toHaveCount(0);
      await expect(
        p.compiler.getByLabel("Proposed native Real default", { exact: true }),
      ).not.toHaveValue("42.0");
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    } finally {
      release();
    }
  });
}

test("recovery document contract rejects altered source, lineage, values, outcome and effects", () => {
  const data = seed();
  expect(
    previousRealDefaultMatches(data.report, data.source, data.receipt),
  ).toBe(true);
  for (const mutate of [
    (r: any) => {
      r.source.capture_id = "0".repeat(32);
    },
    (r: any) => {
      r.origin.parent_receipt_id = "0".repeat(32);
    },
    (r: any) => {
      r.origin.record_ref = "controller/signal-20";
    },
    (r: any) => {
      r.proposal.value_text = "41";
    },
    (r: any) => {
      r.proposal.encoded_sha256 = "0".repeat(64);
    },
    (r: any) => {
      r.current_effective_value = 0;
    },
    (r: any) => {
      r.field_actions = true;
    },
    (r: any) => {
      r.origin.verified_proof.sha256 = "0".repeat(64);
    },
    (r: any) => {
      r.already_recorded = true;
    },
  ]) {
    const copy = structuredClone(data.report);
    mutate(copy);
    expect(
      previousRealDefaultMatches(copy, data.source, data.receipt),
    ).toBeFalsy();
  }
});

test("an already recorded previous value creates no transfer proposal or live-state claim", async ({
  page,
  request,
}) => {
  await reset(request);
  const data = seed(true),
    p = await offline(page, data);
  await p.panel
    .getByRole("button", { name: "Prepare previous Real default", exact: true })
    .click();
  await expect(p.prepared).toContainText(
    "Previous value already recorded in this backup",
  );
  await expect(p.prepared).toContainText(
    "does not establish current live state",
  );
  await expect(
    p.compiler.getByLabel("Proposed native Real default", { exact: true }),
  ).not.toHaveAttribute("readonly", "");
  await expect(
    p.panel.getByRole("region", {
      name: "Reviewed controller default transfer",
      exact: true,
    }),
  ).toHaveCount(0);
  const download = page.waitForEvent("download");
  await p.prepared
    .getByRole("button", {
      name: "Export exact previous-value proposal",
      exact: true,
    })
    .click();
  const exported = JSON.parse(
    readFileSync((await (await download).path())!, "utf8"),
  );
  expect(exported.proposal).toBeNull();
  expect(exported.new_review_required).toBe(false);
  expect(previousRealDefaultMatches(exported, data.source, data.receipt)).toBe(
    true,
  );
});

test("a late receipt selection retires preparation started against the previously displayed receipt", async ({
  page,
  request,
}) => {
  await reset(request);
  const a = seed(),
    b = seed(),
    p = await offline(page, a);
  let releaseReceipt!: () => void,
    seenReceipt!: () => void,
    releasePrepare!: () => void,
    seenPrepare!: () => void;
  const receiptGate = new Promise<void>((resolve) => {
      releaseReceipt = resolve;
    }),
    receiptEntered = new Promise<void>((resolve) => {
      seenReceipt = resolve;
    }),
    prepareGate = new Promise<void>((resolve) => {
      releasePrepare = resolve;
    }),
    prepareEntered = new Promise<void>((resolve) => {
      seenPrepare = resolve;
    });
  const receiptPath = base + "/receipts/" + b.request.receipt_id;
  await page.route("**" + receiptPath, async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    expect(response.ok()).toBe(true);
    seenReceipt();
    await receiptGate;
    await route.fulfill({ response });
  });
  await page.route("**" + preparePath, async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    expect(response.ok()).toBe(true);
    seenPrepare();
    await prepareGate;
    await route.fulfill({ response });
  });
  try {
    await p.panel
      .getByRole("button", {
        name: "Open receipt " + b.request.receipt_id.slice(0, 8),
        exact: true,
      })
      .click();
    await receiptEntered;
    await p.panel
      .getByRole("button", {
        name: "Prepare previous Real default",
        exact: true,
      })
      .click();
    await prepareEntered;
    releaseReceipt();
    await expect(
      p.panel
        .getByRole("region", {
          name: "Native default transfer outcome",
          exact: true,
        })
        .locator("pre"),
    ).toContainText(b.request.receipt_id);
    const finished = page.waitForResponse((response) =>
      response.url().endsWith(preparePath),
    );
    releasePrepare();
    await (await finished).finished();
    await expect(p.prepared).toHaveCount(0);
    await expect(
      p.compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("-0");
  } finally {
    releaseReceipt();
    releasePrepare();
  }
});
