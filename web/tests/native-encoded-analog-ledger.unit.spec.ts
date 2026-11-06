import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedEncodedAnalogLedger } from "./native-encoded-analog-ledger-fixture";
import { recordedEncodedAnalogTerminal } from "../src/nativeEncodedAnalogLedger";
import { recordedTerminal } from "../src/nativeTerminalLedger";
import { recordedInput } from "../src/nativeInputLedger";
let fixture: any;
const value = () => {
  fixture ??= seedEncodedAnalogLedger(
    mkdtempSync(path.join(tmpdir(), "bms-encoded-analog-ledger-")),
  );
  return structuredClone(fixture.metadata);
};
test("actual typed analog receipt remains distinct from earlier input profiles", () => {
  const v = value();
  expect(recordedEncodedAnalogTerminal(v)).toEqual(v);
  expect(recordedTerminal(v)).toBeNull();
  expect(recordedInput(v)).toBeNull();
  expect(recordedEncodedAnalogTerminal(fixture.terminal)).toBeNull();
  expect(recordedEncodedAnalogTerminal(fixture.legacy)).toBeNull();
  expect(recordedEncodedAnalogTerminal(fixture.binary)).toBeNull();
  expect(recordedEncodedAnalogTerminal(v)).toEqual(v);
});
test("paired recorded linear output endpoints retain their typed presence", () => {
  const v = value();
  v.stored_configuration.output_low = 0;
  v.stored_configuration.output_high = 100;
  v.configuration_storage.linear_output_endpoints_present = true;
  v.configuration_storage.present_properties.push(1295, 1296);
  v.configuration_storage.present_properties.sort(
    (a: number, b: number) => a - b,
  );
  expect(recordedEncodedAnalogTerminal(v)).toEqual(v);
});
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "future/1"),
  operation: (v: any) =>
    (v.operation_profile = "native-local-universal-input-transfer/2"),
  action: (v: any) => (v.action = "terminal"),
  object: (v: any) => (v.object_id = "binary-input,101"),
  instance: (v: any) => (v.object_id = "analog-input,4194303"),
  reference: (v: any) => (v.record_ref = "controller/module/0_101"),
  old: (v: any) => (v.old_slot = true),
  slot: (v: any) => (v.slot = "3"),
  same: (v: any) => {
    v.slot = 1;
    v.terminal_label = "UI IN1";
  },
  label: (v: any) => (v.terminal_label = "BI IN3"),
  hash: (v: any) => (v.compilation_sha256 = "bad"),
  missing: (v: any) => delete v.source_sha256,
  extra: (v: any) => (v.can_apply = true),
  scope: (v: any) => (v.scope = "verified live"),
  authority: (v: any) => (v.transfer_authority = true),
  confirmation: (v: any) => (v.confirmations_recorded = 1),
  charset: (v: any) => (v.device_type_character_encoding = false),
  setup: (v: any) => (v.stored_configuration.setup = true),
  real32: (v: any) => (v.stored_configuration.input_low = 0.1),
  endpoint: (v: any) => (v.stored_configuration.output_low = 0),
  presence: (v: any) =>
    (v.configuration_storage.linear_output_endpoints_present = true),
  fields: (v: any) => (v.configuration_storage.present_properties = [true]),
  stored: (v: any) => (v.stored_configuration.polarity = 1),
}))
  test(`analog recorded metadata rejects ${name}`, () => {
    const v = value();
    change(v);
    expect(recordedEncodedAnalogTerminal(v)).toBeNull();
  });
