import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { seedBatchRecovery } from "./native-default-batch-recovery-fixture";
import {
  defaultBatchRecoveryEvidence,
  defaultBatchRecoveryParent,
} from "../src/nativeDefaultBatchRecoveryContract";
import { defaultBatchTransferReceipt } from "../src/nativeDefaultBatchTransferContract";
type Data = Record<string, any>;
const fixtures = Object.fromEntries(
  [
    "valid",
    "partial",
    "already",
    "recompressed",
    "historical",
    "later-unknown",
  ].map((kind) => [
    kind,
    seedBatchRecovery(
      mkdtempSync(join(tmpdir(), "bms-batch-recovery-contract-")),
      kind,
    ),
  ]),
);
for (const kind of Object.keys(fixtures))
  test(`actual ${kind} retained batch recovery evidence qualifies without authority`, async () => {
    const f = fixtures[kind];
    expect(
      await defaultBatchRecoveryEvidence(f.recovery, f.opened, f.receipt),
    ).toBe(true);
    expect(f.recovery.can_apply).toBe(false);
    expect(f.recovery.controller_queries).toBe(false);
  });
const tamper: Record<string, (r: Data) => void> = {
  profile: (r) => (r.profile = "future"),
  authority: (r) => (r.can_apply = true),
  query: (r) => (r.controller_queries = true),
  extra: (r) => (r.token = "a".repeat(32)),
  source: (r) => (r.source.capture_id = "a".repeat(32)),
  parent: (r) => (r.origin.parent_receipt_id = "a".repeat(32)),
  intent: (r) => (r.origin.parent_intent_sha256 = "a".repeat(64)),
  proof: (r) => (r.origin.verified_proof.sha256 = "a".repeat(64)),
  proof_time: (r) => (r.origin.verified_proof.time = "unknown"),
  native: (r) => (r.origin.recorded_native_payload_sha256 = "a".repeat(64)),
  origin_seal: (r) => (r.origin_sha256 = "a".repeat(64)),
  count: (r) => r.origin.fields.pop(),
  previous: (r) => (r.origin.fields[0].previous.bits = "00000000"),
  after: (r) => (r.origin.fields[1].recorded_after.bits = "00000000"),
  current: (r) => (r.origin.fields[0].current.bits = "00000000"),
  reordered: (r) => r.origin.fields.reverse(),
  already: (r) => (r.already_recorded = true),
  proposal: (r) => (r.proposal.changes[0].value_text = "999"),
  selected: (r) => r.proposal.changes.reverse(),
  slot: (r) =>
    (r.compilation.batch_guard.fields.at(-1).saved_storage.datatype = 4),
  output: (r) => (r.output_sha256 = "a".repeat(64)),
  partial_authority: (r) => (r.compilation.can_apply = true),
};
for (const [name, change] of Object.entries(tamper))
  test(`altered ${name} recovery evidence is refused`, async () => {
    const f = fixtures.valid,
      r = structuredClone(f.recovery);
    change(r);
    expect(await defaultBatchRecoveryEvidence(r, f.opened, f.receipt)).toBe(
      false,
    );
  });
test("a pending original and unrelated receipt cannot bind previous values", async () => {
  const f = fixtures.valid;
  expect(
    await defaultBatchRecoveryEvidence(f.recovery, f.opened, {
      ...f.receipt,
      pending: true,
    }),
  ).toBe(false);
  expect(
    await defaultBatchRecoveryEvidence(
      f.recovery,
      f.opened,
      fixtures.partial.receipt,
    ),
  ).toBe(false);
});

test("historical local preparation does not change the existing field receipt predicate", async () => {
  const f = fixtures["later-unknown"];
  expect(await defaultBatchTransferReceipt(f.receipt)).toBe(false);
  expect(await defaultBatchRecoveryParent(f.receipt)).toBe(true);
  expect(
    await defaultBatchRecoveryEvidence(f.recovery, f.opened, f.receipt),
  ).toBe(true);
});
for (const fault of ["no-dispatch", "event-payload", "event-binding"])
  test(`historical ${fault} cannot qualify a recovery parent`, async () => {
    const f = fixtures["later-unknown"],
      r = structuredClone(f.receipt);
    const proof = r.events.find(
      (e: Data) => e.stage === "readback" && e.detail?.status === "verified",
    );
    if (fault === "no-dispatch") r.result.may_have_applied = false;
    if (fault === "event-payload") proof.detail.native_sha256 = "a".repeat(64);
    if (fault === "event-binding") proof.evidence_sha256 = "invalid";
    expect(await defaultBatchRecoveryParent(r)).toBe(false);
    expect(await defaultBatchRecoveryEvidence(f.recovery, f.opened, r)).toBe(
      false,
    );
  });
