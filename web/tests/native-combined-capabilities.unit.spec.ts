import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedCombinedCapabilities } from "./native-combined-capability-fixture";
import { combinedCapabilityEvidence } from "../src/nativeCombinedCapabilityContract";
import { terminalCapabilityEvidence } from "../src/nativeEncodedAnalogCapabilityContract";
import {
  defaultWireCompilation,
  defaultWireReview,
} from "../src/nativeDefaultWireContract";
let data: any;
test.beforeAll(() => {
  data = seedCombinedCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-combined-capabilities-contract-")),
  );
});
for (const kind of ["valid", "unknown", "serial"])
  test(`actual ${kind} report preserves independent old evidence`, () => {
    const { report, archive } = data.cases[kind];
    expect(combinedCapabilityEvidence(report, archive)).toBe(true);
    const previous = structuredClone(report);
    previous.capability_profile = "native-backup-operation-capabilities/18";
    previous.operations = previous.operations.slice(0, -2);
    delete previous.qualification.combined_default_wire;
    expect(terminalCapabilityEvidence(previous, archive)).toBe(true);
    if (kind === "valid") expect(previous).toEqual(data.legacy);
  });
const changes: Record<string, (v: any) => void> = {
  profile: (v) =>
    (v.capability_profile = "native-backup-operation-capabilities/18"),
  capture: (v) => {
    const w = v.qualification.combined_default_wire.witness;
    for (const report of [w.signal, w.source, w.selection])
      report.captured_at = "2020-01-01T00:00:00+00:00";
  },
  signalAuthority: (v) =>
    (v.qualification.combined_default_wire.witness.signal.current_identity_verified = true),
  row: (v) => (v.operations.at(-1).status = "source-qualified"),
  prefix: (v) => (v.operations[0].id = "substituted"),
  identity: (v) => (v.qualification.recorded_identity_verified = false),
  count: (v) => (v.qualification.combined_default_wire.pair_attempts = true),
  limit: (v) => (v.qualification.combined_default_wire.pair_limit = 4096),
  error: (v) => (v.qualification.combined_default_wire.error = "Substituted"),
  extra: (v) =>
    (v.qualification.combined_default_wire.witness.token = "forbidden"),
  device: (v) =>
    (v.qualification.combined_default_wire.witness.signal.device =
      "device,9999"),
  route: (v) =>
    (v.qualification.combined_default_wire.witness.signal.target.router =
      "127.0.0.1:49999"),
  vendor: (v) =>
    (v.qualification.combined_default_wire.witness.signal.identity[
      "vendor-identifier"
    ] = 99),
  source: (v) =>
    (v.qualification.combined_default_wire.witness.source.source_sha256 =
      "0".repeat(64)),
  file: (v) =>
    (v.qualification.combined_default_wire.witness.source.files["12"].bytes +=
      1),
  authority: (v) =>
    (v.qualification.combined_default_wire.witness.source.field_transfer_enabled = true),
  proposal: (v) =>
    (v.qualification.combined_default_wire.witness.edit.value_text = "9"),
  field: (v) =>
    (v.qualification.combined_default_wire.witness.signal.fields[0].class_id = 530),
  bits: (v) =>
    (v.qualification.combined_default_wire.witness.signal.fields[0].effective_bits =
      "7fc00000"),
  before: (v) =>
    (v.qualification.combined_default_wire.witness.compilation.selected_default.before_bits =
      "00000000"),
  wire: (v) =>
    (v.qualification.combined_default_wire.witness.compilation.selected_wire.new[3] += 1),
  order: (v) =>
    (v.qualification.combined_default_wire.witness.compilation.both_orders_identical = false),
  intermediate: (v) =>
    (v.qualification.combined_default_wire.witness.compilation.default_then_wire.intermediate_sha256 =
      "0".repeat(64)),
  payload: (v) =>
    (v.qualification.combined_default_wire.witness.compilation.compiled_native_sha256 =
      "0".repeat(64)),
  qualification: (v) =>
    (v.qualification.combined_default_wire.transfer_qualification.model_inventory_used = true),
  transferError: (v) =>
    (v.qualification.combined_default_wire.transfer_error = "Not qualified"),
};
for (const [name, change] of Object.entries(changes))
  test(`substituted combined capability ${name} is refused`, () => {
    const value = structuredClone(data.cases.valid.report);
    change(value);
    expect(combinedCapabilityEvidence(value, data.cases.valid.archive)).toBe(
      false,
    );
  });
test("local compilation consistency grants no review without its original envelope and seal", () => {
  const w = data.cases.valid.report.qualification.combined_default_wire.witness;
  const f = w.signal.fields.find((v: any) => v.ref === w.edit.record_ref);
  expect(
    defaultWireCompilation(
      w.compilation,
      w.source,
      w.selection,
      w.edit,
      f,
      w.compilation.compiled_sha256,
    ),
  ).toBe(true);
  expect(
    defaultWireReview(
      { compilation: w.compilation },
      w.signal,
      w.source,
      w.selection,
      w.edit,
      f,
    ),
  ).toBe(false);
});
