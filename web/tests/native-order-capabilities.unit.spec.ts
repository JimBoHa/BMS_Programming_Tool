import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedOrderCapabilities } from "./native-order-capability-fixture";
import { orderCapabilityEvidence } from "../src/nativeOrderCapabilityContract";
import { removalCapabilityEvidence } from "../src/nativeRemovalCapabilityContract";
let fixture: any;
function data(kind = "valid") {
  fixture ??= seedOrderCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-order-capability-")),
  );
  return structuredClone(fixture.cases[kind]);
}
for (const kind of [
  "valid",
  "raw",
  "activity",
  "serial",
  "bbmd",
  "chain",
  "unknown",
  "unverified",
  "refused",
  "large",
])
  test(`actual ${kind} source keeps the complete older profile`, async () => {
    const { report, archive, previous } = data(kind);
    expect(await orderCapabilityEvidence(report, archive)).toBe(true);
    const old = structuredClone(report);
    old.capability_profile = "native-backup-operation-capabilities/14";
    old.operations = old.operations.slice(0, -2);
    delete old.qualification.execution_order;
    expect(old).toEqual(previous);
    expect(removalCapabilityEvidence(old, archive)).toBe(true);
  });
const mutations: Record<string, (v: any) => void> = {
  profile: (v) =>
    (v.capability_profile = "native-backup-operation-capabilities/21"),
  capture: (v) => (v.capture_id = "0".repeat(32)),
  source: (v) => (v.sha256 = "f".repeat(64)),
  target: (v) => (v.target.device = "device,99"),
  prefix: (v) => (v.operations[0].id = "substituted"),
  authority: (v) => (v.can_apply = true),
  queries: (v) => (v.controller_queries = true),
  localStatus: (v) => (v.operations.at(-2).status = "not-evaluated"),
  fieldStatus: (v) => (v.operations.at(-1).status = "source-qualified"),
  limit: (v) => (v.qualification.execution_order.limits.diagrams = 9),
  count: (v) => (v.qualification.execution_order.diagram_count = 0),
  attempts: (v) => (v.qualification.execution_order.compile_attempts = true),
  none: (v) => (v.qualification.execution_order.witness = null),
  extra: (v) => (v.qualification.execution_order.can_apply = true),
  error: (v) => (v.qualification.execution_order.error = "Unexpected"),
  order: (v) =>
    (v.qualification.execution_order.witness.request.proposed_order = [
      0, 1, 2, 3,
    ]),
  sourceProof: (v) =>
    (v.qualification.execution_order.witness.review.source.current_identity_verified = true),
  record: (v) =>
    (v.qualification.execution_order.witness.record.class_id = 999),
  width: (v) =>
    (v.qualification.execution_order.witness.review.source.selection.slots[0].payload_bytes = 2),
  phase: (v) =>
    (v.qualification.execution_order.witness.review.source.selection.edge_relationships[0].relationship =
      "after"),
  compile: (v) =>
    (v.qualification.execution_order.witness.transfer_compilation.order_guard.profile =
      "future/2"),
  native: (v) =>
    (v.qualification.execution_order.witness.transfer_compilation.compiled_native_sha256 =
      "f".repeat(64)),
  qualification: (v) =>
    (v.qualification.execution_order.witness.transfer_compilation.parameter_transfer_qualification.model_inventory_used = true),
  missingTransfer: (v) =>
    (v.qualification.execution_order.witness.transfer_compilation = null),
};
for (const [name, mutate] of Object.entries(mutations))
  test(`order capability refuses changed ${name}`, async () => {
    const f = data();
    mutate(f.report);
    expect(await orderCapabilityEvidence(f.report, f.archive)).toBe(false);
  });
test("no-witness statuses cannot claim transfer prerequisites", async () => {
  for (const kind of ["chain", "unknown", "unverified", "large"]) {
    const f = data(kind);
    f.report.operations.at(-1).status = "preflight-required";
    expect(await orderCapabilityEvidence(f.report, f.archive)).toBe(false);
  }
});
test("an offline witness cannot claim current IPv4 access", async () => {
  const f = data("serial");
  f.report.operations.at(-1).status = "preflight-required";
  expect(await orderCapabilityEvidence(f.report, f.archive)).toBe(false);
});
