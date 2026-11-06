import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedBatchCapabilities } from "./native-batch-capability-fixture";
import { batchCapabilityEvidence } from "../src/nativeBatchCapabilityContract";
import { combinedCapabilityEvidence } from "../src/nativeCombinedCapabilityContract";
import {
  defaultBatchCompilation,
  defaultBatchReview,
} from "../src/nativeDefaultBatchContract";

let data: any;
test.beforeAll(() => {
  data = seedBatchCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-batch-capability-contract-")),
  );
});
for (const kind of [
  "valid",
  "serial",
  "unknown",
  "unverified",
  "large",
  "empty",
  "refused",
  "boolean",
  "enum",
])
  test(`actual ${kind} batch analysis preserves the entire prior profile`, () => {
    const { report, archive, previous } = data.cases[kind];
    expect(batchCapabilityEvidence(report, archive)).toBe(true);
    const old = structuredClone(report);
    old.capability_profile = "native-backup-operation-capabilities/19";
    old.operations = old.operations.slice(0, -1);
    delete old.qualification.typed_default_batch;
    expect(old).toEqual(previous);
    expect(combinedCapabilityEvidence(old, archive)).toBe(true);
  });

const changes: Record<string, (v: any) => void> = {
  profile: (v) =>
    (v.capability_profile = "native-backup-operation-capabilities/19"),
  prefix: (v) => (v.operations[0].id = "substituted"),
  row: (v) => (v.operations.at(-1).status = "preflight-required"),
  capture: (v) => (v.capture_id = "0".repeat(32)),
  device: (v) => (v.target.device = "device,9999"),
  authority: (v) => (v.can_apply = true),
  file: (v) => (v.files["12"].bytes += 1),
  identity: (v) => (v.qualification.recorded_identity_verified = false),
  count: (v) => (v.qualification.typed_default_batch.field_count += 1),
  selected: (v) => (v.qualification.typed_default_batch.selected_count = 0),
  attempts: (v) =>
    (v.qualification.typed_default_batch.compile_attempts = true),
  limit: (v) => (v.qualification.typed_default_batch.field_limit = 17),
  error: (v) => (v.qualification.typed_default_batch.error = "Substituted"),
  sourceTime: (v) =>
    (v.qualification.typed_default_batch.witness.source.captured_at =
      "2020-01-01T00:00:00+00:00"),
  sourceFile: (v) =>
    (v.qualification.typed_default_batch.witness.source.files["11"].bytes += 1),
  sourceIdentity: (v) =>
    (v.qualification.typed_default_batch.witness.source.identity[
      "vendor-identifier"
    ] = 99),
  sourceAuthority: (v) =>
    (v.qualification.typed_default_batch.witness.source.field_transfer_enabled = true),
  proposal: (v) =>
    (v.qualification.typed_default_batch.witness.request.changes[0].value_text =
      "9"),
  proposalAuthority: (v) =>
    (v.qualification.typed_default_batch.witness.request.token = "forbidden"),
  field: (v) =>
    (v.qualification.typed_default_batch.witness.source.fields[0].field.class_id = 530),
  selection: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.selected[0].before_encoding_hex =
      "44000000002f"),
  independent: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.independent[0].compilation.other_merged_bytes_preserved = false),
  order: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.both_orders_identical = false),
  intermediate: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.forward[0].edit.source_sha256 =
      "0".repeat(64)),
  final: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.reverse.at(
      -1,
    ).edit.output_sha256 = "0".repeat(64)),
  unknownCompilationAuthority: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.token =
      "forbidden"),
  unknownConstituentAuthority: (v) =>
    (v.qualification.typed_default_batch.witness.compilation.independent[0].compilation.token =
      "forbidden"),
  extraWitnessAuthority: (v) =>
    (v.qualification.typed_default_batch.witness.review_sha256 = "0".repeat(
      64,
    )),
};
for (const [name, change] of Object.entries(changes))
  test(`substituted batch capability ${name} is rejected`, () => {
    const report = structuredClone(data.cases.valid.report);
    change(report);
    expect(batchCapabilityEvidence(report, data.cases.valid.archive)).toBe(
      false,
    );
  });
for (const fault of ["attempts", "limit", "count", "witness"])
  test(`failed bounded probe cannot grant ${fault} evidence`, () => {
    const report = structuredClone(data.cases.refused.report),
      e = report.qualification.typed_default_batch;
    if (fault === "attempts") e.compile_attempts = 0;
    if (fault === "limit") e.selected_count = 17;
    if (fault === "count") e.field_count = null;
    if (fault === "witness")
      e.witness =
        data.cases.valid.report.qualification.typed_default_batch.witness;
    expect(batchCapabilityEvidence(report, data.cases.refused.archive)).toBe(
      false,
    );
  });
test("pure local compilation consistency cannot substitute for an export review", () => {
  const w = data.cases.valid.report.qualification.typed_default_batch.witness;
  expect(
    defaultBatchCompilation(
      w.compilation,
      w.source,
      w.request,
      w.compilation.compiled_sha256,
    ),
  ).toBe(true);
  expect(
    defaultBatchReview({ compilation: w.compilation }, w.source, w.request),
  ).toBe(false);
});
