import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-connection-capability-fixture";
import { connectionCapabilityEvidence } from "../src/nativeConnectionCapabilityContract";

let fixture: any;
function data() {
  fixture ??= seed(
    mkdtempSync(path.join(tmpdir(), "bms-connection-capability-unit-")),
  );
  return structuredClone(fixture);
}
test("actual archive and effective connection witnesses match their distinct captured source hashes", () => {
  const f = data();
  expect(connectionCapabilityEvidence(f.report, f.archive)).toBe(true);
  expect(f.report.qualification.archive_matching_connection.source_sha256).toBe(
    f.archive.sha256,
  );
  expect(
    f.report.qualification.effective_matching_connection.source_sha256,
  ).not.toBe(f.archive.sha256);
});
for (const [name, change] of Object.entries({
  original: (v: any) =>
    (v.qualification.archive_matching_connection.source_sha256 = "0".repeat(
      64,
    )),
  effective: (v: any) =>
    (v.qualification.effective_matching_connection.source_sha256 = "0".repeat(
      64,
    )),
  static: (v: any) =>
    (v.qualification.parameter_merge.static_sha256 = "0".repeat(64)),
  dynamic: (v: any) =>
    (v.qualification.parameter_merge.dynamic_sha256 = "0".repeat(64)),
  identity: (v: any) => (v.qualification.recorded_identity_verified = false),
  tuple: (v: any) =>
    (v.qualification.archive_matching_connection.prototype_old[0] = 99),
  sourceIndex: (v: any) =>
    (v.qualification.archive_matching_connection.source_index = true),
  target: (v: any) =>
    (v.qualification.archive_matching_connection.target_ref =
      v.qualification.archive_matching_connection.source_ref),
  duplicateIndex: (v: any) =>
    (v.qualification.archive_matching_connection.target_index =
      v.qualification.archive_matching_connection.source_index),
  count: (v: any) =>
    (v.qualification.archive_matching_connection.connection_count = 3333),
  metadata: (v: any) =>
    (v.qualification.archive_matching_connection.metadata_property_sha256 =
      null),
  authority: (v: any) =>
    (v.qualification.archive_matching_connection.can_apply = true),
  state: (v: any) =>
    (v.operations.find((r: any) => r.id === "matching-connection-copy").status =
      "preflight-required"),
  missing: (v: any) => delete v.qualification.effective_matching_connection,
  rows: (v: any) => (v.operations = {}),
}))
  test(`connection capability admission refuses substituted ${name}`, () => {
    const f = data();
    change(f.report);
    expect(connectionCapabilityEvidence(f.report, f.archive)).toBe(false);
  });
test("no candidate remains unavailable without inventing a source or a field preflight", () => {
  const f = data();
  f.report.qualification.archive_matching_connection = null;
  f.report.qualification.effective_matching_connection = null;
  for (const row of f.report.operations)
    if (
      ["matching-connection-copy", "effective-connection-compile"].includes(
        row.id,
      )
    )
      row.status = "unsupported-source";
  expect(connectionCapabilityEvidence(f.report, f.archive)).toBe(true);
});
