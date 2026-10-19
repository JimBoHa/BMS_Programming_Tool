import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Download, RefreshCw } from "lucide-react";
import { api, saveBlob } from "./api";
import { showValue } from "./types";

export function Observations() {
  const [status, setStatus] = useState<any>(null),
    [sources, setSources] = useState<any[]>([]),
    [source, setSource] = useState(""),
    [signal, setSignal] = useState(""),
    [filter, setFilter] = useState("all"),
    [samples, setSamples] = useState<any[]>([]),
    [alarms, setAlarms] = useState<any[]>([]),
    [events, setEvents] = useState<any[]>([]),
    [after, setAfter] = useState(0),
    [pages, setPages] = useState<number[]>([]),
    [selectedAlarm, setSelectedAlarm] = useState<number | null>(null),
    [error, setError] = useState(""),
    [auditWarning, setAuditWarning] = useState(""),
    [endNote, setEndNote] = useState(""),
    [endActor, setEndActor] = useState("operator"),
    [busy, setBusy] = useState(false);
  const requestNumber = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++requestNumber.current;
    setBusy(true);
    try {
      const common: Record<string, string> = source ? { source } : {};
      const query = (values: Record<string, string>) =>
        "?" + new URLSearchParams(values);
      const [s, streams, t, a, e] = await Promise.all([
        api("/observations/status"),
        api("/observations/sources"),
        api(
          "/observations/trends" +
            query({
              ...common,
              ...(signal ? { signal } : {}),
              after: String(after),
              limit: "100",
            }),
        ),
        api(
          "/observations/alarms" +
            query({
              ...common,
              ...(filter === "active"
                ? { active: "true" }
                : filter === "unacknowledged"
                  ? { unacknowledged: "true" }
                  : {}),
              limit: "100",
            }),
        ),
        api(
          "/observations/events" +
            query({
              ...common,
              ...(selectedAlarm ? { alarm_id: String(selectedAlarm) } : {}),
              limit: "100",
            }),
        ),
      ]);
      if (request !== requestNumber.current) return;
      setStatus(s);
      setSources(streams);
      setSamples(t);
      setAlarms(a);
      setEvents(e);
      setError("");
    } catch (e) {
      if (request === requestNumber.current) setError(String(e));
    } finally {
      if (request === requestNumber.current) setBusy(false);
    }
  }, [source, signal, filter, after, selectedAlarm]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  function csv() {
    const columns = [
      "sequence",
      "source_kind",
      "source",
      "signal",
      "clock",
      "recorded_at",
      "value",
      "value_type",
      "quality",
      "unit",
    ];
    const quote = (v: unknown) =>
      '"' + String(v ?? "").replaceAll('"', '""') + '"';
    saveBlob(
      new Blob(
        [
          [
            columns.map(quote).join(","),
            ...samples.map((r) => columns.map((c) => quote(r[c])).join(",")),
          ].join("\n"),
        ],
        { type: "text/csv" },
      ),
      "simulation-trends.csv",
    );
  }
  async function retire() {
    if (!source) return;
    setBusy(true);
    try {
      const result = await api("/observations/retire", { source });
      setAuditWarning(result.audit_error || "");
      setSource("");
      setAfter(0);
      setPages([]);
      setSelectedAlarm(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function endSource() {
    if (!source) return;
    setBusy(true);
    try {
      const result = await api("/observations/end", {
        source,
        note: endNote,
        actor: endActor,
      });
      await refresh();
      setAuditWarning(result.audit_error || "");
      setEndNote("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="observations workspace-scroll">
      <div className="workspace-heading">
        <div>
          <h2>
            <Bell size={22} /> Trends &amp; alarms
          </h2>
          <p>
            Durable simulation evidence. Enable Persist history in the Program
            simulator to record successful scans. Source time and receipt time
            are stored separately.
          </p>
        </div>
        <button onClick={refresh} disabled={busy}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      {error && <div className="inline-error">{error}</div>}
      {auditWarning && <div className="inline-error">{auditWarning}</div>}
      {status && (
        <p className="observation-counts">
          {status.samples} / {status.limits.samples} samples ·{" "}
          {status.active_alarms} active alarms · {status.unacknowledged_alarms}{" "}
          unacknowledged · {status.sources} / {status.limits.sources} sources
        </p>
      )}
      <div className="observation-filters">
        <label>
          Simulation source
          <select
            aria-label="Observation source"
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setAfter(0);
              setPages([]);
              setSelectedAlarm(null);
            }}
          >
            <option value="">All sources</option>
            {sources.map((s) => (
              <option value={s.source} key={s.source}>
                {s.source} ({s.samples} samples{s.ended ? "; ended" : ""})
              </option>
            ))}
          </select>
        </label>
        <label>
          Signal identifier
          <input
            value={signal}
            onChange={(e) => {
              setSignal(e.target.value);
              setAfter(0);
              setPages([]);
            }}
            placeholder="Any signal"
          />
        </label>
        <label>
          Alarm filter
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All occurrences</option>
            <option value="active">Active</option>
            <option value="unacknowledged">Unacknowledged</option>
          </select>
        </label>
      </div>
      <h3>Alarm occurrences</h3>
      <p className="help-text">
        Acknowledging an alarm records review; it does not clear its condition.
        A later activation creates a new occurrence. Showing up to 100 most
        recent occurrences.
      </p>
      <div className="observation-alarms">
        {alarms.length ? (
          alarms.map((a) => (
            <AlarmOccurrence
              key={a.id}
              alarm={a}
              onChanged={refresh}
              onEvents={() => setSelectedAlarm(a.id)}
            />
          ))
        ) : (
          <p>No matching alarm occurrences.</p>
        )}
      </div>
      <h3>
        Alarm events{" "}
        {selectedAlarm && (
          <button onClick={() => setSelectedAlarm(null)}>
            Show all events
          </button>
        )}
      </h3>
      <p className="help-text">
        First 100 retained events{" "}
        {selectedAlarm
          ? `for occurrence ${selectedAlarm}`
          : "for the selected source"}
        .
      </p>
      <div className="observation-table">
        <table>
          <thead>
            <tr>
              <th>Event</th>
              <th>Source / signal</th>
              <th>Simulation clock</th>
              <th>Operator / note</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.sequence}>
                <td>
                  #{e.alarm_id} {e.event}
                </td>
                <td>
                  {e.source}
                  <br />
                  {e.signal}
                </td>
                <td>{e.clock}</td>
                <td>
                  {e.actor} {e.note}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="button-row">
        <h3>Trend samples</h3>
        <button disabled={!samples.length} onClick={csv}>
          <Download size={14} /> Export shown trends CSV
        </button>
      </div>
      <div className="observation-table">
        <table>
          <thead>
            <tr>
              <th>Sequence</th>
              <th>Source / signal</th>
              <th>Simulation clock</th>
              <th>Value</th>
              <th>Quality / units</th>
            </tr>
          </thead>
          <tbody>
            {samples.map((s) => (
              <tr key={s.sequence}>
                <td>{s.sequence}</td>
                <td>
                  {s.source}
                  <br />
                  {s.signal}
                </td>
                <td>{s.clock}</td>
                <td>{showValue(s.value)}</td>
                <td>
                  {s.quality} {s.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="button-row">
        <button
          disabled={!pages.length || busy}
          onClick={() => {
            setAfter(pages.at(-1)!);
            setPages(pages.slice(0, -1));
          }}
        >
          Previous samples
        </button>
        <span>
          Page {pages.length + 1} · {samples.length} samples
        </span>
        <button
          disabled={samples.length !== 100 || busy}
          onClick={() => {
            setPages([...pages, after]);
            setAfter(samples.at(-1).sequence);
          }}
        >
          Next samples
        </button>
      </div>
      <details className="observation-retention">
        <summary>Retention and source retirement</summary>
        <p>
          Oldest samples/events expire at the displayed limits. Active or
          unacknowledged occurrences remain. Retiring a selected source
          permanently deletes its retained samples, events and resolved
          occurrences; unresolved alarms prevent retirement. Resetting
          simulation creates a separate source.
        </p>
        <p>
          End an abandoned simulation source to close its active occurrences as
          source-ended. This preserves the distinction from a returned alarm
          condition. Acknowledge those occurrences before retirement. Reset the
          Program simulator before recording a new source.
        </p>
        <div className="alarm-ack">
          <label>
            Operator
            <input
              aria-label="End source operator"
              value={endActor}
              maxLength={120}
              onChange={(e) => setEndActor(e.target.value)}
            />
          </label>
          <label>
            Reason for ending source
            <input
              aria-label="Reason for ending source"
              value={endNote}
              maxLength={1000}
              onChange={(e) => setEndNote(e.target.value)}
            />
          </label>
          <button
            disabled={
              !source ||
              busy ||
              !endNote.trim() ||
              !endActor.trim() ||
              sources.some((s) => s.source === source && s.ended)
            }
            onClick={endSource}
          >
            End selected simulation source
          </button>
        </div>
        <button className="danger" disabled={!source || busy} onClick={retire}>
          Delete selected source and its resolved history
        </button>
      </details>
    </section>
  );
}

function AlarmOccurrence({
  alarm,
  onChanged,
  onEvents,
}: {
  alarm: any;
  onChanged: () => Promise<void>;
  onEvents: () => void;
}) {
  const [note, setNote] = useState(""),
    [actor, setActor] = useState("operator"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function acknowledge() {
    setBusy(true);
    try {
      const result = await api("/observations/acknowledge", {
        alarm_id: alarm.id,
        note,
        actor,
      });
      setError("");
      await onChanged();
      setError(result.audit_error || "");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="alarm-occurrence">
      <div>
        <strong>
          #{alarm.id} {alarm.message}
        </strong>
        <span className={alarm.active ? "alarm-active" : ""}>
          {alarm.state} ·{" "}
          {alarm.acknowledged ? "acknowledged" : "unacknowledged"}
        </span>
        <small>
          {alarm.source} / {alarm.signal}
        </small>
        <small>
          Activated {alarm.activated_at}
          {alarm.returned_at && ` · Returned ${alarm.returned_at}`}
        </small>
      </div>
      {alarm.acknowledged ? (
        <p>
          {alarm.acknowledged_by}: {alarm.acknowledgement_note}
        </p>
      ) : (
        <div className="alarm-ack">
          <label>
            Operator
            <input
              aria-label={`Alarm ${alarm.id} operator`}
              value={actor}
              maxLength={120}
              onChange={(e) => setActor(e.target.value)}
            />
          </label>
          <label>
            Acknowledgment note
            <input
              aria-label={`Alarm ${alarm.id} acknowledgment note`}
              value={note}
              maxLength={1000}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <button
            disabled={!note.trim() || !actor.trim() || busy}
            onClick={acknowledge}
          >
            Acknowledge alarm {alarm.id}
          </button>
        </div>
      )}
      <button onClick={onEvents}>Events for alarm {alarm.id}</button>
      {error && <p className="inline-error">{error}</p>}
    </article>
  );
}
