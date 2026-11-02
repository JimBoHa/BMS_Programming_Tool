import type { ExceptionDraftBuffer } from "./nativeScheduleExceptions";
import { ordered } from "./nativeCalendar";
export const UNFINISHED_EXCEPTION_BYTES = 8 * 1024 * 1024;
export const UNFINISHED_EXCEPTION_PROFILE =
  "native-schedule-unfinished-exception-import/1";
const object = (v: any, required: string[], optional: string[] = []) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  required.every((k) => Object.hasOwn(v, k)) &&
  Object.keys(v).every((k) => required.includes(k) || optional.includes(k));
const text = (v: any, n: number, nonempty = false) =>
  typeof v === "string" && v.length <= n && (!nonempty || !!v);
const fields = (v: any, count: number, n: number) =>
  Array.isArray(v) && v.length === count && v.every((s) => text(s, n));
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const provenance = (v: any) =>
  v === null ||
  (object(v, ["filename", "review_id"]) &&
    text(v.filename, 1024, true) &&
    hash(v.review_id));
export function unfinishedExceptionImport(
  data: any,
  capture: string,
  schedule: string,
  observed: string,
  fileSha: string,
  original: any,
): ExceptionDraftBuffer {
  if (
    !object(data, [
      "profile",
      "document_profile",
      "field_authority",
      "controller_queries",
      "capture_mutations",
      "native_review_created",
      "file_sha256",
      "source",
      "native_type",
      "buffer",
      "provenance_policy",
    ]) ||
    data.profile !== UNFINISHED_EXCEPTION_PROFILE ||
    data.document_profile !== "native-schedule-unfinished-exceptions/1" ||
    data.field_authority !== false ||
    data.controller_queries !== false ||
    data.capture_mutations !== false ||
    data.native_review_created !== false ||
    !hash(data.file_sha256) ||
    data.file_sha256 !== fileSha ||
    ordered(data.source) !== ordered([capture, schedule]) ||
    data.native_type !== observed ||
    !object(original, ["profile", "field_authority", "source", "buffer"]) ||
    original.profile !== data.document_profile ||
    original.field_authority !== false ||
    ordered(original.source) !== ordered(data.source) ||
    ordered(original.buffer) !== ordered(data.buffer) ||
    !text(data.provenance_policy, 256)
  )
    throw new Error(
      "Unfinished exception import differs from this file, original capture or selected Schedule.",
    );
  const buffer = data.buffer;
  if (
    !object(buffer, ["rows", "imported"], ["rawImported"]) ||
    !provenance(buffer.imported) ||
    !Array.isArray(buffer.rows) ||
    buffer.rows.length > 32 ||
    (buffer.rawImported !== undefined &&
      (!object(buffer.rawImported, ["filename", "file_sha256"]) ||
        !text(buffer.rawImported.filename, 1024, true) ||
        !hash(buffer.rawImported.file_sha256)))
  )
    throw new Error("Unfinished exception buffer has an unsupported shape.");
  const rows = new Set<string>(),
    times = new Set<string>();
  for (const row of buffer.rows) {
    if (
      !object(row, [
        "key",
        "kind",
        "date",
        "start",
        "end",
        "fields",
        "reference",
        "priority",
        "transitions",
      ]) ||
      !text(row.key, 80, true) ||
      rows.has(row.key) ||
      !["date", "dateRange", "weekNDay", "calendarReference"].includes(
        row.kind,
      ) ||
      !fields(row.date, 4, 4) ||
      !fields(row.start, 4, 4) ||
      !fields(row.end, 4, 4) ||
      !fields(row.fields, 3, 4) ||
      !text(row.reference, 80) ||
      !text(row.priority, 2) ||
      !Array.isArray(row.transitions) ||
      row.transitions.length > 32
    )
      throw new Error(
        "Unfinished exception event exceeds its raw editor limits.",
      );
    rows.add(row.key);
    for (const time of row.transitions) {
      if (
        !object(time, [
          "key",
          "time",
          "native_type",
          "value_text",
          "string_json",
        ]) ||
        !text(time.key, 80, true) ||
        times.has(time.key) ||
        !fields(time.time, 4, 2) ||
        ![observed, "Null"].includes(time.native_type) ||
        !text(time.value_text, 256) ||
        !text(time.string_json, 1538)
      )
        throw new Error(
          "Unfinished exception time exceeds its raw editor limits.",
        );
      times.add(time.key);
    }
  }
  return structuredClone(buffer);
}
