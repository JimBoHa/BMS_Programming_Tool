import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedDefaultBatch } from "./native-default-batch-fixture";
import {
  nativeBatchDraftBytes,
  nativeBatchDraftDocument,
  parseNativeBatchDraft,
} from "../src/nativeBatchDraftFile";

let data: any, large: any, raw: string;
const entries: Record<string, string> = {
  "controller/575_1.2_12": "",
  "controller/575_1.2_13": "-0",
  "controller/retained-boolean": "false",
  "controller/enum-1": "1e-",
  "controller/saved-enum": "  invalid Ω  ",
};
test.beforeAll(async () => {
  data = seedDefaultBatch(
    mkdtempSync(path.join(tmpdir(), "bms-batch-draft-contract-")),
  );
  large = seedDefaultBatch(
    mkdtempSync(path.join(tmpdir(), "bms-batch-draft-limit-")),
    12,
  );
  raw = await nativeBatchDraftDocument(
    data.signal,
    data.source,
    entries,
  ).text();
});
test("all typed unfinished raw strings round trip without native review or mutation", async () => {
  const before = JSON.stringify(data),
    recovered = parseNativeBatchDraft(raw, data.signal, data.source);
  expect(recovered).toEqual(entries);
  expect(Object.getPrototypeOf(recovered)).toBeNull();
  expect(
    await nativeBatchDraftDocument(data.signal, data.source, recovered).text(),
  ).toBe(raw);
  expect(JSON.stringify(data)).toBe(before);
  const value = JSON.parse(raw);
  expect(value.field_authority).toBe(false);
  expect(value.native_review_created).toBe(false);
  expect(value.current_identity_verified).toBe(false);
  expect(value.controller_queries).toBe(false);
  expect(value.buffers).toHaveLength(5);
  expect(value.source.files).toEqual(data.source.files);
});
for (const text of ["", ".", "+", "12.", " 1e- ", "NaN", "-0", "Ω".repeat(128)])
  test(`Real and Enum raw text stays literal ${JSON.stringify(text)}`, async () => {
    const values = { "controller/575_1.2_12": text, "controller/enum-1": text };
    const file = await nativeBatchDraftDocument(
      data.signal,
      data.source,
      values,
    ).text();
    expect(parseNativeBatchDraft(file, data.signal, data.source)).toEqual(
      values,
    );
  });
const mutations: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "different"),
  authority: (v) => (v.field_authority = true),
  queries: (v) => (v.controller_queries = true),
  review: (v) => (v.native_review_created = true),
  liveIdentity: (v) => (v.current_identity_verified = true),
  extra: (v) => (v.token = "forbidden"),
  capture: (v) => (v.source.capture_id = "0".repeat(32)),
  snapshot: (v) => (v.source.snapshot_sha256 = "0".repeat(64)),
  time: (v) => (v.source.captured_at = "2020-01-01T00:00:00+00:00"),
  device: (v) => (v.source.target.device = "device,9999"),
  address: (v) => (v.source.target.address = "127.0.0.1:49999"),
  router: (v) => (v.source.target.router = "127.0.0.1:49999"),
  network: (v) => (v.source.target.dnet = 1234),
  identity: (v) => (v.source.identity["model-name"] = "Substituted"),
  file: (v) => (v.source.files["12"].sha256 = "0".repeat(64)),
  bytes: (v) => (v.source.files["11"].bytes += 1),
  native: (v) => (v.source.effective_native_sha256 = "0".repeat(64)),
  source: (v) => (v.source.source_sha256 = "0".repeat(64)),
  merge: (v) => (v.source.effective_sha256 = "0".repeat(64)),
  sourceExtra: (v) => (v.source.current_identity_verified = true),
  reference: (v) => (v.buffers[0].field.record_ref = "controller/absent"),
  class: (v) => (v.buffers[0].field.class_id = 530),
  property: (v) => (v.buffers[0].field.property = 85),
  encoding: (v) => (v.buffers[0].field.encoded_sha256 = "0".repeat(64)),
  bits: (v) => (v.buffers[0].field.effective_bits = "00000000"),
  code: (v) => (v.buffers[3].field.effective_value += 1),
  capacity: (v) => (v.buffers[4].field.maximum_code = 4294967295),
  fieldExtra: (v) => (v.buffers[0].field.can_apply = true),
  rowExtra: (v) => (v.buffers[0].review_sha256 = "0".repeat(64)),
  duplicate: (v) => v.buffers.push(v.buffers[0]),
  empty: (v) => (v.buffers = []),
  long: (v) => (v.buffers[0].value_text = "a".repeat(129)),
  number: (v) => (v.buffers[0].value_text = 1),
  unicode: (v) => (v.buffers[0].value_text = "\ud800"),
  boolean: (v) => (v.buffers[2].value_text = "maybe"),
};
for (const [name, mutate] of Object.entries(mutations))
  test(`changed unfinished batch ${name} is refused without modifying the source`, () => {
    const value = JSON.parse(raw),
      before = JSON.stringify(data);
    mutate(value);
    expect(() =>
      parseNativeBatchDraft(JSON.stringify(value), data.signal, data.source),
    ).toThrow();
    expect(JSON.stringify(data)).toBe(before);
  });
for (const fault of [
  "duplicate top",
  "duplicate nested",
  "size",
  "empty",
  "trailing",
  "depth",
])
  test(`malformed raw batch JSON ${fault} is refused`, () => {
    let text = raw;
    if (fault === "duplicate top")
      text = text.replace(
        '"field_authority": false',
        '"field_authority": false, "field_authority": false',
      );
    if (fault === "duplicate nested")
      text = text.replace('"kind": "real"', '"kind": "real", "kind": "real"');
    if (fault === "size") text = " ".repeat(nativeBatchDraftBytes) + text;
    if (fault === "empty") text = "";
    if (fault === "trailing") text += "{}";
    if (fault === "depth") text = "[".repeat(65) + text + "]".repeat(65);
    expect(() =>
      parseNativeBatchDraft(text, data.signal, data.source),
    ).toThrow();
  });
test("sixteen actual fields fit, but a seventeenth or empty selection does not", async () => {
  const values = Object.fromEntries(
    large.source.fields
      .slice(0, 16)
      .map((r: any) => [r.field.ref, r.kind === "boolean" ? "false" : "12."]),
  );
  const text = await nativeBatchDraftDocument(
    large.signal,
    large.source,
    values,
  ).text();
  expect(parseNativeBatchDraft(text, large.signal, large.source)).toEqual(
    values,
  );
  values[large.source.fields[16].field.ref] = "12.";
  expect(() =>
    nativeBatchDraftDocument(large.signal, large.source, values),
  ).toThrow();
  expect(() =>
    nativeBatchDraftDocument(data.signal, data.source, {}),
  ).toThrow();
});
test("file creation requires the actual read-only batch envelope and no extra selection", () => {
  const altered = structuredClone(data.source);
  altered.controller_write = true;
  expect(() =>
    nativeBatchDraftDocument(data.signal, altered, entries),
  ).toThrow();
  expect(() =>
    nativeBatchDraftDocument(data.signal, data.source, { absent: "12." }),
  ).toThrow();
});
