import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedBatchTransfer } from "./native-default-batch-transfer-fixture";
import {
  defaultBatchTransferReview,
  defaultBatchTransferReceipt,
} from "../src/nativeDefaultBatchTransferContract";
import { recordedDefaultBatch } from "../src/NativeDefaultBatchLedgerView";
let d: any;
let controller: any;
test.beforeAll(() => {
  d = seedBatchTransfer(
    mkdtempSync(path.join(tmpdir(), "bms-batch-transfer-contract-")),
  );
  controller = {
    ...d.source.target,
    device: d.source.device,
    interfaceOpen: true,
    ownedCommands: 0,
    interfaceKey: JSON.stringify(d.review.connector_config),
  };
});
const matches = (value: any) =>
  defaultBatchTransferReview(value, d.source, d.proposal, d.opened, controller);
test("actual UDP batch review and receipt permit other fresh settings and preserve typed values", async () => {
  expect(await matches(d.review)).toBe(true);
  expect(await defaultBatchTransferReceipt(d.receipt, d.review)).toBe(true);
  expect(d.receipt.intent.payload_sha256).not.toBe(d.review.payload_sha256);
  expect(recordedDefaultBatch(d.recorded)?.selected).toHaveLength(4);
});
const reviewFaults: Record<string, (v: any) => void> = {
  kind: (v) => (v.change_kind = "signal-default"),
  profile: (v) => (v.operation_profile = "future/2"),
  target: (v) => (v.target.address = "127.0.0.1:1"),
  device: (v) => (v.identity.device = "device,99"),
  vendor: (v) => (v.identity["vendor-identifier"] = 99),
  name: (v) => (v.new_name = "Other"),
  configuration: (v) => (v.connector_config.local_address = "127.0.0.2:47808"),
  capture: (v) => (v.capture_id = "a".repeat(32)),
  snapshot: (v) => (v.snapshot_sha256 = "a".repeat(64)),
  text: (v) => (v.batch_edit.changes[0].value_text = "9"),
  guard: (v) => (v.batch_guard.fields[0].prior_bits = "00000000"),
  storage: (v) =>
    (v.compilation.batch_guard.fields.at(-1).saved_storage.maximum_code =
      4294967295),
  order: (v) => (v.compilation.both_orders_identical = false),
  intermediate: (v) =>
    (v.compilation.forward[0].edit.output_sha256 = "a".repeat(64)),
  saved: (v) => (v.compilation.parameter_merge.dynamic_sha256 = "a".repeat(64)),
  authority: (v) => (v.compilation.field_transfer_enabled = true),
  qualification: (v) =>
    (v.compilation.parameter_transfer_qualification.model_inventory_used = true),
  token: (v) => (v.token = "wrong"),
  canApply: (v) => (v.can_apply = false),
  foreign: (v) => (v.recovery_origin = {}),
  count: (v) => (v.compilation.changed_count = 0),
};
for (const [name, change] of Object.entries(reviewFaults))
  test(`refuse changed batch ${name} review`, async () => {
    const value = structuredClone(d.review);
    change(value);
    expect(await matches(value)).toBe(false);
  });
const receiptFaults: Record<string, (v: any) => void> = {
  kind: (v) => (v.intent.change_kind = "default-wire"),
  confirmation: (v) => (v.intent.defaults_change_confirmed = false),
  identity: (v) => v.intent.new_instance++,
  profile: (v) => (v.intent.operation_profile = "future/2"),
  payload: (v) => (v.intent.native_payload_sha256 = "0".repeat(64)),
  source: (v) => (v.intent.compilation.files["3"].sha256 = "0".repeat(64)),
  selected: (v) => v.result.preservation.selected_defaults.pop(),
  real: (v) =>
    (v.result.preservation.selected_defaults[0].after_bits = "00000000"),
  boolean: (v) =>
    (v.result.preservation.selected_defaults[2].after_value = true),
  enum: (v) => (v.result.preservation.selected_defaults[3].after_value = 1),
  preservation: (v) =>
    (v.result.preservation.application_identical_except_selected_defaults = false),
  semantic: (v) => (v.result.preservation.enum_semantics_verified = true),
  pending: (v) => (v.pending = true),
  native: (v) => (v.result.native_sha256 = "0".repeat(64)),
};
for (const [name, change] of Object.entries(receiptFaults))
  test(`refuse changed batch ${name} receipt`, async () => {
    const value = structuredClone(d.receipt);
    change(value);
    expect(await defaultBatchTransferReceipt(value, d.review)).toBe(false);
  });

for (const [name, change] of Object.entries({
  duplicate: (v: any) => v.selected.push(v.selected[0]),
  boolClass: (v: any) => (v.selected[0].class_id = true),
  nonfinite: (v: any) => (v.selected[0].before_encoding_hex = "447f8000002f"),
  malformedEnum: (v: any) =>
    (v.selected.at(-1).after_encoding_hex = "94000100002f"),
  oversized: (v: any) => (v.selected = Array(17).fill(v.selected[0])),
  ref: (v: any) => (v.selected[0].record_ref = "controller/\u0000bad"),
  authority: (v: any) => (v.field_authority = true),
  confirmation: (v: any) => (v.transfer_confirmation_recorded = false),
}))
  test(`withhold malformed recorded batch ${name}`, () => {
    const value = structuredClone(d.recorded);
    change(value);
    expect(recordedDefaultBatch(value)).toBeNull();
  });
test("uncertainty and later readback retain original compilation without claiming an unverified success", async () => {
  const unknown = structuredClone(d.receipt);
  unknown.pending = true;
  unknown.result = {
    status: "unknown",
    protocol_accepted: true,
    may_have_applied: true,
  };
  expect(await defaultBatchTransferReceipt(unknown, d.review)).toBe(true);
  const unfinished = structuredClone(d.receipt);
  unfinished.result = null;
  unfinished.pending = true;
  expect(await defaultBatchTransferReceipt(unfinished, d.review)).toBe(true);
  const later = structuredClone(d.receipt);
  later.latest_readback = { status: "unknown" };
  expect(await defaultBatchTransferReceipt(later, d.review)).toBe(true);
});
