import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob } from "./api";
import { NativeScheduleWritePanel } from "./NativeScheduleWritePanel";
import { NativeCalendarEditor } from "./NativeCalendarEditor";
import { exceptionWork, type ExceptionWork } from "./nativeScheduleExceptions";
import { calendarWork, type CalendarWork } from "./nativeCalendar";
import { controllerKey, type ControllerTarget } from "./workflow";
import {
  weeklyWork,
  weeklyKey,
  weeklyDraft,
  rememberWeekly,
  type WeeklyWork,
  type WeeklyRow as Row,
} from "./nativeWeeklyWork";
import {
  STRING_DRAFT,
  STRING_DRAFT_RULES,
  STRING_EDITOR_LENGTH,
  nativeString,
  parseStringEditor,
  stringDraftCapability,
  stringDraftReview,
} from "./nativeScheduleStrings";

import "./native-schedule-library.css";

const NativeExceptionEditor = lazy(() =>
  import("./NativeExceptionEditor").then((module) => ({
    default: module.NativeExceptionEditor,
  })),
);

const BASE = "/bacnet/schedules/library";
const CAPTURE = "native-calendar-schedule-capture/1";
const DRAFT = "native-schedule-weekly-day-draft/1";
const ID = /^[a-f0-9]{64}$/;
const TYPES = [
  "Null",
  "Boolean",
  "Unsigned",
  "Integer",
  "Enumerated",
  "Real",
  "Double",
];
type Transition = {
  time: number[];
  native_type: string;
  value_text: string;
};
type Day = {
  day: number;
  transitions: Transition[];
  encoded_hex: string;
  sha256: string;
};
type Schedule = {
  object: string;
  eligible: boolean;
  native_type?: string;
  issues: string[];
  days?: Day[];
  draft_profile?: string;
  rules_sha256?: string;
};
type Capture = {
  id: string;
  source_sha256: string;
  source_report_id: string;
  evidence_sha256: string;
  profile: string;
  target: { device: string; address: string; router?: string; dnet?: number };
  started_at: string;
  finished_at: string;
  origin: string;
  status: string;
  objects: Schedule[];
  report?: unknown;
  integrity?: string;
  scope?: string;
  ingest?: unknown;
  import_provenance?: unknown;
  string_draft?: unknown;
};
function text(value: unknown, maximum = 4096): value is string {
  return typeof value === "string" && value.length <= maximum;
}
function supportedSchedule(item: any, capability: any) {
  return item?.native_type === "CharacterString"
    ? stringDraftCapability(capability) &&
        item.draft_profile === STRING_DRAFT &&
        item.rules_sha256 === STRING_DRAFT_RULES
    : TYPES.includes(item?.native_type);
}
function optionalStringCapability(value: any) {
  return (
    value?.string_draft === undefined ||
    stringDraftCapability(value.string_draft)
  );
}
function captureSummary(value: any): boolean {
  return (
    text(value?.id, 64) &&
    ID.test(value.id) &&
    value.profile === CAPTURE &&
    value.draft_profile === DRAFT &&
    optionalStringCapability(value) &&
    value.source_sha256 === value.id &&
    text(value.source_report_id, 32) &&
    /^[a-f0-9]{32}$/.test(value.source_report_id) &&
    text(value.evidence_sha256, 64) &&
    ID.test(value.evidence_sha256) &&
    text(value.target?.device, 128) &&
    text(value.target?.address, 256) &&
    (value.target.router == null || text(value.target.router, 256)) &&
    (value.target.dnet == null ||
      (Number.isInteger(value.target.dnet) &&
        value.target.dnet >= 1 &&
        value.target.dnet <= 65534)) &&
    [value.started_at, value.finished_at, value.origin, value.status].every(
      (item) => text(item),
    ) &&
    Array.isArray(value.objects) &&
    value.objects.length <= 16 &&
    value.objects.every(
      (item: any) =>
        text(item?.object, 128) &&
        typeof item.eligible === "boolean" &&
        Array.isArray(item.issues) &&
        item.issues.length <= 64 &&
        item.issues.every((issue: unknown) => text(issue)) &&
        (!item.eligible || supportedSchedule(item, value.string_draft)),
    )
  );
}
function libraryProfile(value: any) {
  if (
    value?.profile !== CAPTURE ||
    value.draft_profile !== DRAFT ||
    !optionalStringCapability(value) ||
    !Array.isArray(value.captures) ||
    value.captures.length > 32 ||
    value.captures.some((item: any) => !captureSummary(item)) ||
    new Set(value.captures.map((item: Capture) => item.id)).size !==
      value.captures.length ||
    (value.storage?.durability != null && !text(value.storage.durability)) ||
    (value.storage?.platform != null && !text(value.storage.platform))
  )
    throw new Error("The local library profile is malformed or unsupported.");
  return value;
}
function captureResult(value: any, expected?: string): Capture {
  if (
    !ID.test(value?.id || "") ||
    (expected && value.id !== expected) ||
    value.profile !== CAPTURE ||
    !optionalStringCapability(value) ||
    value.source_sha256 !== value.id ||
    !Array.isArray(value.objects) ||
    typeof value.target?.device !== "string" ||
    typeof value.target?.address !== "string"
  )
    throw new Error("Capture response does not match the selected source.");
  for (const item of value.objects) {
    if (
      typeof item.object !== "string" ||
      typeof item.eligible !== "boolean" ||
      !Array.isArray(item.issues)
    )
      throw new Error("Capture object evidence is malformed.");
    if (
      item.eligible &&
      (!supportedSchedule(item, value.string_draft) ||
        !Array.isArray(item.days) ||
        item.days.length !== 7 ||
        item.days.some(
          (day: any, index: number) =>
            day.day !== index + 1 ||
            !ID.test(day.sha256) ||
            !Array.isArray(day.transitions) ||
            day.transitions.length > 32 ||
            day.transitions.some(
              (row: any) =>
                !validTransition(row, item.native_type === "CharacterString"),
            ),
        ))
    )
      throw new Error(
        "Capture has no exact supported seven-day seed evidence.",
      );
  }
  return value;
}
function validTransition(row: any, strings = false) {
  return (
    Array.isArray(row?.time) &&
    row.time.length === 4 &&
    row.time.every(
      (value: any, index: number) =>
        Number.isInteger(value) &&
        value >= 0 &&
        value <= [23, 59, 59, 99][index],
    ) &&
    (strings
      ? ["CharacterString", "Null"].includes(row.native_type)
      : TYPES.includes(row.native_type)) &&
    typeof row.value_text === "string" &&
    (row.native_type === "CharacterString"
      ? nativeString(row.value_text)
      : row.value_text.length <= 256)
  );
}
function sameTransitions(a: Transition[], b: Transition[]) {
  return (
    a.length === b.length &&
    a.every(
      (row, index) =>
        row.native_type === b[index].native_type &&
        row.value_text === b[index].value_text &&
        row.time.length === 4 &&
        row.time.every((value, field) => value === b[index].time[field]),
    )
  );
}
function reviewResult(value: any) {
  const strings = value?.source?.observed_native_type === "CharacterString";
  const expected = strings ? STRING_DRAFT : DRAFT;
  if (
    !ID.test(value?.id || "") ||
    value.profile !== expected ||
    value.format !== expected ||
    (strings
      ? !stringDraftReview(value)
      : value.request?.draft_profile !== undefined) ||
    !ID.test(value.request?.capture_id || "") ||
    !Array.isArray(value.request?.transitions) ||
    value.request.transitions.length > 32 ||
    value.request.transitions.some(
      (row: any) => !validTransition(row, strings),
    ) ||
    !Number.isInteger(value.request.day) ||
    value.request.day < 1 ||
    value.request.day > 7 ||
    value.source?.capture_id !== value.request.capture_id ||
    value.source?.object !== value.request.object_id ||
    value.source?.day !== value.request.day ||
    value.diff?.property !== "weekly-schedule" ||
    value.diff?.array_index !== value.request.day ||
    value.new?.roundtrip_tags_exhausted !== true ||
    !Array.isArray(value.new?.transitions) ||
    value.new.transitions.length !== value.request.transitions.length ||
    value.new.transitions.some(
      (row: any) => typeof row.wire_value_text !== "string",
    ) ||
    value.field_writes !== false
  )
    throw new Error("The response is not a native weekly-day draft review.");
  return value;
}

