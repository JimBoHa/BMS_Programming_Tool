import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-terminal-recovery-fixture";
import {
  terminalRecoveryDraft,
  terminalRecoveryReview,
  sameTerminalRecoveryLineage,
} from "../src/nativeTerminalRecoveryContract";
let fixture: any;
const data = () =>
  (fixture ??= seed(
    mkdtempSync(path.join(tmpdir(), "bms-terminal-recovery-")),
  ));
test("actual sealed local recovery report binds captured source and verified parent", async () => {
  const f = data();
  expect(
    await terminalRecoveryDraft(
      { data: JSON.parse(f.text), blob: new Blob([f.text]) },
      f.source,
      f.parent,
    ),
  ).toBe(true);
});
for (const [name, change] of Object.entries({
  version: (r: any) => (r.profile = "unknown"),
  capture: (r: any) => (r.source.capture_id = "0".repeat(32)),
  snapshot: (r: any) => (r.origin.current_snapshot_sha256 = "0".repeat(64)),
  parent: (r: any) => (r.origin.parent_receipt_id = "0".repeat(32)),
  parentHash: (r: any) => (r.origin.parent_intent_sha256 = "0".repeat(64)),
  original: (r: any) => (r.origin.original_backup_id = "0".repeat(32)),
  target: (r: any) => (r.source.target.address = "127.0.0.2:47819"),
  slot: (r: any) => (r.origin.previous_slot = true),
  guard: (r: any) => (r.origin.current_configuration_sha256 = "0".repeat(64)),
  mode: (r: any) => (r.inverse_compilation.stored_configuration.setup = 9),
  field: (r: any) => (r.can_apply = true),
  lineage: (r: any) => (r.parent_lineage_enforced_by_field_transfer = true),
  edit: (r: any) => (r.proposal.edit.slot = 2),
  compiler: (r: any) =>
    (r.inverse_compilation.terminal_compilation.profile = "unknown"),
  output: (r: any) => (r.inverse_output_sha256 = "0".repeat(64)),
  seal: (r: any) => (r.evidence_sha256 = "0".repeat(64)),
}))
  test(`previous-terminal report rejects ${name}`, async () => {
    const f = data(),
      r = structuredClone(f.report);
    change(r);
    expect(
      await terminalRecoveryDraft(
        { data: r, blob: new Blob([JSON.stringify(r)]) },
        f.source,
        f.parent,
      ),
    ).toBe(false);
  });
test("field review and receipt keep exact recovery metadata while ordinary reviews withhold it", () => {
  const f = data(),
    r = {
      terminal_recovery_profile: "native-analog-terminal-recovery-transfer/1",
      terminal_recovery_lineage_enforced: true,
      recovery_parent_receipt: f.parent.id,
      recovery_origin: f.report.origin,
      recovery_origin_sha256: f.report.origin_sha256,
    };
  expect(terminalRecoveryReview(r, f.report)).toBe(true);
  expect(terminalRecoveryReview({}, null)).toBe(true);
  expect(terminalRecoveryReview(r, null)).toBe(false);
  for (const key of Object.keys(r)) {
    const changed = { ...r };
    delete changed[key];
    expect(terminalRecoveryReview(changed, f.report)).toBe(false);
    expect(sameTerminalRecoveryLineage(changed, r)).toBe(false);
  }
  expect(sameTerminalRecoveryLineage(r, structuredClone(r))).toBe(true);
  expect(sameTerminalRecoveryLineage({}, {})).toBe(true);
});
