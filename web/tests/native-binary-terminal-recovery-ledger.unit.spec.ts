import { python } from "./native-connection-fixture";
import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-binary-terminal-recovery-ledger-fixture";
import {
  recordedBinaryTerminalRecovery,
  recordedBinaryTerminalRecoveryRow,
} from "../src/nativeBinaryTerminalRecoveryLedger";
let fixture: any;
const data = () =>
  (fixture ??= seed(
    mkdtempSync(path.join(tmpdir(), "bms-binary-recovery-lineage-")),
  ));
test("actual parent-bound inverse has closed independently admitted recorded metadata", () => {
  const f = data();
  expect(
    recordedBinaryTerminalRecovery(f.metadata, f.terminal, f.id, f.device),
  ).toEqual(f.metadata);
});
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "unknown"),
  state: (v: any) => (v.state = "verified"),
  scope: (v: any) => (v.scope = "Current controller verified"),
  extra: (v: any) => (v.extra = true),
  authority: (v: any) => (v.transfer_authority = true),
  revalidated: (v: any) => (v.parent_and_source_revalidated = true),
  flag: (v: any) => (v.lineage_enforced_recorded = 1),
  identity: (v: any) => (v.instance = 5137),
  parent: (v: any) => (v.origin.parent_receipt_id = data().id),
  source: (v: any) =>
    (v.origin.original_backup_id = v.origin.current_capture_id),
  originVersion: (v: any) => (v.origin.profile = "future/1"),
  current: (v: any) => (v.origin.current_slot = 2),
  proposal: (v: any) => (v.origin.proposal_slot = 2),
  bool: (v: any) => (v.origin.previous_slot = true),
  object: (v: any) => (v.origin.object_id = "binary-input,999"),
  guard: (v: any) => (v.origin.current_configuration_sha256 = "0".repeat(64)),
  hash: (v: any) => (v.origin_sha256 = "bad"),
  seal: (v: any) => (v.origin_sha256 = "0".repeat(64)),
  proof: (v: any) => (v.origin.verified_proof.kind = "current-verification"),
  time: (v: any) => (v.origin.verified_proof.time = "2026-11-05T01:00:00"),
}))
  test(`recorded binary recovery rejects ${name}`, () => {
    const f = data(),
      v = structuredClone(f.metadata);
    change(v);
    if (!["hash", "seal"].includes(name)) v.origin_sha256 = seal(v.origin);
    expect(
      recordedBinaryTerminalRecovery(v, f.terminal, f.id, f.device),
    ).toBeNull();
  });
test("valid recorded lineage cannot replace unavailable underlying terminal metadata", () => {
  const f = data();
  expect(
    recordedBinaryTerminalRecovery(
      f.metadata,
      { state: "unavailable" },
      f.id,
      f.device,
    ),
  ).toBeNull();
});

function seal(value: any) {
  return python(
    "import json,sys;from bms_tool.moi_identity import seal;print(seal(json.loads(sys.argv[1])))",
    JSON.stringify(value),
  ).trim();
}
test("Unicode recorded references use the original Python ASCII seal", () => {
  const f = data(),
    v = structuredClone(f.metadata),
    t = structuredClone(f.terminal);
  v.origin.record_ref = t.record_ref = "Δ-controller/3_101";
  v.origin_sha256 = seal(v.origin);
  expect(recordedBinaryTerminalRecovery(v, t, f.id, f.device)).toEqual(v);
  v.origin.record_ref = t.record_ref = "Ω-controller/3_101";
  expect(recordedBinaryTerminalRecovery(v, t, f.id, f.device)).toBeNull();
});

for (const counter of [
  {},
  { "15": 0 },
  { "33": 4294967295 },
  { "15": 999999, "33": 0 },
])
  test(`historical child counters preserve optional presence ${JSON.stringify(counter)}`, () => {
    const f = data(),
      t = structuredClone(f.terminal);
    t.captured_counter_values = counter;
    t.stored_configuration.polarity = null;
    expect(
      recordedBinaryTerminalRecovery(f.metadata, t, f.id, f.device),
    ).toEqual(f.metadata);
  });
for (const counts of [
  { "15": -1 },
  { "33": 4294967296 },
  { "15": true },
  { "15": "77" },
  { "15": 1.5 },
  { "16": 0 },
  [],
  null,
])
  test(`malformed historical child counters ${JSON.stringify(counts)} withhold lineage`, () => {
    const f = data(),
      t = structuredClone(f.terminal);
    t.captured_counter_values = counts;
    expect(
      recordedBinaryTerminalRecovery(f.metadata, t, f.id, f.device),
    ).toBeNull();
  });
function row() {
  const f = data();
  return {
    source: "native",
    native_change_kind: "input",
    native_binary_terminal_recovery: f.metadata,
    native_binary_terminal: f.terminal,
    id: f.id,
    target: { device: f.device },
  };
}
test("recorded binary row requires its own native input kind", () => {
  expect(recordedBinaryTerminalRecoveryRow(row())).toEqual(data().metadata);
  for (const kind of ["point-name", "connection", "instance", null, undefined])
    expect(
      recordedBinaryTerminalRecoveryRow({ ...row(), native_change_kind: kind }),
    ).toBeNull();
  expect(
    recordedBinaryTerminalRecoveryRow({ ...row(), source: "audit" }),
  ).toBeNull();
});
for (const key of [
  "native_input",
  "native_terminal",
  "native_terminal_recovery",
  "native_encoded_analog_terminal",
  "native_encoded_analog_recovery",
  "native_recovery",
  "native_point_name",
  "native_point_name_recovery",
  "native_connection",
])
  test(`binary namespace refuses mixed row family ${key}`, () => {
    expect(
      recordedBinaryTerminalRecoveryRow({
        ...row(),
        [key]: { state: "recorded" },
      }),
    ).toBeNull();
  });
