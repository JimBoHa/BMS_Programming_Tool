import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { matchingConnectionSeed } from "./native-matching-connection-fixture";
import {
  matchingConnectionReview,
  matchingConnectionReceipt,
} from "../src/nativeMatchingConnectionContract";

let fixture: any;
function data(kind = "verified") {
  fixture ??= matchingConnectionSeed(
    mkdtempSync(path.join(tmpdir(), "bms-matching-connection-contract-")),
  );
  return structuredClone(fixture[kind]);
}

test("actual reviewed connection and fresh-setting receipt satisfy the separate contract", async () => {
  const f = data();
  expect(
    await matchingConnectionReview(
      f.review,
      f.source,
      f.proposal,
      f.opened,
      f.controller,
    ),
  ).toBe(true);
  expect(f.receipt.intent.payload_sha256).not.toBe(f.review.payload_sha256);
  expect(await matchingConnectionReceipt(f.receipt, f.review)).toBe(true);
  expect(await matchingConnectionReceipt(f.receipt)).toBe(true);
});

test("uncertainty, intent-only restart and explicit readback preserve the original result", async () => {
  const f = data("uncertain");
  expect(await matchingConnectionReceipt(f.receipt, f.review)).toBe(true);
  expect(await matchingConnectionReceipt(f.reconciled, f.receipt.intent)).toBe(
    true,
  );
  expect(
    await matchingConnectionReceipt({
      ...f.receipt,
      result: null,
      latest_readback: null,
      events: [],
    }),
  ).toBe(true);
  expect(f.reconciled.result).toEqual(f.receipt.result);
  const laterUnknown = {
    ...f.reconciled,
    latest_readback: {
      status: "unknown",
      error: "A later observation timed out",
    },
  };
  // The original attempt was still unknown: an inconsistent cleared pending flag is refused.
  expect(await matchingConnectionReceipt(laterUnknown)).toBe(false);
  const resolved = data();
  expect(
    await matchingConnectionReceipt({
      ...resolved.receipt,
      latest_readback: laterUnknown.latest_readback,
    }),
  ).toBe(true);
});

test("complete original recovery is accepted separately from verifying the appended connection", async () => {
  const f = data("recovered");
  expect(await matchingConnectionReceipt(f.receipt, f.review)).toBe(true);
  expect(f.receipt.result.proposed_change_verified).toBe(false);
  f.receipt.result.status = "verified";
  expect(await matchingConnectionReceipt(f.receipt, f.review)).toBe(false);
});

for (const field of ["id", "operation_id"]) {
  test(`readback cannot substitute another intent's ${field}`, async () => {
    const f = data("uncertain");
    f.reconciled.intent[field] =
      field === "id" ? "f".repeat(32) : "another-owned-apply";
    expect(
      await matchingConnectionReceipt(f.reconciled, f.receipt.intent),
    ).toBe(false);
  });
}

test("a pre-intent refusal cannot claim dispatch or verification", async () => {
  const value = {
    intent: null,
    pending: false,
    result: {
      status: "not_sent",
      may_have_applied: false,
      protocol_accepted: false,
    },
  };
  expect(await matchingConnectionReceipt(value)).toBe(true);
  for (const bad of [
    { ...value, pending: true },
    { ...value, result: { ...value.result, status: "verified" } },
    { ...value, result: { ...value.result, may_have_applied: true } },
  ]) {
    expect(await matchingConnectionReceipt(bad)).toBe(false);
  }
});

