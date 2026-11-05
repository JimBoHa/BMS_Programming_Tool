import { randomUUID } from "./browserCrypto";
export const CALENDAR_PROFILE = "native-calendar-date-list-draft/1";
export const CALENDAR_RULES =
  "b5070ff4633fbf3f11ea9abac9ac9ee8b646f05d94a41e4f39ed353334e5fd69";
export const CALENDAR_BASE = "/bacnet/schedules/library/calendar";
export type CalendarEntry =
  | { kind: "date"; date: number[] }
  | { kind: "dateRange"; start: number[]; end: number[] }
  | { kind: "weekNDay"; fields: number[] };
export type CalendarRow = {
  key: string;
  kind: CalendarEntry["kind"];
  date: string[];
  start: string[];
  end: string[];
  fields: string[];
};
export type CalendarDraftBuffer = {
  rows: CalendarRow[];
  imported: string;
  rawImported?: { filename: string; file_sha256: string };
};
export type CalendarWork = {
  captureId: string;
  open: boolean;
  selected: Map<string, string>;
  drafts: Map<string, CalendarDraftBuffer>;
};
export const CALENDAR_BUFFERS = 512;
export function rememberCalendar(
  work: CalendarWork,
  key: string,
  buffer: CalendarDraftBuffer,
) {
  if (!work.drafts.has(key) && work.drafts.size >= CALENDAR_BUFFERS)
    throw new Error(
      "Calendar workspace is full. Export and discard an existing Calendar draft before editing another.",
    );
  work.drafts.set(key, structuredClone(buffer));
}
export const calendarWork = (): CalendarWork => ({
  captureId: "",
  open: false,
  selected: new Map(),
  drafts: new Map(),
});
export function ordered(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(ordered).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + ordered(value[key]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value) ?? "undefined";
}
const hash = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const hex = (value: unknown) =>
  typeof value === "string" &&
  value.length <= 32768 &&
  /^(?:[a-f0-9]{2})*$/.test(value);
const bytes = (value: unknown, length: number) =>
  Array.isArray(value) &&
  value.length === length &&
  value.every(
    (field) =>
      typeof field === "number" &&
      Number.isInteger(field) &&
      field >= 0 &&
      field <= 255,
  );
export function validCalendarEntry(value: any) {
  return value?.kind === "date"
    ? bytes(value.date, 4)
    : value?.kind === "dateRange"
      ? bytes(value.start, 4) && bytes(value.end, 4)
      : value?.kind === "weekNDay" && bytes(value.fields, 3);
}
const envelope = (data: any) =>
  data?.profile === CALENDAR_PROFILE &&
  data.rules_sha256 === CALENDAR_RULES &&
  data.field_writes === false &&
  data.controller_queries === false &&
  data.capture_mutations === false;
export function calendarSource(data: any, captureId: string) {
  if (
    !envelope(data) ||
    data.capture_id !== captureId ||
    data.source_sha256 !== captureId ||
    !hash(data.evidence_sha256) ||
    typeof data.target?.address !== "string" ||
    typeof data.target?.device !== "string" ||
    !Array.isArray(data.calendars) ||
    data.calendars.length > 16 ||
    new Set(data.calendars.map((row: any) => row?.object)).size !==
      data.calendars.length ||
    data.calendars.some(
      (row: any) =>
        typeof row?.object !== "string" ||
        !/^calendar,(0|[1-9][0-9]*)$/.test(row.object) ||
        typeof row.eligible !== "boolean" ||
        !Array.isArray(row.issues) ||
        row.issues.some((issue: unknown) => typeof issue !== "string") ||
        (row.eligible &&
          (!Array.isArray(row.entries) ||
            row.entries.length > 32 ||
            row.entries.some((entry: unknown) => !validCalendarEntry(entry)) ||
            !hex(row.property_encoded_hex) ||
            !hex(row.value_encoded_hex) ||
            !hash(row.property_sha256) ||
            !hash(row.value_sha256))),
    )
  )
    throw new Error(
      "Calendar source does not match the selected captured evidence.",
    );
  return data;
}
export function blankCalendarRow(
  kind: CalendarEntry["kind"] = "date",
): CalendarRow {
  return {
    key: randomUUID(),
    kind,
    date: ["", "", "", "*"],
    start: ["", "", "", "*"],
    end: ["", "", "", "*"],
    fields: ["", "", "*"],
  };
}
const dateText = (fields: number[]) =>
  fields.map((n, index) =>
    n === 255 ? "*" : String(index === 0 ? 1900 + n : n),
  );
