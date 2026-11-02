import { test, expect } from "@playwright/test";
import {
  recordedPointName,
  POINT_NAME_LEDGER_PROFILE,
  POINT_NAME_LEDGER_SCOPE,
} from "../src/nativePointNameLedger";
import {
  recordedPointNameRecovery,
  POINT_RECOVERY_RECORDED,
  POINT_RECOVERY_SCOPE,
} from "../src/nativePointNameRecoveryLedger";
const point = () =>
  recordedPointName({
    state: "recorded",
    profile: POINT_NAME_LEDGER_PROFILE,
    object_id: "analog-input,101",
    record_ref: "controller/0-101",
    before: "Changed input",
    after: "Authored input",
    character_encoding: 0,
    before_record_sha256: "a".repeat(64),
    compiled_native_sha256: "b".repeat(64),
    name_confirmation_recorded: true,
    scope: POINT_NAME_LEDGER_SCOPE,
  })!;
const value = () => ({
  state: "recorded",
  profile: POINT_RECOVERY_RECORDED,
  object_id: "analog-input,101",
  record_ref: "controller/0-101",
  instance: 5136,
  before: "Changed input",
  after: "Authored input",
  character_encoding: 0,
  parent_receipt_id: "a".repeat(32),
  parent_intent_sha256: "a".repeat(64),
  verified_proof: {
    kind: "result",
    sha256: "b".repeat(64),
    time: "2026-11-02T00:00:00+00:00",
  },
  original_backup_id: "b".repeat(32),
  original_snapshot_sha256: "c".repeat(64),
  current_capture_id: "c".repeat(32),
  current_snapshot_sha256: "d".repeat(64),
  origin_sha256: "e".repeat(64),
  scope: POINT_RECOVERY_SCOPE,
});
const checked = (
  v: unknown,
  p = point(),
  child = "d".repeat(32),
  device = "device,5136",
) => recordedPointNameRecovery(v, p, child, device);

test("known recorded result and historical readback remain point-specific metadata", () => {
  for (const kind of ["result", "readback-event"]) {
    const v = value();
    v.verified_proof.kind = kind;
    expect(checked(v)).toBe(v);
  }
});
test("inconsistent, unknown and authority-looking metadata is unavailable", () => {
  for (const patch of [
    { profile: "future/2" },
    { scope: "current live state" },
    { token: "not-authority" },
    { can_apply: true },
    { origin_sha256: "bad" },
    { parent_receipt_id: "bad" },
    { current_capture_id: "b".repeat(32) },
    { before: "other" },
    { after: "other" },
    { object_id: "analog-input,102" },
    { record_ref: "controller/other" },
    { character_encoding: false },
    { instance: true },
    { instance: 4194303 },
    { verified_proof: { kind: "live", sha256: "b".repeat(64), time: "now" } },
  ])
    expect(checked({ ...value(), ...patch })).toBeNull();
});
test("parent, child, point and Device bindings stay exact", () => {
  const v = value();
  expect(
    checked(v, { ...point(), name_confirmation_recorded: false }),
  ).toBeNull();
  expect(checked(v, point(), v.parent_receipt_id)).toBeNull();
  expect(checked(v, point(), "d".repeat(32), "device,6001")).toBeNull();
  expect(
    recordedPointNameRecovery(v, null, "d".repeat(32), "device,5136"),
  ).toBeNull();
});
test("historical proof requires bounded digest and explicit timezone", () => {
  const v = value();
  for (const proof of [
    { ...v.verified_proof, time: "2026-11-02T00:00:00" },
    { ...v.verified_proof, sha256: "bad" },
    { ...v.verified_proof, token: "untrusted" },
    null,
  ])
    expect(checked({ ...v, verified_proof: proof })).toBeNull();
});
test("recovery names retain current typed-name rules even when ordinary recorded originals allow blanks", () => {
  for (const before of ["", " padded ", "bad\nname", "é".repeat(65)]) {
    const p = { ...point(), before };
    expect(checked({ ...value(), before }, p)).toBeNull();
  }
});
