import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { seedOrderResultMatch } from "./native-order-result-match-fixture";
import {
  orderMatchParent,
  orderResultMatchEvidence,
} from "../src/nativeOrderResultMatchContract";
import { connectionSeal } from "../src/nativeConnectionContract";
const fixtures: Record<string, any> = {};
const kinds = ["match", "historical", "saved", "order", "routed", "reencoded"];
test.beforeAll(() => {
  for (const kind of kinds)
    fixtures[kind] = seedOrderResultMatch(
      mkdtempSync(join(tmpdir(), "bms-order-result-match-")),
      kind,
    );
});
for (const kind of kinds)
  test(`actual ${kind} original and retained order evidence stays historical`, async () => {
    const f = fixtures[kind];
    expect(await orderMatchParent(f.receipt)).toBe(true);
    expect(
      await orderResultMatchEvidence(f.report, f.source, f.opened, f.receipt),
    ).toBe(true);
  });
const faults: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "future/2"),
  scope: (v) => (v.scope = "Current controller verified"),
  receipt: (v) => (v.receipt_id = "f".repeat(32)),
  intent: (v) => (v.intent_sha256 = "f".repeat(64)),
  backup: (v) => (v.original_backup_id = "f".repeat(32)),
  source: (v) => (v.source.capture_id = "f".repeat(32)),
  snapshot: (v) => (v.source.snapshot_sha256 = "f".repeat(64)),
  route: (v) => (v.current_target.address = "3001:99"),
  identity: (v) => (v.recorded_identity["object-name"] = "Other"),
  diagram: (v) => (v.diagram_ref = "other/diagram"),
  expectedNative: (v) => (v.expected_native_sha256 = "f".repeat(64)),
  archive: (v) => (v.archive_selection.source_sha256 = "f".repeat(64)),
  expectedOrder: (v) => (v.expected_selection.original_order = [0, 1, 2, 3]),
  members: (v) => (v.expected_selection.members[0].class_id = 1),
  width: (v) => (v.expected_selection.slots[0].payload_bytes = 4),
  phase: (v) => (v.expected_selection.edge_relationships[0].phase = "other"),
  state: (v) => (v.state = "different"),
  comparison: (v) => (v.comparisons.selected_order_matches = false),
  proof: (v) => (v.verified_proof.sha256 = "f".repeat(64)),
  proofKind: (v) => (v.verified_proof.kind = "readback-event"),
  live: (v) => (v.current_device_verified = true),
  authority: (v) => (v.can_apply = true),
  queries: (v) => (v.controller_queries = true),
  readonly: (v) => (v.read_only = false),
  extra: (v) => (v.token = "untrusted"),
};
for (const [name, mutate] of Object.entries(faults))
  test(`resealed changed ${name} cannot qualify an order comparison`, async () => {
    const f = fixtures.match,
      v = structuredClone(f.report);
    mutate(v);
    const { evidence_sha256, ...body } = v;
    v.evidence_sha256 = await connectionSeal(body);
    expect(
      await orderResultMatchEvidence(v, f.source, f.opened, f.receipt),
    ).toBe(false);
  });
test("original proof, source replacement and invalid pending states cannot be combined", async () => {
  const f = fixtures.match;
  expect(
    await orderResultMatchEvidence(
      f.report,
      fixtures.saved.source,
      f.opened,
      f.receipt,
    ),
  ).toBe(false);
  for (const changed of [
    { ...f.receipt, pending: true },
    {
      ...f.receipt,
      events: [],
      result: { ...f.receipt.result, status: "unknown" },
    },
  ])
    expect(await orderMatchParent(changed)).toBe(false);
  const historical = fixtures.historical;
  expect(historical.receipt.latest_readback.status).toBe("unknown");
  expect(await orderMatchParent(historical.receipt)).toBe(true);
});
