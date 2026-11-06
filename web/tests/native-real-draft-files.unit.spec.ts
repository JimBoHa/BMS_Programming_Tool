import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedRealDrafts, first, second } from "./native-real-draft-fixture";
import {
  nativeRealDraftDocument,
  parseNativeRealDraft,
  nativeRealDraftBytes,
} from "../src/nativeRealDraftFile";
let data: any, source: any, field: any, original: string;
test.beforeAll(async () => {
  data = seedRealDrafts(
    mkdtempSync(path.join(tmpdir(), "bms-native-real-draft-")),
  );
  source = data.a.source;
  field = source.fields.find((f: any) => f.ref === first);
  original = await nativeRealDraftDocument(source, field, "12.").text();
});
for (const raw of [
  "",
  "12.",
  "1e",
  "-0",
  "NaN",
  " 0.1 ",
  "未完成",
  "😀",
  "1".repeat(128),
])
  test(`unfinished Real text ${JSON.stringify(raw)} survives without numeric conversion`, async () => {
    const before = structuredClone(source),
      blob = nativeRealDraftDocument(source, field, raw);
    expect(blob.size).toBeLessThanOrEqual(nativeRealDraftBytes);
    expect(parseNativeRealDraft(await blob.text(), source, field)).toBe(raw);
    expect(source).toEqual(before);
    const value = JSON.parse(await blob.text());
    expect(value.field_authority).toBe(false);
    expect(value.native_review_created).toBe(false);
  });
const changes: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "native-effective-signal-default-compiler/1"),
  authority: (v) => (v.field_authority = true),
  queries: (v) => (v.controller_queries = true),
  review: (v) => (v.native_review_created = true),
  identity: (v) => (v.current_identity_verified = true),
  token: (v) => (v.token = "not-a-restored-plan"),
  reviewSeal: (v) => (v.review_sha256 = "0".repeat(64)),
  bufferAuthority: (v) => (v.buffer.compilation = {}),
  sourceAuthority: (v) => (v.source.can_apply = true),
  capture: (v) => (v.source.capture_id = "0".repeat(32)),
  snapshot: (v) => (v.source.snapshot_sha256 = "0".repeat(64)),
  time: (v) => (v.source.captured_at = "2020-01-01T00:00:00Z"),
  address: (v) => (v.source.target.address = "127.0.0.1:49999"),
  router: (v) => (v.source.target.router = "127.0.0.1:49998"),
  network: (v) => (v.source.target.dnet = 77),
  nonfiniteNetwork: (v) => (v.source.target.dnet = Infinity),
  booleanNetwork: (v) => (v.source.target.dnet = true),
  extraTarget: (v) => (v.source.target.token = "unexpected"),
  device: (v) => (v.source.device = "device,9999"),
  field: (v) => (v.source.record_ref = second),
  class: (v) => (v.source.class_id = 551),
  property: (v) => (v.source.property = 85),
  encoding: (v) => (v.source.encoded_sha256 = "0".repeat(64)),
  bits: (v) => (v.source.effective_bits = "00000000"),
  valueType: (v) => (v.buffer.value_text = 12),
  valueLimit: (v) => (v.buffer.value_text = "x".repeat(129)),
  unicode: (v) => (v.buffer.value_text = "\ud800"),
};
for (const [name, change] of Object.entries(changes))
  test(`unfinished Real file refuses substituted ${name}`, () => {
    const value = JSON.parse(original);
    change(value);
    // A nonfinite JSON number is tested as a literal token; JSON.stringify
    // would otherwise replace it with null and erase the authored fault.
    const raw =
      name === "nonfiniteNetwork"
        ? original.replace('"dnet": null', '"dnet": 1e999')
        : JSON.stringify(value);
    expect(() => parseNativeRealDraft(raw, source, field)).toThrow();
  });
test("an actual different source or field cannot adopt raw text", () => {
  expect(() =>
    parseNativeRealDraft(
      original,
      data.b.source,
      data.b.source.fields.find((f: any) => f.ref === first),
    ),
  ).toThrow();
  expect(() =>
    parseNativeRealDraft(
      original,
      source,
      source.fields.find((f: any) => f.ref === second),
    ),
  ).toThrow();
});
test("raw JSON duplicate keys and byte overflow are refused", () => {
  expect(() =>
    parseNativeRealDraft(
      original.replace(
        '"field_authority": false',
        '"field_authority": false, "field_authority": false',
      ),
      source,
      field,
    ),
  ).toThrow(/duplicate/i);
  expect(() =>
    parseNativeRealDraft(
      " ".repeat(nativeRealDraftBytes) + original,
      source,
      field,
    ),
  ).toThrow(/16 KiB/);
});
test("export requires the selected field in the actual read-only source", () => {
  expect(() =>
    nativeRealDraftDocument(
      { ...source, controller_write: true },
      field,
      "12.",
    ),
  ).toThrow();
  expect(() =>
    nativeRealDraftDocument(
      source,
      { ...field, encoded_sha256: "0".repeat(64) },
      "12.",
    ),
  ).toThrow();
});
