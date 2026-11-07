import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { seedBatchResultMatch } from "./native-default-batch-result-match-fixture";
import {
  batchResultMatchEvidence,
  batchResultMatchParent,
} from "../src/nativeDefaultBatchResultMatchContract";
type Data = Record<string, any>;
const fixtures: Data = {};
test.beforeAll(() => {
  for (const kind of [
    "valid",
    "selected",
    "unselected",
    "recovery",
    "historical",
    "reencoded",
    "routed",
  ])
    fixtures[kind] = seedBatchResultMatch(
      mkdtempSync(join(tmpdir(), "batch-result-match-contract-")),
      kind,
    );
});
for (const kind of [
  "valid",
  "selected",
  "unselected",
  "recovery",
  "historical",
  "reencoded",
  "routed",
])
  test(`actual ${kind} retained result comparison qualifies only its source and receipt`, async () => {
    const f = fixtures[kind];
    expect(
      await batchResultMatchEvidence(f.report, f.source, f.opened, f.receipt),
    ).toBe(true);
    expect(f.report.state).toBe(
      ["selected", "unselected", "routed"].includes(kind)
        ? "different"
        : "application-and-values-match",
    );
  });
const faults: Record<string, (v: Data) => void> = {
  profile: (v) => (v.profile = "unsupported/2"),
  scope: (v) => (v.scope = "Current controller verified"),
  extra: (v) => (v.plan_token = "invalid"),
  read_only: (v) => (v.read_only = false),
  query: (v) => (v.controller_queries = true),
  field: (v) => (v.field_actions = true),
  apply: (v) => (v.can_apply = true),
  transfer: (v) => (v.field_transfer_enabled = true),
  live: (v) => (v.current_device_verified = true),
  parent: (v) => (v.parent_revalidated = true),
  meanings: (v) => (v.enum_semantics_verified = true),
  receipt: (v) => (v.receipt_id = "a".repeat(32)),
  intent: (v) => (v.intent_sha256 = "a".repeat(64)),
  backup: (v) => (v.original_backup_id = "a".repeat(32)),
  snapshot: (v) => (v.original_snapshot_sha256 = "invalid"),
  recovery: (v) => (v.recorded_recovery_child = true),
  target: (v) => (v.recorded_target.address = "127.0.0.1:1"),
  current_target: (v) => (v.current_target.address = "127.0.0.1:1"),
  identity: (v) => (v.recorded_identity["object-name"] = "Different"),
  expected_hash: (v) => (v.expected_native_sha256 = "a".repeat(64)),
  effective_hash: (v) => (v.current_effective_sha256 = "a".repeat(64)),
  native_hash: (v) => (v.current_native_sha256 = "a".repeat(64)),
  effective_native_hash: (v) =>
    (v.current_effective_native_sha256 = "a".repeat(64)),
  seal: (v) => (v.evidence_sha256 = "invalid"),
  source: (v) => (v.source.capture_id = "a".repeat(32)),
  source_sha: (v) => (v.source.source_sha256 = "a".repeat(64)),
  source_files: (v) => (v.source.files["3"].sha256 = "a".repeat(64)),
  source_extra: (v) => (v.source.authority = true),
  proof: (v) => (v.verified_proof.kind = "unverified"),
  proof_sha: (v) => (v.verified_proof.sha256 = "a".repeat(64)),
  proof_time: (v) => (v.verified_proof.time = "unknown"),
  empty: (v) => (v.selected = []),
  order: (v) => v.selected.reverse(),
  kind: (v) => (v.selected[0].kind = "boolean"),
  class: (v) => (v.selected[0].class_id = 530),
  property: (v) => (v.selected[0].property = 1),
  expected: (v) => (v.selected[0].expected.bits = "3f800000"),
  current: (v) => (v.selected[0].current.value.bits = "3f800000"),
  current_kind: (v) => (v.selected[0].current.kind = "enum"),
  current_hash: (v) => (v.selected[0].current.encoded_sha256 = "a".repeat(64)),
  missing: (v) => (v.selected[0].current = null),
  match: (v) => (v.selected[0].matches = false),
  schema: (v) => (v.selected[3].enum_schema_matches = false),
  boolean: (v) => (v.selected[2].current.value.value = 1),
  enum: (v) => (v.selected[3].current.value.value = true),
  nan: (v) => (v.selected[0].expected.bits = "7fc00000"),
  comparisons: (v) => (v.comparisons.selected_values_match = false),
  comparison_extra: (v) => (v.comparisons.authority = true),
  state: (v) => (v.state = "different"),
};
for (const [name, alter] of Object.entries(faults))
  test(`altered ${name} cannot publish a retained result comparison`, async () => {
    const f = fixtures.valid,
      v = structuredClone(f.report);
    alter(v);
    expect(
      await batchResultMatchEvidence(v, f.source, f.opened, f.receipt),
    ).toBe(false);
  });
test("foreign source/receipt and uncertain or no-dispatch parents do not qualify", async () => {
  const f = fixtures.valid;
  expect(
    await batchResultMatchEvidence(
      f.report,
      fixtures.selected.source,
      fixtures.selected.opened,
      f.receipt,
    ),
  ).toBe(false);
  expect(
    await batchResultMatchEvidence(
      f.report,
      f.source,
      f.opened,
      fixtures.recovery.receipt,
    ),
  ).toBe(false);
  expect(await batchResultMatchParent({ ...f.receipt, pending: true })).toBe(
    false,
  );
  const rejected = structuredClone(f.receipt);
  rejected.result.may_have_applied = false;
  expect(await batchResultMatchParent(rejected)).toBe(false);
});
