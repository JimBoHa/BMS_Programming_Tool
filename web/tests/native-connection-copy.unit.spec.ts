import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  connectionSource,
  connectionReview,
  connectionExport,
} from "../src/nativeConnectionContract";
import { seed } from "./native-connection-fixture";

let fixture: any;
function data() {
  fixture ??= seed(mkdtempSync(path.join(tmpdir(), "bms-connection-unit-")));
  return structuredClone(fixture);
}
test("actual native continuation and appended connection proof pass independent client admission", async () => {
  const f = data();
  expect(connectionSource(f.source, f.archive, f.request)).toBe(true);
  expect(
    await connectionReview(f.review, f.archive, f.proposal, f.source.selection),
  ).toBe(true);
});
for (const [name, change] of Object.entries({
  snapshot: (s: any) => (s.snapshot_sha256 = "0".repeat(64)),
  source: (s: any) => (s.source_sha256 = "0".repeat(64)),
  saved: (s: any) => s.files["12"].bytes++,
  route: (s: any) => (s.target.address = "another-address"),
  authority: (s: any) => (s.can_apply = true),
  settings: (s: any) => (s.saved_settings_merged = true),
  prototype: (s: any) => s.selection.prototype.old[0]++,
  sourcePin: (s: any) => s.selection.sources[0].index++,
  inputOwner: (s: any) => {
    s.selection.targets[0].ref = s.selection.prototype.target_ref;
  },
  duplicate: (s: any) => s.selection.targets.push(s.selection.targets[0]),
  continuation: (s: any) =>
    (s.selection.continuation_metadata = "not-recorded"),
  count: (s: any) => s.selection.connection_count++,
}))
  test(`source admission refuses substituted ${name}`, () => {
    const f = data();
    change(f.source);
    expect(connectionSource(f.source, f.archive, f.request)).toBe(false);
  });
for (const [name, change] of Object.entries({
  destination: (v: any) => (v.request.target_ref = "another-target"),
  prototype: (v: any) => v.compilation.prototype_old[1]++,
  newTuple: (v: any) => v.compilation.new[2]++,
  continuation: (v: any) => (v.compilation.metadata_property_sha256 = null),
  source: (v: any) => (v.compilation.source_sha256 = "0".repeat(64)),
  count: (v: any) => v.compilation.connection_count_after++,
  preservation: (v: any) =>
    (v.compilation.other_expanded_bytes_preserved = false),
  readback: (v: any) =>
    (v.compilation.native_structure_readback_verified = false),
  authority: (v: any) => (v.compilation.field_transfer_enabled = true),
  seal: (v: any) => (v.compilation.compilation_sha256 = "0".repeat(64)),
  encoding: (v: any) => (v.compilation.new_encoding_hex = ""),
}))
  test(`review admission refuses substituted ${name}`, async () => {
    const f = data();
    change(f.review);
    expect(
      await connectionReview(
        f.review,
        f.archive,
        f.proposal,
        f.source.selection,
      ),
    ).toBe(false);
  });
test("export requires actual artifact bytes and all five independent proof headers", async () => {
  const f = data(),
    blob = new Blob(["authored output"]);
  const digest = Buffer.from(
    await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
  ).toString("hex");
  const review = { ...f.review, output_sha256: digest };
  const headers = new Headers({
    "X-Studio-Artifact-Sha256": digest,
    "X-Studio-Review-Sha256": review.review_sha256,
    "X-Studio-Snapshot-Sha256": review.snapshot_sha256,
    "X-Studio-Source-Sha256": review.source_sha256,
    "X-Studio-Compilation-Sha256": review.compilation.compilation_sha256,
  });
  expect(await connectionExport({ blob, headers }, review)).toBe(true);
  for (const key of headers.keys()) {
    const missing = new Headers(headers);
    missing.delete(key);
    expect(await connectionExport({ blob, headers: missing }, review)).toBe(
      false,
    );
  }
  expect(
    await connectionExport(
      { blob: new Blob(["different output"]), headers },
      review,
    ),
  ).toBe(false);
});
