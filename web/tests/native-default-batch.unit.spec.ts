import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedDefaultBatch } from "./native-default-batch-fixture";
import {
  defaultBatchSource,
  defaultBatchReview,
  defaultBatchRequest,
} from "../src/nativeDefaultBatchContract";
let data: any;
test.beforeAll(() => {
  data = seedDefaultBatch(
    mkdtempSync(path.join(tmpdir(), "bms-native-default-batch-")),
  );
});
test("actual mixed source and both composition chains qualify without field authority", () => {
  expect(defaultBatchSource(data.source, data.signal)).toBe(true);
  expect(defaultBatchReview(data.review, data.source, data.body)).toBe(true);
  const drafts = Object.fromEntries(
    data.body.changes.map((c: any) => [
      c.record_ref,
      c.kind === "real" ? c.value_text : String(c.value),
    ]),
  );
  expect(defaultBatchRequest(data.signal, data.source, drafts)).toEqual(
    data.body,
  );
  expect(data.review.can_apply).toBe(false);
  expect(data.review.field_transfer_enabled).toBe(false);
});
const sourceFaults: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "native-effective-signal-default-compiler/1"),
  capture: (v) => (v.capture_id = "0".repeat(32)),
  snapshot: (v) => (v.snapshot_sha256 = "0".repeat(64)),
  route: (v) => (v.target.router = "127.0.0.1:49999"),
  file: (v) => (v.files["12"].sha256 = "0".repeat(64)),
  merge: (v) => (v.parameter_merge.output_sha256 = "0".repeat(64)),
  authority: (v) => (v.can_apply = true),
  token: (v) => (v.token = "forbidden"),
  row: (v) => (v.fields[0].kind = "enum"),
  class: (v) => (v.fields[0].field.class_id = 551),
  bits: (v) => (v.fields[0].field.effective_bits = "7fc00000"),
  duplicate: (v) => v.fields.push(v.fields[0]),
  limit: (v) => (v.edit_limit = 32),
};
for (const [name, change] of Object.entries(sourceFaults))
  test(`substituted batch source ${name} is refused`, () => {
    const value = structuredClone(data.source);
    change(value);
    expect(defaultBatchSource(value, data.signal)).toBe(false);
  });
const reviewFaults: Record<string, (v: any) => void> = {
  nestedToken: (v) => (v.compilation.token = "forbidden"),
  selectedAuthority: (v) => (v.compilation.selected[0].can_apply = true),
  independentAuthority: (v) =>
    (v.compilation.independent[0].compilation.field_actions = true),
  token: (v) => (v.token = "forbidden"),
  source: (v) => (v.source_sha256 = "0".repeat(64)),
  seal: (v) => (v.review_sha256 = "bad"),
  authority: (v) => (v.can_apply = true),
  target: (v) => (v.target.dnet = 71),
  request: (v) => (v.request.changes[0].value_text = "99"),
  count: (v) => (v.compilation.edit_count = 6),
  changed: (v) => (v.compilation.changed_count = 0),
  order: (v) => (v.compilation.both_orders_identical = false),
  preserve: (v) => (v.compilation.other_merged_bytes_preserved = false),
  output: (v) => (v.compilation.compiled_sha256 = "0".repeat(64)),
  native: (v) => (v.compilation.effective_native_sha256 = "0".repeat(64)),
  selected: (v) => (v.compilation.selected[0].record_ref = "unknown"),
  byte: (v) => (v.compilation.selected[0].after_encoding_hex = "44000000002f"),
  selectedCount: (v) => v.compilation.selected.pop(),
  independentProfile: (v) =>
    (v.compilation.independent[0].compilation.profile = "substituted"),
  independentMerge: (v) =>
    (v.compilation.independent[0].compilation.parameter_merge.static_sha256 =
      "0".repeat(64)),
  independentValue: (v) =>
    (v.compilation.independent[0].compilation.selected_edit.after_bits =
      "00000000"),
  boolean: (v) =>
    (v.compilation.independent.find(
      (r: any) => r.kind === "boolean",
    ).compilation.selected_edit.after_value = true),
  enumCapacity: (v) =>
    (v.compilation.independent
      .filter((r: any) => r.kind === "enum")
      .at(-1).compilation.maximum_code = 4294967295),
  enumSemantics: (v) => (v.compilation.enum_semantics_verified = true),
  forward: (v) =>
    (v.compilation.forward[0].edit.source_sha256 = "0".repeat(64)),
  reverse: (v) => v.compilation.reverse.reverse(),
  final: (v) =>
    (v.compilation.reverse.at(-1).edit.output_sha256 = "0".repeat(64)),
};
for (const [name, change] of Object.entries(reviewFaults))
  test(`substituted batch review ${name} is refused`, () => {
    const value = structuredClone(data.review);
    change(value);
    expect(defaultBatchReview(value, data.source, data.body)).toBe(false);
  });
for (const [kind, text] of [
  ["real", "1e-999"],
  ["real", "1e999"],
  ["real", "12x"],
  ["boolean", "1"],
  ["enum", "12."],
  ["enum", "4294967296"],
])
  test(`raw ${kind} proposal ${text} cannot grant batch review`, () => {
    const row = data.source.fields.find((r: any) => r.kind === kind);
    expect(() =>
      defaultBatchRequest(data.signal, data.source, { [row.field.ref]: text }),
    ).toThrow();
  });
test("raw batch draft bounds refuse empty and more than16 selections", () => {
  expect(() => defaultBatchRequest(data.signal, data.source, {})).toThrow();
  expect(() =>
    defaultBatchRequest(
      data.signal,
      data.source,
      Object.fromEntries(
        Array.from({ length: 17 }, (_, i) => ["field" + i, "0"]),
      ),
    ),
  ).toThrow();
});
