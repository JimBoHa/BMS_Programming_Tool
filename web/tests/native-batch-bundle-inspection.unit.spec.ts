import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { checkedBatchBundle } from "../src/nativeBatchBundleInspectionContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import { seedBundleInspection } from "./native-batch-bundle-inspection-fixture";
const fixtures: Record<string, any> = {};
const kinds = [
  "valid",
  "historical",
  "recovery",
  "different",
  "routed",
  "same-capture",
  "reencoded",
];
test.beforeAll(() => {
  for (const kind of kinds)
    fixtures[kind] = seedBundleInspection(
      mkdtempSync(join(tmpdir(), "bms-bundle-inspection-")),
      kind,
    );
});
const file = (f: any, type = "application/zip") =>
  new Blob([Buffer.from(f.bundle, "base64")], { type });
for (const kind of kinds)
  test(`actual ${kind} bundle inspection binds original bytes and reconstruction`, async () => {
    const f = fixtures[kind];
    const checked = await checkedBatchBundle(f.inspection, file(f));
    expect(checked).not.toBeNull();
    expect(checked!.members.size).toBe(f.metadata.member_count);
  });
const mutations: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "future/2"),
  scope: (v) => (v.scope = "Current controller verified"),
  bytes: (v) => v.bundle_bytes++,
  digest: (v) => (v.bundle_sha256 = "f".repeat(64)),
  manifestHash: (v) => (v.manifest_sha256 = "f".repeat(64)),
  captureCount: (v) => (v.capture_count = 1),
  memberCount: (v) => v.members.pop(),
  memberName: (v) => (v.members[0].name = "../outside.zip"),
  memberSize: (v) => v.members[0].bytes++,
  memberHash: (v) => (v.members[0].sha256 = "f".repeat(64)),
  manifest: (v) => (v.manifest.current_capture_id = "f".repeat(32)),
  report: (v) => (v.comparison.state = "different"),
  values: (v) => (v.comparison.selected[0].expected.bits = "00000000"),
  source: (v) => (v.comparison.source.capture_id = "f".repeat(32)),
  proof: (v) => (v.comparison.verified_proof.sha256 = "f".repeat(64)),
  reconstructed: (v) => (v.native_result_reconstructed = false),
  consistency: (v) => (v.internal_consistency_verified = false),
  readOnly: (v) => (v.read_only = false),
  imported: (v) => (v.storage_imported = true),
  receipt: (v) => (v.receipt_restored = true),
  provenance: (v) => (v.vendor_provenance_verified = true),
  currentDevice: (v) => (v.current_device_verified = true),
  fieldActions: (v) => (v.field_actions = true),
  authority: (v) => (v.can_apply = true),
  reviews: (v) => (v.reviews_restored = true),
  credentials: (v) => (v.credentials_restored = true),
  extra: (v) => (v.plan_token = "untrusted"),
};
for (const [name, mutate] of Object.entries(mutations))
  test(`resealed ${name} response cannot qualify another bundle inspection`, async () => {
    const f = fixtures.valid,
      v = structuredClone(f.inspection);
    mutate(v);
    const { inspection_sha256: _, ...body } = v;
    v.inspection_sha256 = await connectionSeal(body);
    expect(await checkedBatchBundle(v, file(f))).toBeNull();
  });
test("a re-sealed comparison still cannot replace original bundled JSON", async () => {
  const f = fixtures.valid,
    v = structuredClone(f.inspection);
  v.comparison.selected[0].expected.bits = "00000000";
  const { evidence_sha256: _, ...body } = v.comparison;
  v.comparison.evidence_sha256 = await connectionSeal(body);
  const { inspection_sha256: __, ...outer } = v;
  v.inspection_sha256 = await connectionSeal(outer);
  expect(await checkedBatchBundle(v, file(f))).toBeNull();
});
test("OS file MIME and original bytes stay distinct", async () => {
  for (const mime of ["", "application/octet-stream", "application/zip"])
    expect(
      await checkedBatchBundle(
        fixtures.valid.inspection,
        file(fixtures.valid, mime),
      ),
    ).not.toBeNull();
});
test("another source and malformed or oversized files refuse", async () => {
  expect(
    await checkedBatchBundle(
      fixtures.valid.inspection,
      file(fixtures.recovery),
    ),
  ).toBeNull();
  expect(
    await checkedBatchBundle(fixtures.valid.inspection, new Blob(["bad"])),
  ).toBeNull();
  expect(
    await checkedBatchBundle(
      fixtures.valid.inspection,
      new Blob([new Uint8Array(20 * 1024 * 1024 + 1)]),
    ),
  ).toBeNull();
});
