import { useEffect, useRef, useState } from "react";
import { Database, Download, History, RefreshCw, Save } from "lucide-react";
import { api, saveBlob, type JsonDocument } from "./api";
import { historyEvidence, historyVisible } from "./historyEvidence";
import { MultipleHistoryPanel } from "./MultipleHistoryPanel";
import "./temco-simulator.css";

type RecordValue = {
  sequence: number | null;
  source_clock: string | null;
  recorded_at: string;
  local_timestamp: { date: number[]; time: number[] };
  timestamp_error: string | null;
  datum_type: string;
  quality: string;
  sample: boolean;
  value?: unknown;
  status_flags: Record<string, boolean> | null;
  [key: string]: unknown;
};
type Report = {
  id: string;
  target: { address: string; object_id: string };
  request: Record<string, unknown>;
  source_kind: string;
  records: RecordValue[];
  read_at: string;
  received_at: string;
  complete: boolean;
  truncated: boolean;
  errors: string[];
  warnings: string[];
  next_cursor: { mode: string; reference: number } | null;
  scope: string;
  consistency?: string;
  [key: string]: unknown;
};

function csvCell(value: unknown) {
  let text =
    value === null || value === undefined
      ? ""
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  if (typeof value === "string" && /^[\s]*[=+@-]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}

export function DeviceHistory() {
  const [status, setStatus] = useState<any>(null);
  const [address, setAddress] = useState("");
  const [objectId, setObjectId] = useState("trend-log,1");
  const [zone, setZone] = useState("");
  const [mode, setMode] = useState("sequence");
  const [reference, setReference] = useState("1");
  const [referenceTime, setReferenceTime] = useState("");
  const [count, setCount] = useState("100");
  const [pageSize, setPageSize] = useState("25");
  const [fold, setFold] = useState("");
  const [document, setDocument] = useState<JsonDocument<Report> | null>(null);
  const report = document?.data ?? null;
  const [capture, setCapture] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const mounted = useRef(false);
  const generation = useRef(0);
  const statusRequest = useRef(0);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    mounted.current = true;
    refresh().catch((e) => {
      if (mounted.current) setError(String(e));
    });
    return () => {
      mounted.current = false;
      generation.current++;
      statusRequest.current++;
    };
  }, []);
  function invalidate() {
    generation.current++;
    setDocument(null);
    setMessage("");
    setError("");
    setOffset(0);
  }
  async function refresh() {
    const request = ++statusRequest.current;
    try {
      const value = await api("/bacnet/history/status");
      if (mounted.current && request === statusRequest.current)
        setStatus(value);
    } catch (e) {
      if (mounted.current && request === statusRequest.current) throw e;
    }
  }
  async function action(kind: "read" | "save" | "load" | "refresh") {
    if (busy) return;
    const current = generation.current;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let next: JsonDocument<Report> | null = null;
      if (kind === "read") {
        const requested = Number(count),
          size = Number(pageSize),
          anchor = Number(reference);
        if (!address.trim() || !zone.trim())
          throw new Error(
            "Enter the target address and the timezone used by the device clock.",
          );
        if (
          !Number.isInteger(requested) ||
          requested < 1 ||
          requested > 1000 ||
          !Number.isInteger(size) ||
          size < 1 ||
          size > 100
        )
          throw new Error(
            "History count must be 1..1000 and page size 1..100.",
          );
        if (
          mode === "time"
            ? !referenceTime
            : !reference ||
              !Number.isInteger(anchor) ||
              anchor < (mode === "position" ? 1 : 0) ||
              anchor > 4294967295
        )
          throw new Error(
            "Enter a valid range reference for the selected mode.",
          );
        setDocument(null);
        next = await historyEvidence<Report>(
          "/bacnet/history/read",
          "trend-log",
          {
            address: address.trim(),
            object_id: objectId.trim(),
            device_timezone: zone.trim(),
            mode,
            ...(mode === "time"
              ? { reference_time: referenceTime + "Z" }
              : { reference: anchor }),
            count: requested,
            page_size: size,
            ...(fold ? { fold: Number(fold) } : {}),
          },
        );
      } else if (kind === "save") {
        if (!report) throw new Error("Read history before saving a capture.");
        await api("/bacnet/history/save", { id: report.id });
        if (mounted.current)
          setMessage(
            "Saved an immutable local device-history capture. Repeated save retains the original evidence.",
          );
      } else if (kind === "load") {
        if (!capture) throw new Error("Choose a saved capture.");
        setDocument(null);
        next = await historyEvidence<Report>(
          "/bacnet/history/captures/" + capture,
          "trend-log",
          undefined,
          capture,
        );
      }
      if (!mounted.current || current !== generation.current) return;
      if (next) {
        setDocument(next);
        setOffset(0);
      }
      await refresh();
    } catch (e) {
      if (mounted.current && current === generation.current)
        setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function jsonDownload() {
    if (document && !busy && mounted.current && historyVisible(panel.current))
      saveBlob(
        document.blob,
        "bacnet-device-history-" + document.data.id + ".json",
      );
  }
  function csvDownload() {
    if (!report) return;
    const recordColumns = [
      "source_kind",
      "address",
      "object_id",
      "sequence",
      "source_clock_utc",
      "recorded_at_utc",
      "local_timestamp",
      "datum_type",
      "sample",
      "value",
      "quality",
      "status_flags",
      "timestamp_error",
    ];
    const provenanceColumns = [
      "export_row_kind",
      "report_id",
      "report_record_count",
      "report_read_at_utc",
      "report_received_at_utc",
      "device_timezone",
      "clock_fold",
      "timezone_provenance",
      "range_request",
      "report_complete",
      "report_truncated",
      "report_errors",
      "report_warnings",
      "next_cursor",
      "report_consistency",
      "report_scope",
    ];
    const provenance = [
      report.id,
      report.records.length,
      report.read_at,
      report.received_at,
      report.request.device_timezone,
      report.request.fold,
      report.timezone,
      report.request,
      report.complete,
      report.truncated,
      report.errors,
      report.warnings || [],
      report.next_cursor,
      report.consistency,
      report.scope,
    ];
    const rows: unknown[][] = report.records.map((row) => [
      report.source_kind,
      report.target.address,
      report.target.object_id,
      row.sequence,
      row.source_clock,
      row.recorded_at,
      row.local_timestamp,
      row.datum_type,
      row.sample,
      row.value,
      row.quality,
      row.status_flags,
      row.timestamp_error,
      "record",
      ...provenance,
    ]);
    if (!rows.length) {
      rows.push([
        report.source_kind,
        report.target.address,
        report.target.object_id,
        ...Array(recordColumns.length - 3).fill(null),
        "report_metadata",
        ...provenance,
      ]);
    }
    saveBlob(
      new Blob(
        [
          [[...recordColumns, ...provenanceColumns], ...rows]
            .map((row) => row.map(csvCell).join(","))
            .join("\r\n") + "\r\n",
        ],
        { type: "text/csv;charset=utf-8" },
      ),
      "bacnet-device-history-" + report.id + ".csv",
    );
  }
  function localText(row: RecordValue) {
    return JSON.stringify(row.local_timestamp);
  }

  return (
    <div className="workspace-page temco-simulator" ref={panel}>
      <div className="page-intro">
        <div>
          <span className="eyebrow">BACNET · EXISTING DEVICE HISTORY</span>
          <h1>Device history</h1>
          <p>
            Read stored Trend Log, Trend Log Multiple and Event Log records
            through the shared BACnet connection. Save explicit local captures
            without starting a polling job.
          </p>
        </div>
        <History size={30} />
      </div>
      <p className="temco-scope">
        BACnet log timestamps do not include a timezone. Single-value Trend Log
        reads require a device timezone; the other profiles can retain
        unresolved native clocks. Unresolved clock values and non-sample records
        remain visible with their original data. These captures stay separate
        from simulation and live field-trend databases.
      </p>
      {status?.storage && (
        <p className="temco-scope" aria-label="History storage durability">
          Local capture storage: {status.storage.durability}
        </p>
      )}
      <section className="temco-card" aria-label="BACnet history request">
        <h2>Addressed read-only request</h2>
        <p>
          Connect the intended interface in Connect, then refresh status here.
          Sequence mode provides a stable pagination anchor when the device
          supplies sequence metadata.
        </p>
        <p>
          Shared BACnet interface:{" "}
          {status
            ? status.connected
              ? "connected"
              : "not connected"
            : "checking…"}
        </p>
        <div className="temco-actions">
          <label style={{ maxWidth: 230 }}>
            History device address
            <input
              aria-label="History device address"
              placeholder="e.g. 192.0.2.10 or 2001:5"
              value={address}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setAddress(e.target.value);
              }}
            />
          </label>
          <label style={{ maxWidth: 190 }}>
            Trend Log object
            <input
              aria-label="History Trend Log object"
              value={objectId}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setObjectId(e.target.value);
              }}
            />
          </label>
          <label style={{ maxWidth: 240 }}>
            Device clock timezone
            <input
              aria-label="History device clock timezone"
              placeholder="e.g. America/Los_Angeles"
              value={zone}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setZone(e.target.value);
              }}
            />
          </label>
        </div>
        <div className="temco-actions">
          <label>
            Range mode
            <select
              aria-label="History range mode"
              value={mode}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setMode(e.target.value);
              }}
            >
              <option value="sequence">Sequence number</option>
              <option value="position">List position</option>
              <option value="time">Recorded time</option>
            </select>
          </label>
          {mode === "time" ? (
            <label className="temco-clock-label">
              Reference time (UTC)
              <input
                aria-label="History reference time UTC"
                type="datetime-local"
                step="0.01"
                value={referenceTime}
                disabled={busy}
                onChange={(e) => {
                  invalidate();
                  setReferenceTime(e.target.value);
                }}
              />
            </label>
          ) : (
            <label>
              Reference {mode === "position" ? "position" : "sequence"}
              <input
                aria-label="History range reference"
                type="number"
                min={mode === "position" ? 1 : 0}
                max="4294967295"
                step="1"
                value={reference}
                disabled={busy}
                onChange={(e) => {
                  invalidate();
                  setReference(e.target.value);
                }}
              />
            </label>
          )}
          <label>
            Record limit
            <input
              aria-label="History record limit"
              type="number"
              min="1"
              max="1000"
              step="1"
              value={count}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setCount(e.target.value);
              }}
            />
          </label>
          <label>
            Records per request
            <input
              aria-label="History page size"
              type="number"
              min="1"
              max="100"
              step="1"
              value={pageSize}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setPageSize(e.target.value);
              }}
            />
          </label>
          <label style={{ maxWidth: 230 }}>
            Repeated local hour
            <select
              aria-label="History ambiguous local hour"
              value={fold}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setFold(e.target.value);
              }}
            >
              <option value="">Preserve unresolved time</option>
              <option value="0">First occurrence (fold 0)</option>
              <option value="1">Second occurrence (fold 1)</option>
            </select>
          </label>
        </div>
        <div className="temco-actions">
          <button disabled={busy} onClick={() => action("refresh")}>
            <RefreshCw size={15} />
            Refresh history status
          </button>
          <button
            className="primary"
            disabled={busy || !status?.connected}
            onClick={() => action("read")}
          >
            <History size={15} />
            Read device history
          </button>
          {busy && (
            <span role="status">Working on the explicit history request…</span>
          )}
        </div>
      </section>
      <section
        className="temco-card"
        aria-label="Saved device history captures"
      >
        <h2>Saved local captures</h2>
        <div className="temco-actions">
          <label style={{ maxWidth: 620 }}>
            Capture
            <select
              aria-label="Saved device history capture"
              value={capture}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setCapture(e.target.value);
              }}
            >
              <option value="">Choose a capture…</option>
              {status?.captures.map((item: any) => (
                <option value={item.id} key={item.id}>
                  {item.read_at} · {item.target.address} ·{" "}
                  {item.target.object_id} · {item.records} records
                </option>
              ))}
            </select>
          </label>
          <button disabled={busy || !capture} onClick={() => action("load")}>
            <Database size={15} />
            Open history capture
          </button>
        </div>
        <p className="temco-muted">
          Only a report created by this server can be saved. Captures retain
          timestamps, quality, request parameters and partial-read evidence.
          Nothing is deleted automatically.
        </p>
      </section>
      {error && (
        <div className="temco-error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <p className="temco-result-match" role="status">
          {message}
        </p>
      )}
      {report && (
        <section className="temco-card" aria-label="Device history records">
          <h2>{report.records.length} device-history records</h2>
          <p
            className={
              report.complete &&
              !report.errors.length &&
              !report.warnings?.length
                ? "temco-result-match"
                : "temco-result-held"
            }
            role="status"
          >
            {report.errors.length
              ? "Partial history retained; review acquisition errors."
              : report.warnings?.length
                ? "History retrieved with sequence warnings."
                : report.complete
                  ? "Reached the end of the device log."
                  : "Requested record limit reached; additional history may exist."}
          </p>
          <p>
            {report.target.address} · {report.target.object_id} · captured{" "}
            {report.received_at}.{" "}
            {report.records.filter((row) => row.sample).length} sample records,{" "}
            {report.records.filter((row) => !row.sample).length} non-sample or
            unresolved records.
          </p>
          {report.errors.map((item, i) => (
            <p className="temco-error" key={i}>
              {item}
            </p>
          ))}
          {(report.warnings || []).map((item, i) => (
            <p className="temco-result-held" key={i}>
              {item}
            </p>
          ))}
          {report.consistency && (
            <p className="temco-scope">{report.consistency}</p>
          )}
          <div className="button-row">
            <button disabled={busy} onClick={() => action("save")}>
              <Save size={15} />
              Save immutable history capture
            </button>
            <button disabled={busy} onClick={jsonDownload}>
              <Download size={15} />
              Download device history JSON
            </button>
            <button onClick={csvDownload}>
              <Download size={15} />
              Download device history CSV
            </button>
          </div>
          <p className="temco-muted">
            JSON preserves the original server response bytes and native numeric
            values. Browser display and CSV use formatted values.
          </p>
          <p className="temco-muted">
            CSV repeats capture provenance on each row. Empty reports contain a
            metadata-only row with blank record values.
          </p>
          <div className="temco-table-wrap">
            <table className="temco-results">
              <thead>
                <tr>
                  <th>Sequence / source UTC</th>
                  <th>Device local timestamp</th>
                  <th>Recorded datum</th>
                  <th>Quality / evidence</th>
                </tr>
              </thead>
              <tbody>
                {report.records.slice(offset, offset + 100).map((row, i) => (
                  <tr key={offset + i}>
                    <td>
                      {row.sequence ?? "Unspecified sequence"}
                      <small>{row.source_clock || "Unresolved UTC time"}</small>
                    </td>
                    <td>
                      <code>{localText(row)}</code>
                      <small>Received {row.recorded_at}</small>
                    </td>
                    <td>
                      <b>{row.datum_type}</b>
                      <small>
                        {row.value === undefined
                          ? "No numeric/Boolean sample value"
                          : typeof row.value === "object"
                            ? JSON.stringify(row.value)
                            : String(row.value)}
                      </small>
                    </td>
                    <td>
                      {row.quality}
                      {row.timestamp_error && (
                        <small>{row.timestamp_error}</small>
                      )}
                      <details>
                        <summary>Inspect original record fields</summary>
                        <pre>{JSON.stringify(row, null, 2)}</pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 100))}
            >
              Previous history page
            </button>
            <span>
              {report.records.length ? offset + 1 : 0}–
              {Math.min(offset + 100, report.records.length)} of{" "}
              {report.records.length}
            </span>
            <button
              disabled={offset + 100 >= report.records.length}
              onClick={() => setOffset(offset + 100)}
            >
              Next history page
            </button>
          </div>
          <details>
            <summary>Request, cursor and timestamp provenance</summary>
            <pre>
              {JSON.stringify({ ...report, records: undefined }, null, 2)}
            </pre>
          </details>
        </section>
      )}
      <MultipleHistoryPanel />
      <MultipleHistoryPanel eventLog />
    </div>
  );
}
