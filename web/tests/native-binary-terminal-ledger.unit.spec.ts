import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedBinaryLedger } from "./native-binary-terminal-ledger-fixture";
import { recordedBinaryTerminal } from "../src/nativeBinaryTerminalLedger";
import { recordedTerminal } from "../src/nativeTerminalLedger";
import { recordedInput } from "../src/nativeInputLedger";
let fixture: any;
const value = () => {
  fixture ??= seedBinaryLedger(
    mkdtempSync(path.join(tmpdir(), "bms-binary-ledger-")),
  );
  return structuredClone(fixture.metadata);
};
test("actual binary receipt remains distinct from analog recorded profiles", () => {
  const v = value();
  expect(recordedBinaryTerminal(v)).toEqual(v);
  expect(recordedTerminal(v)).toBeNull();
  expect(recordedInput(v)).toBeNull();
  expect(recordedBinaryTerminal(fixture.terminal)).toBeNull();
  expect(recordedBinaryTerminal(fixture.legacy)).toBeNull();
  v.captured_counter_values = {};
  v.stored_configuration.polarity = null;
  expect(recordedBinaryTerminal(v)).toEqual(v);
});
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "future/1"),
  operation: (v: any) =>
    (v.operation_profile = "native-local-universal-input-transfer/2"),
  action: (v: any) => (v.action = "terminal"),
  object: (v: any) => (v.object_id = "analog-input,101"),
  instance: (v: any) => (v.object_id = "binary-input,4194303"),
  reference: (v: any) => (v.record_ref = "controller/module/3_101"),
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
  text: (v: any) => (v.stored_configuration.active_text = 1),
  states: (v: any) => (v.stored_configuration.states_text_index = -1),
  polarity: (v: any) => (v.stored_configuration.polarity = true),
  stored: (v: any) => (v.stored_configuration.setup = 1),
  counter: (v: any) => (v.captured_counter_values["15"] = true),
  counterRange: (v: any) => (v.captured_counter_values["33"] = 4294967296),
  counterKey: (v: any) => (v.captured_counter_values["85"] = 1),
  counterArray: (v: any) => (v.captured_counter_values = []),
}))
  test(`binary recorded metadata rejects ${name}`, () => {
    const v = value();
    change(v);
    expect(recordedBinaryTerminal(v)).toBeNull();
  });
