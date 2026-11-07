import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { sha256 } from "@noble/hashes/sha2.js";
import {
  batchEvidenceDocument,
  batchEvidenceLimit,
} from "../src/nativeDefaultBatchEvidenceContract";
import {
  alteredBatchEvidence,
  seedBatchEvidence,
} from "./native-default-batch-evidence-fixture";
type Data = Record<string, any>;
const fixtures: Data = {};
test.beforeAll(() => {
  for (const kind of [
    "valid",
    "historical",
    "recovery",
    "different",
    "routed",
    "same-capture",
    "reencoded",
  ])
    fixtures[kind] = seedBatchEvidence(
      mkdtempSync(join(tmpdir(), "native-batch-evidence-")),
      kind,
    );
});
const blob = (f: Data) =>
  new Blob([Buffer.from(f.bundle, "base64")], { type: "application/zip" });
for (const kind of [
  "valid",
  "historical",
  "recovery",
  "different",
  "routed",
  "same-capture",
  "reencoded",
])
  test(`actual ${kind} evidence bundle binds its checked archive to the comparison`, async () => {
    const f = fixtures[kind];
    expect(
      await batchEvidenceDocument(
        blob(f),
        JSON.stringify(f.metadata),
        f.report,
      ),
    ).not.toBeNull();
  });
const faults: Record<string, (v: Data) => void> = {
  profile: (v) => (v.profile = "unsupported/2"),
  scope: (v) => (v.scope = "Full controller backup"),
  extra: (v) => (v.plan_token = "invalid"),
  receipt: (v) => (v.receipt_id = "a".repeat(32)),
  comparison: (v) => (v.comparison_sha256 = "a".repeat(64)),
  state: (v) => (v.comparison_state = "different"),
  original: (v) => (v.original_backup_id = "a".repeat(32)),
  current: (v) => (v.current_capture_id = "a".repeat(32)),
  proof: (v) => (v.proof_sha256 = "a".repeat(64)),
  manifest: (v) => (v.manifest_sha256 = "a".repeat(64)),
  bundle: (v) => (v.bundle_sha256 = "a".repeat(64)),
  bytes: (v) => v.bytes++,
  count: (v) => v.capture_count++,
  members: (v) => v.member_count++,
  read_only: (v) => (v.read_only = false),
  actions: (v) => (v.field_actions = true),
  apply: (v) => (v.can_apply = true),
  live: (v) => (v.current_device_verified = true),
  credentials: (v) => (v.credentials_restored = true),
  reviews: (v) => (v.reviews_restored = true),
  controller_backup: (v) => (v.complete_controller_backup = true),
  journal: (v) => (v.complete_journal = true),
};
for (const [name, alter] of Object.entries(faults))
  test(`altered ${name} metadata cannot qualify an evidence download`, async () => {
    const f = fixtures.valid,
      v = structuredClone(f.metadata);
    alter(v);
    expect(
      await batchEvidenceDocument(blob(f), JSON.stringify(v), f.report),
    ).toBeNull();
  });
for (const fault of [
  "data",
  "crc",
  "directory",
  "boundary",
  "comment",
  "manifest",
])
  test(`rehashing damaged ${fault} ZIP bytes cannot bypass archive checks`, async () => {
    const f = fixtures.valid,
      bytes = Buffer.from(f.bundle, "base64"),
      v = structuredClone(f.metadata);
    if (fault === "data") bytes[50] ^= 1;
    else if (fault === "crc") bytes[14] ^= 1;
    else if (fault === "directory")
      bytes[bytes.readUInt32LE(bytes.length - 22 + 16)] ^= 1;
    else if (fault === "boundary") bytes[bytes.length - 22] ^= 1;
    else if (fault === "comment") bytes.writeUInt16LE(1, bytes.length - 2);
    else bytes.writeUInt32LE(0xffffffff, 18);
    v.bundle_sha256 = Array.from(sha256(bytes), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
    expect(
      await batchEvidenceDocument(
        new Blob([bytes], { type: "application/zip" }),
        JSON.stringify(v),
        f.report,
      ),
    ).toBeNull();
  });
test("foreign comparison, malformed descriptions, wrong MIME and oversized buffers refuse", async () => {
  const f = fixtures.valid;
  expect(
    await batchEvidenceDocument(
      blob(f),
      JSON.stringify(f.metadata),
      fixtures.recovery.report,
    ),
  ).toBeNull();
  expect(await batchEvidenceDocument(blob(f), null, f.report)).toBeNull();
  expect(await batchEvidenceDocument(blob(f), "invalid", f.report)).toBeNull();
  expect(
    await batchEvidenceDocument(blob(f), " ".repeat(4097), f.report),
  ).toBeNull();
  expect(
    await batchEvidenceDocument(
      new Blob([Buffer.from(f.bundle, "base64")], { type: "text/plain" }),
      JSON.stringify(f.metadata),
      f.report,
    ),
  ).toBeNull();
  expect(
    await batchEvidenceDocument(
      new Blob([new Uint8Array(batchEvidenceLimit + 1)], {
        type: "application/zip",
      }),
      JSON.stringify(f.metadata),
      f.report,
    ),
  ).toBeNull();
  const report = structuredClone(f.report);
  report.can_apply = true;
  expect(
    await batchEvidenceDocument(blob(f), JSON.stringify(f.metadata), report),
  ).toBeNull();
});

for (const fault of [
  "manifest-authority",
  "manifest-source",
  "manifest-snapshot",
  "manifest-member-hash",
  "manifest-member-bytes",
  "manifest-extra",
  "manifest-seal",
  "proof-body",
  "intent-body",
  "comparison-body",
  "member-path",
  "symlink",
])
  test(`rebuilt and rehashed ${fault} archive cannot replace selected evidence`, async () => {
    const f = fixtures.valid,
      altered = alteredBatchEvidence(f, fault);
    expect(
      await batchEvidenceDocument(
        blob(altered),
        JSON.stringify(altered.metadata),
        f.report,
      ),
    ).toBeNull();
  });
