import {
  blankCalendarRow,
  calendarRows,
  calendarEntryRequest,
  validCalendarEntry,
  ordered,
  type CalendarEntry,
  type CalendarRow,
} from "./nativeCalendar";
import { calendarTarget, calendarDocumentSha } from "./nativeCalendarWrite";
import { nativeString, parseStringEditor } from "./nativeScheduleStrings";

export const EXCEPTION_BASE = "/bacnet/schedules/library/exceptions";
export const EXCEPTION_PROFILE = "native-schedule-exception-draft/1";
export const EXCEPTION_RULES =
  "a8c23c4eae7e65d1d81371aa4d004d54353ae3e896abfbf6515b0362ccb46232";
export const EXCEPTION_DOCUMENT_BYTES = 512 * 1024;
const TYPES = [
  "Null",
  "Boolean",
  "Unsigned",
  "Integer",
  "Enumerated",
  "Real",
  "Double",
  "CharacterString",
];
type Period = CalendarEntry | { kind: "calendarReference"; object_id: string };
export type NativeExceptionEvent = {
  period: Period;
  priority: number;
  transitions: { time: number[]; native_type: string; value_text: string }[];
};
export type ExceptionTime = {
  key: string;
  time: string[];
  native_type: string;
  value_text: string;
  string_json: string;
};
export type ExceptionRow = Omit<CalendarRow, "kind"> & {
  kind: Period["kind"];
  reference: string;
  priority: string;
  transitions: ExceptionTime[];
};
export type ExceptionDraftBuffer = {
  rows: ExceptionRow[];
  imported: { filename: string; review_id: string } | null;
  rawImported?: { filename: string; file_sha256: string };
};
export type ExceptionWork = {
  captureId: string;
  open: boolean;
  selected: Map<string, string>;
  cursors: Map<string, number>;
  drafts: Map<string, ExceptionDraftBuffer>;
};
export const exceptionWork = (): ExceptionWork => ({
  captureId: "",
  open: false,
  selected: new Map(),
  cursors: new Map(),
  drafts: new Map(),
});
export const exceptionKey = (capture: string, object: string) =>
  JSON.stringify([capture, object]);
export const EXCEPTION_BUFFERS = 64,
  EXCEPTION_BUFFER_BYTES = 4 * 1024 * 1024;
