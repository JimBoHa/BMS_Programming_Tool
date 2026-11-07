import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedBatchTransferCapabilities } from "./native-batch-transfer-capability-fixture";
import { batchTransferCapabilityEvidence } from "../src/nativeBatchTransferCapabilityContract";
import { batchCapabilityEvidence } from "../src/nativeBatchCapabilityContract";
import {
  defaultBatchTransferCompilation,
  defaultBatchTransferProblem,
  defaultBatchTransferProposal,
} from "../src/nativeDefaultBatchTransferContract";
import { defaultBatchRequest } from "../src/nativeDefaultBatchContract";
let data: any;
test.beforeAll(() => {
  data = seedBatchTransferCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-batch-transfer-capability-")),
  );
});
for (const kind of [
  "valid",
  "serial",
  "bbmd",
  "unknown",
  "unverified",
  "large",
  "empty",
  "refused",
  "boolean",
  "enum",
  "unfixed",
])
  test(`actual ${kind} transfer preflight retains its full profile20 prefix`, () => {
    const { report, archive, previous } = data.cases[kind];
    expect(batchTransferCapabilityEvidence(report, archive)).toBe(true);
    const old = structuredClone(report);
    old.capability_profile = "native-backup-operation-capabilities/20";
    old.operations.pop();
    delete old.qualification.typed_default_batch_transfer;
    expect(old).toEqual(previous);
    expect(batchCapabilityEvidence(old, archive)).toBe(true);
  });
const changes: Record<string, (v: any) => void> = {
  profile: (v) =>
    (v.capability_profile = "native-backup-operation-capabilities/20"),
  prefix: (v) => (v.operations[0].id = "substituted"),
  row: (v) => (v.operations.at(-1).status = "preflight-required"),
  capture: (v) => (v.capture_id = "0".repeat(32)),
  target: (v) => (v.target.device = "device,99"),
  authority: (v) => (v.can_apply = true),
  queries: (v) => (v.controller_queries = true),
  identity: (v) => (v.qualification.recorded_identity_verified = false),
  count: (v) => v.qualification.typed_default_batch_transfer.field_count++,
  candidates: (v) =>
    v.qualification.typed_default_batch_transfer.candidate_count++,
  selected: (v) =>
    (v.qualification.typed_default_batch_transfer.selected_count = 0),
  attempts: (v) =>
    (v.qualification.typed_default_batch_transfer.compile_attempts = true),
  limit: (v) => (v.qualification.typed_default_batch_transfer.field_limit = 17),
  error: (v) =>
    (v.qualification.typed_default_batch_transfer.error = "Unexpected"),
  sourceTime: (v) =>
    (v.qualification.typed_default_batch_transfer.source.captured_at =
      "2020-01-01T00:00:00Z"),
  sourceFile: (v) =>
    v.qualification.typed_default_batch_transfer.source.files["11"].bytes++,
  sourceIdentity: (v) =>
    (v.qualification.typed_default_batch_transfer.source.identity[
      "vendor-identifier"
    ] = 99),
  fieldType: (v) =>
    (v.qualification.typed_default_batch_transfer.fields[0].kind = "boolean"),
  fieldClass: (v) =>
    (v.qualification.typed_default_batch_transfer.fields[0].class_id = 999),
  fieldPrerequisite: (v) =>
    (v.qualification.typed_default_batch_transfer.fields[0].prerequisite =
      "requires-fixed-enum-slot"),
  fixedClaim: (v) =>
    (v.qualification.typed_default_batch_transfer.fields[3].prerequisite =
      "candidate-for-review"),
  transferProfile: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.transfer_profile =
      "future/2"),
  proposed: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.request.changes[0].value_text =
      "9"),
  guard: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.batch_guard.fields[0].prior_bits =
      "00000000"),
  capacity: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.batch_guard.fields.at(
      -1,
    ).saved_storage.maximum_code = 4294967295),
  qualification: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.parameter_transfer_qualification.model_inventory_used = true),
  payload: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.compiled_sha256 =
      "0".repeat(64)),
  nativeHashShape: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.compiled_native_sha256 =
      "bad"),
  compilerAuthority: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.field_transfer_enabled = true),
  composition: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.both_orders_identical = false),
  intermediate: (v) =>
    (v.qualification.typed_default_batch_transfer.witness.compilation.reverse[0].edit.output_sha256 =
      "0".repeat(64)),
  unknown: (v) => (v.qualification.typed_default_batch_transfer.future = true),
};
for (const [name, change] of Object.entries(changes))
  test(`reject changed transfer prerequisite ${name}`, () => {
    const { report, archive } = data.cases.valid,
      value = structuredClone(report);
    change(value);
    expect(batchTransferCapabilityEvidence(value, archive)).toBe(false);
  });
test("bounded transfer compilation evidence grants neither local review nor field authority", () => {
  const e = data.cases.valid.report.qualification.typed_default_batch_transfer,
    w = e.witness;
  expect(
    defaultBatchTransferCompilation(w.compilation, w.request, e.source),
  ).toBe(true);
  expect(defaultBatchTransferProblem(w.request, e.source)).toBeNull();
  expect(e.source.can_apply).toBe(false);
  expect(w.compilation.field_transfer_enabled).toBe(false);
  expect(w.token).toBeUndefined();
  expect(w.review_sha256).toBeUndefined();
});
test("an unfixed selected Enum explains its existing field refusal without disabling local work", () => {
  const e =
      data.cases.unfixed.report.qualification.typed_default_batch_transfer,
    f = e.source.fields[0].field;
  const request = defaultBatchRequest(e.source, e.source, { [f.ref]: "0" });
  expect(defaultBatchTransferProposal(request, e.source)).toBe(false);
  expect(defaultBatchTransferProblem(request, e.source)).toContain(
    "no captured fixed saved-value slot",
  );
  expect(defaultBatchTransferProblem(request, e.source)).toContain(
    "local copy remains available",
  );
});
test("uninspected and unfinished selections receive non-authorizing prerequisites", () => {
  expect(defaultBatchTransferProblem(null, null)).toContain("Inspect");
  expect(
    defaultBatchTransferProblem(
      null,
      data.cases.valid.report.qualification.typed_default_batch_transfer.source,
    ),
  ).toContain("Select 1–16");
});
