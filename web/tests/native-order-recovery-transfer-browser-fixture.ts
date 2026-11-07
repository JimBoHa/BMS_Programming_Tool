import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { freePort } from "./workflow-peer";
import { python } from "./native-connection-fixture";
import { openOrder } from "./native-execution-order-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
  openNativeCompiler,
} from "./workspace-navigation";
export const nativeBase = "/api/bacnet/controller/native-application";
export async function seedPreviousOrderAPI(
  request: APIRequestContext,
  peer: any,
  routed: boolean,
  historical = false,
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  async function post(path: string, data: any) {
    const response = await request.post(path, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBe(true);
    return response.json();
  }
  const target = {
    address: routed ? "3001:7" : peer.direct,
    device: "device,5136",
    router: routed ? peer.router : null,
    dnet: routed ? 3001 : null,
  };
  await post("/api/bacnet/connect", {
    local_address: `127.0.0.1:${await freePort()}`,
    instance: 4190001,
    router: target.router,
    dnet: target.dnet,
  });
  await post(nativeBase + "/credentials", {
    backup: "authored-backup",
    restore: "authored-restore",
  });
  const original = await post(nativeBase + "/capture", {
    ...target,
    operation_id: "seed-original-order-capture",
  });
  const query = {
    capture_id: original.id,
    snapshot_sha256: original.snapshot_evidence_sha256,
  };
  const source = await post(nativeBase + "/inspection/source", query);
  const records = await post(nativeBase + "/inspection/records", query);
  const diagram = records.records.find((row: any) => row.class_id === 575);
  expect(diagram).toBeTruthy();
  const opened = await post(nativeBase + "/inspection/execution-order/source", {
    ...query,
    source_sha256: source.sha256,
    diagram_ref: diagram.ref,
    record_sha256: diagram.record_sha256,
  });
  const proposed = [...opened.selection.original_order];
  [proposed[0], proposed[1]] = [proposed[1], proposed[0]];
  const proposal = {
    ...query,
    source_sha256: source.sha256,
    diagram_ref: diagram.ref,
    record_sha256: diagram.record_sha256,
    effective_sha256: opened.effective_sha256,
    effective_record_sha256: opened.selection.record_sha256,
    selection_sha256: opened.selection.selection_sha256,
    proposed_order: proposed,
  };
  const plan = await post(nativeBase + "/execution-order/transfer/preview", {
    ...target,
    ...proposal,
    operation_id: "seed-original-order-review",
  });
  if (historical) await peer.command("mode drop-end");
  let parent = await post(nativeBase + "/execution-order/transfer/apply", {
    token: plan.token,
    review_sha256: plan.review_sha256,
    operation_id: "seed-original-order-apply",
    order_change_confirmed: true,
    application_transfer_confirmed: true,
  });
  if (historical) {
    expect(parent.pending).toBe(true);
    await peer.command("mode normal");
    parent = await post(nativeBase + "/readback", {
      operation_id: "seed-original-order-readback",
      receipt_id: parent.intent.id,
    });
    expect(parent.latest_readback.status).toBe("verified");
  } else expect(parent.result.status).toBe("verified");
  const current = await post(nativeBase + "/capture", {
    ...target,
    operation_id: "seed-current-after-order",
  });
  return { parent, current, original, target, headers };
}

export async function openPreviousOrderUI(
  page: Page,
  seeded: any,
  caf = false,
) {
  await page.goto("/");
  if (caf) {
    const encoded = python(
      "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
    ).trim();
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "previous-order-controller.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(encoded, "base64"),
      });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("previous-order-controller.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTool(page, "Graph editor");
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Preserved previous-order local graph");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(seeded.target.address);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill(seeded.target.device);
  await page
    .getByLabel("Known router", { exact: true })
    .fill(seeded.target.router || "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(seeded.target.dnet?.toString() || "");
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored native wire controller");
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(seeded.current.id);
  const { panel: editor } = await openOrder(page, compiler);
  await editor
    .getByLabel("Native execution-order block", { exact: true })
    .selectOption("2");
  await editor
    .getByRole("button", { name: "Move native block later", exact: true })
    .click();
  const table = editor.getByRole("table", {
    name: "Proposed native execution order",
    exact: true,
  });
  const draft = await table.textContent();
  await editor
    .getByLabel("Native execution-order destination", { exact: true })
    .selectOption("controller");
  const transfer = editor.getByRole("region", {
    name: "Native execution-order controller transfer",
    exact: true,
  });
  await transfer
    .getByText("Retained execution-order receipts", { exact: true })
    .click();
  await transfer
    .getByLabel("Execution-order receipt", { exact: true })
    .selectOption(seeded.parent.intent.id);
  await transfer
    .getByRole("button", { name: "Load execution-order receipt", exact: true })
    .click();
  const comparison = transfer.getByLabel(
    "Retained execution-order result comparison",
    { exact: true },
  );
  await comparison.locator(":scope > summary").click();
  await comparison
    .getByRole("button", {
      name: "Compare retained source with recorded execution order",
      exact: true,
    })
    .click();
  const prepare = comparison.getByLabel("Previous execution-order proposal", {
    exact: true,
  });
  await prepare.locator(":scope > summary").click();
  await prepare
    .getByRole("button", {
      name: "Prepare previous order proposal",
      exact: true,
    })
    .click();
  const prepared = prepare.getByRole("region", {
    name: "Prepared previous execution order",
    exact: true,
  });
  await expect(prepared).toBeVisible();
  return { editor, compiler, transfer, comparison, prepared, table, draft };
}

export async function choosePrevious(
  page: Page,
  opened: Awaited<ReturnType<typeof openPreviousOrderUI>>,
  review = true,
) {
  await opened.prepared
    .getByRole("button", {
      name: "Use previous order for controller review",
      exact: true,
    })
    .click();
  await expect(
    opened.transfer.getByRole("region", {
      name: "Selected previous execution-order transfer",
      exact: true,
    }),
  ).toBeVisible();
  await expect(opened.table).toHaveText(opened.draft!);
  const plan = opened.transfer.getByRole("region", {
    name: "Reviewed controller execution order",
    exact: true,
  });
  if (review) {
    await opened.transfer
      .getByRole("button", {
        name: "Review previous execution-order transfer",
        exact: true,
      })
      .click();
    await expect(plan).toBeVisible();
  }
  return plan;
}
