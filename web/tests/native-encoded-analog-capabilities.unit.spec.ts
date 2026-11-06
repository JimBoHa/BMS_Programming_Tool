import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedEncodedAnalogCapabilities } from "./native-encoded-analog-capability-fixture";
import { terminalCapabilityEvidence } from "../src/nativeEncodedAnalogCapabilityContract";
import { terminalCapabilityEvidence as legacyEvidence } from "../src/nativeBinaryTerminalCapabilityContract";
let fixture: any;
const data = () =>
  (fixture ??= seedEncodedAnalogCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-typed-analog-capability-")),
  ));
for (const kind of [
  "ucs2",
  "ascii",
  "linear",
  "unknown",
  "unverified",
  "serial",
  "output",
  "binary",
  "configuration",
  "endpoint",
])
  test(`${kind} typed analog capability report admits current and independent predecessor evidence`, () => {
    const f = data()[kind];
    expect(terminalCapabilityEvidence(f.report, f.archive)).toBe(true);
    expect(legacyEvidence(f.report, f.archive)).toBe(false);
  });
for (const [name, change] of Object.entries({
  profile: (r: any) =>
    (r.capability_profile = "native-backup-operation-capabilities/17"),
  source: (r: any) =>
    (r.qualification.encoded_analog_terminal.source_sha256 = "0".repeat(64)),
  merge: (r: any) =>
    (r.qualification.encoded_analog_terminal.parameter_merge.static_sha256 =
      "0".repeat(64)),
  effective: (r: any) =>
    (r.qualification.encoded_analog_terminal.effective_sha256 = "0".repeat(64)),
  native: (r: any) =>
    (r.qualification.encoded_analog_terminal.source_native_sha256 = "0".repeat(
      64,
    )),
  root: (r: any) =>
    (r.qualification.encoded_analog_terminal.ref = "other/0_101"),
  object: (r: any) =>
    (r.qualification.encoded_analog_terminal.object = "binary-input,101"),
  instance: (r: any) =>
    (r.qualification.encoded_analog_terminal.object = "analog-input,4194303"),
  slot: (r: any) =>
    (r.qualification.encoded_analog_terminal.destination_slot = true),
  occupied: (r: any) =>
    (r.qualification.encoded_analog_terminal.free_slots = [1, 3]),
  order: (r: any) =>
    (r.qualification.encoded_analog_terminal.free_slots = [3, 2]),
  destination: (r: any) =>
    (r.qualification.encoded_analog_terminal.destination_slot = 3),
  operation: (r: any) =>
    (r.qualification.encoded_analog_terminal.operation_profile =
      "native-local-universal-input-transfer/2"),
  compiler: (r: any) =>
    (r.qualification.encoded_analog_terminal.compiler_profile =
      "tagged-moi-local-terminal-copy/1"),
  charset: (r: any) =>
    (r.qualification.encoded_analog_terminal.device_type_character_encoding = 5),
  bool: (r: any) =>
    (r.qualification.encoded_analog_terminal.device_type_character_encoding = false),
  preserved: (r: any) =>
    (r.qualification.encoded_analog_terminal.device_type_encoding_preserved = false),
  configuration: (r: any) =>
    (r.qualification.encoded_analog_terminal.configuration_sha256 = "bad"),
  setup: (r: any) =>
    (r.qualification.encoded_analog_terminal.stored_configuration.setup = true),
  real32: (r: any) =>
    (r.qualification.encoded_analog_terminal.stored_configuration.input_low = 0.1),
  output: (r: any) =>
    (r.qualification.encoded_analog_terminal.stored_configuration.output_low = 0),
  storage: (r: any) =>
    (r.qualification.encoded_analog_terminal.configuration_storage.linear_output_endpoints_present = true),
  present: (r: any) =>
    (r.qualification.encoded_analog_terminal.configuration_storage.present_properties =
      [true]),
  extraConfiguration: (r: any) =>
    (r.qualification.encoded_analog_terminal.stored_configuration.polarity = 1),
  authority: (r: any) =>
    (r.qualification.encoded_analog_terminal.field_transfer_enabled = true),
  physical: (r: any) =>
    (r.qualification.encoded_analog_terminal.physical_terminal_or_wiring_verified = true),
  missing: (r: any) =>
    delete r.qualification.encoded_analog_terminal.source_native_sha256,
  extra: (r: any) => (r.qualification.encoded_analog_terminal.can_apply = true),
  error: (r: any) =>
    (r.qualification.encoded_analog_terminal_error = "Contradiction"),
  row: (r: any) => r.operations.push(r.operations.at(-1)),
  status: (r: any) => (r.operations.at(-1).status = "source-qualified"),
  rowAuthority: (r: any) => (r.operations.at(-1).can_apply = true),
  legacy: (r: any) =>
    (r.qualification.encoded_archive_terminal.device_type_character_encoding = 5),
}))
  test(`typed analog capability rejects ${name}`, () => {
    const f = data().ucs2,
      r = structuredClone(f.report);
    change(r);
    expect(terminalCapabilityEvidence(r, f.archive)).toBe(false);
  });
