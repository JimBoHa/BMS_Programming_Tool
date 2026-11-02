import { test, expect } from "@playwright/test";
import {
  recordedInput,
  INPUT_LEDGER_PROFILE,
  INPUT_LEDGER_SCOPE,
} from "../src/nativeInputLedger";
const value = () => ({
  state: "recorded",
  profile: INPUT_LEDGER_PROFILE,
  scope: INPUT_LEDGER_SCOPE,
  action: "allocate",
  object_id: "analog-input,3000010",
  record_ref: "controller/0_3000010",
  slot: 1,
  terminal_label: "UI IN1",
  requested_name: "Authored new input",
  requested_configuration: {
    mode: "voltage",
    input_low: -0,
    input_high: 10,
    output_low: 0,
    output_high: 0.1,
    units: 98,
    minimum: 0,
    maximum: 100,
  },
  stored_configuration: {
    setup: 1,
    field_units: 5,
    input_low: -0,
    input_high: 10,
    output_low: 0,
    output_high: Math.fround(0.1),
    units: 98,
    minimum: 0,
    maximum: 100,
  },
  allocation_receipt_id: null,
  wiring_confirmation_recorded: true,
});
test("recorded metadata preserves exact single precision and signed zero", () => {
  const original = value(),
    record = recordedInput(original);
  expect(record).not.toBeNull();
  expect(Object.is(record!.stored_configuration!.input_low, -0)).toBe(true);
  original.stored_configuration.output_high = 0.1000000001;
  expect(recordedInput(original)).toBeNull();
});
test("unknown profile, authority claims and malformed terminal or origin stay unavailable", () => {
  for (const patch of [
    { profile: "future/2" },
    { slot: "1" },
    { slot: true },
    { object_id: "analog-input,03000010" },
    { can_apply: true },
    { scope: "This grants field authority" },
    { record_ref: "bad/\ud800" },
  ])
    expect(recordedInput({ ...value(), ...patch })).toBeNull();
  const removal = {
    ...value(),
    action: "remove-allocated",
    requested_name: null,
    requested_configuration: null,
    stored_configuration: null,
    allocation_receipt_id: "a".repeat(32),
  };
  expect(recordedInput(removal)).not.toBeNull();
  expect(
    recordedInput({ ...removal, allocation_receipt_id: "bad" }),
  ).toBeNull();
});
