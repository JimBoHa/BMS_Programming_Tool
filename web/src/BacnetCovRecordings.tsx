import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

/** Saved local evidence: opening history never starts a field subscription. */
export function BacnetCovRecordings() {
  const [recordings, setRecordings] = useState<any[] | null>(null);
  const [monitor, setMonitor] = useState("");
  const [events, setEvents] = useState<any[]>([]);
  const [after, setAfter] = useState(0);
  const [pages, setPages] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );

  async function load(selected: string, cursor = 0, prior: number[] = []) {
    const request = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const [sources, rows] = await Promise.all([
        api("/bacnet/cov/recordings"),
        selected
          ? api(
              `/bacnet/cov/recordings/${encodeURIComponent(selected)}/events?after=${cursor}&limit=100`,
            )
          : Promise.resolve([]),
      ]);
      if (request !== generation.current) return;
      setRecordings(sources);
      setMonitor(selected);
      setEvents(rows);
      setAfter(cursor);
      setPages(prior);
    } catch (e) {
      if (request === generation.current) setError(String(e));
    } finally {
      if (request === generation.current) setBusy(false);
    }
  }

  function download() {
    saveBlob(
      new Blob(
        [
          JSON.stringify(
            {
              recording: recordings?.find((item) => item.monitor === monitor),
              page: { after, limit: 100, count: events.length },
              events,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
      `${monitor}-saved-cov-page.json`,
    );
  }
  const selected = recordings?.find((item) => item.monitor === monitor);
  return (
    <section aria-label="Saved COV observations">
      <h4>Saved COV receipts and trends</h4>
      <p className="help-text">
        Explicit recording only. Saved notification receipts remain after
        restart; subscriptions and recording stay off. Controller timestamps are
        unknown. Eligible numeric values appear in Field trends with receipt
        time and unknown quality unless received flags identify a fault or
        unreliable condition. Raw evidence is separate from polled samples.
        Retention and queue loss are counted below.
      </p>
      <button disabled={busy} onClick={() => void load(monitor, after, pages)}>
        {recordings === null
          ? "Load saved COV observations"
          : "Refresh saved COV observations"}
      </button>
      {recordings !== null && (
        <>
          <label>
            Saved COV recording
            <select
              aria-label="Saved COV recording"
              value={monitor}
              disabled={busy}
              onChange={(e) => void load(e.target.value)}
            >
              <option value="">Select a saved recording</option>
              {recordings.map((item) => (
                <option key={item.monitor} value={item.monitor}>
                  {item.monitor} · {item.metadata.config.device} ·{" "}
                  {item.metadata.config.object_id} · {item.state}
                </option>
              ))}
            </select>
          </label>
          {!recordings.length && <p>No COV recording has been saved.</p>}
        </>
      )}
      {selected && (
        <>
          <p>
            {selected.source} · {selected.state} · Recorded: {selected.recorded}{" "}
            · Queue/storage omissions: {selected.dropped} · Rejected packets:{" "}
            {selected.discarded} · Evidence evicted: {selected.events_evicted} ·
            Trend samples evicted for retained receipts:{" "}
            {selected.samples_evicted}
          </p>
          {selected.last_error && <p role="status">{selected.last_error}</p>}
          <details>
            <summary>Saved COV source provenance</summary>
            <pre>{JSON.stringify(selected.metadata, null, 2)}</pre>
          </details>
          <div className="button-row">
            <button
              disabled={busy || !pages.length}
              onClick={() =>
                void load(monitor, pages.at(-1)!, pages.slice(0, -1))
              }
            >
              Previous saved COV page
            </button>
            <span>{events.length} saved events shown</span>
            <button
              disabled={busy || events.length < 100}
              onClick={() =>
                void load(monitor, events.at(-1).sequence, [...pages, after])
              }
            >
              Next saved COV page
            </button>
            <button disabled={busy || !events.length} onClick={download}>
              Download saved COV page
            </button>
          </div>
          {events.map((event) => (
            <details key={event.sequence}>
              <summary>
                {event.event} · Receipt/event UTC {event.received_at}
              </summary>
              <p>Saved UTC {event.recorded_at} · Controller clock unknown</p>
              <pre>{JSON.stringify(event.evidence, null, 2)}</pre>
            </details>
          ))}
        </>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
    </section>
  );
}
