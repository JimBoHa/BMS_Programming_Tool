import { useEffect, useMemo, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob } from "./api";
import { controllerKey, type ControllerTarget } from "./workflow";
import { ordered } from "./nativeCalendar";
import {
  Choice,
  DateFields,
  calendarPatternOptions,
} from "./NativeCalendarEditor";
import {
  EXCEPTION_BASE as base,
  EXCEPTION_DOCUMENT_BYTES,
  exceptionWork,
  exceptionKey,
  exceptionBuffer,
  rememberExceptions,
  exceptionRows,
  blankException,
  blankExceptionTime,
  exceptionRequest,
  exceptionSource,
  exceptionReview,
  type ExceptionWork,
  type ExceptionRow,
} from "./nativeScheduleExceptions";
import "./native-exceptions.css";

export function NativeExceptionEditor({
  captureId,
  connectionKey,
  connected,
  selectedTarget,
  work: provided,
}: {
  captureId: string;
  connectionKey: string;
  connected: boolean;
  selectedTarget: ControllerTarget | null;
  work?: ExceptionWork;
}) {
  const fallback = useRef(exceptionWork()),
    work = provided || fallback.current;
  const [sourceRecord, setSourceRecord] = useState<{
      owner: string;
      data: any;
    } | null>(null),
    [selectedObject, setSelectedObject] = useState(
      work.selected.get(captureId) || "",
    ),
    [, paint] = useState(0),
    [reviewRecord, setReviewRecord] = useState<{
      key: string;
      data: any;
      generation: number;
    } | null>(null),
    [pending, setPending] = useState(""),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [managed, setManaged] = useState("");
  const alive = useRef(false),
    generation = useRef(0),
    operation = useRef(0),
    sourceEpoch = useRef(0),
    fileInput = useRef<HTMLInputElement>(null);
  const owner = ordered([
      captureId,
      connected ? connectionKey : "closed",
      selectedTarget ? controllerKey(selectedTarget) : null,
    ]),
    ownerNow = useRef(owner);
  ownerNow.current = owner;
  const source = sourceRecord?.owner === owner ? sourceRecord.data : null,
    selected = source?.schedules.find(
      (row: any) => row.object === selectedObject,
    ),
    key = selected ? exceptionKey(captureId, selectedObject) : "",
    retained = key ? exceptionBuffer(work, key) : null;
  const seeds = useMemo(
    () => (selected?.eligible ? exceptionRows(selected.events) : []),
    [captureId, selected?.object, selected?.value_sha256],
  );
  const rows = retained?.rows ?? seeds;
  const cursor = key
      ? Math.min(work.cursors.get(key) || 0, Math.max(0, rows.length - 1))
      : 0,
    row = rows[cursor];
  const context = ordered([owner, selectedObject, rows]),
    contextNow = useRef(context);
  if (contextNow.current !== context) {
    contextNow.current = context;
    generation.current++;
  }
  const review =
    reviewRecord?.key === context &&
    reviewRecord.generation === generation.current
      ? reviewRecord.data
      : null;
  const current = (id: number, epoch: number, wanted: string) =>
    alive.current &&
    operation.current === id &&
    generation.current === epoch &&
    contextNow.current === wanted;
  function retire() {
    generation.current++;
    operation.current++;
    setReviewRecord(null);
    setPending("");
  }
  async function load() {
    retire();
    const ticket = ++sourceEpoch.current,
      wanted = ownerNow.current;
    setLoading(true);
    setError("");
    setSourceRecord(null);
    try {
      const data = exceptionSource(
        await api(base + "/source", { id: captureId }),
        captureId,
      );
      if (
        !alive.current ||
        sourceEpoch.current !== ticket ||
        ownerNow.current !== wanted
      )
        return;
      const object =
        data.schedules.find(
          (row: any) =>
            row.eligible && row.object === work.selected.get(captureId),
        ) || data.schedules.find((row: any) => row.eligible);
      if (object) work.selected.set(captureId, object.object);
      setSelectedObject(object?.object || "");
      setSourceRecord({ owner: wanted, data });
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
        setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    const hidden = () => {
      sourceEpoch.current++;
      retire();
      setLoading(false);
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      generation.current++;
      operation.current++;
      sourceEpoch.current++;
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    void load();
  }, [owner]);
  function change(
    next: ExceptionRow[],
    imported?: { filename: string; review_id: string },
  ) {
    if (!key) return false;
    try {
      rememberExceptions(work, key, {
        rows: next,
        imported: imported ?? retained?.imported ?? null,
      });
      retire();
      setError("");
      paint((n) => n + 1);
      return true;
    } catch (failure) {
      setError(String(failure));
      return false;
    }
  }
  function update(changes: Partial<ExceptionRow>) {
    if (row)
      change(
        rows.map((old) => (old.key === row.key ? { ...old, ...changes } : old)),
      );
  }
  function discard(wanted: string) {
    if (pending) return;
    work.drafts.delete(wanted);
    work.cursors.delete(wanted);
    if (wanted === key) retire();
    setManaged("");
    setError("");
    paint((n) => n + 1);
  }
  async function run(kind: "review" | "export" | "import", file?: File) {
    if (!selected?.eligible || pending) return;
    const id = ++operation.current,
      epoch = generation.current,
      wanted = context;
    setPending(kind);
    setError("");
    if (kind === "review") setReviewRecord(null);
    try {
      if (kind === "import") {
        if (!file || file.size > EXCEPTION_DOCUMENT_BYTES)
          throw new Error("Exception draft exceeds 512 KiB.");
        const form = new FormData();
        form.append("file", file);
        const data = await exceptionReview(
          await api(base + "/import", form),
          source,
          selected,
        );
        if (current(id, epoch, wanted)) {
          if (work.drafts.has(key))
            throw new Error(
              "Discard this retained exception draft before importing a replacement for the same Schedule. Existing work was kept.",
            );
          change(exceptionRows(data.request.events), {
            filename: file.name,
            review_id: data.id,
          });
        }
      } else {
        const request = exceptionRequest(captureId, selectedObject, rows);
        if (kind === "review") {
          const data = await exceptionReview(
            await api(base + "/review", request),
            source,
            selected,
            request,
          );
          if (current(id, epoch, wanted))
            setReviewRecord({ key: wanted, generation: epoch, data });
        } else {
          if (!review)
            throw new Error(
              "Review this exact exception draft before exporting.",
            );
          const document = await apiJsonDocument(base + "/export", {
            draft: request,
            expected_review_id: review.id,
          });
          const data = await exceptionReview(
            document.data,
            source,
            selected,
            request,
          );
          if (ordered(data) !== ordered(review))
            throw new Error(
              "Exception export differs from the exact reviewed proof.",
            );
          if (current(id, epoch, wanted))
            saveBlob(
              document.blob,
              `native-schedule-exceptions-${review.id}.json`,
            );
        }
      }
    } catch (failure) {
      if (current(id, epoch, wanted)) setError(String(failure));
    } finally {
      if (current(id, epoch, wanted)) setPending("");
    }
  }
  const managedDraft = work.drafts.get(managed);
  return (
    <section
      className="native-calendar-editor native-exception-editor"
      aria-label="Captured Schedule exception editor"
    >
      <p>
        Edit captured Schedule exceptions locally. Export saves native encoding
        evidence; it does not change a controller or a CAF.
      </p>
      <button disabled={loading} onClick={() => void load()}>
        Refresh captured exception sources
      </button>
      {loading && <p role="status">Reading local exception evidence…</p>}
      {error && <p role="alert">{error}</p>}
      <details>
        <summary>Retained exception drafts</summary>
        <p>
          {work.drafts.size} of 64 source drafts used; 4 MiB total. No work is
          evicted. Save before reloading.
        </p>
        <label>
          Retained exception source
          <select
            aria-label="Retained exception source"
            value={managedDraft ? managed : ""}
            onChange={(event) => setManaged(event.target.value)}
          >
            <option value="" disabled>
              Choose retained work
            </option>
            {[...work.drafts].map(([key, buffer]) => {
              const [capture, object] = JSON.parse(key);
              return (
                <option key={key} value={key}>
                  {object} · {capture.slice(0, 12)} · {buffer.rows.length}{" "}
                  events
                </option>
              );
            })}
          </select>
        </label>
        {managedDraft && (
          <div className="toolbar">
            <button
              disabled={!!pending}
              onClick={() =>
                saveBlob(
                  new Blob(
                    [
                      JSON.stringify(
                        {
                          profile: "native-schedule-unfinished-exceptions/1",
                          field_authority: false,
                          source: JSON.parse(managed),
                          buffer: managedDraft,
                        },
                        null,
                        2,
                      ) + "\n",
                    ],
                    { type: "application/json" },
                  ),
                  `unfinished-exception-text-${Date.now()}.json`,
                )
              }
            >
              Save unfinished exception text
            </button>
            <button disabled={!!pending} onClick={() => discard(managed)}>
              Discard selected retained exceptions
            </button>
          </div>
        )}
        <p className="help-text">
          The unfinished-text export retains raw fields and references for
          manual recovery. It has no import action or native review proof.
          Original captures remain separate.
        </p>
      </details>
      {source && (
        <>
          <p>
            Captured source: {source.target.device} at {source.target.address}
            {source.target.router
              ? ` via ${source.target.router} / ${source.target.dnet}`
              : ""}
            .
          </p>
          {source.schedules
            .filter((row: any) => !row.eligible)
            .map((row: any) => (
              <p key={row.object}>
                {row.object}: exception editing unavailable ·{" "}
                {row.issues.join("; ")}
              </p>
            ))}
          {!source.schedules.some((row: any) => row.eligible) ? (
            <p>
              No captured Schedule meets this exception profile. Original
              evidence remains available.
            </p>
          ) : (
            <>
              <label>
                Captured Schedule for exceptions
                <select
                  aria-label="Captured Schedule for exceptions"
                  value={selectedObject}
                  onChange={(event) => {
                    retire();
                    setError("");
                    work.selected.set(captureId, event.target.value);
                    setSelectedObject(event.target.value);
                  }}
                >
                  {source.schedules
                    .filter((row: any) => row.eligible)
                    .map((row: any) => (
                      <option key={row.object} value={row.object}>
                        {row.object} · {row.native_type}
                      </option>
                    ))}
                </select>
              </label>
              <p>
                Values use captured {selected?.native_type}; Null is an explicit
                release. Event priority is independent of the Schedule’s writing
                priority. Event order and duplicates stay intact.
              </p>
              {retained?.imported && (
                <>
                  <p role="status">
                    Imported exception draft. Review again before export.
                  </p>
                  <details aria-label="Imported exception provenance">
                    <summary>Imported exception provenance</summary>
                    <p>Original file: {retained.imported.filename}</p>
                    <p>Original local review: {retained.imported.review_id}</p>
                  </details>
                </>
              )}
              <div className="toolbar">
                <button
                  disabled={rows.length >= 32}
                  onClick={() => {
                    const next = [...rows, blankException()];
                    if (change(next)) work.cursors.set(key, next.length - 1);
                  }}
                >
                  Add exception event
                </button>
                <button disabled={!!pending} onClick={() => discard(key)}>
                  Discard exception edits
                </button>
              </div>
              {!!rows.length && (
                <>
                  <label>
                    Exception event
                    <select
                      aria-label="Exception event"
                      value={String(cursor)}
                      onChange={(event) => {
                        work.cursors.set(key, Number(event.target.value));
                        paint((n) => n + 1);
                      }}
                    >
                      {rows.map((row, index) => (
                        <option key={row.key} value={String(index)}>
                          Event {index + 1} · {row.kind} · priority{" "}
                          {row.priority || "unfinished"}
                        </option>
                      ))}
                    </select>
                  </label>
                  {row && (
                    <fieldset
                      className="native-exception-fields"
                      aria-label={`Exception event ${cursor + 1} fields`}
                    >
                      <legend>Event {cursor + 1}</legend>
                      <div className="form-grid">
                        <label>
                          Event priority (1 highest, 16 lowest)
                          <input
                            aria-label="Exception event priority"
                            inputMode="numeric"
                            maxLength={2}
                            value={row.priority}
                            onChange={(event) =>
                              update({ priority: event.target.value })
                            }
                          />
                        </label>
                        <label>
                          Exception period
                          <select
                            aria-label="Exception period"
                            value={row.kind}
                            onChange={(event) =>
                              update({
                                kind: event.target
                                  .value as ExceptionRow["kind"],
                              })
                            }
                          >
                            <option value="date">Date pattern</option>
                            <option value="dateRange">Date range</option>
                            <option value="weekNDay">Weekday pattern</option>
                            <option value="calendarReference">
                              Calendar reference
                            </option>
                          </select>
                        </label>
                      </div>
                      {row.kind === "calendarReference" ? (
                        <label>
                          Calendar reference on the captured Device
                          <input
                            aria-label="Exception Calendar reference"
                            maxLength={80}
                            placeholder="calendar,2"
                            value={row.reference}
                            onChange={(event) =>
                              update({ reference: event.target.value })
                            }
                          />
                        </label>
                      ) : row.kind === "date" ? (
                        <DateFields
                          label="Exception date"
                          value={row.date}
                          change={(date) => update({ date })}
                        />
                      ) : row.kind === "dateRange" ? (
                        <>
                          <p className="help-text">
                            Fully specify each range endpoint and its matching
                            weekday, or use Any in all four fields.
                          </p>
                          <DateFields
                            label="Exception range start"
                            value={row.start}
                            change={(start) => update({ start })}
                          />
                          <DateFields
                            label="Exception range end"
                            value={row.end}
                            change={(end) => update({ end })}
                          />
                        </>
                      ) : (
                        <div className="native-calendar-fields">
                          {(
                            [
                              ["month", calendarPatternOptions.months],
                              ["week", calendarPatternOptions.weeks],
                              ["weekday", calendarPatternOptions.weekdays],
                            ] as const
                          ).map(([name, options], index) => (
                            <Choice
                              key={name}
                              label={`Exception ${name}`}
                              value={row.fields[index]}
                              options={options}
                              change={(text) =>
                                update({
                                  fields: row.fields.map((old, i) =>
                                    i === index ? text : old,
                                  ),
                                })
                              }
                            />
                          ))}
                        </div>
                      )}
                      <p className="help-text">
                        Calendar references are retained without querying the
                        Calendar. Times and periods are encoded without
                        evaluating overlap or inferring a timezone.
                      </p>
                      <div className="toolbar">
                        <button
                          disabled={cursor === 0}
                          onClick={() => {
                            const next = [...rows];
                            [next[cursor - 1], next[cursor]] = [
                              next[cursor],
                              next[cursor - 1],
                            ];
                            if (change(next)) work.cursors.set(key, cursor - 1);
                          }}
                        >
                          Move exception earlier
                        </button>
                        <button
                          disabled={cursor === rows.length - 1}
                          onClick={() => {
                            const next = [...rows];
                            [next[cursor + 1], next[cursor]] = [
                              next[cursor],
                              next[cursor + 1],
                            ];
                            if (change(next)) work.cursors.set(key, cursor + 1);
                          }}
                        >
                          Move exception later
                        </button>
                        <button
                          onClick={() =>
                            change(rows.filter((old) => old.key !== row.key))
                          }
                        >
                          Remove selected exception
                        </button>
                      </div>
                      <div className="native-calendar-scroll">
                        <table>
                          <caption>Exception time values</caption>
                          <thead>
                            <tr>
                              <th>Time</th>
                              <th>Native value</th>
                              <th>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {row.transitions.map((time, index) => {
                              const changeTime = (
                                changes: Partial<typeof time>,
                              ) =>
                                update({
                                  transitions: row.transitions.map((old) =>
                                    old.key === time.key
                                      ? { ...old, ...changes }
                                      : old,
                                  ),
                                });
                              return (
                                <tr key={time.key}>
                                  <td>
                                    <div className="native-exception-clock">
                                      {[
                                        "hour",
                                        "minute",
                                        "second",
                                        "hundredth",
                                      ].map((part, field) => (
                                        <label key={part}>
                                          {part}
                                          <input
                                            aria-label={`Exception time ${index + 1} ${part}`}
                                            inputMode="numeric"
                                            maxLength={2}
                                            value={time.time[field]}
                                            onChange={(event) =>
                                              changeTime({
                                                time: time.time.map((old, i) =>
                                                  i === field
                                                    ? event.target.value
                                                    : old,
                                                ),
                                              })
                                            }
                                          />
                                        </label>
                                      ))}
                                    </div>
                                  </td>
                                  <td>
                                    <label>
                                      Value kind
                                      <select
                                        aria-label={`Exception time ${index + 1} kind`}
                                        value={time.native_type}
                                        onChange={(event) =>
                                          changeTime({
                                            native_type: event.target.value,
                                          })
                                        }
                                      >
                                        <option value={selected.native_type}>
                                          {selected.native_type}
                                        </option>
                                        <option value="Null">
                                          Null release
                                        </option>
                                      </select>
                                    </label>
                                    <label>
                                      {time.native_type === "CharacterString"
                                        ? "Quoted JSON String"
                                        : "Native value text"}
                                      <input
                                        aria-label={`Exception time ${index + 1} value`}
                                        maxLength={
                                          time.native_type === "CharacterString"
                                            ? 1538
                                            : 256
                                        }
                                        value={
                                          time.native_type === "CharacterString"
                                            ? time.string_json
                                            : time.native_type === "Null"
                                              ? "null"
                                              : time.value_text
                                        }
                                        readOnly={time.native_type === "Null"}
                                        onChange={(event) =>
                                          changeTime(
                                            time.native_type ===
                                              "CharacterString"
                                              ? {
                                                  string_json:
                                                    event.target.value,
                                                }
                                              : {
                                                  value_text:
                                                    event.target.value,
                                                },
                                          )
                                        }
                                      />
                                    </label>
                                  </td>
                                  <td>
                                    <button
                                      onClick={() =>
                                        update({
                                          transitions: row.transitions.filter(
                                            (old) => old.key !== time.key,
                                          ),
                                        })
                                      }
                                    >
                                      Remove exception time {index + 1}
                                    </button>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                      <button
                        disabled={row.transitions.length >= 32}
                        onClick={() =>
                          update({
                            transitions: [
                              ...row.transitions,
                              blankExceptionTime(selected.native_type),
                            ],
                          })
                        }
                      >
                        Add exception time
                      </button>
                    </fieldset>
                  )}
                </>
              )}
              <div className="toolbar">
                <button
                  className={review ? "" : "primary"}
                  disabled={!!pending}
                  onClick={() => void run("review")}
                >
                  Review exception draft
                </button>
                <button
                  className={review ? "primary" : ""}
                  disabled={!!pending || !review}
                  onClick={() => void run("export")}
                >
                  Export reviewed exceptions
                </button>
                <button
                  disabled={!!pending}
                  onClick={() => fileInput.current?.click()}
                >
                  Import reviewed exceptions
                </button>
                <input
                  type="file"
                  accept=".json"
                  hidden
                  ref={fileInput}
                  aria-label="Import exception draft file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void run("import", file);
                  }}
                />
              </div>
              {pending && (
                <p role="status">Checking local exception evidence…</p>
              )}
              {review && (
                <section aria-label="Native exception draft review">
                  <h4>Local exception encoding reviewed</h4>
                  <p>
                    {review.diff.old_count} original events →{" "}
                    {review.diff.new_count} proposed events.{" "}
                    {review.diff.changed
                      ? "Native value changes."
                      : "Exact native no-op."}{" "}
                    No controller authority.
                  </p>
                  {review.new.minimum_known_protocol_revision && (
                    <p>
                      Weekday patterns require protocol revision{" "}
                      {review.new.minimum_known_protocol_revision} or later. The
                      current target revision has not been verified.
                    </p>
                  )}
                  <details>
                    <summary>Exception native proof</summary>
                    <pre>{JSON.stringify(review, null, 2)}</pre>
                  </details>
                </section>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
