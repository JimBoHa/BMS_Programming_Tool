import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { orderRecoveryTransferSeed } from "./native-order-recovery-transfer-fixture";
import {
  orderTransferReview,
  orderTransferReceipt,
} from "../src/nativeOrderTransferContract";
import {
  orderRecoveryMetadata,
  orderRecoveryOrigin,
} from "../src/nativeOrderRecoveryTransferContract";
import { recordedOrderRecovery } from "../src/nativeOrderRecoveryLedger";
import { connectionSeal } from "../src/nativeConnectionContract";
let fixture: any;
const data = (kind = "verified") => {
  fixture ??= orderRecoveryTransferSeed(
    mkdtempSync(path.join(tmpdir(), "bms-previous-order-contract-")),
  );
  return structuredClone(fixture[kind]);
};
const review = (f: any, previous = f.prepared) =>
  orderTransferReview(
    f.review,
    f.source,
    f.proposal,
    f.opened,
    f.controller,
    previous,
  );
const reseal = async (f: any) => {
  const { token, review_sha256, ...body } = f.review;
  f.review.review_sha256 = await connectionSeal(body);
};
for (const kind of ["verified", "historical", "uncertain"])
  test(`actual ${kind} previous-order review and recorded receipt satisfy typed lineage`, async () => {
    const f = data(kind);
    expect(await review(f)).toBe(true);
    expect(
      await orderTransferReview(
        f.review,
        f.source,
        f.proposal,
        f.opened,
        f.controller,
      ),
    ).toBe(false);
    expect(f.receipt.intent.payload_sha256).not.toBe(f.review.payload_sha256);
    expect(await orderTransferReceipt(f.receipt, f.review)).toBe(true);
    expect(await orderTransferReceipt(f.receipt)).toBe(true);
    expect(recordedOrderRecovery(f.row)?.origin).toEqual(f.prepared.origin);
    if (kind === "uncertain") {
      expect(await orderTransferReceipt(f.reconciled, f.receipt.intent)).toBe(
        true,
      );
      expect(f.reconciled.result).toEqual(f.receipt.result);
      expect(
        await orderTransferReceipt({
          ...f.reconciled,
          latest_readback: { status: "unknown" },
        }),
      ).toBe(false);
    }
  });

for (const fault of [
  "profile",
  "scope",
  "extra",
  "missing",
  "origin-hash",
  "parent",
  "proof-kind",
  "proof-time",
  "proof-number",
  "extra-origin",
  "wrong-proposal",
])
  test(`resealed ${fault} previous-order review cannot acquire authority`, async () => {
    const f = data();
    if (fault === "profile") f.review.recovery_profile += "future";
    else if (fault === "scope") f.review.recovery_scope += "future";
    else if (fault === "extra") f.review.recovery_authority = true;
    else if (fault === "missing") delete f.review.recovery_origin;
    else if (fault === "origin-hash")
      f.review.recovery_origin_sha256 = "a".repeat(64);
    else if (fault === "parent")
      f.review.recovery_origin.parent_receipt_id = "a".repeat(32);
    else if (fault === "proof-kind")
      f.review.recovery_origin.verified_proof.kind = "latest-unknown";
    else if (fault === "proof-time")
      f.review.recovery_origin.verified_proof.time = "2026-01-01T00:00:00";
    else if (fault === "proof-number")
      f.review.recovery_origin.verified_proof.time = 1;
    else if (fault === "extra-origin")
      f.review.recovery_origin.field_authority = true;
    else f.prepared.proposal.proposed_order = [0, 1, 3, 2];
    if (f.review.recovery_origin && fault !== "origin-hash")
      f.review.recovery_origin_sha256 = await connectionSeal(
        f.review.recovery_origin,
      );
    await reseal(f);
    expect(await review(f)).toBe(false);
  });

test("a receipt cannot add valid lineage to a known ordinary review", async () => {
  const f = data(),
    ordinary = structuredClone(f.review);
  for (const key of Object.keys(ordinary).filter((key) =>
    key.startsWith("recovery_"),
  ))
    delete ordinary[key];
  expect(await orderTransferReceipt(f.receipt, ordinary)).toBe(false);
  expect(orderRecoveryMetadata(f.review, null)).toBe(false);
  expect(orderRecoveryOrigin(f.prepared.origin, f.prepared.origin_sha256)).toBe(
    true,
  );
});

for (const fault of [
  "source",
  "kind",
  "child",
  "device",
  "diagram",
  "before",
  "after",
  "width",
  "width-bool",
  "origin",
  "authority",
  "parent-revalidated",
  "extra",
])
  test(`recorded ${fault} lineage does not mislabel a Changes row`, () => {
    const f = data(),
      r = f.row,
      v = r.native_order_recovery;
    if (fault === "source") r.source = "audit";
    else if (fault === "kind") r.native_change_kind = "input";
    else if (fault === "child") v.child_receipt_id = "a".repeat(32);
    else if (fault === "device") r.target.device = "device,99";
    else if (fault === "diagram") v.diagram_ref += "different";
    else if (fault === "before") v.before[0] = true;
    else if (fault === "after") v.after = [...v.before];
    else if (fault === "width") v.payload_widths[0] = 0;
    else if (fault === "width-bool") v.payload_widths[0] = true;
    else if (fault === "origin") v.origin_sha256 = "a".repeat(64);
    else if (fault === "authority") v.field_authority = true;
    else if (fault === "parent-revalidated") v.parent_revalidated = true;
    else v.can_apply = true;
    expect(recordedOrderRecovery(r)).toBeNull();
  });
