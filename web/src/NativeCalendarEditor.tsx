import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
} from "react";
import { ChevronDown } from "lucide-react";
import { api, apiJsonDocument, saveBlob } from "./api";
import { NativeCalendarWritePanel } from "./NativeCalendarWritePanel";
import { sameCalendarTarget } from "./nativeCalendarWrite";
import type { ControllerTarget } from "./workflow";
import {
  CALENDAR_BASE,
  blankCalendarRow,
  calendarRequest,
  calendarReview,
  calendarRows,
  calendarSource,
  ordered,
  type CalendarRow,
  type CalendarWork,
} from "./nativeCalendar";
import "./native-calendar.css";

function Select(props: ComponentProps<"select">) {
  return (
    <span className="native-calendar-select">
      <select {...props} />
      <ChevronDown aria-hidden="true" size={16} />
    </span>
  );
}

const MONTHS = [
  ...Array.from({ length: 12 }, (_, i) => [String(i + 1), String(i + 1)]),
  ["13", "Odd months"],
  ["14", "Even months"],
  ["*", "Any month"],
];
const DAYS = [
  ...Array.from({ length: 31 }, (_, i) => [String(i + 1), String(i + 1)]),
  ["32", "Last day"],
  ["33", "Odd days"],
  ["34", "Even days"],
  ["*", "Any day"],
];
const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
]
  .map((name, i) => [String(i + 1), name])
  .concat([["*", "Any weekday"]]);
const WEEKS = [
  ["1", "Days 1–7"],
  ["2", "Days 8–14"],
  ["3", "Days 15–21"],
  ["4", "Days 22–28"],
  ["5", "Days 29–31"],
  ["6", "Last 7 days"],
  ["7", "7 days before last 7"],
  ["8", "7 days before last 14"],
  ["9", "7 days before last 21"],
  ["*", "Any week"],
];
export function Choice({
  label,
  value,
  options,
  change,
}: {
  label: string;
  value: string;
  options: string[][];
  change: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <Select
        aria-label={label}
        value={value}
        onChange={(event) => change(event.target.value)}
      >
        <option value="" disabled>
          Choose…
        </option>
        {options.map(([id, title]) => (
          <option key={id} value={id}>
            {title}
          </option>
        ))}
      </Select>
    </label>
  );
}
export function DateFields({
  label,
  value,
  change,
}: {
  label: string;
  value: string[];
  change: (value: string[]) => void;
}) {
  const field = (index: number, text: string) =>
    change(value.map((old, i) => (i === index ? text : old)));
  return (
    <div className="native-calendar-fields">
      <label>
        {label} year
        <input
          aria-label={label + " year"}
          value={value[0]}
          placeholder="Year or *"
          maxLength={4}
          onChange={(event) => field(0, event.target.value)}
        />
      </label>
      <Choice
        label={label + " month"}
        value={value[1]}
        options={MONTHS}
        change={(text) => field(1, text)}
      />
      <Choice
        label={label + " day"}
        value={value[2]}
        options={DAYS}
        change={(text) => field(2, text)}
      />
      <Choice
        label={label + " weekday"}
        value={value[3]}
        options={WEEKDAYS}
        change={(text) => field(3, text)}
      />
    </div>
  );
}

export const calendarPatternOptions = {
  months: MONTHS,
  weeks: WEEKS,
  weekdays: WEEKDAYS,
};

