import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-removal-capability-fixture";
import { removalCapabilityEvidence } from "../src/nativeRemovalCapabilityContract";
import { matchingConnectionTransferCapability } from "../src/nativeConnectionCapabilityContract";

let fixture: any;
function data() {
  fixture ??= seed(mkdtempSync(path.join(tmpdir(), "bms-removal-capability-")));
  return structuredClone(fixture);
}
test("actual original and saved-effective removal witnesses match only explicit14", () => {
  const f = data();
  expect(removalCapabilityEvidence(f.report, f.archive)).toBe(true);
  expect(matchingConnectionTransferCapability(f.report, f.archive)).toBe(false);
  expect(
    matchingConnectionTransferCapability(
      {
        ...f.report,
        capability_profile: "native-backup-operation-capabilities/13",
      },
      f.archive,
    ),
  ).toBe(true);
  expect(
    removalCapabilityEvidence(
      {
        ...f.report,
        capability_profile: "native-backup-operation-capabilities/13",
      },
      f.archive,
    ),
  ).toBe(false);
  expect(f.report.qualification.archive_connection_removal.source_sha256).toBe(
    f.archive.sha256,
  );
  expect(
    f.report.qualification.effective_connection_removal.source_sha256,
  ).not.toBe(f.archive.sha256);
});
for (const key of [
  "archive_connection_removal",
  "effective_connection_removal",
] as const)
  for (const [name, change] of Object.entries({
    source: (w: any) => (w.source_sha256 = "0".repeat(64)),
    record: (w: any) => (w.record_sha256 = "bad-hash"),
    property: (w: any) => (w.property_sha256 = "bad-hash"),
    index: (w: any) => (w.wire_index = w.connection_count),
    count: (w: any) => (w.connection_count = 3334),
    BooleanCount: (w: any) => (w.block_count = true),
    tuple: (w: any) => w.old.pop(),
    unsigned: (w: any) => (w.old[1] = -1),
    outside: (w: any) => (w.old[2] = w.block_count),
    selfRef: (w: any) => (w.source_ref = w.target_ref),
    continuation: (w: any) => (w.continuation_metadata = "not-recorded"),
    scope: (w: any) => (w.native_fallback_or_retention_verified = true),
    field: (w: any) => (w.field_transfer_enabled = true),
    unknownAuthority: (w: any) => (w.can_apply = true),
    missing: (w: any) => delete w.old,
  }))
    test(`${key} refuses substituted ${name}`, () => {
      const f = data();
      change(f.report.qualification[key]);
      expect(removalCapabilityEvidence(f.report, f.archive)).toBe(false);
    });
for (const [name, change] of Object.entries({
  static: (v: any) =>
    (v.qualification.parameter_merge.static_sha256 = "0".repeat(64)),
  dynamic: (v: any) =>
    (v.qualification.parameter_merge.dynamic_sha256 = "0".repeat(64)),
  identity: (v: any) => (v.qualification.recorded_identity_verified = false),
  mismatch: (v: any) => (v.qualification.identity_matches_snapshot = false),
  error: (v: any) => (v.qualification.archive_connection_removal_error = false),
  absent: (v: any) => delete v.qualification.effective_connection_removal,
  archiveStatus: (v: any) =>
    (v.operations.find((r: any) => r.id === "connection-removal-copy").status =
      "preflight-required"),
  savedStatus: (v: any) =>
    (v.operations.find(
      (r: any) => r.id === "effective-connection-removal-compile",
    ).status = "source-mismatch"),
  duplicate: (v: any) =>
    v.operations.push(
      v.operations.find((r: any) => r.id === "connection-removal-copy"),
    ),
  oldAuthority: (v: any) =>
    (v.qualification.archive_matching_connection.can_apply = true),
  transferState: (v: any) =>
    (v.operations.find(
      (r: any) => r.id === "matching-connection-transfer",
    ).status = "source-qualified"),
}))
  test(`profile14 refuses substituted ${name}`, () => {
    const f = data();
    change(f.report);
    expect(removalCapabilityEvidence(f.report, f.archive)).toBe(false);
  });
test("no observed edge stays unavailable rather than inventing removal or field authority", () => {
  const f = data();
  f.report.qualification.archive_connection_removal = null;
  f.report.qualification.effective_connection_removal = null;
  for (const row of f.report.operations)
    if (
      [
        "connection-removal-copy",
        "effective-connection-removal-compile",
      ].includes(row.id)
    )
      row.status = "unsupported-source";
  expect(removalCapabilityEvidence(f.report, f.archive)).toBe(true);
  f.report.operations.find(
    (r: any) => r.id === "connection-removal-copy",
  ).status = "source-qualified";
  expect(removalCapabilityEvidence(f.report, f.archive)).toBe(false);
});