const reviewMutations: Record<string, (v: any) => void> = {
  profile: (v) =>
    (v.operation_profile = "native-effective-wire-source-transfer/1"),
  kind: (v) => (v.change_kind = "wire-source"),
  application: (v) => (v.profile = "future/2"),
  target: (v) => (v.target.address = "3001:99"),
  device: (v) => (v.identity.device = "device,99"),
  name: (v) => (v.new_name = "Another controller"),
  instance: (v) => v.new_instance++,
  interface: (v) => (v.connector_config.local_address = "127.0.0.1:1"),
  snapshot: (v) => (v.snapshot_sha256 = "f".repeat(64)),
  archive: (v) => (v.application_sha256 = "f".repeat(64)),
  directory: (v) => (v.static_parameters_sha256 = "f".repeat(64)),
  targetReference: (v) =>
    (v.connection_edit.target_ref = v.connection_edit.source_ref),
  prototype: (v) => v.connection_edit.prototype_old[3]++,
  count: (v) => v.connection_edit.connection_count++,
  extraProposal: (v) => (v.connection_edit.can_apply = true),
  guard: (v) => (v.connection_guard.configuration_sha256 = "f".repeat(64)),
  guardProfile: (v) => (v.connection_guard.profile = "future/2"),
  payload: (v) => (v.payload_sha256 = "f".repeat(64)),
  native: (v) => (v.compilation.compiled_native_sha256 = "f".repeat(64)),
  newTuple: (v) => v.compilation.connection_edit.new[2]++,
  preserved: (v) => (v.compilation.other_merged_bytes_preserved = false),
  merged: (v) => (v.compilation.saved_settings_merged = false),
  file: (v) => v.compilation.files["12"].bytes++,
  effective: (v) => (v.compilation.effective_sha256 = "f".repeat(64)),
  qualification: (v) =>
    (v.compilation.parameter_transfer_qualification.model_inventory_used = true),
  compilerSeal: (v) => (v.compilation.compilation_sha256 = "f".repeat(64)),
  transferSeal: (v) =>
    (v.compilation.connection_compilation_sha256 = "f".repeat(64)),
  nestedSeal: (v) =>
    (v.compilation.connection_edit.compilation_sha256 = "f".repeat(64)),
  wrongOperation: (v) => (v.wire_edit = {}),
  recovery: (v) => (v.recovery_origin = {}),
  confirmationAuthority: (v) => (v.can_apply = false),
  token: (v) => (v.token = "wrong"),
  expiry: (v) => (v.expires_at = "Invalid expiry"),
};
for (const [name, mutate] of Object.entries(reviewMutations)) {
  test(`review refuses changed ${name}`, async () => {
    const f = data();
    mutate(f.review);
    expect(
      await matchingConnectionReview(
        f.review,
        f.source,
        f.proposal,
        f.opened,
        f.controller,
      ),
    ).toBe(false);
  });
}

const receiptMutations: Record<string, (v: any) => void> = {
  profile: (v) => (v.intent.operation_profile = "future/2"),
  kind: (v) => (v.intent.change_kind = "wire-source"),
  proposal: (v) =>
    (v.intent.connection_edit.target_ref = v.intent.connection_edit.source_ref),
  guard: (v) =>
    (v.intent.connection_guard.configuration_sha256 = "f".repeat(64)),
  payload: (v) => (v.intent.payload_sha256 = "f".repeat(64)),
  native: (v) => (v.intent.native_payload_sha256 = "f".repeat(64)),
  confirmation: (v) => (v.intent.connection_change_confirmed = "true"),
  interruption: (v) => (v.intent.application_transfer_confirmed = 1),
  review: (v) => (v.intent.review_sha256 = "f".repeat(64)),
  target: (v) => (v.intent.target.address = "3001:99"),
  original: (v) => (v.intent.review_capture_id = "f".repeat(32)),
  identity: (v) => v.intent.new_instance++,
  merged: (v) => (v.intent.compilation.saved_settings_merged = false),
  seal: (v) =>
    (v.intent.compilation.connection_compilation_sha256 = "f".repeat(64)),
  otherOperation: (v) => (v.intent.wire_edit = {}),
  pending: (v) => (v.pending = true),
  operational: (v) => (v.result.operational = false),
  observed: (v) => (v.result.native_sha256 = "f".repeat(64)),
  proofProfile: (v) => (v.result.preservation.profile = "future/2"),
  proof: (v) =>
    (v.result.preservation.application_matches_reviewed_connection_and_fresh_settings = false),
  otherBytes: (v) =>
    (v.result.preservation.other_merged_application_bytes_preserved = false),
  edge: (v) => v.result.preservation.selected_connection.new[3]++,
  effectiveEdge: (v) =>
    (v.result.preservation.selected_connection.effective_connection_verified = false),
  count: (v) =>
    v.result.preservation.selected_connection.connection_count_after++,
  continuation: (v) =>
    (v.result.preservation.selected_connection.continuation_prototype_sha256 =
      "f".repeat(64)),
};
for (const [name, mutate] of Object.entries(receiptMutations)) {
  test(`receipt refuses changed ${name}`, async () => {
    const f = data();
    mutate(f.receipt);
    expect(await matchingConnectionReceipt(f.receipt, f.review)).toBe(false);
  });
}