export function NativeCalendarEditor({
  captureId,
  connectionKey,
  work,
  connected,
  selectedTarget,
}: {
  captureId: string;
  connectionKey: string;
  work: CalendarWork;
  connected: boolean;
  selectedTarget: ControllerTarget | null;
}) {
  const [sourceRecord, setSourceRecord] = useState<{
      owner: string;
      data: any;
    } | null>(null),
    [selectedObject, setSelectedObject] = useState(
      work.selected.get(captureId) || "",
    ),
    [, paint] = useState(0),
    [reviewRecord, setReviewRecord] = useState<{
      context: string;
      generation: number;
      data: any;
    } | null>(null),
    [pending, setPending] = useState<{ id: number; context: string } | null>(
      null,
    ),
    [loading, setLoading] = useState(""),
    [error, setError] = useState("");
  const alive = useRef(false),
    sourceEpoch = useRef(0),
    generation = useRef(0),
    operation = useRef(0);
  const owner = JSON.stringify([captureId, connectionKey]),
    ownerNow = useRef(owner);
  ownerNow.current = owner;
  const source = sourceRecord?.owner === owner ? sourceRecord.data : null;
  const selected = source?.calendars.find(
    (row: any) => row.object === selectedObject,
  );
  const key = selected ? JSON.stringify([captureId, selectedObject]) : "";
  const cached = key ? work.drafts.get(key) : undefined;
  const seedRows = useMemo(
    () => (selected?.eligible ? calendarRows(selected.entries) : []),
    [captureId, selected?.object, selected?.value_sha256],
  );
  const rows = cached?.rows || seedRows;
  const context = ordered([owner, selectedObject, rows]),
    contextNow = useRef(context);
  if (contextNow.current !== context) {
    contextNow.current = context;
    generation.current++;
  }
  const review =
    reviewRecord?.context === context &&
    reviewRecord.generation === generation.current
      ? reviewRecord.data
      : null;
  const busy = pending?.context === context;
  const current = (id: number, epoch: number, wanted: string) =>
    alive.current &&
    operation.current === id &&
    generation.current === epoch &&
    contextNow.current === wanted;

  function cache(object: any) {
    work.selected.set(captureId, object.object);
    return object.object;
  }
  async function load() {
    const ticket = ++sourceEpoch.current,
      wanted = ownerNow.current;
    generation.current++;
    operation.current++;
    setPending(null);
    setReviewRecord(null);
    setSourceRecord(null);
    setError("");
    setLoading(wanted);
    try {
      const data = calendarSource(
        await api(CALENDAR_BASE + "/source", { id: captureId }),
        captureId,
      );
      if (
        alive.current &&
        sourceEpoch.current === ticket &&
        ownerNow.current === wanted
      ) {
        const object =
          data.calendars.find(
            (row: any) =>
              row.eligible && row.object === work.selected.get(captureId),
          ) || data.calendars.find((row: any) => row.eligible);
        const chosen = object ? cache(object) : "";
        setSelectedObject(chosen);
        setSourceRecord({ owner: wanted, data });
      }
    } catch (failure) {
      if (
        alive.current &&
        sourceEpoch.current === ticket &&
        ownerNow.current === wanted
      )
        setError(String(failure));
    } finally {
      if (
        alive.current &&
        sourceEpoch.current === ticket &&
        ownerNow.current === wanted
      )
        setLoading("");
    }
  }
  useEffect(() => {
    alive.current = true;
    const retire = () => {
      sourceEpoch.current++;
      generation.current++;
      operation.current++;
      setSourceRecord(null);
      setReviewRecord(null);
      setLoading("");
      setPending(null);
      setError("");
    };
    document.addEventListener("visibilitychange", retire);
    return () => {
      alive.current = false;
      sourceEpoch.current++;
      generation.current++;
      operation.current++;
      document.removeEventListener("visibilitychange", retire);
    };
  }, []);
  useEffect(() => {
    void load();
  }, [owner]);

  function choose(objectId: string) {
    generation.current++;
    operation.current++;
    setReviewRecord(null);
    setPending(null);
    setError("");
    try {
      const object = source.calendars.find(
        (row: any) => row.object === objectId && row.eligible,
      );
      if (!object) throw new Error("Select an eligible captured Calendar.");
      setSelectedObject(cache(object));
    } catch (failure) {
      setError(String(failure));
    }
  }
  function change(next: CalendarRow[], imported = "") {
    if (!key) return;
    if (!work.drafts.has(key) && work.drafts.size >= 512) {
      setError(
        "Calendar workspace is full. Export and discard an existing Calendar draft before editing another.",
      );
      return;
    }
    generation.current++;
    operation.current++;
    work.drafts.set(key, { rows: next, imported });
    setReviewRecord(null);
    setPending(null);
    setError("");
    paint((n) => n + 1);
  }
  async function run(kind: "review" | "export", file?: File) {
    if (!selected?.eligible || busy) return;
    const id = ++operation.current,
      epoch = generation.current,
      wanted = context;
    setPending({ id, context: wanted });
    setError("");
    if (kind === "review") setReviewRecord(null);
    try {
      if (file) {
        if (file.size > 128 * 1024)
          throw new Error("Calendar draft exceeds 128 KiB.");
        const form = new FormData();
        form.append("file", file);
        const data = calendarReview(
          await api(CALENDAR_BASE + "/import", form),
          source,
          selected,
        );
        if (current(id, epoch, wanted))
          change(calendarRows(data.request.entries), data.id);
      } else {
        const draft = calendarRequest(captureId, selectedObject, rows);
        if (kind === "review") {
          const data = calendarReview(
            await api(CALENDAR_BASE + "/review", draft),
            source,
            selected,
            draft,
          );
          if (current(id, epoch, wanted))
            setReviewRecord({ context: wanted, generation: epoch, data });
        } else {
          if (!review)
            throw new Error(
              "Review this exact Calendar draft before exporting.",
            );
          const document = await apiJsonDocument(CALENDAR_BASE + "/export", {
            draft,
            expected_review_id: review.id,
          });
          const data = calendarReview(
            JSON.parse(await document.blob.text()),
            source,
            selected,
            draft,
          );
          if (ordered(data) !== ordered(review))
            throw new Error(
              "Calendar export differs from its exact reviewed evidence.",
            );
          if (current(id, epoch, wanted))
            saveBlob(document.blob, `native-calendar-draft-${review.id}.json`);
        }
      }
    } catch (failure) {
      if (current(id, epoch, wanted)) setError(String(failure));
    } finally {
      if (current(id, epoch, wanted)) setPending(null);
    }
  }
  const input = useRef<HTMLInputElement>(null);
  return (
    <section
      className="native-calendar-editor"
      aria-label="Captured Calendar date editor"
    >
      <p>
        Edit the original captured Calendar’s dates locally. Saving this draft
        does not change a controller.
      </p>
      <button disabled={loading === owner} onClick={() => void load()}>
        Refresh captured Calendars
      </button>
      {loading === owner && (
        <p role="status">Reading captured Calendar evidence…</p>
      )}
      {error && <p role="alert">{error}</p>}
      {source && (
        <>
          <p>
            Captured source: {source.target.device} at {source.target.address}
            {source.target.router
              ? ` via ${source.target.router} / ${source.target.dnet}`
              : ""}
            .
          </p>
          <p className="mono">Original capture SHA-256: {captureId}</p>
          {source.calendars
            .filter((row: any) => !row.eligible)
            .map((row: any) => (
              <p key={row.object}>
                {row.object}: local draft unavailable · {row.issues.join("; ")}
              </p>
            ))}
          {!source.calendars.some((row: any) => row.eligible) ? (
            <p>
              No captured Calendar meets this draft profile. Original evidence
              remains available in the capture.
            </p>
          ) : (
            <>
              <label>
                Captured Calendar
                <Select
                  aria-label="Captured Calendar for date draft"
                  value={selectedObject}
                  onChange={(event) => choose(event.target.value)}
                >
                  {source.calendars
                    .filter((row: any) => row.eligible)
                    .map((row: any) => (
                      <option key={row.object} value={row.object}>
                        {row.object}
                      </option>
                    ))}
                </Select>
              </label>
              <p>
                Use * for any year. Dates remain in their original order;
                patterns are encoded without inferring a controller date or
                timezone.
              </p>
              {cached?.imported && (
                <p role="status">
                  Imported local Calendar review {cached.imported}. Review again
                  before exporting.
                </p>
              )}
              <div className="native-calendar-scroll">
                <table>
                  <caption>Local Calendar entries</caption>
                  <thead>
                    <tr>
                      <th>Entry type</th>
                      <th>Pattern</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => {
                      const label = `Calendar entry ${index + 1}`;
                      const update = (changes: Partial<CalendarRow>) =>
                        change(
                          rows.map((old) =>
                            old.key === row.key ? { ...old, ...changes } : old,
                          ),
                        );
                      return (
                        <tr key={row.key}>
                          <td>
                            <label>
                              {label} type
                              <Select
                                aria-label={label + " type"}
                                value={row.kind}
                                onChange={(event) =>
                                  update({
                                    kind: event.target
                                      .value as CalendarRow["kind"],
                                  })
                                }
                              >
                                <option value="date">Date pattern</option>
                                <option value="dateRange">Date range</option>
                                <option value="weekNDay">
                                  Weekday pattern
                                </option>
                              </Select>
                            </label>
                          </td>
                          <td>
                            {row.kind === "date" ? (
                              <DateFields
                                label={label}
                                value={row.date}
                                change={(date) => update({ date })}
                              />
                            ) : row.kind === "dateRange" ? (
                              <>
                                <p className="help-text">
                                  For controller deployment, fully specify each
                                  endpoint and its matching weekday, or choose
                                  Any in all four fields.
                                </p>
                                <DateFields
                                  label={label + " start"}
                                  value={row.start}
                                  change={(start) => update({ start })}
                                />
                                <DateFields
                                  label={label + " end"}
                                  value={row.end}
                                  change={(end) => update({ end })}
                                />
                              </>
                            ) : (
                              <div className="native-calendar-fields">
                                {[MONTHS, WEEKS, WEEKDAYS].map((choices, i) => (
                                  <Choice
                                    key={i}
                                    label={`${label} ${["month", "week", "weekday"][i]}`}
                                    value={row.fields[i]}
                                    options={choices}
                                    change={(text) =>
                                      update({
                                        fields: row.fields.map((v, n) =>
                                          n === i ? text : v,
                                        ),
                                      })
                                    }
                                  />
                                ))}
                              </div>
                            )}
                          </td>
                          <td>
                            <button
                              onClick={() =>
                                change(
                                  rows.filter((old) => old.key !== row.key),
                                )
                              }
                            >
                              Remove Calendar entry {index + 1}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="toolbar">
                <button
                  disabled={rows.length >= 32}
                  onClick={() => change([...rows, blankCalendarRow()])}
                >
                  Add Calendar entry
                </button>
                <button
                  onClick={() => {
                    generation.current++;
                    operation.current++;
                    work.drafts.delete(key);
                    setReviewRecord(null);
                    setPending(null);
                    setError("");
                    paint((n) => n + 1);
                  }}
                >
                  Discard Calendar edits
                </button>
                <button
                  className={review ? "" : "primary"}
                  disabled={busy}
                  onClick={() => void run("review")}
                >
                  Review Calendar dates
                </button>
                <button
                  className={
                    review &&
                    (!connected ||
                      !sameCalendarTarget(
                        review.source.target,
                        selectedTarget,
                      ) ||
                      !review.diff.changed)
                      ? "primary"
                      : ""
                  }
                  disabled={busy || !review}
                  onClick={() => void run("export")}
                >
                  Export reviewed Calendar draft
                </button>
                <button disabled={busy} onClick={() => input.current?.click()}>
                  Import reviewed Calendar draft
                </button>
                <input
                  hidden
                  type="file"
                  ref={input}
                  accept=".json"
                  aria-label="Import Calendar draft file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void run("review", file);
                  }}
                />
              </div>
              {busy && <p role="status">Checking local Calendar evidence…</p>}
              {review && (
                <div aria-label="Calendar date draft review">
                  <p>
                    <strong>
                      {review.diff.changed
                        ? "Local Calendar value changed"
                        : "Exact native Calendar no-op"}
                    </strong>{" "}
                    · {review.diff.old_count} original entries →{" "}
                    {review.diff.new_count} proposed entries.
                  </p>
                  <p>
                    Native encoding verified. This is a local draft, not a
                    controller write approval or calendar evaluation.
                  </p>
                  {review.new.minimum_known_protocol_revision && (
                    <p>
                      Newer weekday patterns require protocol revision 18 or
                      later. Target revision and acceptance remain unverified.
                    </p>
                  )}
                  <details>
                    <summary>Calendar encoding evidence</summary>
                    <pre>{JSON.stringify(review, null, 2)}</pre>
                  </details>
                </div>
              )}
            </>
          )}
        </>
      )}
      <NativeCalendarWritePanel
        review={review}
        context={ordered([context, generation.current, sourceEpoch.current])}
        connected={connected}
        selectedTarget={selectedTarget}
      />
    </section>
  );
}
