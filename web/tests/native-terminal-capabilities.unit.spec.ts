import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-terminal-capability-fixture";
import { terminalCapabilityEvidence } from "../src/nativeTerminalCapabilityContract";

let fixture: any;
const data = () =>
  (fixture ??= seed(
    mkdtempSync(path.join(tmpdir(), "bms-terminal-capability-")),
  ));
for (const kind of [
  "analog",
  "binary",
  "unknown",
  "unverified",
  "output",
  "serial",
])
  test(`${kind} actual source has independently admitted terminal support`, () => {
    const f = data()[kind];
    expect(terminalCapabilityEvidence(f.report, f.archive)).toBe(true);
  });
for (const [name, change] of Object.entries({
  version: (r: any) =>
    (r.capability_profile = "native-backup-operation-capabilities/14"),
  source: (r: any) =>
    (r.qualification.archive_terminal.source_sha256 = "0".repeat(64)),
  parent: (r: any) => (r.qualification.archive_terminal.ref = "other/0_101"),
  record: (r: any) =>
    (r.qualification.archive_terminal.record_sha256 = "unknown"),
  slot: (r: any) => (r.qualification.archive_terminal.destination_slot = true),
  occupied: (r: any) => (r.qualification.archive_terminal.free_slots = [1, 2]),
  class: (r: any) => (r.qualification.archive_terminal.class_id = 242),
  merge: (r: any) =>
    (r.qualification.effective_terminal.parameter_merge.static_sha256 =
      "0".repeat(64)),
  effective: (r: any) =>
    (r.qualification.effective_terminal.source_sha256 = "0".repeat(64)),
  authority: (r: any) =>
    (r.qualification.analog_terminal.field_transfer_enabled = true),
  wiring: (r: any) =>
    (r.qualification.archive_terminal.physical_terminal_or_wiring_verified = true),
  configuration: (r: any) =>
    (r.qualification.analog_terminal.configuration_sha256 = "unknown"),
  compiler: (r: any) =>
    (r.qualification.analog_terminal.compiler_profile =
      "tagged-moi-local-terminal-copy/1"),
  operation: (r: any) =>
    (r.qualification.analog_terminal.operation_profile =
      "native-local-universal-input-transfer/1"),
  status: (r: any) =>
    (r.operations.find((x: any) => x.id === "analog-terminal-transfer").status =
      "source-qualified"),
  transport: (r: any) => (r.qualification.captured_plain_ipv4 = false),
  error: (r: any) => (r.qualification.archive_terminal_error = "Contradiction"),
  row: (r: any) => r.operations.push(r.operations[0]),
}))
  test(`terminal support rejects substituted ${name}`, () => {
    const f = data().analog,
      r = structuredClone(f.report);
    change(r);
    expect(terminalCapabilityEvidence(r, f.archive)).toBe(false);
  });
