import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedTerminalLedger } from "./native-terminal-ledger-fixture";
import { recordedTerminal } from "../src/nativeTerminalLedger";
import { recordedInput } from "../src/nativeInputLedger";

let fixture: any;
const value = () => {
  fixture ??= seedTerminalLedger(
    mkdtempSync(path.join(tmpdir(), "bms-terminal-ledger-")),
  );
  return structuredClone(fixture.metadata);
};
test("actual receipt terminal metadata stays distinct from the legacy input profile", () => {
  const v = value();
  expect(recordedTerminal(v)).toEqual(v);
  expect(recordedInput(v)).toBeNull();
  expect(recordedTerminal(fixture.legacy)).toBeNull();
  v.stored_configuration.input_low = -0;
  expect(
    Object.is(recordedTerminal(v)!.stored_configuration.input_low, -0),
  ).toBe(true);
});
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "future/3"),
  action: (v: any) => (v.action = "mode"),
  object: (v: any) => (v.object_id = "binary-input,101"),
  reference: (v: any) => (v.record_ref = "controller/sa/0_101"),
  old: (v: any) => (v.old_slot = true),
  slot: (v: any) => (v.slot = "3"),
  same: (v: any) => {
    v.slot = 1;
    v.terminal_label = "UI IN1";
  },
  label: (v: any) => (v.terminal_label = "BI IN3"),
  hash: (v: any) => (v.compilation_sha256 = "bad"),
  keys: (v: any) => delete v.source_sha256,
  extra: (v: any) => (v.can_apply = true),
  write: (v: any) => (v.controller_write = true),
  scope: (v: any) => (v.scope = "verified live"),
  confirmation: (v: any) => (v.wiring_confirmation_recorded = 1),
  stored: (v: any) => (v.stored_configuration.input_low = false),
  precision: (v: any) => (v.stored_configuration.output_high = 0.1),
  units: (v: any) => (v.stored_configuration.units = 1.5),
  unknown: (v: any) => (v.stored_configuration.extra = 1),
})) {
  test(`terminal recorded metadata rejects ${name}`, () => {
    const v = value();
    change(v);
    expect(recordedTerminal(v)).toBeNull();
  });
}
