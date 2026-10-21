import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

function cell(value: unknown) {
  let text =
    value == null
      ? ""
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  if (typeof value === "string" && /^\s*[=+@-]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
export function MultipleHistoryPanel() {
  const [status, setStatus] = useState<any>(null);
  const [fields, setFields] = useState({
    address: "",
    device: "",
    object_id: "trend-log-multiple,1",
    router: "",
    dnet: "",
    device_timezone: "",
    mode: "sequence",
    reference: "1",
    reference_time: "",
    count: "100",
    page_size: "25",
    fold: "",
  });
  const [report, setReport] = useState<any>(null);
  const [capture, setCapture] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const operation = useRef<string | null>(null);
  const mounted = useRef(false);
  const epoch = useRef(0);
  const statusRequest = useRef(0);
  function cancelDetached() {
    if (operation.current)
      void api("/bacnet/history-multiple/cancel", {
        operation_id: operation.current,
      }).catch(() => {});
  }
  async function refresh() {
    const request = ++statusRequest.current;
    const next = await api("/bacnet/history-multiple/status");
    if (mounted.current && request === statusRequest.current) setStatus(next);
  }
  useEffect(() => {
    mounted.current = true;
    void refresh().catch((failure) => {
      if (mounted.current) setError(String(failure));
    });
    return () => {
      mounted.current = false;
      epoch.current++;
      statusRequest.current++;
      cancelDetached();
    };
  }, []);
  function edit(key: keyof typeof fields, value: string) {
    if (busy) return;
    epoch.current++;
    setFields((old) => ({ ...old, [key]: value }));
    setReport(null);
    setOffset(0);
    setError("");
    setMessage("");
  }
  async function read(continuation = false) {
    if (busy || operation.current) return;
    const generation = ++epoch.current,
      identifier = crypto.randomUUID().replaceAll("-", "");
    operation.current = identifier;
    setBusy(true);
    setError("");
    setMessage("");
    setReport(null);
    setOffset(0);
    try {
      if (!fields.address.trim() || !fields.device.trim())
        throw new Error("Enter an exact address and Device identifier.");
      const payload: any = {
        operation_id: identifier,
        address: fields.address.trim(),
        device: fields.device.trim(),
        object_id: fields.object_id.trim(),
        ...(fields.device_timezone.trim()
          ? { device_timezone: fields.device_timezone.trim() }
          : {}),
        mode: fields.mode,
        count: Number(fields.count),
        page_size: Number(fields.page_size),
        ...(fields.fold ? { fold: Number(fields.fold) } : {}),
        ...(fields.router.trim() || fields.dnet.trim()
          ? { router: fields.router.trim(), dnet: Number(fields.dnet) }
          : {}),
        ...(fields.mode === "time"
          ? { reference_time: fields.reference_time + "Z" }
          : { reference: Number(fields.reference) }),
      };
      if (continuation) {
        if (!report?.next_cursor)
          throw new Error("No native continuation anchor is available.");
        delete payload.reference_time;
        Object.assign(payload, report.next_cursor);
      }
      const result = await api("/bacnet/history-multiple/read", payload);
      if (mounted.current && generation === epoch.current) setReport(result);
    } catch (failure) {
      if (mounted.current && generation === epoch.current)
        setError(String(failure));
    } finally {
      if (operation.current === identifier) operation.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  async function localAction(kind: "refresh" | "save" | "load") {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (kind === "save") {
        await api("/bacnet/history-multiple/save", { id: report.id });
        setMessage(
          "Saved a sealed local Trend Log Multiple capture. Repeated saves retain the original evidence.",
        );
      } else if (kind === "load") {
        const saved = await api("/bacnet/history-multiple/captures/" + capture);
        if (mounted.current) {
          setReport(saved);
          setOffset(0);
          const source = saved.request;
          setFields({
            address: source.address,
            device: source.device,
            object_id: source.object_id,
            router: source.router ?? "",
            dnet: source.dnet == null ? "" : String(source.dnet),
            device_timezone: source.device_timezone ?? "",
            mode: source.mode,
            reference: source.reference == null ? "" : String(source.reference),
            reference_time: source.reference_time
              ? new Date(source.reference_time).toISOString().slice(0, -1)
              : "",
            count: String(source.count),
            page_size: String(source.page_size),
            fold: source.fold == null ? "" : String(source.fold),
          });
        }
      }
      await refresh();
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function exportJson() {
    if (report)
      saveBlob(
        new Blob([JSON.stringify(report, null, 2)], {
          type: "application/json",
        }),
        `bacnet-multiple-history-${report.id}.json`,
      );
  }
  function exportCsv() {
    if (!report) return;
    const columns = [
      "source_kind",
      "report_id",
      "report_sha256",
      "address",
      "device",
      "router",
      "dnet",
      "object_id",
      "report_status",
      "complete",
      "records_complete",
      "truncated",
      "errors",
      "warnings",
      "next_cursor",
      "timezone",
      "channel_reference_basis",
      "channel_reference_consistency",
      "sequence",
      "native_timestamp",
      "source_clock_utc",
      "received_at_utc",
      "datum_type",
      "record_reference_alignment",
      "native_channel_count",
      "channel_index",
      "current_channel_reference",
      "channel_datum_type",
      "native_value",
      "quality",
      "quality_basis",
      "raw_record",
    ];
    const rows = report.records.flatMap((row: any) =>
      (row.channels.length ? row.channels : [null]).map((channel: any) => [
        report.source_kind,
        report.id,
        report.evidence_sha256,
        report.target.address,
        report.target.device,
        report.target.router,
        report.target.dnet,
        report.target.object_id,
        report.status,
        report.complete,
        report.records_complete,
        report.truncated,
        report.errors,
        report.warnings,
        report.next_cursor,
        report.timezone,
        report.channel_reference_basis,
        report.channel_reference_consistency,
        row.sequence,
        row.local_timestamp,
        row.source_clock,
        row.recorded_at,
        row.datum_type,
        row.reference_alignment,
        row.channel_count,
        channel?.index,
        channel?.reference,
        channel?.datum_type,
        channel?.raw ?? row.log_status ?? row.time_change,
        channel?.quality ?? row.quality,
        channel?.quality_basis ?? row.quality_basis,
        row.raw,
      ]),
    );
    if (!rows.length)
      rows.push([
        report.source_kind,
        report.id,
        report.evidence_sha256,
        report.target.address,
        report.target.device,
        report.target.router,
        report.target.dnet,
        report.target.object_id,
        report.status,
        report.complete,
        report.records_complete,
        report.truncated,
        report.errors,
        report.warnings,
        report.next_cursor,
        report.timezone,
        report.channel_reference_basis,
        report.channel_reference_consistency,
        ...Array(14).fill(null),
      ]);
    saveBlob(
      new Blob(
        [
          "\ufeff" +
            [columns, ...rows]
              .map((row) => row.map(cell).join(","))
              .join("\r\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
      `bacnet-multiple-history-${report.id}.csv`,
    );
  }
  const input = (
    key: keyof typeof fields,
    label: string,
    type = "text",
    placeholder = "",
  ) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={fields[key]}
        type={type}
        placeholder={placeholder}
        step={type === "datetime-local" ? "0.01" : undefined}
        onChange={(event) => edit(key, event.target.value)}
      />
    </label>
  );
  return (
    <section
      className="temco-card"
      aria-label="BACnet Trend Log Multiple history"
    >
      <h2>Multiple-channel device history</h2>
      <p>
        Explicitly read standard Trend Log Multiple objects through the current
        BACnet/IP interface or a pinned IP router. Native channels, nulls,
        failures, clock changes, and log status remain distinct. This is not a
        proprietary JCI history or device/program backup.
      </p>
      <p>
        Historical channel quality is unknown because this native record type
        has no per-channel historical status flags. Current channel references
        do not establish historical wiring or channel assignments. Leave the
        clock timezone blank to preserve unresolved native date/time without
        inventing UTC.
      </p>
      <p>
        Shared interface: {status?.connected ? "connected" : "not connected"}.
        No automatic polling or device writes.
      </p>
      <fieldset disabled={busy}>
        <legend>Exact multiple-channel source and range</legend>
        <div className="temco-actions">
          {input(
            "address",
            "Multiple history device address",
            "text",
            "IPv4:port or DNET:MAC",
          )}
          {input(
            "device",
            "Multiple history Device object",
            "text",
            "device,1234",
          )}
          {input("object_id", "Multiple history Trend Log object")}
          {input(
            "router",
            "Multiple history router",
            "text",
            "Explicit IPv4 next hop",
          )}
          {input("dnet", "Multiple history DNET", "number")}
          {input(
            "device_timezone",
            "Multiple history clock timezone",
            "text",
            "Optional IANA zone",
          )}
        </div>
        <div className="temco-actions">
          <label>
            Multiple history range mode
            <select
              value={fields.mode}
              onChange={(event) => edit("mode", event.target.value)}
            >
              <option value="sequence">Sequence number</option>
              <option value="position">List position</option>
              <option value="time">Recorded time</option>
            </select>
          </label>
          {fields.mode === "time"
            ? input(
                "reference_time",
                "Multiple history reference time UTC",
                "datetime-local",
              )
            : input("reference", "Multiple history range reference", "number")}
          {input("count", "Multiple history record limit", "number")}
          {input("page_size", "Multiple history page size", "number")}
          <label>
            Multiple history DST fold
            <select
              value={fields.fold}
              onChange={(event) => edit("fold", event.target.value)}
            >
              <option value="">Leave ambiguous clocks unresolved</option>
              <option value="0">First occurrence</option>
              <option value="1">Second occurrence</option>
            </select>
          </label>
        </div>
      </fieldset>
      <div className="temco-actions">
        <button
          disabled={busy || !status?.connected}
          onClick={() => void read()}
        >
          Read multiple-channel history
        </button>
        <button
          disabled={busy || !status?.connected || !report?.next_cursor}
          onClick={() => void read(true)}
        >
          Read next multiple-history range
        </button>
        <button disabled={!operation.current} onClick={cancelDetached}>
          Cancel multiple-history read
        </button>
        <button disabled={busy} onClick={() => void localAction("refresh")}>
          Refresh multiple-history status
        </button>
        <button
          disabled={busy || !report}
          onClick={() => void localAction("save")}
        >
          Save multiple-history capture
        </button>
        <button disabled={busy || !report} onClick={exportJson}>
          Export multiple-history JSON
        </button>
        <button disabled={busy || !report} onClick={exportCsv}>
          Export multiple-history CSV
        </button>
      </div>
      <div className="temco-actions">
        <label>
          Saved multiple-history capture
          <select
            aria-label="Saved multiple-history capture"
            disabled={busy}
            value={capture}
            onChange={(event) => setCapture(event.target.value)}
          >
            <option value="">Choose a sealed local capture</option>
            {status?.captures.map((item: any) => (
              <option key={item.id} value={item.id}>
                {item.target.object_id} at {item.target.address} ·{" "}
                {item.records} records · {item.read_at}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={busy || !capture}
          onClick={() => void localAction("load")}
        >
          Load multiple-history capture
        </button>
      </div>
      {busy && (
        <p role="status">
          Reading the selected source or local capture. Operations are bounded;
          completed native pages remain evidence.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {report && (
        <section aria-label="Multiple history evidence">
          <p role="status">
            {report.status} · {report.records.length} native records ·{" "}
            {report.pages.length} pages · identity{" "}
            {report.identity_verified ? "verified" : "unverified"} ·{" "}
            {report.complete ? "complete" : "incomplete"}
          </p>
          <p>
            {report.target.device} / {report.target.object_id} at{" "}
            {report.target.address}
            {report.target.router
              ? ` through ${report.target.router}, DNET ${report.target.dnet}`
              : ""}
            . Clock: {report.timezone?.name ?? "unresolved native time"}.
          </p>
          {report.errors.map((value: string, index: number) => (
            <p key={index}>{value}</p>
          ))}
          {report.warnings.map((value: string, index: number) => (
            <p key={index}>{value}</p>
          ))}
          <p>
            Current reference coherence: {report.channel_reference_consistency}.
            Native range completion: {String(report.records_complete)}. Matching
            current snapshots do not prove historical assignments.
          </p>
          <details>
            <summary>Current channel-reference metadata</summary>
            <pre>
              {JSON.stringify(
                {
                  basis: report.channel_reference_basis,
                  references: report.channel_references,
                  recheck: report.channel_reference_recheck,
                  metadata: report.metadata,
                },
                null,
                2,
              )}
            </pre>
          </details>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Sequence</th>
                  <th>Native date/time</th>
                  <th>Interpreted UTC</th>
                  <th>Native record choice</th>
                  <th>Channels and values</th>
                </tr>
              </thead>
              <tbody>
                {report.records
                  .slice(offset, offset + 50)
                  .map((row: any, index: number) => (
                    <tr key={index}>
                      <td>{row.sequence ?? "unavailable"}</td>
                      <td>
                        {row.reference_alignment && (
                          <p>{row.reference_alignment}</p>
                        )}
                        {JSON.stringify(row.local_timestamp)}
                        {row.timestamp_error && <p>{row.timestamp_error}</p>}
                      </td>
                      <td>{row.source_clock ?? "unresolved"}</td>
                      <td>{row.datum_type}</td>
                      <td>
                        {row.channels.map((channel: any) => (
                          <p key={channel.index}>
                            Channel {channel.index}: {channel.datum_type}{" "}
                            {JSON.stringify(channel.raw.value)} · quality{" "}
                            {channel.quality}
                          </p>
                        ))}
                        {row.log_status && (
                          <p>{JSON.stringify(row.log_status)}</p>
                        )}
                        {row.time_change !== undefined && (
                          <p>
                            {JSON.stringify(row.time_change)} seconds clock
                            adjustment
                          </p>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <div className="temco-actions">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous multiple-history rows
            </button>
            <span>
              {report.records.length ? offset + 1 : 0}–
              {Math.min(offset + 50, report.records.length)} of{" "}
              {report.records.length}
            </span>
            <button
              disabled={offset + 50 >= report.records.length}
              onClick={() => setOffset(offset + 50)}
            >
              Next multiple-history rows
            </button>
          </div>
          <details>
            <summary>Native multiple-history evidence and provenance</summary>
            <pre>{JSON.stringify(report, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