export function exceptionBuffer(work: ExceptionWork, key: string) {
  const buffer = work.drafts.get(key);
  return buffer ? structuredClone(buffer) : null;
}
export function rememberExceptions(
  work: ExceptionWork,
  key: string,
  buffer: ExceptionDraftBuffer,
) {
  if (!work.drafts.has(key) && work.drafts.size >= EXCEPTION_BUFFERS)
    throw new Error(
      "Exception workspace has 64 retained drafts. Export and explicitly discard retained work before editing another source.",
    );
  const next = structuredClone(buffer);
  if (
    next.rows.length > 32 ||
    next.rows.some(
      (row) =>
        row.priority.length > 2 ||
        row.reference.length > 80 ||
        row.transitions.length > 32 ||
        [...row.date, ...row.start, ...row.end, ...row.fields].some(
          (value) => value.length > 4,
        ) ||
        row.transitions.some(
          (value) =>
            value.time.length !== 4 ||
            value.time.some((part) => part.length > 2) ||
            value.value_text.length > 256 ||
            value.string_json.length > 1538,
        ),
    )
  )
    throw new Error(
      "Exception workspace exceeds its raw editor limits; earlier work was kept.",
    );
  const encoder = new TextEncoder();
  let bytes = encoder.encode(JSON.stringify([key, next])).length;
  for (const [other, value] of work.drafts)
    if (other !== key)
      bytes += encoder.encode(JSON.stringify([other, value])).length;
  if (bytes > EXCEPTION_BUFFER_BYTES)
    throw new Error(
      "Exception workspace exceeds 4 MiB. Export and explicitly discard retained work; earlier drafts were kept.",
    );
  work.drafts.set(key, next);
}
export function blankExceptionTime(type: string): ExceptionTime {
  return {
    key: crypto.randomUUID(),
    time: ["", "", "", ""],
    native_type: type,
    value_text: type === "Null" ? "null" : type === "Boolean" ? "false" : "0",
    string_json: '""',
  };
}
export function blankException(): ExceptionRow {
  return {
    ...blankCalendarRow(),
    kind: "date",
    reference: "",
    priority: "8",
    transitions: [],
  };
}
export function exceptionRows(events: NativeExceptionEvent[]): ExceptionRow[] {
  return events.map((event) => ({
    ...(event.period.kind === "calendarReference"
      ? blankCalendarRow()
      : calendarRows([event.period])[0]),
    kind: event.period.kind,
    reference:
      event.period.kind === "calendarReference" ? event.period.object_id : "",
    priority: String(event.priority),
    transitions: event.transitions.map((row) => ({
      key: crypto.randomUUID(),
      time: row.time.map(String),
      native_type: row.native_type,
      value_text: row.value_text,
      string_json:
        row.native_type === "CharacterString"
          ? JSON.stringify(row.value_text)
          : '""',
    })),
  }));
}
const integer = (text: string, label: string) => {
  if (!/^[0-9]{1,2}$/.test(text))
    throw new Error(`Complete ${label} using decimal whole numbers.`);
  return Number(text);
};
export function exceptionRequest(
  capture: string,
  object: string,
  rows: ExceptionRow[],
) {
  return {
    capture_id: capture,
    object_id: object,
    events: rows.map((row) => ({
      period:
        row.kind === "calendarReference"
          ? { kind: row.kind, object_id: row.reference }
          : calendarEntryRequest(row as CalendarRow),
      priority: integer(row.priority, "event priority"),
      transitions: row.transitions.map((time) => ({
        time: time.time.map((value) => integer(value, "exception time")),
        native_type: time.native_type,
        value_text:
          time.native_type === "CharacterString"
            ? parseStringEditor(time.string_json)
            : time.native_type === "Null"
              ? "null"
              : time.value_text,
      })),
    })),
  };
}
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const wire = (v: any) =>
  typeof v === "string" &&
  v.length <= EXCEPTION_DOCUMENT_BYTES * 2 &&
  /^(?:[a-f0-9]{2})*$/.test(v);
const objectId = (v: any, type: string) =>
  typeof v === "string" &&
  new RegExp(`^${type},(0|[1-9][0-9]{0,6})$`).test(v) &&
  Number(v.split(",")[1]) <= 4194302;
const period = (v: any) =>
  v?.kind === "calendarReference"
    ? objectId(v.object_id, "calendar")
    : validCalendarEntry(v);
function event(v: any) {
  return (
    !!v &&
    period(v.period) &&
    Number.isInteger(v.priority) &&
    v.priority >= 1 &&
    v.priority <= 16 &&
    Array.isArray(v.transitions) &&
    v.transitions.length <= 32 &&
    v.transitions.every(
      (row: any) =>
        Array.isArray(row?.time) &&
        row.time.length === 4 &&
        row.time.every(
          (part: any, i: number) =>
            Number.isInteger(part) && part >= 0 && part <= [23, 59, 59, 99][i],
        ) &&
        TYPES.includes(row.native_type) &&
        typeof row.value_text === "string" &&
        row.value_text.length <= 256 &&
        (row.native_type !== "CharacterString" || nativeString(row.value_text)),
    )
  );
}
const envelope = (v: any) =>
  v?.profile === EXCEPTION_PROFILE &&
  v.rules_sha256 === EXCEPTION_RULES &&
  v.field_writes === false &&
  v.controller_queries === false &&
  v.capture_mutations === false;
