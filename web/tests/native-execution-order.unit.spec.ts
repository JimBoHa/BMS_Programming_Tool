import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { orderFixture } from "./native-execution-order-fixture";
import { connectionSeal } from "../src/nativeConnectionContract";
import {
  nativeOrderSource,
  nativeOrderReview,
  nativeOrderExport,
  nativeOrderRequest,
  nativeOrderDraftKey,
  nativeOrderDraft,
  rememberNativeOrder,
  nativeOrderAllowed,
} from "../src/nativeExecutionOrderContract";
import type { WireCopyDrafts } from "../src/nativeWireDrafts";
let original: any;
test.beforeAll(() => {
  original = orderFixture(
    mkdtempSync(join(tmpdir(), "native-order-contract-")),
  );
});
async function seal(x: any, key: string) {
  const { [key]: _, ...body } = x;
  return { ...body, [key]: await connectionSeal(body) };
}
for (const kind of [
  "normal",
  "raw",
  "activity",
  "empty",
  "backward",
  "serial",
  "noop",
])
  test(`actual ${kind} saved order proof binds source/review/download`, async () => {
    const f = orderFixture(
      mkdtempSync(join(tmpdir(), "native-order-contract-")),
      kind,
    );
    expect(await nativeOrderSource(f.source, f.archive, f.record)).toBe(true);
    expect(
      nativeOrderRequest(
        f.archive,
        f.record,
        f.source,
        f.request.proposed_order,
      ),
    ).toEqual(f.request);
    expect(
      await nativeOrderReview(
        f.review,
        f.archive,
        f.record,
        f.source,
        f.request,
      ),
    ).toBe(true);
    expect(
      await nativeOrderExport(
        {
          blob: new Blob([Buffer.from(f.output, "base64")]),
          headers: new Headers(f.headers),
        },
        f.review,
      ),
    ).toBe(true);
  });
const sources: Record<string, (s: any) => void> = {
  extra: (s) => (s.plan_token = "invalid"),
  capture: (s) => (s.capture_id = "a".repeat(32)),
  snapshot: (s) => (s.snapshot_sha256 = "a".repeat(64)),
  source: (s) => (s.source_sha256 = "a".repeat(64)),
  target: (s) => (s.target.address = "99"),
  files: (s) => s.files["12"].bytes++,
  record: (s) => (s.archive_record_sha256 = "a".repeat(64)),
  vendor: (s) => (s.identity["vendor-identifier"] = 999),
  authority: (s) => (s.can_apply = true),
  merged: (s) => (s.saved_settings_merged = false),
  phase: (s) => (s.selection.edge_relationships[0].relationship = "after"),
  slot: (s) =>
    (s.selection.slots[1].payload_offset = s.selection.slots[0].payload_offset),
  order: (s) => (s.selection.original_order = [0, 0, 2, 3]),
  member: (s) => (s.selection.members[0].ref = "different/2_10"),
  width: (s) => (s.selection.slots[0].payload_bytes = 0),
  selection: (s) => (s.selection.selection_sha256 = "a".repeat(64)),
};
for (const [name, change] of Object.entries(sources))
  test(`source rejects resealed ${name}`, async () => {
    const s = structuredClone(original.source);
    change(s);
    if (name !== "selection")
      s.selection = await seal(s.selection, "selection_sha256");
    expect(
      await nativeOrderSource(
        await seal(s, "source_report_sha256"),
        original.archive,
        original.record,
      ),
    ).toBe(false);
  });
const reviews: Record<string, (r: any) => void> = {
  extra: (r) => (r.plan_token = "invalid"),
  request: (r) => (r.request.proposed_order = [0, 1, 2, 3]),
  files: (r) => (r.compilation.files["12"].sha256 = "a".repeat(64)),
  merge: (r) => r.compilation.parameter_merge.matched_parameters++,
  source: (r) => (r.source.target.address = "99"),
  patch: (r) => (r.compilation.order_edit.patches[0].new_index = 2),
  patch_missing: (r) => r.compilation.order_edit.patches.pop(),
  width: (r) => (r.compilation.order_edit.patches[0].payload_bytes = 4),
  unchanged: (r) => (r.compilation.other_merged_bytes_preserved = false),
  authority: (r) => (r.field_transfer_enabled = true),
  compiled: (r) => (r.compilation.compiled_sha256 = "a".repeat(64)),
  selection: (r) =>
    (r.compilation.order_edit.selection.property_sha256 = "a".repeat(64)),
  native: (r) =>
    (r.compilation.order_edit.output_native_sha256 = "a".repeat(64)),
};
for (const [name, change] of Object.entries(reviews))
  test(`review rejects resealed ${name}`, async () => {
    const r = structuredClone(original.review);
    change(r);
    r.compilation.order_edit = await seal(
      r.compilation.order_edit,
      "compilation_sha256",
    );
    r.compilation = await seal(r.compilation, "compilation_sha256");
    expect(
      await nativeOrderReview(
        await seal(r, "review_sha256"),
        original.archive,
        original.record,
        original.source,
        original.request,
      ),
    ).toBe(false);
  });
for (const key of [
  "Content-Type",
  "X-Studio-Artifact-Sha256",
  "X-Studio-Source-Sha256",
  "X-Studio-Snapshot-Sha256",
  "X-Studio-Compilation-Sha256",
  "X-Studio-Review-Sha256",
])
  test(`wrong ${key} header refuses native export`, async () => {
    const headers = new Headers(original.headers);
    headers.set(key, "wrong");
    expect(
      await nativeOrderExport(
        { blob: new Blob([Buffer.from(original.output, "base64")]), headers },
        original.review,
      ),
    ).toBe(false);
  });
test("changed native bytes do not qualify under original headers", async () => {
  const b = Buffer.from(original.output, "base64");
  b[15] ^= 1;
  expect(
    await nativeOrderExport(
      { blob: new Blob([b]), headers: new Headers(original.headers) },
      original.review,
    ),
  ).toBe(false);
});
test("bounded graph drafts retain raw proposals without widening256slots", () => {
  const drafts: WireCopyDrafts = new Map();
  for (let i = 0; i < 256; i++) drafts.set(String(i), "existing");
  const s = original.source.selection,
    key = nativeOrderDraftKey(original.archive, original.record),
    before = JSON.stringify([...drafts]);
  expect(() => rememberNativeOrder(drafts, key, s, [1, 0, 2, 3])).toThrow(
    "256",
  );
  expect(JSON.stringify([...drafts])).toBe(before);
  drafts.delete("0");
  rememberNativeOrder(drafts, key, s, [1, 0, 2, 3]);
  expect(drafts.size).toBe(256);
  expect(nativeOrderDraft(drafts, key, s).proposed).toEqual([1, 0, 2, 3]);
  expect(nativeOrderAllowed(s, [2, 1, 0, 3])).toBe(false);
  expect(() => rememberNativeOrder(drafts, key, s, [2, 1, 0, 3])).toThrow(
    "wire relationship",
  );
  rememberNativeOrder(drafts, key, s, [0, 1, 2, 3]);
  expect(drafts.size).toBe(255);
  drafts.set(key, "opaque unsupported draft");
  expect(() => nativeOrderDraft(drafts, key, s)).toThrow(
    "Discard it explicitly",
  );
  expect(drafts.get(key)).toBe("opaque unsupported draft");
});
