import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sha256 } from "@noble/hashes/sha2.js";
import { batchRecoveryOriginJSON } from "../src/nativeDefaultBatchRecoveryContract";
import {
  recordedBatchRecovery,
  recordedBatchValue,
} from "../src/nativeDefaultBatchRecoveryLedger";
import { seedBatchRecoveryLedger } from "./native-default-batch-recovery-ledger-fixture";
type Data = Record<string, any>;
let data: Data;
test.beforeAll(() => {
  data = seedBatchRecoveryLedger(
    mkdtempSync(join(tmpdir(), "batch-recovery-ledger-contract-")),
  );
});
test("actual recorded recovery binds its child, typed defaults and sealed original lineage", () => {
  const value = recordedBatchRecovery(data.row);
  expect(value).not.toBeNull();
  expect(value!.origin.parent_receipt_id).toBe(data.parent);
  expect(
    Object.is(
      recordedBatchValue("real", value!.origin.fields[1].recorded_after),
      -0,
    ),
  ).toBe(true);
  expect(value!.field_authority).toBe(false);
});
const faults: Record<string, (row: Data, v: Data, o: Data) => void> = {
  profile: (r, v) => (v.profile = "unsupported/2"),
  scope: (r, v) => (v.scope = "Live state"),
  authority: (r, v) => (v.field_authority = true),
  parent_checked: (r, v) => (v.parent_revalidated = true),
  source_checked: (r, v) => (v.source_revalidated = true),
  live: (r, v) => (v.current_device_verified = true),
  extra: (r, v) => (v.plan_token = "invalid"),
  child: (r, v) => (v.child_receipt_id = "a".repeat(32)),
  row_id: (r) => (r.id = "invalid"),
  source: (r) => (r.source = "audit"),
  kind: (r) => (r.native_change_kind = "input"),
  device: (r) => (r.target.device = "device,1"),
  instance: (r, v) => (v.instance = true),
  base: (r) =>
    (r.native_default_batch.selected[0].after_encoding_hex = "443f8000002f"),
  payload: (r, v) => (v.compiled_native_sha256 = "a".repeat(64)),
  origin_profile: (r, v, o) => (o.profile = "unsupported/2"),
  own_parent: (r, v, o) => (o.parent_receipt_id = r.id),
  backup: (r, v, o) => (o.original_backup_id = o.current_capture_id),
  capture: (r, v, o) => (o.current_capture_id = "a".repeat(32)),
  snapshot: (r, v, o) => (o.current_snapshot_sha256 = "a".repeat(64)),
  extra_origin: (r, v, o) => (o.authority = true),
  dispatch: (r, v, o) => (o.original_dispatch = "not possible"),
  proof: (r, v, o) => (o.verified_proof.kind = "unverified"),
  proof_time: (r, v, o) => (o.verified_proof.time = 1),
  naive_time: (r, v, o) => (o.verified_proof.time = "2026-11-06T08:00:00"),
  proof_hash: (r, v, o) => (o.verified_proof.sha256 = "invalid"),
  empty: (r, v, o) => (o.fields = []),
  limit: (r, v, o) => (o.fields = Array(17).fill(o.fields[0])),
  order: (r, v, o) => o.fields.reverse(),
  duplicate: (r, v, o) => (o.fields[1] = o.fields[0]),
  property: (r, v, o) => (o.fields[0].property = 1),
  class: (r, v, o) => (o.fields[0].class_id = 530),
  reference: (r, v, o) => (o.fields[0].record_ref = "different"),
  previous: (r, v, o) => (o.fields[0].previous.bits = "3f800000"),
  current: (r, v, o) => (o.fields[0].current.bits = "3f800000"),
  recorded_after: (r, v, o) => (o.fields[0].recorded_after.bits = "3f800000"),
  nan: (r, v, o) => (o.fields[0].previous.bits = "7fc00000"),
  boolean: (r, v, o) => (o.fields[2].previous.value = 1),
  enum: (r, v, o) => (o.fields[3].previous.value = 65536),
  encoded: (r, v, o) => (o.fields[0].current_encoded_sha256 = "a".repeat(64)),
  already: (r, v, o) => (o.fields[0].already_recorded = true),
  enum_meanings: (r, v, o) => (o.enum_semantics_verified = true),
};
for (const [name, alter] of Object.entries(faults))
  test(`resealed ${name} cannot qualify recorded batch recovery`, () => {
    const row = structuredClone(data.row),
      v = row.native_default_batch_recovery,
      o = v.origin;
    alter(row, v, o);
    v.origin_sha256 = Array.from(
      sha256(new TextEncoder().encode(batchRecoveryOriginJSON(o))),
      (b) => b.toString(16).padStart(2, "0"),
    ).join("");
    expect(recordedBatchRecovery(row)).toBeNull();
  });
test("unknown origin seal is refused without converting the original record", () => {
  const row = structuredClone(data.row);
  row.native_default_batch_recovery.origin_sha256 = "a".repeat(64);
  expect(recordedBatchRecovery(row)).toBeNull();
  expect(recordedBatchRecovery(data.row)).not.toBeNull();
});
