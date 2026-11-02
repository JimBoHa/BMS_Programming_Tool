import { test, expect } from "@playwright/test";
import {
  recordedPointName,
  POINT_NAME_LEDGER_PROFILE,
  POINT_NAME_LEDGER_SCOPE,
} from "../src/nativePointNameLedger";
const value = () => ({
  state: "recorded",
  profile: POINT_NAME_LEDGER_PROFILE,
  object_id: "analog-input,1",
  record_ref: "controller/input",
  before: "",
  after: "Changed input",
  character_encoding: 0,
  before_record_sha256: "a".repeat(64),
  compiled_native_sha256: "b".repeat(64),
  name_confirmation_recorded: true,
  scope: POINT_NAME_LEDGER_SCOPE,
});
test("exact recorded names include empty originals and all supported value object families", () => {
  for (const type of [
    "analog-input",
    "analog-output",
    "analog-value",
    "binary-input",
    "binary-output",
    "binary-value",
    "multi-state-input",
    "multi-state-output",
    "multi-state-value",
  ]) {
    expect(
      recordedPointName({ ...value(), object_id: type + ",1" }),
    ).not.toBeNull();
  }
  expect(recordedPointName({ ...value(), before: "old\nname" })?.before).toBe(
    "old\nname",
  );
});
test("unknown, malformed or authority-looking metadata withholds tool binding", () => {
  for (const change of [
    { profile: "future/2" },
    { token: "not-authority" },
    { object_id: "device,1" },
    { object_id: "analog-input,01" },
    { object_id: "analog-input,4194303" },
    { record_ref: "bad" },
    { record_ref: "controller/\ud800" },
    { before: "x".repeat(4097) },
    { after: "  name" },
    { after: "a\x00b" },
    { character_encoding: true },
    { compiled_native_sha256: "bad" },
    { scope: "verified live name" },
  ])
    expect(recordedPointName({ ...value(), ...change })).toBeNull();
});
