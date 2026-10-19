import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Download,
  Plus,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";
import { api, saveBlob } from "./api";
import { showValue } from "./types";

type Point = {
  signal: string;
  address: string;
  object_id: string;
  property_id: string;
  unit: string;
  value_type: string;
};
const point = (index: number): Point => ({
  signal: `point_${index}`,
  address: "127.0.0.1:47808",
  object_id: `analog-input,${index}`,
  property_id: "present-value",
  unit: "",
  value_type: "number",
});

export function FieldTrends() {
  const [points, setPoints] = useState<Point[]>([point(1)]);
  const [name, setName] = useState("");
  const [interval, setIntervalSeconds] = useState(10);
  const [verifyQuality, setVerifyQuality] = useState(true);
  const [status, setStatus] = useState<any>({ jobs: [], running_jobs: 0 });
  const [connected, setConnected] = useState(false);
  const [sources, setSources] = useState<any[]>([]);
  const [source, setSource] = useState("");
  const [samples, setSamples] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [after, setAfter] = useState(0);
  const [pages, setPages] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef(0);
  const refresh = useCallback(async () => {
    const current = ++request.current;
    const query = new URLSearchParams({ after: String(after), limit: "100" });
    if (source) query.set("source", source);
    try {
      const [state, link, streams, data, log] = await Promise.all([
        api("/field-trends/status"),
        api("/bacnet/status"),
        api("/field-trends/sources"),
        api("/field-trends/samples?" + query),
        api(
          "/field-trends/events?" +
            new URLSearchParams(
              source ? { source, limit: "100" } : { limit: "100" },
            ),
        ),
      ]);
      if (current !== request.current) return;
      setStatus(state);
      setConnected(link.connected);
      setSources(streams);
      setSamples(data);
      setEvents(log);
    } catch (e) {
      if (current === request.current) setError(String(e));
    }
  }, [source, after]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => {
      request.current++;
      window.clearInterval(timer);
    };
  }, [refresh]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function update(index: number, key: keyof Point, value: string) {
    setPoints((old) =>
      old.map((p, i) => (i === index ? { ...p, [key]: value } : p)),
    );
  }
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
    const quote = (value: unknown) =>
      '"' + String(value ?? "").replaceAll('"', '""') + '"';
    saveBlob(
      new Blob(
        [
          [
            columns.map(quote).join(","),
            ...samples.map((row) =>
              columns.map((key) => quote(row[key])).join(","),
            ),
          ].join("\r\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
      "field-trends-page.csv",
    );
  }
  return (
    <div className="workspace-page field-trends">
      <div className="page-intro">
        <div>
          <span className="eyebrow">FIELD OBSERVATIONS</span>
          <h1>Field trends</h1>
          <p>
            Read addressed BACnet values through the interface selected in
            Connect. Samples and acquisition events persist locally.
          </p>
        </div>
        <span className={"connection-badge " + (connected ? "connected" : "")}>
          <span className="status-dot" />
          {connected
            ? "BACnet interface open"
            : "Open a BACnet interface in Connect"}
        </span>
      </div>
      <section className="card" aria-label="Field trend acquisition">
        <div className="card-header">
          <h3>
            <Activity size={18} /> Start read-only sampling
          </h3>
          <span className="pill">EXPLICIT START</span>
        </div>
        <div className="card-body">
          <p className="help-text">
            Starting a job sends property reads through the existing BACnet
            interface. Jobs stop if that interface changes or fails. A restart
            preserves samples and requires an explicit new start. This does not
            download programs, command outputs, or acquire controller-native
            alarm events.
          </p>
          <div className="form-grid">
            <label>
              Trend job name
              <input
                aria-label="Trend job name"
                value={name}
                maxLength={120}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Sampling interval (seconds)
              <input
                aria-label="Field sampling interval"
                type="number"
                min={5}
                max={3600}
                value={interval}
                onChange={(e) => setIntervalSeconds(Number(e.target.value))}
              />
            </label>
            <label className="full">
              <span>
                <input
                  type="checkbox"
                  checked={verifyQuality}
                  onChange={(e) => setVerifyQuality(e.target.checked)}
                />{" "}
                Verify BACnet reliability, status flags and out-of-service
              </span>
            </label>
          </div>
          <p className="help-text">
            Raw values carry unknown quality unless all requested quality checks
            succeed. Read failures appear in the acquisition log; no zero value
            is substituted. Units are operator labels, not device conversions.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Unicast target</th>
                  <th>Object</th>
                  <th>Property</th>
                  <th>Value type</th>
                  <th>Unit label</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {points.map((p, i) => (
                  <tr key={i}>
                    {(
                      ["signal", "address", "object_id", "property_id"] as const
                    ).map((key) => (
                      <td key={key}>
                        <input
                          aria-label={`Field ${{ object_id: "object identifier", property_id: "property identifier", signal: "signal", address: "address" }[key]} ${i + 1}`}
                          value={p[key]}
                          onChange={(e) => update(i, key, e.target.value)}
                        />
                      </td>
                    ))}
                    <td>
                      <select
                        aria-label={`Field value type ${i + 1}`}
                        value={p.value_type}
                        onChange={(e) =>
                          update(i, "value_type", e.target.value)
                        }
                      >
                        <option value="number">Number</option>
                        <option value="boolean">Boolean</option>
                      </select>
                    </td>
                    <td>
                      <input
                        aria-label={`Field unit ${i + 1}`}
                        value={p.unit}
                        onChange={(e) => update(i, "unit", e.target.value)}
                      />
                    </td>
                    <td>
                      <button
                        aria-label={`Remove field point ${i + 1}`}
                        disabled={points.length === 1}
                        onClick={() =>
                          setPoints(points.filter((_, j) => j !== i))
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button
              disabled={points.length >= 16}
              onClick={() => setPoints([...points, point(points.length + 1)])}
            >
              <Plus size={15} /> Add field point
            </button>
            <button
              className="primary"
              disabled={busy || !connected}
              onClick={() =>
                action(async () => {
                  const job = await api("/field-trends/start", {
                    points,
                    name,
                    interval_seconds: interval,
                    verify_quality: verifyQuality,
                  });
                  setSource(job.source);
                  setAfter(0);
                  setPages([]);
                })
              }
            >
              Start field sampling
            </button>
          </div>
        </div>
      </section>
      <section className="card" aria-label="Field sampling jobs">
        <div className="card-header">
          <h3>Sampling jobs</h3>
          <button onClick={() => action(refresh)} disabled={busy}>
            <RefreshCw size={15} /> Refresh field trends
          </button>
        </div>
        {!status.jobs.length ? (
          <div className="card-body">
            No sampling jobs in this server session. Saved samples remain below.
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>State</th>
                  <th>Polls</th>
                  <th>Samples</th>
                  <th>Failures</th>
                  <th>Last error</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {status.jobs.map((job: any) => (
                  <tr key={job.id}>
                    <td>
                      <button
                        onClick={() => {
                          setSource(job.source);
                          setAfter(0);
                          setPages([]);
                        }}
                      >
                        {job.name || job.id}
                      </button>
                    </td>
                    <td>{job.state}</td>
                    <td>{job.polls}</td>
                    <td>{job.samples}</td>
                    <td>{job.failures}</td>
                    <td>{job.last_error || "—"}</td>
                    <td>
                      <button
                        disabled={busy || !job.running}
                        onClick={() =>
                          action(async () => {
                            await api("/field-trends/stop", { id: job.id });
                          })
                        }
                      >
                        <Square size={13} /> Stop sampling
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="card" aria-label="Saved field trend samples">
        <div className="card-header">
          <h3>Saved field samples</h3>
          <button disabled={!samples.length} onClick={csv}>
            <Download size={15} /> Export field page CSV
          </button>
        </div>
        <div className="card-body">
          <label>
            Field source
            <select
              aria-label="Field trend source"
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setAfter(0);
                setPages([]);
              }}
            >
              <option value="">All field sources</option>
              {sources.map((stream: any) => (
                <option key={stream.source} value={stream.source}>
                  {stream.source} · {stream.samples} samples
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              disabled={
                busy ||
                !sources.find((s) => s.source === source)?.ended ||
                status.jobs.some(
                  (job: any) => job.source === source && job.running,
                )
              }
              onClick={() =>
                action(async () => {
                  const result = await api("/field-trends/retire", { source });
                  if (result.audit_error) setError(result.audit_error);
                  setSource("");
                  setAfter(0);
                  setPages([]);
                })
              }
            >
              Delete ended field history
            </button>
            <span className="help-text">
              Deletes saved samples and the selected ended source marker.
              Acquisition log events remain.
            </span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Source / signal</th>
                <th>Acquired UTC</th>
                <th>Received UTC</th>
                <th>Value</th>
                <th>Quality</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((sample) => (
                <tr key={sample.sequence}>
                  <td>
                    {sample.source}
                    <br />
                    {sample.signal}
                  </td>
                  <td>{sample.clock}</td>
                  <td>{sample.recorded_at}</td>
                  <td>{showValue(sample.value)}</td>
                  <td>{sample.quality}</td>
                  <td>{sample.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card-body button-row">
          <button
            disabled={!pages.length}
            onClick={() => {
              setAfter(pages.at(-1)!);
              setPages(pages.slice(0, -1));
            }}
          >
            Previous field page
          </button>
          <span>{samples.length} samples shown</span>
          <button
            disabled={samples.length < 100}
            onClick={() => {
              setPages([...pages, after]);
              setAfter(samples.at(-1).sequence);
            }}
          >
            Next field page
          </button>
        </div>
      </section>
      <section className="card" aria-label="Field acquisition events">
        <div className="card-header">
          <h3>Acquisition log</h3>
        </div>
        <div className="card-body">
          <pre className="result">
            {events.length
              ? JSON.stringify(events, null, 2)
              : "No acquisition events recorded."}
          </pre>
        </div>
      </section>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
