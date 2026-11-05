import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-terminal-recovery-ledger-fixture";
import { recordedTerminalRecovery } from "../src/nativeTerminalRecoveryLedger";
let fixture: any;
const data = () =>
  (fixture ??= seed(mkdtempSync(path.join(tmpdir(), "bms-terminal-lineage-"))));
test("actual parent-bound inverse has closed independently admitted recorded metadata", () => {
  const f = data();
  expect(
    recordedTerminalRecovery(f.metadata, f.terminal, f.id, f.device),
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
  object: (v: any) => (v.origin.object_id = "analog-input,999"),
  guard: (v: any) => (v.origin.current_configuration_sha256 = "0".repeat(64)),
  hash: (v: any) => (v.origin_sha256 = "bad"),
  proof: (v: any) => (v.origin.verified_proof.kind = "current-verification"),
  time: (v: any) => (v.origin.verified_proof.time = "2026-11-05T01:00:00"),
}))
  test(`recorded terminal recovery rejects ${name}`, () => {
    const f = data(),
      v = structuredClone(f.metadata);
    change(v);
    expect(recordedTerminalRecovery(v, f.terminal, f.id, f.device)).toBeNull();
  });
test("valid recorded lineage cannot replace unavailable underlying terminal metadata", () => {
  const f = data();
  expect(
    recordedTerminalRecovery(
      f.metadata,
      { state: "unavailable" },
      f.id,
      f.device,
    ),
  ).toBeNull();
});
