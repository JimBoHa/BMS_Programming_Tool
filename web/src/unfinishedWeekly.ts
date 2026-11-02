import type { WeeklyDraft } from "./nativeWeeklyWork";
import { ordered } from "./nativeCalendar";

export const UNFINISHED_WEEKLY_BYTES = 512 * 1024;
export const UNFINISHED_WEEKLY_DOCUMENT = "native-schedule-unfinished-weekly/1";
export const UNFINISHED_WEEKLY_IMPORT =
  "native-schedule-unfinished-weekly-import/1";
type RawBuffer = Omit<WeeklyDraft, "dirty" | "rows"> & {
  rows: Omit<WeeklyDraft["rows"][number], "key">[];
};
const object = (v: any, required: string[], optional: string[] = []) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  required.every((key) => Object.hasOwn(v, key)) &&
  Object.keys(v).every(
    (key) => required.includes(key) || optional.includes(key),
  );
const text = (v: any, maximum: number, nonempty = false) =>
  typeof v === "string" &&
  v.length <= maximum &&
  (!nonempty || !!v) &&
  !/[\uD800-\uDFFF]/u.test(v);
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
function rawBuffer(buffer: any, observed: string): RawBuffer {
  if (
    !object(buffer, ["rows", "imported"], ["rawImported"]) ||
    (buffer.imported !== null &&
      (!object(buffer.imported, ["filename", "review_id"]) ||
        !text(buffer.imported.filename, 1024, true) ||
        !hash(buffer.imported.review_id))) ||
    (buffer.rawImported !== undefined &&
      (!object(buffer.rawImported, ["filename", "file_sha256"]) ||
        !text(buffer.rawImported.filename, 1024, true) ||
        !hash(buffer.rawImported.file_sha256))) ||
    !Array.isArray(buffer.rows) ||
    buffer.rows.length > 32
  )
    throw new Error("Unfinished weekly buffer has an unsupported shape.");
  for (const row of buffer.rows)
    if (
      !object(row, ["time", "native_type", "value_text"], ["string_json"]) ||
      !Array.isArray(row.time) ||
      row.time.length !== 4 ||
      !row.time.every((value: any) => text(value, 2)) ||
      ![observed, "Null"].includes(row.native_type) ||
      !text(row.value_text, 256) ||
      (row.string_json !== undefined && !text(row.string_json, 1538))
    )
      throw new Error(
        "Unfinished weekly transition exceeds its raw editor limits.",
      );
  return structuredClone(buffer);
}

export function unfinishedWeeklyDocument(
  capture: string,
  schedule: string,
  day: number,
  draft: WeeklyDraft,
  observed: string,
) {
  if (
    !hash(capture) ||
    !/^schedule,(0|[1-9][0-9]*)$/.test(schedule) ||
    Number(schedule.split(",")[1]) > 4194302 ||
    !Number.isInteger(day) ||
    day < 1 ||
    day > 7
  )
    throw new Error("Select an exact captured Schedule and weekly day.");
  const buffer = rawBuffer(
    {
      rows: draft.rows.map(({ key, ...row }) => row),
      imported: draft.imported,
      ...(draft.rawImported ? { rawImported: draft.rawImported } : {}),
    },
    observed,
  );
  const blob = new Blob(
    [
      JSON.stringify(
        {
          profile: UNFINISHED_WEEKLY_DOCUMENT,
          field_authority: false,
          source: [capture, schedule, String(day)],
          buffer,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  if (blob.size > UNFINISHED_WEEKLY_BYTES)
    throw new Error(
      "Unfinished weekly file exceeds 512 KiB; existing work was kept.",
    );
  return blob;
}

export function unfinishedWeeklyImport(
  data: any,
  capture: string,
  schedule: string,
  day: number,
  observed: string,
  fileSha: string,
  original: any,
): RawBuffer {
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
    data.profile !== UNFINISHED_WEEKLY_IMPORT ||
    data.document_profile !== UNFINISHED_WEEKLY_DOCUMENT ||
    data.field_authority !== false ||
    data.controller_queries !== false ||
    data.capture_mutations !== false ||
    data.native_review_created !== false ||
    !hash(data.file_sha256) ||
    data.file_sha256 !== fileSha ||
    ordered(data.source) !== ordered([capture, schedule, String(day)]) ||
    data.native_type !== observed ||
    !text(data.provenance_policy, 256) ||
    !object(original, ["profile", "field_authority", "source", "buffer"]) ||
    original.profile !== UNFINISHED_WEEKLY_DOCUMENT ||
    original.field_authority !== false ||
    ordered(original.source) !== ordered(data.source) ||
    ordered(original.buffer) !== ordered(data.buffer)
  )
    throw new Error(
      "Unfinished weekly import differs from this file, original capture, Schedule or day.",
    );
  return rawBuffer(data.buffer, observed);
}
