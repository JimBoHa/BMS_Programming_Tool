import { useEffect, useRef, useState } from "react";
import { api, download } from "./api";
import { ScheduleLibraryPanel } from "./ScheduleLibraryPanel";
type Props = {
  connected: boolean;
  defaultAddress: string;
  defaultDevice: string;
  defaultRouter?: string;
  defaultDnet?: number | null;
};
export function ScheduleInventoryPanel({
  connected,
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
    [clock, setClock] = useState(false);
  const [busy, setBusy] = useState(false),
    [report, setReport] = useState<any>(null),
    [profile, setProfile] = useState<any>(null),
    [error, setError] = useState("");
  const alive = useRef(true),
    selection = useRef(0),
    active = useRef<string | null>(null);
  const defaultsKey = JSON.stringify([
      connected,
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
    ]),
    formNow = useRef(formKey);
  formNow.current = formKey;
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
  }, [connected, defaultAddress, defaultDevice, defaultRouter, defaultDnet]);
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
      const result = await api("/bacnet/schedules/read", {
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
      });
      if (current(ticket, source, draft)) setReport(result);
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
      <div className="toolbar">
        <button disabled={!connected || busy} onClick={() => void read()}>
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
      <ScheduleLibraryPanel sessionReportId={report?.id || null} />
    </section>
  );
}
