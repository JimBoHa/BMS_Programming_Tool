import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { seedOrderRecoveryProposal } from "./native-order-recovery-proposal-fixture";
import { orderRecoveryProposalEvidence } from "../src/nativeOrderRecoveryProposalContract";
import { connectionSeal } from "../src/nativeConnectionContract";
const fixtures: Record<string, any> = {};
test.beforeAll(() => {
  for (const kind of ["match", "historical", "reencoded"])
    fixtures[kind] = seedOrderRecoveryProposal(
      mkdtempSync(join(tmpdir(), "bms-order-previous-")),
      kind,
    );
});
for (const kind of ["match", "historical", "reencoded"])
  test(`actual ${kind} previous-order compilation binds original proof and source`, async () => {
    const f = fixtures[kind];
    expect(
      await orderRecoveryProposalEvidence(
        f.proposal,
        f.source,
        f.opened,
        f.receipt,
        f.report,
      ),
    ).toBe(true);
  });
const faults: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "future/2"),
  scope: (v) => (v.scope = "Automatic rollback"),
  source: (v) => (v.comparison.source.capture_id = "f".repeat(32)),
  parent: (v) => (v.origin.parent_receipt_id = "f".repeat(32)),
  proof: (v) => (v.origin.verified_proof.sha256 = "f".repeat(64)),
  origin: (v) => (v.origin_sha256 = "f".repeat(64)),
  comparison: (v) =>
    (v.comparison.comparisons.original_saved_directory_matches = false),
  previous: (v) => (v.proposal.proposed_order = [1, 0, 2, 3]),
  permutation: (v) => (v.proposal.proposed_order = [0, 0, 2, 3]),
  width: (v) =>
    (v.preview.compilation.order_edit.selection.slots[0].payload_bytes = 4),
  phase: (v) =>
    (v.preview.compilation.order_edit.selection.edge_relationships[0].phase =
      "different"),
  output: (v) => (v.preview.output_sha256 = "f".repeat(64)),
  compilation: (v) =>
    (v.preview.compilation.other_merged_bytes_preserved = false),
  preview: (v) => (v.preview.request.proposed_order = [1, 0, 2, 3]),
  live: (v) => (v.current_device_verified = true),
  authority: (v) => (v.can_apply = true),
  query: (v) => (v.controller_queries = true),
  write: (v) => (v.field_actions = true),
  transfer: (v) => (v.field_transfer_enabled = true),
  lineage: (v) => (v.recovery_lineage_recorded = true),
  review: (v) => (v.new_review_required = false),
  readonly: (v) => (v.read_only = 1),
  extra: (v) => (v.token = "untrusted"),
};
for (const [name, mutate] of Object.entries(faults))
  test(`resealed ${name} cannot qualify previous-order assistance`, async () => {
    const f = fixtures.match,
      v = structuredClone(f.proposal);
    mutate(v);
    const { evidence_sha256, ...body } = v;
    v.evidence_sha256 = await connectionSeal(body);
    expect(
      await orderRecoveryProposalEvidence(
        v,
        f.source,
        f.opened,
        f.receipt,
        f.report,
      ),
    ).toBe(false);
  });