export function exceptionSource(v: any, capture: string) {
  if (
    !envelope(v) ||
    v.capture_id !== capture ||
    v.source_sha256 !== capture ||
    !hash(v.evidence_sha256) ||
    !calendarTarget(v.target) ||
    !Array.isArray(v.schedules) ||
    v.schedules.length > 16 ||
    new Set(v.schedules.map((row: any) => row?.object)).size !==
      v.schedules.length ||
    v.schedules.some(
      (row: any) =>
        !objectId(row?.object, "schedule") ||
        typeof row.eligible !== "boolean" ||
        !Array.isArray(row.issues) ||
        row.issues.some((issue: any) => typeof issue !== "string") ||
        (row.eligible &&
          (!TYPES.includes(row.native_type) ||
            row.native_type === "Null" ||
            !Array.isArray(row.events) ||
            row.events.length > 32 ||
            row.events.some((item: any) => !event(item)) ||
            !wire(row.value_encoded_hex) ||
            !hash(row.value_sha256) ||
            row.Calendar_references_queried !== false ||
            ![null, 18].includes(row.minimum_known_protocol_revision))),
    )
  )
    throw new Error(
      "Exception source differs from the selected native capture.",
    );
  return v;
}
export async function exceptionReview(
  v: any,
  source: any,
  selected: any,
  request?: any,
) {
  if (
    !envelope(v) ||
    v.format !== EXCEPTION_PROFILE ||
    !hash(v.id) ||
    v.source?.capture_id !== source.capture_id ||
    v.source.source_sha256 !== source.capture_id ||
    v.source.evidence_sha256 !== source.evidence_sha256 ||
    ordered(v.source.target) !== ordered(source.target) ||
    v.source.object !== selected.object ||
    v.source.property !== "exception-schedule" ||
    v.source.array_index !== null ||
    v.source.native_type !== selected.native_type ||
    !hash(v.source.exception_evidence_sha256) ||
    !hash(v.source.unchanged_context_sha256) ||
    v.request?.capture_id !== source.capture_id ||
    v.request.object_id !== selected.object ||
    !Array.isArray(v.request.events) ||
    v.request.events.length > 32 ||
    v.request.events.some((row: any) => !event(row)) ||
    v.old?.encoded_hex !== selected.value_encoded_hex ||
    v.old.sha256 !== selected.value_sha256 ||
    !Array.isArray(v.old.events) ||
    ordered(v.old.events) !== ordered(selected.events) ||
    !wire(v.new?.encoded_hex) ||
    !hash(v.new.sha256) ||
    v.new.roundtrip_tags_exhausted !== true ||
    v.new.target_revision_verified !== false ||
    v.new.Calendar_references_queried !== false ||
    ![null, 18].includes(v.new.minimum_known_protocol_revision) ||
    !Array.isArray(v.new.events) ||
    v.new.events.length !== v.request.events.length ||
    v.new.events.some(
      (row: any, i: number) =>
        !event(row) ||
        ordered(row.period) !== ordered(v.request.events[i].period) ||
        row.priority !== v.request.events[i].priority ||
        row.transitions.length !== v.request.events[i].transitions.length ||
        row.transitions.some(
          (time: any, j: number) =>
            time.native_type !==
              v.request.events[i].transitions[j].native_type ||
            ordered(time.time) !==
              ordered(v.request.events[i].transitions[j].time),
        ),
    ) ||
    typeof v.diff?.changed !== "boolean" ||
    v.diff.changed !== (v.old.encoded_hex !== v.new.encoded_hex) ||
    v.diff.old_count !== selected.events.length ||
    v.diff.new_count !== v.request.events.length ||
    v.diff.other_properties_changed !== false ||
    (request && ordered(v.request) !== ordered(request))
  )
    throw new Error(
      "Exception review differs from this source, Schedule or draft.",
    );
  const minimum = [...selected.events, ...v.request.events].some(
    (row: any) =>
      row.period.kind === "weekNDay" &&
      row.period.fields[1] >= 7 &&
      row.period.fields[1] <= 9,
  )
    ? 18
    : null;
  if (v.new.minimum_known_protocol_revision !== minimum)
    throw new Error(
      "Exception week-pattern revision proof differs from the source or draft.",
    );
  for (const side of [v.old, v.new]) {
    const bytes = Uint8Array.from(
      (side.encoded_hex as string).match(/../g) || [],
      (part) => Number.parseInt(part, 16),
    );
    if ((await calendarDocumentSha(new Blob([bytes]))) !== side.sha256)
      throw new Error(
        "Exception native bytes differ from their recorded SHA-256.",
      );
  }
  return v;
}
