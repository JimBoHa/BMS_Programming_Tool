import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { seedBatchRecoveryTransfer } from "./native-default-batch-recovery-transfer-fixture";
import {
  batchRecoveryTransferReview,
  batchRecoveryTransferReceipt,
} from "../src/nativeDefaultBatchRecoveryTransferContract";
import { defaultBatchTransferReceipt } from "../src/nativeDefaultBatchTransferContract";
const fixtures = Object.fromEntries(
  ["valid", "fresh", "uncertain", "historical", "later-unknown"].map((kind) => [
    kind,
    seedBatchRecoveryTransfer(
      mkdtempSync(join(tmpdir(), "bms-previous-transfer-")),
      kind,
    ),
  ]),
);
for (const kind of Object.keys(fixtures))
  test(`actual ${kind} previous batch review and recorded receipt qualify separately`, async () => {
    const f = fixtures[kind],
      context = {
        report: f.prepared,
        parent: f.parent,
        generation: 1,
        current: () => true,
      };
    expect(
      await batchRecoveryTransferReview(
        f.review,
        f.source,
        f.proposal,
        f.opened,
        f.controller,
        context,
      ),
    ).toBe(true);
    expect(await defaultBatchTransferReceipt(f.receipt)).toBe(false);
    expect(await batchRecoveryTransferReceipt(f.receipt, f.review)).toBe(true);
    expect(await batchRecoveryTransferReceipt(f.receipt)).toBe(true);
  });
test("a retired preparation cannot admit controller review", async () => {
  const f = fixtures.valid;
  expect(
    await batchRecoveryTransferReview(
      f.review,
      f.source,
      f.proposal,
      f.opened,
      f.controller,
      {
        report: f.prepared,
        parent: f.parent,
        generation: 1,
        current: () => false,
      },
    ),
  ).toBe(false);
});

type Data = Record<string, any>;
const altered: Record<string, (v: Data) => void> = {
  profile: (v) => (v.recovery_profile = "future"),
  scope: (v) => (v.recovery_scope = "Physical acceptance"),
  authority: (v) => (v.recovery_authority = true),
  unknown: (v) => (v.recovery_origin.can_apply = true),
  parent: (v) => (v.recovery_origin.parent_receipt_id = "bad"),
  parent_intent: (v) => (v.recovery_origin.parent_intent_sha256 = "bad"),
  dispatch: (v) => (v.recovery_origin.original_dispatch = "not-sent"),
  proof: (v) => (v.recovery_origin.verified_proof.kind = "unverified"),
  proof_time: (v) => (v.recovery_origin.verified_proof.time = "unknown"),
  backup: (v) => (v.recovery_origin.original_backup_id = "bad"),
  source: (v) => (v.recovery_origin.current_capture_id = "a".repeat(32)),
  snapshot: (v) => (v.recovery_origin.current_snapshot_sha256 = "a".repeat(64)),
  count: (v) => v.recovery_origin.fields.pop(),
  order: (v) => v.recovery_origin.fields.reverse(),
  previous: (v) => (v.recovery_origin.fields[0].previous.bits = "00000000"),
  nonfinite: (v) => (v.recovery_origin.fields[0].previous.bits = "7f800000"),
  current: (v) => (v.recovery_origin.fields[0].current.bits = "00000000"),
  encoded: (v) =>
    (v.recovery_origin.fields[0].current_encoded_sha256 = "a".repeat(64)),
  already: (v) => (v.recovery_origin.fields[0].already_recorded = true),
  boolean: (v) => (v.recovery_origin.fields[2].previous.value = 1),
  enum: (v) => (v.recovery_origin.fields[3].previous.value = 65536),
  seal: (v) => (v.recovery_origin_sha256 = "a".repeat(64)),
  guard: (v) => (v.compilation.batch_guard.fields[0].prior_bits = "00000000"),
};
for (const [name, change] of Object.entries(altered))
  test(`altered ${name} cannot qualify recovery review or receipt`, async () => {
    const f = fixtures.valid,
      review = structuredClone(f.review),
      receipt = structuredClone(f.receipt);
    change(review);
    change(receipt.intent);
    const context = {
      report: f.prepared,
      parent: f.parent,
      generation: 1,
      current: () => true,
    };
    expect(
      await batchRecoveryTransferReview(
        review,
        f.source,
        f.proposal,
        f.opened,
        f.controller,
        context,
      ),
    ).toBe(false);
    expect(await batchRecoveryTransferReceipt(receipt, f.review)).toBe(false);
    expect(await batchRecoveryTransferReceipt(receipt)).toBe(false);
  });
test("a foreign recovery reference is refused and no-intent refusal stays a refusal", async () => {
  const f = fixtures.valid,
    r = {
      intent: null,
      pending: false,
      result: {
        status: "not_sent",
        may_have_applied: false,
        protocol_accepted: false,
      },
    };
  expect(
    await batchRecoveryTransferReceipt(f.receipt, fixtures.fresh.review),
  ).toBe(false);
  expect(await batchRecoveryTransferReceipt(r, f.review)).toBe(true);
  expect(
    await batchRecoveryTransferReceipt(
      { ...r, result: { ...r.result, may_have_applied: true } },
      f.review,
    ),
  ).toBe(false);
});
