import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-effective-enum-fixture";
import {
  effectiveEnumSource,
  checkEffectiveEnumReview,
} from "../src/nativeEnumEffective";

let fixture: any;
function data() {
  fixture ??= seed(
    mkdtempSync(path.join(tmpdir(), "bms-effective-enum-unit-")),
  );
  const f = structuredClone(fixture),
    s = f.source,
    field = s.fields[0];
  return {
    ...f,
    archive: {
      capture_id: s.capture_id,
      snapshot_sha256: s.snapshot_sha256,
      sha256: s.source_sha256,
      files: s.files,
      target: s.target,
    },
    field: {
      ref: field.ref,
      class_id: field.class_id,
      encoded_sha256: "a".repeat(64),
      value: field.archive_value,
    },
  };
}
test("effective Enum source binds actual merged settings and two-byte storage while withholding semantics", () => {
  const f = data(),
    selected = effectiveEnumSource(f.source, f.archive, f.field);
  expect(selected.archive_value).toBe(1);
  expect(selected.effective_value).toBe(513);
  expect(selected.maximum_code).toBe(65535);
  expect(selected.enum_semantics_verified).toBe(false);
  expect(() =>
    checkEffectiveEnumReview(
      f.review,
      f.archive,
      selected,
      f.source,
      f.request,
    ),
  ).not.toThrow();
});
test("substituted source hashes, identity, storage capacity, field counts and authority are refused", () => {
  for (const change of [
    (s: any) => {
      s.effective_sha256 = "0".repeat(64);
    },
    (s: any) => {
      s.identity["vendor-identifier"] = 99;
    },
    (s: any) => {
      s.fields[0].maximum_code = 4294967295;
    },
    (s: any) => {
      s.fields.push(s.fields[0]);
    },
    (s: any) => {
      s.field_transfer_enabled = true;
    },
    (s: any) => {
      s.fields[0].archive_value = 2;
    },
  ]) {
    const f = data();
    change(f.source);
    expect(() => effectiveEnumSource(f.source, f.archive, f.field)).toThrow(
      "differs",
    );
  }
});
test("invalid fixed slot offsets and invented Enum semantics cannot pass source qualification", () => {
  for (const change of [
    (s: any) => {
      s.fields[0].saved_storage.dynamic_value_offset = s.files["12"].bytes;
    },
    (s: any) => {
      s.fields[0].saved_storage.static_record_offset = -1;
    },
    (s: any) => {
      s.fields[0].enum_semantics_verified = true;
    },
    (s: any) => {
      s.fields[0].class_id = 530;
    },
  ]) {
    const f = data();
    change(f.source);
    expect(() => effectiveEnumSource(f.source, f.archive, f.field)).toThrow(
      "differs",
    );
  }
});
test("review binds selected edit, parameter merge, capacity, files and exact request together", () => {
  for (const change of [
    (r: any) => {
      r.edit.before_value = 2;
    },
    (r: any) => {
      r.compilation.saved_storage.bytes = 4;
    },
    (r: any) => {
      r.compilation.saved_settings_merged = false;
    },
    (r: any) => {
      r.current_identity_verified = true;
    },
    (r: any) => {
      r.request.value = 2;
    },
    (r: any) => {
      r.compilation.files["12"].sha256 = "0".repeat(64);
    },
  ]) {
    const f = data(),
      selected = effectiveEnumSource(f.source, f.archive, f.field);
    change(f.review);
    expect(() =>
      checkEffectiveEnumReview(
        f.review,
        f.archive,
        selected,
        f.source,
        f.request,
      ),
    ).toThrow("differs");
  }
});
