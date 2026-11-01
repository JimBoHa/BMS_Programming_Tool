import { TargetFields } from "./ControllerWorkspace";
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiJsonDocument, download, saveBlob } from "./api";
import { ScheduleLibraryPanel } from "./ScheduleLibraryPanel";
import {
  scheduleDiagnostic,
  type ScheduleTraceFocus,
} from "./scheduleDiagnostic";
import "./schedule-inventory.css";
type Props = {
  connected: boolean;
  interfaceIdentity: string;
  defaultAddress: string;
  defaultDevice: string;
  defaultRouter?: string;
  defaultDnet?: number | null;
};
export function ScheduleInventoryPanel({
  connected,
  interfaceIdentity,
  defaultAddress,
  defaultDevice,
  defaultRouter = "",
  defaultDnet: suppliedDnet,
}: Props) {
  const defaultDnet = suppliedDnet ?? null;
  const [address, setAddress] = useState(defaultAddress),
    [device, setDevice] = useState(defaultDevice),
    [router, setRouter] = useState(defaultRouter),
    [dnet, setDnet] = useState(defaultDnet == null ? "" : String(defaultDnet));
  const [objects, setObjects] = useState(""),
    [offset, setOffset] = useState("0"),
    [limit, setLimit] = useState("64"),
    [maximum, setMaximum] = useState("4"),
    [clock, setClock] = useState(false),
    [includeTrace, setIncludeTrace] = useState(false),
    [traceObject, setTraceObject] = useState(""),
    [traceProperty, setTraceProperty] = useState(
      "list-of-object-property-references",
    ),
    [traceIndex, setTraceIndex] = useState("1");
  const [busy, setBusy] = useState(false),
    [retained, setRetained] = useState<{
      report: any;
      diagnostic: Awaited<ReturnType<typeof scheduleDiagnostic>> | null;
      owner: string;
      ticket: number;
    } | null>(null),
    [profile, setProfile] = useState<any>(null),
    [error, setError] = useState("");
  const alive = useRef(true),
    selection = useRef(0),
    active = useRef<string | null>(null);
  const defaultsKey = JSON.stringify([
      connected,
      interfaceIdentity,
      defaultAddress,
      defaultDevice,
      defaultRouter,
      defaultDnet,
    ]),
    defaultsNow = useRef(defaultsKey);
  defaultsNow.current = defaultsKey;
  const formKey = JSON.stringify([
      address,
      device,
      router,
      dnet,
      objects,
      offset,
      limit,
      maximum,
      clock,
      includeTrace,
      traceObject,
      traceProperty,
      traceIndex,
    ]),
    formNow = useRef(formKey);
  formNow.current = formKey;
  const owner = JSON.stringify([defaultsKey, formKey]),
    ownerNow = useRef(owner);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    selection.current++;
  }
  // A form/target/interface change retires both views and downloads before paint,
  // including an A -> B -> A return while an earlier request is still pending.
  const record =
    retained?.owner === owner && retained.ticket === selection.current
      ? retained
      : null;
  const report = record?.report,
    diagnostic = record?.diagnostic;
  const setReport = (value: any) =>
    setRetained(
      value
        ? {
            report: value,
            diagnostic: null,
            owner: ownerNow.current,
            ticket: selection.current,
          }
        : null,
    );
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      selection.current++;
      if (active.current)
        void api("/bacnet/schedules/cancel", {
          operation_id: active.current,
        }).catch(() => {});
    };
  }, []);
  useEffect(() => {
    selection.current++;
    setAddress(defaultAddress);
    setDevice(defaultDevice);
    setRouter(defaultRouter);
    setDnet(defaultDnet == null ? "" : String(defaultDnet));
    setReport(null);
    setError("");
    if (active.current)
      void api("/bacnet/schedules/cancel", {
        operation_id: active.current,
      }).catch(() => {});
  }, [
    connected,
    interfaceIdentity,
    defaultAddress,
    defaultDevice,
    defaultRouter,
    defaultDnet,
  ]);
  useEffect(() => {
    selection.current++;
    setReport(null);
    setError("");
  }, [formKey]);
  const current = (ticket: number, source: string, draft: string) =>
    alive.current &&
    selection.current === ticket &&
    defaultsNow.current === source &&
    formNow.current === draft;
  async function read() {
    const operation = crypto.randomUUID();
    active.current = operation;
    const ticket = ++selection.current,
      source = defaultsNow.current,
      draft = formNow.current;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      const body = {
        operation_id: operation,
        address: address.trim(),
        device: device.trim(),
        router: router.trim() || null,
        dnet: dnet.trim() ? Number(dnet) : null,
        object_ids: objects.trim()
          ? objects
              .split(/[;\n]+/)
              .map((v) => v.trim())
              .filter(Boolean)
          : null,
        object_list_offset: Number(offset),
        object_list_limit: Number(limit),
        max_objects: Number(maximum),
        include_device_clock: clock,
      };
      if (includeTrace) {
        const focus: ScheduleTraceFocus = {
          object_id: traceObject.trim(),
          property: traceProperty,
          array_index: ["weekly-schedule", "exception-schedule"].includes(
            traceProperty,
          )
            ? Number(traceIndex)
            : null,
        };
        const document = await apiJsonDocument(
          "/bacnet/schedules/read-diagnostics",
          { request: body, trace_focus: focus },
          true,
        );
        const result = await scheduleDiagnostic(document, body, focus);
        if (current(ticket, source, draft))
          setRetained({
            report: result.report,
            diagnostic: result,
            owner: ownerNow.current,
            ticket,
          });
      } else {
        const result = await api("/bacnet/schedules/read", body);
        if (current(ticket, source, draft)) setReport(result);
      }
    } catch (failure) {
      if (current(ticket, source, draft)) setError(String(failure));
    } finally {
      if (active.current === operation) active.current = null;
      if (alive.current) setBusy(false);
    }
  }
  async function cancel() {
    if (active.current)
      try {
        await api("/bacnet/schedules/cancel", { operation_id: active.current });
      } catch (failure) {
        if (alive.current) setError(String(failure));
      }
  }
  async function refresh() {
    try {
      const result = await api("/bacnet/schedules/profile");
      if (alive.current) setProfile(result);
    } catch (failure) {
      if (alive.current) setError(String(failure));
    }
  }
  async function reopen(id: string) {
    const ticket = ++selection.current,
      source = defaultsNow.current,
      draft = formNow.current;
    setReport(null);
    setError("");
    try {
      const result = await api("/bacnet/schedules/reports/" + id);
      if (current(ticket, source, draft)) setReport(result);
    } catch (failure) {
      if (current(ticket, source, draft)) setError(String(failure));
    }
  }
  async function exportReport() {
    if (!report) return;
    if (diagnostic) {
      if (
        record?.owner === ownerNow.current &&
        record.ticket === selection.current
      )
        saveBlob(diagnostic.core, `bacnet-schedules-${report.id}.json`);
      return;
    }
    const ticket = selection.current,
      source = defaultsNow.current,
      draft = formNow.current,
      id = report.id;
    try {
      await download(
        "/bacnet/schedules/export",
        { id },
        `bacnet-schedules-${id}.json`,
        () => current(ticket, source, draft),
      );
    } catch (failure) {
      if (current(ticket, source, draft)) setError(String(failure));
    }
  }
  return (
    <section
      className="card"
      aria-label="Native Calendar and Schedule inventory"
    >
      <h2>Native Calendar / Schedule inventory</h2>
      <p>
        Explicit read-only BACnet Calendar (6) and Schedule (17) evidence.
        Sequential reads do not establish a coherent backup. Editing, transfer
        and the portable schedule simulator are separate.
      </p>
      <p>
        Plain IPv4 or explicit IPv4 router and DNET:MAC; already-open interface
        required. No BBMD or direct serial in this profile. At most 32 exception
        entries; oversized or segmented values remain incomplete.
      </p>
      <div className="form-grid">
        <TargetFields>
          <label>
            Schedule source address
            <input
              aria-label="Schedule source address"
              value={address}
              disabled={busy}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="192.0.2.10 or 3001:7"
            />
          </label>
        </TargetFields>
        <TargetFields>
          <label>
            Schedule Device identifier
            <input
              aria-label="Schedule Device identifier"
              value={device}
              disabled={busy}
              onChange={(e) => setDevice(e.target.value)}
              placeholder="device,1234"
            />
          </label>
        </TargetFields>
        <TargetFields>
          <label>
            Schedule router endpoint
            <input
              aria-label="Schedule router endpoint"
              value={router}
              disabled={busy}
              onChange={(e) => setRouter(e.target.value)}
              placeholder="Optional explicit IPv4:port"
            />
          </label>
        </TargetFields>
        <TargetFields>
          <label>
            Schedule DNET
            <input
              aria-label="Schedule DNET"
              type="number"
              min={1}
              max={65534}
              value={dnet}
              disabled={busy}
              onChange={(e) => setDnet(e.target.value)}
            />
          </label>
        </TargetFields>
        <label className="full">
          Calendar/Schedule object selection
          <textarea
            aria-label="Calendar/Schedule object selection"
            value={objects}
            disabled={busy}
            onChange={(e) => setObjects(e.target.value)}
            placeholder="calendar,1; schedule,2 — empty reads an explicit Object_List page"
          />
        </label>
        <label>
          Object_List offset
          <input
            aria-label="Schedule Object_List offset"
            type="number"
            min={0}
            max={20000}
            value={offset}
            disabled={busy}
            onChange={(e) => setOffset(e.target.value)}
          />
        </label>
        <label>
          Object_List page limit
          <input
            aria-label="Schedule Object_List page limit"
            type="number"
            min={1}
            max={256}
            value={limit}
            disabled={busy}
            onChange={(e) => setLimit(e.target.value)}
          />
        </label>
        <label>
          Maximum selected objects
          <input
            aria-label="Schedule maximum objects"
            type="number"
            min={1}
            max={16}
            value={maximum}
            disabled={busy}
            onChange={(e) => setMaximum(e.target.value)}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={clock}
            disabled={busy}
            onChange={(e) => setClock(e.target.checked)}
          />
          Read raw Device clock fields
        </label>
      </div>
      <details className="schedule-read-diagnostics">
        <summary>Read diagnostics</summary>
        <label className="schedule-trace-enable">
          <input
            type="checkbox"
            checked={includeTrace}
            disabled={busy}
            onChange={(e) => setIncludeTrace(e.target.checked)}
          />
          Include one-property Schedule trace
        </label>
        {includeTrace && (
          <>
            <p>
              Explicitly select the object above, then choose one property to
              observe during the same inventory read. No extra queries or
              retries. Unreached properties produce an empty trace.
            </p>
            <div className="form-grid">
              <label>
                Trace Calendar/Schedule object
                <input
                  aria-label="Trace Calendar/Schedule object"
                  value={traceObject}
                  disabled={busy}
                  onChange={(e) => setTraceObject(e.target.value)}
                  placeholder="schedule,1"
                />
              </label>
              <label>
                Trace native property
                <span className="schedule-trace-select">
                  <select
                    aria-label="Trace native property"
                    value={traceProperty}
                    disabled={busy}
                    onChange={(e) => setTraceProperty(e.target.value)}
                  >
                    {[
                      "object-identifier",
                      "object-name",
                      "description",
                      "present-value",
                      "date-list",
                      "effective-period",
                      "schedule-default",
                      "priority-for-writing",
                      "list-of-object-property-references",
                      "status-flags",
                      "reliability",
                      "out-of-service",
                      "weekly-schedule",
                      "exception-schedule",
                    ].map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} aria-hidden="true" />
                </span>
              </label>
              {["weekly-schedule", "exception-schedule"].includes(
                traceProperty,
              ) && (
                <label>
                  Trace array index (0 reads count)
                  <input
                    aria-label="Schedule trace array index"
                    type="number"
                    min={0}
                    max={traceProperty === "weekly-schedule" ? 7 : 32}
                    value={traceIndex}
                    disabled={busy}
                    onChange={(e) => setTraceIndex(e.target.value)}
                  />
                </label>
              )}
            </div>
          </>
        )}
      </details>
      <div className="toolbar">
        <button
          className="primary"
          disabled={!connected || busy}
          onClick={() => void read()}
        >
          Read native schedules
        </button>
        <button disabled={!busy} onClick={() => void cancel()}>
          Cancel schedule read
        </button>
        <button onClick={() => void refresh()}>
          Refresh retained schedule reports
        </button>
        <button disabled={!report || busy} onClick={() => void exportReport()}>
          Export exact schedule evidence
        </button>
      </div>
      {busy && <p role="status">Reading finite native schedule evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {diagnostic && (
        <section
          className="schedule-property-trace"
          aria-label="Schedule property diagnostic trace"
        >
          <h3>Schedule property trace</h3>
          <p>
            {diagnostic.focus.object_id} · {diagnostic.focus.property}
            {diagnostic.focus.array_index == null
              ? ""
              : ` [${diagnostic.focus.array_index}]`}{" "}
            · {diagnostic.trace?.state ?? "unavailable"}
          </p>
          <p>
            Native handoff and multiplexer observations; not socket transmission
            or all UDP ingress. Trace limits are separate from the complete
            evidence report.
          </p>
          {diagnostic.trace?.counts && (
            <p>
              {diagnostic.trace.counts.reads} observed reads ·{" "}
              {diagnostic.trace.counts.retained_events} retained events ·{" "}
              {diagnostic.trace.counts.dropped_events} dropped events.
            </p>
          )}
          {diagnostic.envelope && (
            <button
              onClick={() => {
                if (
                  record?.owner === ownerNow.current &&
                  record.ticket === selection.current
                )
                  saveBlob(
                    diagnostic.envelope!,
                    `schedule-diagnostics-${report.id}.json`,
                  );
              }}
            >
              Download original Schedule diagnostic bundle
            </button>
          )}
          <details>
            <summary>Bounded Schedule phases and visibility</summary>
            <pre>{JSON.stringify(diagnostic.trace, null, 2)}</pre>
          </details>
        </section>
      )}
      {profile && (
        <details>
          <summary>Retained reports and limits</summary>
          <p>
            Session memory only: export before restart or eviction. Reopening a
            report does not contact a device.
          </p>
          <pre>{JSON.stringify(profile.limits, null, 2)}</pre>
          {(profile.reports || []).map((row: any) => (
            <p key={row.id}>
              <button disabled={busy} onClick={() => void reopen(row.id)}>
                Open schedule report {row.id.slice(0, 8)}
              </button>{" "}
              {row.target.device} at {row.target.address} · {row.status} ·{" "}
              {row.finished_at}
            </p>
          ))}
        </details>
      )}
      {report && (
        <div aria-label="Schedule evidence report">
          <p>
            <strong>{report.status}</strong> · Device identity{" "}
            {report.identity_verified ? "verified" : "unverified"} ·{" "}
            {report.requests} ReadProperty requests · {report.target.device} at{" "}
            {report.target.address}
            {report.target.router
              ? ` via ${report.target.router} / DNET ${report.target.dnet}`
              : ""}
          </p>
          <p>
            Observed {report.started_at} through {report.finished_at}.{" "}
            {report.consistency} Raw clock evidence has no resolved IANA
            timezone.
          </p>
          <p>
            Browser JSON previews normalize number spelling; exact export
            preserves native float evidence and its hash.
          </p>
          {!!report.errors?.length && (
            <pre>{JSON.stringify(report.errors, null, 2)}</pre>
          )}
          {report.inventory?.next_offset != null && (
            <p>
              Object_List page incomplete. Next offset:{" "}
              <strong>{report.inventory.next_offset}</strong>. Enter that offset
              and explicitly read another page; this does not freeze a coherent
              snapshot.
            </p>
          )}
          {(report.objects || []).map((obj: any) => (
            <details key={obj.object} open>
              <summary>
                {obj.object} ·{" "}
                {obj.complete ? "all selected properties read" : "incomplete"} ·
                identity {obj.identity_verified ? "verified" : "unverified"}
              </summary>
              {obj.error && <p role="alert">{obj.error}</p>}
              <table>
                <thead>
                  <tr>
                    <th>Native property</th>
                    <th>Status</th>
                    <th>Value / native evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(obj.properties).map(([name, raw]) => {
                    const value = raw as any;
                    return (
                      <tr key={name}>
                        <td>{name}</td>
                        <td>{value.status}</td>
                        <td>
                          <details>
                            <summary>
                              {value.datatype ||
                                (value.elements
                                  ? `${value.elements.length} indexed entries`
                                  : value.error || "Native evidence")}
                            </summary>
                            <pre>{JSON.stringify(value, null, 2)}</pre>
                          </details>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </details>
          ))}
          <details>
            <summary>
              Complete evidence, native choices, per-property failures and
              transport provenance
            </summary>
            <pre className="result">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </div>
      )}
      <ScheduleLibraryPanel
        sessionReportId={report?.id || null}
        connected={connected}
        connectionKey={JSON.stringify([
          defaultsKey,
          address,
          device,
          router,
          dnet,
        ])}
      />
    </section>
  );
}
