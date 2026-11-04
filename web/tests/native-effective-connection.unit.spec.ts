import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-effective-connection-fixture";
import {
  effectiveConnectionSource,
  effectiveConnectionReview,
} from "../src/nativeEffectiveConnectionContract";
import {
  connectionSource,
  connectionReview,
} from "../src/nativeConnectionContract";

let fixture: any;
function data() {
  fixture ??= seed(
    mkdtempSync(path.join(tmpdir(), "bms-effective-connection-unit-")),
  );
  return structuredClone(fixture);
}
test("saved-effective merge and nested connection proofs pass only the explicit effective contract", async () => {
  const f = data();
  expect(effectiveConnectionSource(f.source, f.archive, f.request)).toBe(true);
  expect(
    await effectiveConnectionReview(f.review, f.archive, f.proposal, f.source),
  ).toBe(true);
  expect(connectionSource(f.source, f.archive, f.request)).toBe(false);
  expect(
    await connectionReview(f.review, f.archive, f.proposal, f.source.selection),
  ).toBe(false);
});
for (const [name, change] of Object.entries({
  snapshot: (v: any) => (v.snapshot_sha256 = "0".repeat(64)),
  original: (v: any) => (v.source_sha256 = "0".repeat(64)),
  record: (v: any) => (v.archive_record_sha256 = "0".repeat(64)),
  effective: (v: any) => (v.effective_sha256 = "0".repeat(64)),
  static: (v: any) => (v.parameter_merge.static_sha256 = "0".repeat(64)),
  dynamic: (v: any) => (v.parameter_merge.dynamic_sha256 = "0".repeat(64)),
  mutable: (v: any) => (v.source_immutable = false),
  currentIdentity: (v: any) => (v.current_identity_verified = true),
  field: (v: any) => (v.field_transfer_enabled = true),
  unmerged: (v: any) => (v.saved_settings_merged = false),
  prototype: (v: any) => v.selection.prototype.old[2]++,
  candidate: (v: any) => (v.selection.targets[0].index = 0),
}))
  test(`effective source refuses substituted ${name}`, () => {
    const f = data();
    change(f.source);
    expect(effectiveConnectionSource(f.source, f.archive, f.request)).toBe(
      false,
    );
  });
for (const [name, change] of Object.entries({
  original: (v: any) => (v.compilation.archive_sha256 = "0".repeat(64)),
  effective: (v: any) => (v.compilation.effective_sha256 = "0".repeat(64)),
  request: (v: any) => (v.request.effective_record_sha256 = "0".repeat(64)),
  saved: (v: any) => v.compilation.parameter_merge.matched_parameters++,
  files: (v: any) => v.compilation.files["12"].bytes++,
  input: (v: any) => v.compilation.connection_edit.new[2]++,
  innerSeal: (v: any) =>
    (v.compilation.connection_edit.compilation_sha256 = "0".repeat(64)),
  outerSeal: (v: any) => (v.compilation.compilation_sha256 = "0".repeat(64)),
  preservation: (v: any) =>
    (v.compilation.other_merged_bytes_preserved = false),
  merge: (v: any) => (v.compilation.saved_settings_merged = false),
  field: (v: any) => (v.compilation.field_transfer_enabled = true),
  native: (v: any) => (v.compilation.compiled_native_sha256 = "0".repeat(64)),
}))
  test(`effective review refuses substituted ${name}`, async () => {
    const f = data();
    change(f.review);
    expect(
      await effectiveConnectionReview(
        f.review,
        f.archive,
        f.proposal,
        f.source,
      ),
    ).toBe(false);
  });
