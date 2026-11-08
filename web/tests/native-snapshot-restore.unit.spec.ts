import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { snapshotRestoreFixture } from "./native-snapshot-restore-fixture";
import {
  snapshotRestoreSource,
  snapshotRestoreReview,
  snapshotRestoreReceipt,
  restoreHash,
  restoreID,
} from "../src/nativeSnapshotRestoreContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import { recordedSnapshotRestore } from "../src/NativeSnapshotRestoreLedgerView";
let fixture: any;
function data(kind = "verified") {
  fixture ??= snapshotRestoreFixture(
    mkdtempSync(path.join(tmpdir(), "bms-retained-restore-contract-")),
  );
  return structuredClone(fixture[kind]);
}
for (const kind of ["verified", "uncertain", "recovered-original"])
  test(`actual ${kind} retained image, review, receipt and recorded provenance satisfy contract`, async () => {
    const f = data(kind);
    expect(await snapshotRestoreSource(f.inspected, f.archive)).toBe(true);
    expect(
      await snapshotRestoreReview(
        f.review,
        f.archive,
        f.inspected,
        f.controller,
      ),
    ).toBe(true);
    expect(await snapshotRestoreReceipt(f.receipt, f.review)).toBe(true);
    expect(await snapshotRestoreReceipt(f.receipt)).toBe(true);
    expect(recordedSnapshotRestore(f.row)?.restore_capture_id).toBe(
      f.archive.capture_id,
    );
    if (f.reconciled)
      expect(await snapshotRestoreReceipt(f.reconciled, f.receipt.intent)).toBe(
        true,
      );
  });
for (const fault of [
  "source",
  "source-scope",
  "source-authority",
  "counter-guard",
  "current-source",
  "payload",
  "difference",
  "target",
  "interface",
  "extra-source",
])
  test(`resealed ${fault} restore review cannot acquire browser authority`, async () => {
    const f = data();
    const r = f.review;
    if (fault === "source")
      r.restore_source.request.restore_capture_id = "f".repeat(32);
    else if (fault === "source-scope")
      r.restore_source.scope = "Unqualified scope";
    else if (fault === "source-authority") r.restore_source.can_apply = true;
    else if (fault === "counter-guard")
      r.compilation.prewrite_guard.counter_count = true;
    else if (fault === "current-source") r.capture_id = f.archive.capture_id;
    else if (fault === "payload") r.payload_sha256 = "f".repeat(64);
    else if (fault === "difference") r.compilation.difference.removed_records++;
    else if (fault === "target") r.target.address = "3001:8";
    else if (fault === "interface")
      r.connector_config.local_address = "127.0.0.1:49000";
    else r.restore_source.unqualified_authority = true;
    r.restore_source.evidence_sha256 = await connectionSeal(
      Object.fromEntries(
        Object.entries(r.restore_source).filter(
          ([key]) => key !== "evidence_sha256",
        ),
      ),
    );
    r.compilation.restore_source_evidence_sha256 =
      r.restore_source.evidence_sha256;
    r.compilation.compilation_sha256 = await connectionSeal(
      Object.fromEntries(
        Object.entries(r.compilation).filter(
          ([key]) => key !== "compilation_sha256",
        ),
      ),
    );
    const { token, review_sha256, ...body } = r;
    r.review_sha256 = await connectionSeal(body);
    expect(
      await snapshotRestoreReview(r, f.archive, f.inspected, f.controller),
    ).toBe(false);
  });
for (const fault of [
  "receipt-id",
  "source",
  "prewrite-backup",
  "kind",
  "native-hash",
  "result-binding",
  "latest-readback",
])
  test(`altered ${fault} recorded restore cannot be mistaken for the admitted result`, async () => {
    const f = data(fault === "latest-readback" ? "uncertain" : "verified");
    const r = fault === "latest-readback" ? f.reconciled : f.receipt;
    if (fault === "receipt-id") r.intent.id = "f".repeat(32);
    else if (fault === "source")
      r.intent.restore_source.request.restore_capture_id = "f".repeat(32);
    else if (fault === "prewrite-backup")
      r.intent.backup_id = f.archive.capture_id;
    else if (fault === "kind") r.intent.change_kind = "signal-default";
    else if (fault === "native-hash")
      r.intent.native_payload_sha256 = "f".repeat(64);
    else if (fault === "result-binding")
      r.result.intent_sha256 = "f".repeat(64);
    else
      r.latest_readback.preservation.restore_source_capture_id = "f".repeat(32);
    expect(await snapshotRestoreReceipt(r, f.review)).toBe(false);
  });
for (const fault of [
  "source",
  "kind",
  "child",
  "target",
  "source-reference",
  "prewrite",
  "counter-authority",
  "counts",
  "scope",
  "unknown",
])
  test(`recorded ${fault} provenance mismatch grants no tools or field authority`, () => {
    const f = data();
    const r = f.row,
      v = r.native_application_restore;
    if (fault === "source") r.source = "audit";
    else if (fault === "kind") r.native_change_kind = "input";
    else if (fault === "child") r.id = "f".repeat(32);
    else if (fault === "target") r.target.device = "device,99";
    else if (fault === "source-reference") v.restore_capture_id = "unavailable";
    else if (fault === "prewrite") v.prewrite_backup_id = v.restore_capture_id;
    else if (fault === "counter-authority") v.field_authority = true;
    else if (fault === "scope") v.difference.scope += "future";
    else if (fault === "unknown") v.future_authority = true;
    else v.difference.added_records++;
    expect(recordedSnapshotRestore(r)).toBeNull();
  });
test("native restore identifier and hash guards reject final newlines", () => {
  expect(restoreID("f".repeat(32) + "\n")).toBe(false);
  expect(restoreHash("f".repeat(64) + "\n")).toBe(false);
});
