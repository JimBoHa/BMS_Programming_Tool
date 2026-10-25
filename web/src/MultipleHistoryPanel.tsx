import { useEffect, useRef, useState } from "react";
import { api, saveBlob, type JsonDocument } from "./api";
import { historyEvidence, historyVisible } from "./historyEvidence";
import type { ControllerTarget } from "./workflow";

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
export function MultipleHistoryPanel({
  eventLog = false,
  defaultTarget,
}: {
  eventLog?: boolean;
  defaultTarget?: ControllerTarget | null;
}) {
  const endpoint = eventLog ? "/bacnet/event-log" : "/bacnet/history-multiple";
  const filePrefix = eventLog
    ? "bacnet-event-log-history"
    : "bacnet-multiple-history";
  function label(value: string) {
    return eventLog
      ? value
          .replaceAll(
            "BACnet Trend Log Multiple history",
            "BACnet Event Log history",
          )
          .replaceAll("Multiple history Trend Log object", "Event log object")
          .replaceAll(
            "Multiple history clock timezone",
            "Event log logger timezone",
          )
          .replaceAll(
            "Multiple-channel device history",
            "Native Event Log history",
          )
          .replaceAll("Trend Log Multiple", "Event Log")
          .replaceAll("Multiple history", "Event log")
          .replaceAll("multiple-channel", "event-log")
          .replaceAll("multiple-history", "event-log")
      : value;
  }
  const [status, setStatus] = useState<any>(null);
  const [fields, setFields] = useState({
    address: defaultTarget?.address || "",
    device: defaultTarget?.device || "",
    object_id: eventLog ? "event-log,1" : "trend-log-multiple,1",
    router: defaultTarget?.router || "",
    dnet: defaultTarget?.dnet == null ? "" : String(defaultTarget.dnet),
    device_timezone: "",
    mode: "sequence",
    reference: "1",
    reference_time: "",
    count: "100",
    page_size: "25",
    fold: "",
  });
  const [document, setDocument] = useState<JsonDocument | null>(null);
  const report = document?.data ?? null;
  const [capture, setCapture] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const operation = useRef<string | null>(null);
  const mounted = useRef(false);
  const epoch = useRef(0);
  const statusRequest = useRef(0);
  const panel = useRef<HTMLElement>(null);
  function cancelDetached() {
    if (operation.current)
      void api(endpoint + "/cancel", {
        operation_id: operation.current,
      }).catch(() => {});
  }
  async function refresh() {
    const request = ++statusRequest.current;
    const next = await api(endpoint + "/status");
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
    setDocument(null);
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
    setDocument(null);
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
      const result = await historyEvidence(
        endpoint + "/read",
        eventLog ? "event-log" : "trend-log-multiple",
        payload,
      );
      if (mounted.current && generation === epoch.current) setDocument(result);
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
    const generation = epoch.current;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (kind === "save") {
        await api(endpoint + "/save", { id: report.id });
        setMessage(
          label(
            "Saved a sealed local Trend Log Multiple capture. Repeated saves retain the original evidence.",
          ),
        );
      } else if (kind === "load") {
        setDocument(null);
        const original = await historyEvidence(
          endpoint + "/captures/" + capture,
          eventLog ? "event-log" : "trend-log-multiple",
          undefined,
          capture,
        );
        const saved = original.data;
        if (mounted.current && generation === epoch.current) {
          setDocument(original);
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
    if (document && !busy && mounted.current && historyVisible(panel.current))
      saveBlob(document.blob, `${filePrefix}-${document.data.id}.json`);
  }
  function exportEventCsv() {
    const common = {
      source_kind: report.source_kind,
      report_id: report.id,
      report_sha256: report.evidence_sha256,
      address: report.target.address,
      device: report.target.device,
      router: report.target.router,
      dnet: report.target.dnet,
      event_log_object: report.target.object_id,
      report_status: report.status,
      complete: report.complete,
      records_complete: report.records_complete,
      truncated: report.truncated,
      errors: report.errors,
      warnings: report.warnings,
      next_cursor: report.next_cursor,
      logger_timezone: report.timezone,
      current_configuration_basis: report.current_configuration_basis,
      current_configuration_consistency:
        report.current_configuration_consistency,
    };
    const recordColumns = [
      "export_row_kind",
      "sequence",
      "logger_native_timestamp",
      "logger_interpreted_utc",
      "read_receipt_utc",
      "datum_type",
      "process_identifier",
      "initiating_device",
      "event_object",
      "notification_class",
      "priority",
      "event_type",
      "notify_type",
      "ack_required",
      "from_state",
      "to_state",
      "embedded_event_timestamp",
      "embedded_event_utc",
      "native_event_values",
      "message_text",
      "log_status",
      "time_change",
      "quality",
      "quality_basis",
      "raw_record",
      "undecoded_page",
    ];
    const columns = [...Object.keys(common), ...recordColumns];
    const rows: Record<string, unknown>[] = report.records.map((row: any) => ({
      ...common,
      export_row_kind: "native_record",
      sequence: row.sequence,
      logger_native_timestamp: row.local_timestamp,
      logger_interpreted_utc: row.source_clock,
      read_receipt_utc: row.read_received_at,
      datum_type: row.datum_type,
      process_identifier: row.notification?.process_identifier,
      initiating_device: row.notification?.initiating_device,
      event_object: row.notification?.event_object,
      notification_class: row.notification?.notification_class,
      priority: row.notification?.priority,
      event_type: row.notification?.event_type,
      notify_type: row.notification?.notify_type,
      ack_required: row.notification?.ack_required,
      from_state: row.notification?.from_state,
      to_state: row.notification?.to_state,
      embedded_event_timestamp: row.notification?.event_timestamp.raw,
      embedded_event_utc: row.notification?.event_timestamp.source_clock_utc,
      native_event_values: row.notification?.event_values,
      message_text: row.notification?.message_text,
      log_status: row.log_status,
      time_change: row.time_change,
      quality: row.quality,
      quality_basis: row.quality_basis,
      raw_record: row.raw,
    }));
    for (const page of report.undecoded_pages ?? [])
      rows.push({
        ...common,
        export_row_kind: "undecoded_native_page",
        undecoded_page: page,
      });
    if (!rows.length)
      rows.push({ ...common, export_row_kind: "report_metadata" });
    saveBlob(
      new Blob(
        [
          "\ufeff" +
            [
              columns.map(cell).join(","),
              ...rows.map((row) =>
                columns.map((key) => cell(row[key])).join(","),
              ),
            ].join("\r\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
      `${filePrefix}-${report.id}.csv`,
    );
  }
  function exportCsv() {
    if (!report) return;
    if (eventLog) {
      exportEventCsv();
      return;
    }
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
      `${filePrefix}-${report.id}.csv`,
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
        readOnly={
          !!defaultTarget &&
          ["address", "device", "router", "dnet"].includes(key)
        }
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
      aria-label={label("BACnet Trend Log Multiple history")}
      ref={panel}
    >
      <h2>{label("Multiple-channel device history")}</h2>
      {eventLog ? (
        <>
          <p>
            Explicitly read recorded native Event Log notifications, log status
            and clock adjustments. A recorded notification does not prove
            delivery, human receipt, acknowledgement lifecycle or resolution. No
            unsolicited subscriptions or device writes are started.
          </p>
          <p>
            The outer logger timestamp, embedded event-source timestamp and
            local read receipt remain separate. An optional logger timezone
            never assigns a timezone to another initiating device. Current
            logger configuration is read-time evidence, not proven historical
            configuration.
          </p>
        </>
      ) : (
        <>
          <p>
            Explicitly read standard Trend Log Multiple objects through the
            current BACnet/IP interface or a pinned IP router. Native channels,
            nulls, failures, clock changes, and log status remain distinct. This
            is not a proprietary JCI history or device/program backup.
          </p>
          <p>
            Historical channel quality is unknown because this native record
            type has no per-channel historical status flags. Current channel
            references do not establish historical wiring or channel
            assignments. Leave the clock timezone blank to preserve unresolved
            native date/time without inventing UTC.
          </p>
        </>
      )}
      <p>
        Shared interface: {status?.connected ? "connected" : "not connected"}.
        No automatic polling or device writes.
      </p>
      <fieldset disabled={busy}>
        <legend>{label("Exact multiple-channel source and range")}</legend>
        <div className="temco-actions">
          {input(
            "address",
            label("Multiple history device address"),
            "text",
            "IPv4:port or DNET:MAC",
          )}
          {input(
            "device",
            label("Multiple history Device object"),
            "text",
            "device,1234",
          )}
          {input("object_id", label("Multiple history Trend Log object"))}
          {input(
            "router",
            label("Multiple history router"),
            "text",
            "Explicit IPv4 next hop",
          )}
          {input("dnet", label("Multiple history DNET"), "number")}
          {input(
            "device_timezone",
            label("Multiple history clock timezone"),
            "text",
            "Optional IANA zone",
          )}
        </div>
        <div className="temco-actions">
          <label>
            {label("Multiple history range mode")}
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
                label("Multiple history reference time UTC"),
                "datetime-local",
              )
            : input(
                "reference",
                label("Multiple history range reference"),
                "number",
              )}
          {input("count", label("Multiple history record limit"), "number")}
          {input("page_size", label("Multiple history page size"), "number")}
          <label>
            {label("Multiple history DST fold")}
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
          {label("Read multiple-channel history")}
        </button>
        <button
          disabled={busy || !status?.connected || !report?.next_cursor}
          onClick={() => void read(true)}
        >
          {label("Read next multiple-history range")}
        </button>
        <button disabled={!operation.current} onClick={cancelDetached}>
          {label("Cancel multiple-history read")}
        </button>
        <button disabled={busy} onClick={() => void localAction("refresh")}>
          {label("Refresh multiple-history status")}
        </button>
        <button
          disabled={busy || !report}
          onClick={() => void localAction("save")}
        >
          {label("Save multiple-history capture")}
        </button>
        <button disabled={busy || !report} onClick={exportJson}>
          {label("Export multiple-history JSON")}
        </button>
        <button disabled={busy || !report} onClick={exportCsv}>
          {label("Export multiple-history CSV")}
        </button>
      </div>
      <div className="temco-actions">
        <label>
          {label("Saved multiple-history capture")}
          <select
            aria-label={label("Saved multiple-history capture")}
            disabled={busy}
            value={capture}
            onChange={(event) => {
              epoch.current++;
              setDocument(null);
              setError("");
              setMessage("");
              setCapture(event.target.value);
            }}
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
          {label("Load multiple-history capture")}
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
        <p className="temco-muted">
          JSON preserves the original server response bytes, native numeric
          values and evidence seal. Browser display and CSV use formatted
          values.
        </p>
      )}
      {report && (
        <section aria-label={label("Multiple history evidence")}>
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
          {eventLog &&
            report.undecoded_pages?.map((page: any, index: number) => (
              <section key={index} aria-label="Uninterpreted native event page">
                <p>
                  Typed interpretation deferred. Native itemData:{" "}
                  {page.item_data_tags.bytes} bytes · SHA-256{" "}
                  {page.item_data_tags.sha256} · truncated:{" "}
                  {String(page.item_data_tags.truncated)}. No notification
                  records were guessed from this page.
                </p>
                <details>
                  <summary>Uninterpreted native page evidence</summary>
                  <pre>{JSON.stringify(page, null, 2)}</pre>
                </details>
              </section>
            ))}
          {eventLog ? (
            <p>
              Current logger configuration:{" "}
              {report.current_configuration_consistency}. Native range
              completion: {String(report.records_complete)}. Stored notification
              fields do not establish human receipt or resolution.
            </p>
          ) : (
            <p>
              Current reference coherence:{" "}
              {report.channel_reference_consistency}. Native range completion:{" "}
              {String(report.records_complete)}. Matching current snapshots do
              not prove historical assignments.
            </p>
          )}
          <details>
            <summary>
              {eventLog
                ? "Current logger configuration metadata"
                : "Current channel-reference metadata"}
            </summary>
            <pre>
              {JSON.stringify(
                eventLog
                  ? {
                      basis: report.current_configuration_basis,
                      before: report.metadata,
                      after: report.current_configuration_recheck,
                    }
                  : {
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
                  <th>
                    {eventLog
                      ? "Recorded native notification and values"
                      : "Channels and values"}
                  </th>
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
                        {(row.channels ?? []).map((channel: any) => (
                          <p key={channel.index}>
                            Channel {channel.index}: {channel.datum_type}{" "}
                            {JSON.stringify(channel.raw.value)} · quality{" "}
                            {channel.quality}
                          </p>
                        ))}
                        {row.notification && (
                          <>
                            <p>
                              {row.notification.initiating_device} ·{" "}
                              {row.notification.event_object} ·{" "}
                              {row.notification.notify_type.name}
                            </p>
                            <p>
                              Native event type{" "}
                              {row.notification.event_type.name} (
                              {row.notification.event_type.value}); state{" "}
                              {row.notification.from_state?.name ??
                                "not recorded"}{" "}
                              → {row.notification.to_state.name}; priority{" "}
                              {row.notification.priority}.
                            </p>
                            <p>
                              Embedded event timestamp:{" "}
                              <code>
                                {JSON.stringify(
                                  row.notification.event_timestamp.raw,
                                )}
                              </code>
                              . Source UTC unresolved.
                            </p>
                            {row.notification.message_text !== null && (
                              <p>{row.notification.message_text}</p>
                            )}
                            <details>
                              <summary>
                                Native recorded notification parameters
                              </summary>
                              <pre>
                                {JSON.stringify(row.notification, null, 2)}
                              </pre>
                            </details>
                          </>
                        )}
                        {eventLog && (
                          <p>Historical event quality: {row.quality}.</p>
                        )}
                        {row.status_decode_error && (
                          <p>{row.status_decode_error}</p>
                        )}
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
              {label("Previous multiple-history rows")}
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
              {label("Next multiple-history rows")}
            </button>
          </div>
          <details>
            <summary>
              {label("Native multiple-history evidence and provenance")}
            </summary>
            <pre>{JSON.stringify(report, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
