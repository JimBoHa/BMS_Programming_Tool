import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedBinaryCapabilities } from "./native-binary-terminal-capability-fixture";
import { terminalCapabilityEvidence } from "../src/nativeBinaryTerminalCapabilityContract";
import { terminalCapabilityEvidence as legacyEvidence } from "../src/nativeEncodedTerminalCapabilityContract";
let fixture: any;
const data = () =>
  (fixture ??= seedBinaryCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-binary-capability-")),
  ));
for (const kind of [
  "ucs2",
  "ascii",
  "unknown",
  "unverified",
  "serial",
  "output",
  "analog",
  "configuration",
  "counter",
])
  test(`${kind} binary capability report admits current and independent predecessor evidence`, () => {
    const f = data()[kind];
    expect(terminalCapabilityEvidence(f.report, f.archive)).toBe(true);
    expect(legacyEvidence(f.report, f.archive)).toBe(false);
  });
for (const [name, change] of Object.entries({
  profile: (r: any) =>
    (r.capability_profile = "native-backup-operation-capabilities/16"),
  source: (r: any) =>
    (r.qualification.binary_terminal.source_sha256 = "0".repeat(64)),
  merge: (r: any) =>
    (r.qualification.binary_terminal.parameter_merge.static_sha256 = "0".repeat(
      64,
    )),
  effective: (r: any) =>
    (r.qualification.binary_terminal.effective_sha256 = "0".repeat(64)),
  native: (r: any) =>
    (r.qualification.binary_terminal.source_native_sha256 = "0".repeat(64)),
  root: (r: any) => (r.qualification.binary_terminal.ref = "other/3_101"),
  object: (r: any) =>
    (r.qualification.binary_terminal.object = "analog-input,101"),
  instance: (r: any) =>
    (r.qualification.binary_terminal.object = "binary-input,4194303"),
  slot: (r: any) => (r.qualification.binary_terminal.destination_slot = true),
  occupied: (r: any) => (r.qualification.binary_terminal.free_slots = [1, 3]),
  order: (r: any) => (r.qualification.binary_terminal.free_slots = [3, 2]),
  destination: (r: any) =>
    (r.qualification.binary_terminal.destination_slot = 3),
  operation: (r: any) =>
    (r.qualification.binary_terminal.operation_profile =
      "native-local-universal-input-transfer/2"),
  compiler: (r: any) =>
    (r.qualification.binary_terminal.compiler_profile =
      "tagged-moi-local-terminal-copy/1"),
  charset: (r: any) =>
    (r.qualification.binary_terminal.device_type_character_encoding = 5),
  bool: (r: any) =>
    (r.qualification.binary_terminal.device_type_character_encoding = false),
  preserved: (r: any) =>
    (r.qualification.binary_terminal.device_type_encoding_preserved = false),
  configuration: (r: any) =>
    (r.qualification.binary_terminal.configuration_sha256 = "bad"),
  text: (r: any) =>
    (r.qualification.binary_terminal.stored_configuration.active_text = true),
  states: (r: any) =>
    (r.qualification.binary_terminal.stored_configuration.states_text_index =
      -1),
  polarity: (r: any) =>
    (r.qualification.binary_terminal.stored_configuration.polarity = true),
  extraConfiguration: (r: any) =>
    (r.qualification.binary_terminal.stored_configuration.setup = 1),
  counter: (r: any) =>
    (r.qualification.binary_terminal.captured_counter_values["15"] = false),
  unknownCounter: (r: any) =>
    (r.qualification.binary_terminal.captured_counter_values["85"] = 1),
  liveCounter: (r: any) =>
    (r.qualification.binary_terminal.counter_values_are_live = true),
  authority: (r: any) =>
    (r.qualification.binary_terminal.field_transfer_enabled = true),
  physical: (r: any) =>
    (r.qualification.binary_terminal.physical_terminal_or_wiring_verified = true),
  missing: (r: any) =>
    delete r.qualification.binary_terminal.source_native_sha256,
  extra: (r: any) => (r.qualification.binary_terminal.can_apply = true),
  error: (r: any) => (r.qualification.binary_terminal_error = "Contradiction"),
  row: (r: any) => r.operations.push(r.operations.at(-1)),
  status: (r: any) => (r.operations.at(-1).status = "source-qualified"),
  rowAuthority: (r: any) => (r.operations.at(-1).can_apply = true),
  legacy: (r: any) =>
    (r.qualification.encoded_archive_terminal.device_type_character_encoding = 5),
}))
  test(`binary capability rejects ${name}`, () => {
    const f = data().ucs2,
      r = structuredClone(f.report);
    change(r);
    expect(terminalCapabilityEvidence(r, f.archive)).toBe(false);
  });