export function calendarRows(entries: CalendarEntry[]): CalendarRow[] {
  return entries.map((entry) => {
    const row = blankCalendarRow(entry.kind);
    if (entry.kind === "date") row.date = dateText(entry.date);
    else if (entry.kind === "dateRange") {
      row.start = dateText(entry.start);
      row.end = dateText(entry.end);
    } else row.fields = entry.fields.map((n) => (n === 255 ? "*" : String(n)));
    return row;
  });
}
function field(text: string, year = false) {
  if (text === "*") return 255;
  if (!/^(0|[1-9][0-9]*)$/.test(text))
    throw new Error("Complete every Calendar pattern field, or choose Any.");
  const value = Number(text);
  if (year) {
    if (value < 1900 || value > 2154)
      throw new Error("Calendar year must be 1900–2154 or * for any year.");
    return value - 1900;
  }
  if (value > 255) throw new Error("Calendar field exceeds its native range.");
  return value;
}
const dateValue = (values: string[]) =>
  values.map((value, i) => field(value, i === 0));
export function calendarEntryRequest(row: CalendarRow): CalendarEntry {
  return row.kind === "date"
    ? { kind: "date", date: dateValue(row.date) }
    : row.kind === "dateRange"
      ? {
          kind: "dateRange",
          start: dateValue(row.start),
          end: dateValue(row.end),
        }
      : { kind: "weekNDay", fields: row.fields.map((value) => field(value)) };
}
export function calendarRequest(
  captureId: string,
  objectId: string,
  rows: CalendarRow[],
) {
  return {
    capture_id: captureId,
    object_id: objectId,
    entries: rows.map(calendarEntryRequest),
  };
}
export function calendarReview(
  data: any,
  source: any,
  selected: any,
  request?: any,
) {
  if (
    !envelope(data) ||
    data.format !== CALENDAR_PROFILE ||
    !hash(data.id) ||
    data.source?.capture_id !== source.capture_id ||
    data.source.source_sha256 !== source.capture_id ||
    data.source.evidence_sha256 !== source.evidence_sha256 ||
    ordered(data.source.target) !== ordered(source.target) ||
    data.source.object !== selected.object ||
    data.source.property !== "date-list" ||
    data.source.array_index !== null ||
    data.source.property_sha256 !== selected.property_sha256 ||
    !hash(data.source.property_evidence_sha256) ||
    !hash(data.source.unchanged_context_sha256) ||
    data.request?.capture_id !== source.capture_id ||
    data.request.object_id !== selected.object ||
    !Array.isArray(data.request.entries) ||
    data.request.entries.length > 32 ||
    data.request.entries.some((entry: unknown) => !validCalendarEntry(entry)) ||
    (request && ordered(data.request) !== ordered(request)) ||
    data.old?.encoded_hex !== selected.value_encoded_hex ||
    data.old.sha256 !== selected.value_sha256 ||
    ordered(data.old.entries) !== ordered(selected.entries) ||
    !hex(data.new?.encoded_hex) ||
    !hash(data.new.sha256) ||
    data.new.roundtrip_tags_exhausted !== true ||
    data.new.target_revision_verified !== false ||
    ordered(data.new.entries) !== ordered(data.request.entries) ||
    data.diff?.other_properties_changed !== false ||
    data.diff.old_count !== selected.entries.length ||
    data.diff.new_count !== data.request.entries.length ||
    data.diff.changed !== (data.old.encoded_hex !== data.new.encoded_hex)
  )
    throw new Error(
      "Calendar review does not match this source, object and draft.",
    );
  const modern = data.request.entries.some(
    (entry: CalendarEntry) =>
      entry.kind === "weekNDay" && entry.fields[1] >= 7 && entry.fields[1] <= 9,
  );
  if (data.new.minimum_known_protocol_revision !== (modern ? 18 : null))
    throw new Error(
      "Calendar review did not retain its protocol revision qualification.",
    );
  return data;
}
