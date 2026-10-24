import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";
import { BacnetEventAckPanel } from "./BacnetEventAckPanel";
import "./bacnet-events.css";

type EventRow = {
  object_id: string;
  event_state: { value: unknown; name: string };
  notify_type: { value: unknown; name: string };
  acknowledged_transitions: Record<string, boolean>;
  event_enable: Record<string, boolean>;
  event_priorities: Record<string, number>;
  event_timestamps: {
    transition: string;
    raw: unknown;
    source_clock_utc: null;
    clock_status: string;
  }[];
  quality: string;
  received_at: string;
  raw: unknown;
};

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

export function BacnetEventsPanel({
  connected,
  defaultAddress,
  defaultDevice,
  defaultRouter = "",
  defaultDnet = null,
}: {
  connected: boolean;
  defaultAddress: string;
  defaultDevice: string;
  defaultRouter?: string;
  defaultDnet?: number | null;
}) {
  const [address, setAddress] = useState(defaultAddress);
  const [device, setDevice] = useState(defaultDevice);
  const [router, setRouter] = useState(defaultRouter);
  const [dnet, setDnet] = useState(
    defaultDnet === null ? "" : String(defaultDnet),
  );
  const [pages, setPages] = useState("1");
  const [profile, setProfile] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [selected, setSelected] = useState<EventRow | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [ackBusy, setAckBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const mounted = useRef(false);
  const epoch = useRef(0);
  const operation = useRef<string | null>(null);

  function cancelDetached() {
    if (operation.current)
      void api("/bacnet/events/cancel", {
        operation_id: operation.current,
      }).catch(() => {});
  }
  useEffect(() => {
    mounted.current = true;
    api("/bacnet/events/profile")
      .then((value) => {
        if (mounted.current) setProfile(value);
      })
      .catch((failure) => {
        if (mounted.current) setError(String(failure));
      });
    return () => {
      mounted.current = false;
      epoch.current++;
      cancelDetached();
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    cancelDetached();
    setAddress(defaultAddress);
    setDevice(defaultDevice);
    setRouter(defaultRouter);
    setDnet(defaultDnet === null ? "" : String(defaultDnet));
    setReport(null);
    setSelected(null);
    setOffset(0);
    setError("");
    setMessage("");
  }, [connected, defaultAddress, defaultDevice, defaultRouter, defaultDnet]);

  function edit(change: () => void) {
    if (operation.current) return;
    epoch.current++;
    setReport(null);
    setSelected(null);
    setOffset(0);
    setError("");
    setMessage("");
    change();
  }
  async function read(resume = false) {
    if (!connected || operation.current || ackBusy) return;
    const generation = ++epoch.current;
    let identifier: string | null = null;
    setError("");
    setMessage("");
    try {
      const pageCount = Number(pages),
        network = Number(dnet);
      if (!address.trim() || !device.trim())
        throw new Error(
          "Enter the explicit address and Device object identifier.",
        );
      if (!Number.isInteger(pageCount) || pageCount < 1 || pageCount > 5)
        throw new Error("Read 1 through 5 device pages per request.");
      if (
        !!router.trim() !== !!dnet.trim() ||
        (dnet.trim() &&
          (!Number.isInteger(network) || network < 1 || network > 65534))
      )
        throw new Error(
          "Routed queries require both an explicit router and DNET from 1 through 65534.",
        );
      if (resume && !report?.next_cursor)
        throw new Error("No unused continuation cursor is available.");
      identifier = crypto.randomUUID().replaceAll("-", "");
      operation.current = identifier;
      setBusy(true);
      setSelected(null);
      if (!resume) setReport(null);
      const result = await api("/bacnet/events/read", {
        address: address.trim(),
        device: device.trim(),
        ...(router.trim() ? { router: router.trim(), dnet: network } : {}),
        operation_id: identifier,
        pages_per_request: pageCount,
        ...(resume
          ? { report_id: report.id, cursor: report.next_cursor.token }
          : {}),
      });
      if (mounted.current && generation === epoch.current) {
        setReport(result);
        setOffset(0);
      }
    } catch (failure) {
      if (mounted.current && generation === epoch.current)
        setError(String(failure));
    } finally {
      if (operation.current === identifier) operation.current = null;
      if (mounted.current) {
        setBusy(false);
        setCancelling(false);
      }
    }
  }
  async function cancel() {
    if (!operation.current || cancelling) return;
    const identifier = operation.current;
    setCancelling(true);
    try {
      const outcome = await api("/bacnet/events/cancel", {
        operation_id: identifier,
      });
      if (mounted.current)
        setMessage(
          outcome.cancel_requested
            ? "Cancellation requested. Completed pages remain evidence."
            : "The operation finished or was cancelled before admission.",
        );
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    } finally {
      if (mounted.current) setCancelling(false);
    }
  }
  function exportJson() {
    if (!report || busy) return;
    saveBlob(
      new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
      `bacnet-events-${report.id}.json`,
    );
  }
  function exportCsv() {
    if (!report || busy) return;
    const columns = [
      "source_kind",
      "report_id",
      "report_sha256",
      "address",
      "device",
      "router",
      "dnet",
      "report_status",
      "report_outcome",
      "report_complete",
      "identity_verified",
      "report_started_at_utc",
      "report_finished_at_utc",
      "report_event_count",
      "report_page_count",
      "object_id",
      "event_state",
      "notify_type",
      "acknowledged_transitions",
      "event_enable",
      "event_priorities",
      "event_timestamps_raw",
      "received_at_utc",
      "quality",
      "raw_summary",
      "report_errors",
      "report_next_cursor",
      "report_consistency",
      "timestamp_basis",
      "acknowledgement_basis",
      "report_scope",
    ];
    const rows = (report.events.length ? report.events : [null]).map(
      (value: EventRow | null) => [
        report.source_kind,
        report.id,
        report.evidence_sha256,
        report.target.address,
        report.target.device,
        report.target.router,
        report.target.dnet,
        report.status,
        report.outcome,
        report.complete,
        report.identity_verified,
        report.started_at,
        report.finished_at,
        report.events.length,
        report.pages.length,
        value?.object_id,
        value?.event_state,
        value?.notify_type,
        value?.acknowledged_transitions,
        value?.event_enable,
        value?.event_priorities,
        value?.event_timestamps,
        value?.received_at,
        value?.quality,
        value?.raw,
        report.errors,
        report.next_cursor,
        report.consistency,
        report.timestamp_basis,
        report.acknowledgement_basis,
        report.scope,
      ],
    );
    const text =
      "\ufeff" +
      [columns, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
    saveBlob(
      new Blob([text], { type: "text/csv;charset=utf-8" }),
      `bacnet-events-${report.id}.csv`,
    );
  }

  return (
    <section className="card bacnet-events" aria-label="BACnet field events">
      <div className="card-header">
        <h2>Device event states</h2>
      </div>
      <p>
        Explicitly read BACnet GetEventInformation. These are device
        EventSummary states and transition acknowledgement bits. Normal states
        may still have unacknowledged transitions.
      </p>
      <p>
        This query does not subscribe, acknowledge events, or deliver alarms.
        Support depends on the selected device; a timeout or unsupported reply
        does not mean no alarms exist.
      </p>
      {!connected && (
        <p>Open a BACnet/IP interface in Connect before querying events.</p>
      )}
      <fieldset disabled={busy || ackBusy}>
        <legend>Exact event source</legend>
        <div className="bacnet-events-fields">
          <label>
            Event device address
            <input
              value={address}
              placeholder="IPv4:port or DNET:MAC"
              onChange={(event) => edit(() => setAddress(event.target.value))}
            />
          </label>
          <label>
            Event Device object
            <input
              value={device}
              placeholder="device,1234"
              onChange={(event) => edit(() => setDevice(event.target.value))}
            />
          </label>
          <label>
            Event router (routed queries)
            <input
              value={router}
              placeholder="Explicit IPv4 next hop"
              onChange={(event) => edit(() => setRouter(event.target.value))}
            />
          </label>
          <label>
            Event DNET (routed queries)
            <input
              value={dnet}
              inputMode="numeric"
              onChange={(event) => edit(() => setDnet(event.target.value))}
            />
          </label>
          <label>
            Event pages per request
            <input
              value={pages}
              type="number"
              min={1}
              max={5}
              onChange={(event) => setPages(event.target.value)}
            />
          </label>
        </div>
      </fieldset>
      <div className="bacnet-events-actions">
        <button
          className="primary"
          disabled={!connected || busy || ackBusy}
          onClick={() => void read()}
        >
          Query device events
        </button>
        <button
          disabled={!connected || busy || ackBusy || !report?.next_cursor}
          onClick={() => void read(true)}
        >
          Continue event query
        </button>
        <button disabled={!busy || cancelling} onClick={() => void cancel()}>
          Cancel event query
        </button>
        <button disabled={!report || busy} onClick={exportJson}>
          Export event JSON
        </button>
        <button disabled={!report || busy} onClick={exportCsv}>
          Export event CSV
        </button>
      </div>
      {profile && (
        <p>
          Bounded to {profile.limits.pages_per_report} pages,{" "}
          {profile.limits.events} events, {profile.limits.operation_seconds}s
          per request; continuation expires after{" "}
          {profile.limits.cursor_seconds}s. No automatic polling.
        </p>
      )}
      {busy && (
        <p role="status" aria-label="Event query progress">
          Reading the selected device's event summaries…
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      {report && (
        <div aria-label="Device event evidence">
          <p role="status" aria-label="Event query result">
            <b>{report.status}</b> · {report.outcome} · {report.events.length}{" "}
            event summaries · {report.pages.length} device pages · Device
            identity {report.identity_verified ? "verified" : "unverified"}
          </p>
          <p>
            Source: {report.target.device} at {report.target.address}
            {report.target.router
              ? ` through ${report.target.router} / DNET ${report.target.dnet}`
              : ""}
            . Last request finished {report.finished_at}.
          </p>
          {report.complete && report.events.length === 0 && (
            <p>
              The device returned an empty complete GetEventInformation list.
            </p>
          )}
          {report.next_cursor && (
            <p>
              More events reported. Continue explicitly using the unused cursor
              after {report.next_cursor.last_received_object_identifier}.
            </p>
          )}
          {report.errors.map((failure: any, index: number) => (
            <p key={index} className="bacnet-events-error">
              {failure.status}: {failure.error} ({failure.received_at})
            </p>
          ))}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Object</th>
                  <th>Device event state</th>
                  <th>Notify type</th>
                  <th>Acknowledged transitions</th>
                  <th>Received UTC</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {report.events
                  .slice(offset, offset + 50)
                  .map((value: EventRow) => (
                    <tr key={value.object_id}>
                      <td>{value.object_id}</td>
                      <td>
                        {value.event_state.name} (
                        {JSON.stringify(value.event_state.value)})
                      </td>
                      <td>{value.notify_type.name}</td>
                      <td>
                        {Object.entries(value.acknowledged_transitions)
                          .map(
                            ([key, acknowledged]) =>
                              `${key}: ${acknowledged ? "yes" : "no"}`,
                          )
                          .join(" · ")}
                      </td>
                      <td>{value.received_at}</td>
                      <td>
                        <button
                          disabled={ackBusy}
                          onClick={() => setSelected(value)}
                        >
                          Inspect event {value.object_id}
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {report.events.length > 50 && (
            <div className="bacnet-events-actions">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous event rows
              </button>
              <span>
                {offset + 1}–{Math.min(offset + 50, report.events.length)} of{" "}
                {report.events.length}
              </span>
              <button
                disabled={offset + 50 >= report.events.length}
                onClick={() => setOffset(offset + 50)}
              >
                Next event rows
              </button>
            </div>
          )}
          {selected && (
            <section aria-label="Selected native event summary">
              <h3>{selected.object_id} native evidence</h3>
              <p>
                Device timestamp choices and wildcard fields remain raw. Receipt
                time is local UTC. Quality: {selected.quality}.
              </p>
              <pre>{JSON.stringify(selected, null, 2)}</pre>
            </section>
          )}
          <details>
            <summary>Inspect report provenance and cursor evidence</summary>
            <pre>
              {JSON.stringify({ ...report, events: undefined }, null, 2)}
            </pre>
          </details>
        </div>
      )}
      <BacnetEventAckPanel
        connected={connected}
        report={report}
        selected={selected}
        parentBusy={busy}
        onBusy={setAckBusy}
        onAttempt={() => {
          setReport(null);
          setSelected(null);
        }}
      />
    </section>
  );
}