export function ScheduleLibraryPanel({
  sessionReportId,
  connected = false,
  connectionKey = "",
  selectedTarget = null,
  calendarWorkspace: suppliedCalendarWorkspace,
  weeklyWorkspace: suppliedWeeklyWorkspace,
  exceptionWorkspace: suppliedExceptionWorkspace,
}: {
  sessionReportId: string | null;
  connected?: boolean;
  connectionKey?: string;
  selectedTarget?: ControllerTarget | null;
  calendarWorkspace?: CalendarWork;
  weeklyWorkspace?: WeeklyWork;
  exceptionWorkspace?: ExceptionWork;
}) {
  const fallbackWeeklyWorkspace = useRef(weeklyWork());
  const weeklyWorkspace =
    suppliedWeeklyWorkspace || fallbackWeeklyWorkspace.current;
  const fallbackCalendarWorkspace = useRef(calendarWork());
  const calendarWorkspace =
    suppliedCalendarWorkspace || fallbackCalendarWorkspace.current;
  const [calendarOpen, setCalendarOpen] = useState(calendarWorkspace.open);
  const fallbackExceptionWorkspace = useRef(exceptionWork());
  const exceptionWorkspace =
    suppliedExceptionWorkspace || fallbackExceptionWorkspace.current;
  const [exceptionsOpen, setExceptionsOpen] = useState(exceptionWorkspace.open);
  const [profile, setProfile] = useState<any>(null),
    [capture, setCapture] = useState<Capture | null>(null),
    [object, setObject] = useState(""),
    [day, setDay] = useState(1),
    [rows, setRows] = useState<Row[]>([]),
    [review, setReview] = useState<any>(null),
    [busy, setBusy] = useState(""),
    [exporting, setExporting] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const alive = useRef(true),
    epoch = useRef(0),
    listEpoch = useRef(0),
    working = useRef(false),
    exportPending = useRef(false),
    nextRow = useRef(0);
  const sourceNow = useRef(sessionReportId);
  sourceNow.current = sessionReportId;
  const captureNow = useRef(capture?.id || "");
  captureNow.current = capture?.id || "";
  const reviewNow = useRef(review?.id || "");
  reviewNow.current = review?.id || "";
  const input = useRef<HTMLInputElement>(null),
    draftInput = useRef<HTMLInputElement>(null);
  const selected = capture?.objects.find((item) => item.object === object);
  const seed = selected?.days?.find((item) => item.day === day);
  const bufferKey = weeklyKey(capture?.id || "", object, day);
  const retained = weeklyDraft(weeklyWorkspace, bufferKey);
  const fieldContext = JSON.stringify([
    connected,
    // Remembered settings have no field authority while disconnected/unverified.
    // Loading them must not cancel an operation on the local capture library.
    connected ? connectionKey : "closed",
    selectedTarget ? controllerKey(selectedTarget) : null,
  ]);
  const boundary = useRef({ context: fieldContext, version: 0 });
  if (boundary.current.context !== fieldContext)
    boundary.current = {
      context: fieldContext,
      version: boundary.current.version + 1,
    };
  const signature = JSON.stringify([
    fieldContext,
    boundary.current.version,
    capture?.id,
    object,
    day,
    rows.map(({ key, ...row }) => row),
  ]);
  const signatureNow = useRef(signature);
  signatureNow.current = signature;
  const current = (ticket: number, source: string) =>
    alive.current &&
    epoch.current === ticket &&
    signatureNow.current === source;
  function rowCopies(transitions: Transition[]): Row[] {
    return transitions.map((item) => ({
      key: nextRow.current++,
      time: item.time.map(String),
      native_type: item.native_type,
      value_text: item.value_text,
    }));
  }
  function replaceSelection(
    value: Capture,
    wanted?: string,
    wantedDay = 1,
    transitions?: Transition[],
    imported: { review_id: string; filename: string } | null = null,
  ) {
    const previous = weeklyWorkspace.selected.get(value.id);
    if (!wanted && previous) {
      wanted = previous.object;
      wantedDay = previous.day;
    }
    const item =
      value.objects.find((candidate) => candidate.object === wanted) ||
      value.objects.find((candidate) => candidate.eligible);
    const key = weeklyKey(value.id, item?.object || "", wantedDay);
    let buffered = weeklyDraft(weeklyWorkspace, key);
    if (transitions) {
      if (buffered?.dirty)
        throw new Error(
          "This imported day already has unfinished work. Export or explicitly discard that day's draft before importing a replacement.",
        );
      buffered = { rows: rowCopies(transitions), dirty: true, imported };
      rememberWeekly(weeklyWorkspace, key, buffered);
    }
    const next =
      buffered?.rows ||
      rowCopies(
        item?.days?.find((candidate) => candidate.day === wantedDay)
          ?.transitions || [],
      );
    nextRow.current = Math.max(
      nextRow.current,
      ...next.map((row) => row.key + 1),
    );
    epoch.current++;
    weeklyWorkspace.captureId = value.id;
    weeklyWorkspace.selected.set(value.id, {
      object: item?.object || "",
      day: wantedDay,
    });
    setCapture(value);
    calendarWorkspace.captureId = value.id;
    exceptionWorkspace.captureId = value.id;
    setObject(item?.object || "");
    setDay(wantedDay);
    setRows(next);
    setReview(null);
    setError("");
  }
  function changed(next: Row[]) {
    epoch.current++;
    setReview(null);
    try {
      rememberWeekly(weeklyWorkspace, bufferKey, {
        rows: next,
        dirty: true,
        imported: retained?.imported || null,
      });
    } catch (failure) {
      setError(String(failure));
      return;
    }
    setRows(next);
    setReview(null);
    setError("");
    setNotice("");
  }
  async function refresh() {
    const ticket = ++listEpoch.current;
    try {
      const result = libraryProfile(await api(BASE + "/profile"));
      if (alive.current && ticket === listEpoch.current) setProfile(result);
    } catch (failure) {
      if (alive.current && ticket === listEpoch.current)
        setError(String(failure));
    }
  }
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
      epoch.current++;
      listEpoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    setReview(null);
  }, [fieldContext]);
  useEffect(() => {
    const retire = () => {
      epoch.current++;
      setReview(null);
    };
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
    };
  }, []);
  async function action(
    label: string,
    work: () => Promise<void>,
    valid = () => true,
  ) {
    if (working.current) return;
    working.current = true;
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (failure) {
      if (alive.current && valid()) setError(String(failure));
    } finally {
      working.current = false;
      if (alive.current) setBusy("");
    }
  }
  async function open(id: string) {
    const ticket = ++epoch.current,
      source = signatureNow.current;
    await action(
      "Opening local capture",
      async () => {
        const result = captureResult(await api(BASE + "/captures/" + id), id);
        if (current(ticket, source)) replaceSelection(result);
      },
      () => current(ticket, source),
    );
  }
  useEffect(() => {
    // Restore only a local source. Field connection and write reviews are not restored.
    const id =
      weeklyWorkspace.captureId ||
      calendarWorkspace.captureId ||
      exceptionWorkspace.captureId;
    if (id) void open(id);
  }, []);
  async function saveCurrent() {
    if (!sessionReportId) return;
    const report = sessionReportId,
      ticket = epoch.current,
      source = signatureNow.current;
    await action(
      "Saving captured evidence",
      async () => {
        const result = captureResult(await api(BASE + "/save", { id: report }));
        if (!alive.current || sourceNow.current !== report) return;
        if (result.source_report_id !== report)
          throw new Error(
            "Saved capture belongs to a different inventory report.",
          );
        if (!capture && current(ticket, source)) replaceSelection(result);
        setNotice(
          `Saved capture ${result.id.slice(0, 12)} for ${result.target.device} at ${result.target.address}.`,
        );
        await refresh();
      },
      () => sourceNow.current === report,
    );
  }
  async function importFile(file: File, draft: boolean) {
    const ticket = ++epoch.current,
      source = signatureNow.current;
    await action(
      draft ? "Importing reviewed draft" : "Importing capture",
      async () => {
        const form = new FormData();
        form.append("file", file);
        const result = await api(
          BASE + (draft ? "/drafts/import" : "/import"),
          form,
        );
        if (!current(ticket, source)) return;
        if (draft) {
          const accepted = reviewResult(result),
            request = accepted.request;
          const detail = captureResult(
            await api(BASE + "/captures/" + request.capture_id),
            request.capture_id,
          );
          if (!current(ticket, source)) return;
          replaceSelection(
            detail,
            request.object_id,
            request.day,
            request.transitions,
            { review_id: accepted.id, filename: file.name },
          );
          setReview(accepted);
          setNotice(
            "Imported review regenerated against its exact local source capture.",
          );
        } else {
          const detail = captureResult(result);
          replaceSelection(detail);
          setNotice(`Imported capture ${detail.id.slice(0, 12)}.`);
        }
        await refresh();
      },
      () => current(ticket, source),
    );
  }
  function request() {
    if (!capture || !selected?.eligible)
      throw new Error("Select an eligible captured Schedule.");
    return {
      capture_id: capture.id,
      object_id: object,
      day,
      transitions: rows.map((row) => ({
        time: row.time.map((text, index) => {
          const high = [23, 59, 59, 99][index];
          if (!/^\d{1,2}$/.test(text) || Number(text) > high)
            throw new Error(
              "Enter specific native hour, minute, second and hundredth fields.",
            );
          return Number(text);
        }),
        native_type: row.native_type,
        value_text:
          row.native_type === "CharacterString"
            ? parseStringEditor(
                row.string_json ?? JSON.stringify(row.value_text),
              )
            : row.value_text,
      })),
      ...(selected.native_type === "CharacterString"
        ? { draft_profile: STRING_DRAFT }
        : {}),
    };
  }
  async function prepare() {
    const ticket = epoch.current,
      source = signatureNow.current;
    await action(
      "Reviewing offline weekly draft",
      async () => {
        const proposed = request(),
          result = reviewResult(await api(BASE + "/drafts/review", proposed));
        if (!current(ticket, source)) return;
        if (
          result.request.capture_id !== proposed.capture_id ||
          result.request.object_id !== proposed.object_id ||
          result.request.day !== proposed.day ||
          !sameTransitions(result.request.transitions, proposed.transitions)
        )
          throw new Error(
            "Draft review does not match the current capture, day and transitions.",
          );
        setReview(result);
      },
      () => current(ticket, source),
    );
  }
  async function exportDocument(kind: "capture" | "source" | "draft") {
    if (!capture || (kind === "draft" && !review) || exportPending.current)
      return;
    exportPending.current = true;
    const ticket = epoch.current,
      source = signatureNow.current,
      id = capture.id,
      reviewId = review?.id;
    setExporting(true);
    setError("");
    try {
      const response = await apiJsonDocument(
        BASE +
          (kind === "draft"
            ? "/drafts/export"
            : kind === "source"
              ? "/source-export"
              : "/export"),
        { id: kind === "draft" ? reviewId : id },
      );
      if (
        !current(ticket, source) ||
        captureNow.current !== id ||
        (kind === "draft" && reviewNow.current !== reviewId)
      )
        return;
      if (kind === "draft") {
        if (reviewResult(response.data).id !== reviewId)
          throw new Error("Exported review has a different identity.");
      } else if (kind === "source") {
        const sha = Array.from(
          new Uint8Array(
            await crypto.subtle.digest(
              "SHA-256",
              await response.blob.arrayBuffer(),
            ),
          ),
          (value) => value.toString(16).padStart(2, "0"),
        ).join("");
        if (sha !== capture.source_sha256)
          throw new Error("Original source bytes do not match this capture.");
      } else if (
        response.data.id !== id ||
        response.data.source_sha256 !== id ||
        response.data.format !== CAPTURE
      )
        throw new Error("Exported archive has a different source identity.");
      if (
        !current(ticket, source) ||
        captureNow.current !== id ||
        (kind === "draft" && reviewNow.current !== reviewId)
      )
        return;
      saveBlob(
        response.blob,
        `native-schedule-${kind}-${(kind === "draft" ? reviewId : id).slice(0, 12)}.json`,
      );
      if (kind === "draft") {
        const saved = weeklyDraft(weeklyWorkspace, bufferKey);
        if (saved)
          rememberWeekly(weeklyWorkspace, bufferKey, {
            ...saved,
            dirty: false,
          });
      }
      setNotice(
        `Exported exact ${kind === "draft" ? "reviewed day draft" : kind === "source" ? "original source report" : "capture archive"}.`,
      );
    } catch (failure) {
      if (current(ticket, source)) setError(String(failure));
    } finally {
      exportPending.current = false;
      if (alive.current) setExporting(false);
    }
  }
  function choose(nextObject: string, nextDay: number) {
    if (!capture) return;
    replaceSelection(capture, nextObject, nextDay);
  }
  return (
    <section
      className="card native-schedule-library"
      aria-label="Native Schedule capture library"
    >
      <h3>Offline Calendar and Schedule library</h3>
      <p>
        Save native captures, reopen them offline and review Calendar dates or
        one weekly-day draft. Drafts do not send changes to a controller.
      </p>
      <p>
        Calendar and weekly edits stay with their captured source while
        switching tasks. Export all local work before restarting. Write reviews
        are never restored by navigation.
      </p>
      <div className="toolbar">
        <button
          disabled={!sessionReportId || !!busy}
          onClick={() => void saveCurrent()}
        >
          Save current schedule report locally
        </button>
        <button disabled={!!busy} onClick={() => void refresh()}>
          Refresh local schedule library
        </button>
        <button disabled={!!busy} onClick={() => input.current?.click()}>
          Import schedule capture
        </button>
        <button disabled={!!busy} onClick={() => draftInput.current?.click()}>
          Import reviewed weekly draft
        </button>
        <input
          hidden
          ref={input}
          aria-label="Import native schedule capture file"
          type="file"
          accept=".json"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void importFile(file, false);
          }}
        />
        <input
          hidden
          ref={draftInput}
          aria-label="Import native weekly draft file"
          type="file"
          accept=".json"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void importFile(file, true);
          }}
        />
      </div>
      {busy && <p role="status">{busy}…</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {profile && (
        <>
          <p>
            {profile.captures.length} saved captures ·{" "}
            {profile.storage?.durability ||
              profile.storage?.platform ||
              "local storage"}
          </p>
          <div className="native-schedule-table-scroll">
            <table aria-label="Saved native schedule captures">
              <thead>
                <tr>
                  <th>Capture</th>
                  <th>Captured target</th>
                  <th>Observed through</th>
                  <th>Origin / status</th>
                </tr>
              </thead>
              <tbody>
                {profile.captures.map((item: Capture) => (
                  <tr key={item.id}>
                    <td>
                      <button
                        disabled={!!busy}
                        onClick={() => void open(item.id)}
                      >
                        Open capture {item.id.slice(0, 12)}
                      </button>
                    </td>
                    <td>
                      {item.target.device} at {item.target.address}
                      {item.target.router
                        ? ` via ${item.target.router} / ${item.target.dnet}`
                        : ""}
                    </td>
                    <td>{item.finished_at}</td>
                    <td>
                      {item.origin} · {item.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Library limits and draft policy</summary>
            <pre>
              {JSON.stringify(
                {
                  limits: profile.limits,
                  draft_policy: profile.draft_policy,
                  storage: profile.storage,
                  scope: profile.scope,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </>
      )}
      {capture && (
        <div aria-label="Opened native schedule capture">
          <h4>
            {capture.target.device} at {capture.target.address}
          </h4>
          <p>
            Captured {capture.started_at} through {capture.finished_at}. These
            are sequential observations with unresolved source-clock context.
          </p>
          <p className="mono">Capture SHA-256: {capture.id}</p>
          <details
            aria-label="Captured Calendar dates"
            open={calendarOpen}
            onToggle={(event) => {
              const next = event.currentTarget.open;
              calendarWorkspace.open = next;
              setCalendarOpen(next);
            }}
          >
            <summary>Calendar dates</summary>
            {calendarOpen && (
              <NativeCalendarEditor
                connected={connected}
                selectedTarget={selectedTarget}
                captureId={capture.id}
                connectionKey={connectionKey}
                work={calendarWorkspace}
              />
            )}
          </details>
          <details
            aria-label="Captured Schedule exceptions"
            open={exceptionsOpen}
            onToggle={(event) => {
              exceptionWorkspace.open = event.currentTarget.open;
              setExceptionsOpen(event.currentTarget.open);
            }}
          >
            <summary>Schedule exceptions</summary>
            {exceptionsOpen && (
              <Suspense fallback={<p>Opening local exception editor…</p>}>
                <NativeExceptionEditor
                  captureId={capture.id}
                  connectionKey={connectionKey}
                  connected={connected}
                  selectedTarget={selectedTarget}
                  work={exceptionWorkspace}
                />
              </Suspense>
            )}
          </details>
          <div className="toolbar">
            <button
              disabled={exporting}
              onClick={() => void exportDocument("capture")}
            >
              Export exact capture archive
            </button>
            <button
              disabled={exporting}
              onClick={() => void exportDocument("source")}
            >
              Export original schedule source
            </button>
          </div>
          <details>
            <summary>Captured provenance and native evidence preview</summary>
            <p>{capture.integrity}</p>
            <p>{capture.scope}</p>
            <pre>
              {JSON.stringify(
                {
                  source_report_id: capture.source_report_id,
                  evidence_sha256: capture.evidence_sha256,
                  origin: capture.origin,
                  ingest: capture.ingest,
                  import_provenance: capture.import_provenance,
                },
                null,
                2,
              )}
            </pre>
            <p>
              JSON previews normalize numeric spelling. Downloads retain
              authoritative bytes; editors use exact typed native seeds.
            </p>
            <pre className="result">
              {JSON.stringify(capture.report, null, 2)}
            </pre>
          </details>
          {capture.objects.map(
            (item) =>
              !item.eligible && (
                <p key={item.object}>
                  {item.object}: draft unavailable · {item.issues.join("; ")}
                </p>
              ),
          )}
          {!capture.objects.some((item) => item.eligible) && (
            <p>
              No Schedule in this capture meets the weekly-day draft profile.
              Original Calendar and Schedule evidence remains available above.
            </p>
          )}
          {!!capture.objects.some((item) => item.eligible) && (
            <div aria-label="Native weekly day editor">
              <div className="form-grid">
                <label>
                  Captured Schedule
                  <select
                    aria-label="Captured Schedule for weekly draft"
                    value={object}
                    onChange={(event) => choose(event.target.value, day)}
                  >
                    {capture.objects
                      .filter((item) => item.eligible)
                      .map((item) => (
                        <option key={item.object} value={item.object}>
                          {item.object} · {item.native_type}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Native weekly day
                  <select
                    aria-label="Native weekly day"
                    value={day}
                    onChange={(event) =>
                      choose(object, Number(event.target.value))
                    }
                  >
                    {[1, 2, 3, 4, 5, 6, 7].map((value) => (
                      <option key={value} value={value}>
                        {
                          [
                            "Monday",
                            "Tuesday",
                            "Wednesday",
                            "Thursday",
                            "Friday",
                            "Saturday",
                            "Sunday",
                          ][value - 1]
                        }{" "}
                        ({value})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p>
                Specific native times only, in strictly increasing order. The
                captured type is {selected?.native_type}; native Null remains a
                separate choice. No timezone or controller execution is
                inferred.
              </p>
              {retained?.imported && (
                <details aria-label="Imported weekly draft provenance">
                  <summary>Imported weekly draft source</summary>
                  <p>
                    Retained text needs a current local review; navigation never
                    restores field authority.
                  </p>
                  <pre className="result">
                    {JSON.stringify(retained.imported, null, 2)}
                  </pre>
                </details>
              )}
              <details>
                <summary>Weekly workspace draft limits</summary>
                <p>
                  {weeklyWorkspace.drafts.size} retained days; maximum 128
                  drafts and 4 MiB. Existing work is never evicted. Export and
                  explicitly discard a selected draft to free space. Buffers
                  stay in memory until this application reloads.
                </p>
              </details>
              <div className="native-schedule-table-scroll">
                <table aria-label="Native daily transitions">
                  <thead>
                    <tr>
                      <th>Native time (hour / minute / second / hundredth)</th>
                      <th>Native type</th>
                      <th>Exact value text</th>
                      <th>Row</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={row.key}>
                        <td>
                          <div className="toolbar">
                            {["Hour", "Minute", "Second", "Hundredth"].map(
                              (label, field) => (
                                <input
                                  key={label}
                                  aria-label={`Transition ${index + 1} ${label.toLowerCase()}`}
                                  inputMode="numeric"
                                  size={2}
                                  maxLength={2}
                                  value={row.time[field]}
                                  onChange={(event) =>
                                    changed(
                                      rows.map((item) =>
                                        item.key === row.key
                                          ? {
                                              ...item,
                                              time: item.time.map(
                                                (value, position) =>
                                                  position === field
                                                    ? event.target.value
                                                    : value,
                                              ),
                                            }
                                          : item,
                                      ),
                                    )
                                  }
                                />
                              ),
                            )}
                          </div>
                        </td>
                        <td>
                          <select
                            aria-label={`Transition ${index + 1} native type`}
                            value={row.native_type}
                            onChange={(event) =>
                              changed(
                                rows.map((item) =>
                                  item.key === row.key
                                    ? {
                                        ...item,
                                        native_type: event.target.value,
                                        string_json: undefined,
                                        value_text:
                                          event.target.value === "Null"
                                            ? "null"
                                            : item.value_text === "null"
                                              ? ""
                                              : item.value_text,
                                      }
                                    : item,
                                ),
                              )
                            }
                          >
                            <option value={selected?.native_type}>
                              {selected?.native_type}
                            </option>
                            <option value="Null">Null</option>
                          </select>
                        </td>
                        <td>
                          {row.native_type === "CharacterString" ? (
                            <>
                              <textarea
                                aria-label={`Transition ${index + 1} CharacterString JSON literal`}
                                value={
                                  row.string_json ??
                                  JSON.stringify(row.value_text)
                                }
                                maxLength={STRING_EDITOR_LENGTH}
                                rows={2}
                                onChange={(event) =>
                                  changed(
                                    rows.map((item) =>
                                      item.key === row.key
                                        ? {
                                            ...item,
                                            string_json: event.target.value,
                                          }
                                        : item,
                                    ),
                                  )
                                }
                              />
                              <small>
                                Quoted JSON string; empty is {`""`}. Escapes
                                preserve CR, LF and NUL. Maximum 256 UTF-8
                                bytes; no trimming or Unicode normalization.
                              </small>
                            </>
                          ) : (
                            <input
                              aria-label={`Transition ${index + 1} exact value text`}
                              value={row.value_text}
                              maxLength={256}
                              readOnly={row.native_type === "Null"}
                              onChange={(event) =>
                                changed(
                                  rows.map((item) =>
                                    item.key === row.key
                                      ? {
                                          ...item,
                                          value_text: event.target.value,
                                        }
                                      : item,
                                  ),
                                )
                              }
                            />
                          )}
                        </td>
                        <td>
                          <button
                            onClick={() =>
                              changed(
                                rows.filter((item) => item.key !== row.key),
                              )
                            }
                            aria-label={`Remove transition ${index + 1}`}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!rows.length && <p>This proposed day has no transitions.</p>}
              <div className="toolbar">
                <button
                  disabled={rows.length >= (profile?.limits?.transitions || 32)}
                  onClick={() =>
                    changed([
                      ...rows,
                      {
                        key: nextRow.current++,
                        time: ["", "", "", ""],
                        native_type: selected?.native_type || "Null",
                        value_text: "",
                      },
                    ])
                  }
                >
                  Add daily transition
                </button>
                <button
                  disabled={!retained && !review}
                  onClick={() => {
                    epoch.current++;
                    weeklyWorkspace.drafts.delete(bufferKey);
                    setRows(rowCopies(seed?.transitions || []));
                    setReview(null);
                    setError("");
                    setNotice("Discarded the local weekly draft.");
                  }}
                >
                  Discard weekly draft
                </button>
                <button disabled={!!busy} onClick={() => void prepare()}>
                  Review native weekly draft
                </button>
              </div>
              {seed && (
                <details>
                  <summary>Original captured day tags</summary>
                  <p>{seed.sha256}</p>
                  <pre>{seed.encoded_hex}</pre>
                </details>
              )}
              {review && (
                <div aria-label="Native weekly draft review">
                  <h4>
                    {review.diff.changed
                      ? "Changed weekly day"
                      : "No native day changes"}
                  </h4>
                  <p>
                    {review.diff.old_transition_count} →{" "}
                    {review.diff.new_transition_count} transitions ·
                    weekly-schedule index {review.diff.array_index}
                  </p>
                  <p>
                    Other days unchanged in this draft. Captured default,
                    priority, references, effective period and exception context
                    remain bound to this review.
                  </p>
                  <div className="native-schedule-table-scroll">
                    <table aria-label="Requested and encoded native values">
                      <thead>
                        <tr>
                          <th>Native time</th>
                          <th>Type</th>
                          <th>Requested text</th>
                          <th>Wire value text</th>
                          <th>Precision change</th>
                        </tr>
                      </thead>
                      <tbody>
                        {review.new.transitions.map(
                          (item: any, index: number) => (
                            <tr key={index}>
                              <td>{item.time.join(":")}</td>
                              <td>{item.native_type}</td>
                              <td>
                                {item.native_type === "CharacterString"
                                  ? JSON.stringify(item.value_text)
                                  : item.value_text}
                              </td>
                              <td>
                                {item.native_type === "CharacterString"
                                  ? JSON.stringify(item.wire_value_text)
                                  : item.wire_value_text}
                              </td>
                              <td>
                                {item.native_type === "CharacterString"
                                  ? "Exact UTF-8 text"
                                  : item.decimal_text_changed ||
                                      item.binary64_to_wire_changed
                                    ? "Inspect rounding"
                                    : "No reported numeric change"}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                  <button
                    disabled={exporting || !!busy}
                    onClick={() => void exportDocument("draft")}
                  >
                    Export exact reviewed weekly draft
                  </button>
                  <details>
                    <summary>
                      Native day diff, source binding and encoding proof
                    </summary>
                    <pre className="result">
                      {JSON.stringify(review, null, 2)}
                    </pre>
                  </details>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      <NativeScheduleWritePanel
        selectedTarget={selectedTarget}
        draft={review}
        connected={connected}
        connectionKey={connectionKey}
      />
    </section>
  );
}
