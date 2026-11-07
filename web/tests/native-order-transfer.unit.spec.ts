import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { orderTransferSeed } from "./native-order-transfer-fixture";
import {
  orderTransferReview,
  orderTransferReceipt,
} from "../src/nativeOrderTransferContract";
import { connectionSeal } from "../src/nativeConnectionContract";

let fixture: any;
function data(kind = "verified") {
  fixture ??= orderTransferSeed(
    mkdtempSync(path.join(tmpdir(), "bms-order-contract-")),
  );
  return structuredClone(fixture[kind]);
}
const review = (f: any) =>
  orderTransferReview(f.review, f.source, f.proposal, f.opened, f.controller);

test("actual review and fresh-setting receipt satisfy the separate order contract", async () => {
  const f = data();
  expect(await review(f)).toBe(true);
  expect(f.receipt.intent.payload_sha256).not.toBe(f.review.payload_sha256);
  expect(await orderTransferReceipt(f.receipt, f.review)).toBe(true);
  expect(await orderTransferReceipt(f.receipt)).toBe(true);
});
test("uncertainty, intent-only restart and readback retain the original attempt", async () => {
  const f = data("uncertain");
  expect(await orderTransferReceipt(f.receipt, f.review)).toBe(true);
  expect(await orderTransferReceipt(f.reconciled, f.receipt.intent)).toBe(true);
  expect(
    await orderTransferReceipt({
      ...f.receipt,
      result: null,
      latest_readback: null,
      events: [],
    }),
  ).toBe(true);
  expect(f.reconciled.result).toEqual(f.receipt.result);
  expect(
    await orderTransferReceipt({
      ...f.reconciled,
      latest_readback: { status: "unknown" },
    }),
  ).toBe(false);
  expect(
    await orderTransferReceipt({
      ...data().receipt,
      latest_readback: { status: "unknown" },
    }),
  ).toBe(true);
});
test("original recovery is distinct from verifying the new order", async () => {
  const f = data("recovered");
  expect(await orderTransferReceipt(f.receipt, f.review)).toBe(true);
  expect(f.receipt.result.proposed_change_verified).toBe(false);
  f.receipt.result.status = "verified";
  expect(await orderTransferReceipt(f.receipt, f.review)).toBe(false);
});
const reviewMutations: Record<string, (v: any) => void> = {
  profile: (v) =>
    (v.operation_profile = "native-effective-matching-connection-transfer/1"),
  kind: (v) => (v.change_kind = "connection"),
  target: (v) => (v.target.address = "3001:99"),
  device: (v) => (v.identity.device = "device,99"),
  interface: (v) => (v.connector_config.local_address = "127.0.0.1:1"),
  snapshot: (v) => (v.snapshot_sha256 = "f".repeat(64)),
  archive: (v) => (v.application_sha256 = "f".repeat(64)),
  directory: (v) => (v.static_parameters_sha256 = "f".repeat(64)),
  order: (v) => (v.order_edit.proposed_order = [0, 1, 2, 3]),
  guard: (v) => (v.order_guard.configuration_sha256 = "f".repeat(64)),
  guardProfile: (v) => (v.order_guard.profile = "future/2"),
  payload: (v) => (v.payload_sha256 = "f".repeat(64)),
  native: (v) => (v.compilation.compiled_native_sha256 = "f".repeat(64)),
  patch: (v) => (v.compilation.order_edit.patches[0].new_index = 3),
  preserved: (v) => (v.compilation.other_merged_bytes_preserved = false),
  merged: (v) => (v.compilation.saved_settings_merged = false),
  effective: (v) => (v.compilation.effective_sha256 = "f".repeat(64)),
  qualification: (v) =>
    (v.compilation.parameter_transfer_qualification.model_inventory_used = true),
  compilerSeal: (v) => (v.compilation.compilation_sha256 = "f".repeat(64)),
  transferSeal: (v) =>
    (v.compilation.order_compilation_sha256 = "f".repeat(64)),
  nestedSeal: (v) =>
    (v.compilation.order_edit.compilation_sha256 = "f".repeat(64)),
  sourceProof: (v) =>
    (v.local_review.source.selection.slots[0].payload_bytes = 2),
  otherOperation: (v) => (v.connection_edit = {}),
  recovery: (v) => (v.recovery_origin = {}),
  authority: (v) => (v.can_apply = false),
  token: (v) => (v.token = "wrong"),
  expiry: (v) => (v.expires_at = "Invalid expiry"),
};
for (const [name, mutate] of Object.entries(reviewMutations))
  test(`review refuses changed ${name}`, async () => {
    const f = data();
    mutate(f.review);
    expect(await review(f)).toBe(false);
  });

const receiptMutations: Record<string, (v: any) => void> = {
  profile: (v) => (v.intent.operation_profile = "future/2"),
  kind: (v) => (v.intent.change_kind = "connection"),
  proposal: (v) => (v.intent.order_edit.proposed_order = [0, 1, 2, 3]),
  guard: (v) => (v.intent.order_guard.payload_widths[0] = 2),
  confirmation: (v) => (v.intent.order_change_confirmed = "true"),
  interruption: (v) => (v.intent.application_transfer_confirmed = 1),
  payload: (v) => (v.intent.payload_sha256 = "f".repeat(64)),
  original: (v) => (v.intent.review_capture_id = "f".repeat(32)),
  snapshot: (v) => (v.intent.review_snapshot_sha256 = "f".repeat(64)),
  seal: (v) => (v.intent.evidence_sha256 = "f".repeat(64)),
  saved: (v) =>
    (v.result.preservation.saved_application_parameters_verified = -1),
  order: (v) => (v.result.preservation.selected_order.after = [0, 1, 2, 3]),
  phase: (v) =>
    (v.result.preservation.selected_order.edge_relationships_sha256 =
      "f".repeat(64)),
  identity: (v) => (v.result.preservation.identity_unchanged = false),
  fullNative: (v) => (v.result.native_sha256 = "f".repeat(64)),
  stillPending: (v) => (v.pending = true),
};
for (const [name, mutate] of Object.entries(receiptMutations))
  test(`receipt refuses changed ${name}`, async () => {
    const f = data();
    mutate(f.receipt);
    expect(await orderTransferReceipt(f.receipt, f.review)).toBe(false);
  });

test("even resealed intent cannot substitute another target for its review", async () => {
  const f = data();
  f.receipt.intent.target.address = "3001:99";
  const { evidence_sha256: _, ...body } = f.receipt.intent;
  f.receipt.intent.evidence_sha256 = await connectionSeal(body);
  expect(await orderTransferReceipt(f.receipt, f.review)).toBe(false);
});
test("readback stays bound to its original operation", async () => {
  const f = data("uncertain");
  f.reconciled.intent.operation_id = "another-owned-apply";
  expect(await orderTransferReceipt(f.reconciled, f.receipt.intent)).toBe(
    false,
  );
});
test("pre-intent refusal never claims dispatch or verification", async () => {
  const f = {
    intent: null,
    pending: false,
    result: {
      status: "not_sent",
      may_have_applied: false,
      protocol_accepted: false,
    },
  };
  expect(await orderTransferReceipt(f, data().review)).toBe(true);
  expect(
    await orderTransferReceipt({
      ...f,
      result: { ...f.result, may_have_applied: true },
    }),
  ).toBe(false);
  expect(await orderTransferReceipt(f, data("uncertain").receipt.intent)).toBe(
    false,
  );
});
