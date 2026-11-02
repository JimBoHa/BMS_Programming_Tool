import { ordered, type CalendarDraftBuffer } from "./nativeCalendar";

export const UNFINISHED_CALENDAR_BYTES = 128 * 1024;
export const UNFINISHED_CALENDAR_DOCUMENT = "native-calendar-unfinished-text/1";
export const UNFINISHED_CALENDAR_IMPORT =
  "native-calendar-unfinished-text-import/1";
type RawBuffer = Omit<CalendarDraftBuffer, "rows"> & {
  rows: Omit<CalendarDraftBuffer["rows"][number], "key">[];
};
const object = (v: any, required: string[], optional: string[] = []) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  required.every((key) => Object.hasOwn(v, key)) &&
  Object.keys(v).every(
    (key) => required.includes(key) || optional.includes(key),
  );
const text = (v: any, n: number, nonempty = false) =>
  typeof v === "string" &&
  v.length <= n &&
  (!nonempty || !!v) &&
  !/[\uD800-\uDFFF]/u.test(v);
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
function rawBuffer(value: any): RawBuffer {
  if (
    !object(value, ["rows", "imported"], ["rawImported"]) ||
    !(value.imported === "" || hash(value.imported)) ||
    !Array.isArray(value.rows) ||
    value.rows.length > 32 ||
    (value.rawImported !== undefined &&
      (!object(value.rawImported, ["filename", "file_sha256"]) ||
        !text(value.rawImported.filename, 1024, true) ||
        !hash(value.rawImported.file_sha256)))
  )
    throw new Error("Unfinished Calendar buffer has an unsupported shape.");
  for (const row of value.rows) {
    if (
      !object(row, ["kind", "date", "start", "end", "fields"]) ||
      !["date", "dateRange", "weekNDay"].includes(row.kind)
    )
      throw new Error("Unfinished Calendar entry has an unsupported shape.");
    for (const [name, count] of [
      ["date", 4],
      ["start", 4],
      ["end", 4],
      ["fields", 3],
    ] as const)
      if (
        !Array.isArray(row[name]) ||
        row[name].length !== count ||
        !row[name].every((field: any) => text(field, 4))
      )
        throw new Error(
          "Unfinished Calendar fields exceed their raw editor limits.",
        );
  }
  return structuredClone(value);
}
export function unfinishedCalendarDocument(
  capture: string,
  calendar: string,
  buffer: CalendarDraftBuffer,
) {
  if (
    !hash(capture) ||
    !/^calendar,(0|[1-9][0-9]*)$/.test(calendar) ||
    Number(calendar.split(",")[1]) > 4194302
  )
    throw new Error("Select an exact captured Calendar.");
  const value = rawBuffer({
    rows: buffer.rows.map(({ key, ...row }) => row),
    imported: buffer.imported,
    ...(buffer.rawImported ? { rawImported: buffer.rawImported } : {}),
  });
  const blob = new Blob(
    [
      JSON.stringify(
        {
          profile: UNFINISHED_CALENDAR_DOCUMENT,
          field_authority: false,
          source: [capture, calendar],
          buffer: value,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  if (blob.size > UNFINISHED_CALENDAR_BYTES)
    throw new Error(
      "Unfinished Calendar file exceeds 128 KiB; existing work was kept.",
    );
  return blob;
}
export function unfinishedCalendarImport(
  data: any,
  capture: string,
  calendar: string,
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
      "buffer",
      "provenance_policy",
    ]) ||
    data.profile !== UNFINISHED_CALENDAR_IMPORT ||
    data.document_profile !== UNFINISHED_CALENDAR_DOCUMENT ||
    data.field_authority !== false ||
    data.controller_queries !== false ||
    data.capture_mutations !== false ||
    data.native_review_created !== false ||
    !hash(data.file_sha256) ||
    data.file_sha256 !== fileSha ||
    ordered(data.source) !== ordered([capture, calendar]) ||
    !text(data.provenance_policy, 256) ||
    !object(original, ["profile", "field_authority", "source", "buffer"]) ||
    original.profile !== UNFINISHED_CALENDAR_DOCUMENT ||
    original.field_authority !== false ||
    ordered(original.source) !== ordered(data.source) ||
    ordered(original.buffer) !== ordered(data.buffer)
  )
    throw new Error(
      "Unfinished Calendar import differs from this file, original capture or selected Calendar.",
    );
  return rawBuffer(data.buffer);
}
