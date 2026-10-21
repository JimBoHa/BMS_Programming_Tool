import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

export function BacnetCovPanel({
  connected,
  defaultAddress,
  defaultDevice,
  defaultObject,
  defaultRouter = "",
  defaultDnet,
}: {
  connected: boolean;
  defaultAddress: string;
  defaultDevice: string;
  defaultObject: string;
  defaultRouter?: string;
  defaultDnet?: number;
}) {
  const [address, setAddress] = useState(defaultAddress);
  const [mode, setMode] = useState(defaultRouter ? "routed" : "direct");
  const [router, setRouter] = useState(defaultRouter);
  const [dnet, setDnet] = useState(String(defaultDnet || ""));
  const [mac, setMac] = useState("");
  const [notice, setNotice] = useState("");
  const selection = useRef(0);
  const previousSource = useRef({
    path: JSON.stringify([defaultAddress, defaultRouter, defaultDnet]),
    device: defaultDevice,
  });
  const [device, setDevice] = useState(defaultDevice);
  const [object, setObject] = useState(defaultObject);
  const [lifetime, setLifetime] = useState("60");
  const [confirmed, setConfirmed] = useState(true);
  const [status, setStatus] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const operation = useRef(false);
  useEffect(() => {
    selection.current++;
    setAddress(
      defaultAddress.includes(":") && !defaultAddress.includes(".")
        ? ""
        : defaultAddress,
    );
    const path = JSON.stringify([defaultAddress, defaultRouter, defaultDnet]);
    setDevice(
      path !== previousSource.current.path &&
        defaultDevice === previousSource.current.device
        ? ""
        : defaultDevice,
    );
    previousSource.current = { path, device: defaultDevice };
    setObject(defaultObject.startsWith("device,") ? "" : defaultObject);
    setMode(defaultRouter ? "routed" : "direct");
    setRouter(defaultRouter);
    setDnet(String(defaultDnet || ""));
    const match = /^([0-9]+):([0-9]+)$/.exec(defaultAddress);
    setMac(match ? match[2] : "");
    setError("");
    setNotice("");
  }, [
    defaultAddress,
    defaultDevice,
    defaultObject,
    defaultRouter,
    defaultDnet,
  ]);
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const result = await api("/bacnet/cov/status");
        if (!cancelled) setStatus(result);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) timer = setTimeout(refresh, 1000);
      }
    }
    void refresh();
    return () => {
      cancelled = true;
      mounted.current = false;
      clearTimeout(timer);
    };
  }, []);

  async function act(action: string, id?: string) {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    const generation = selection.current;
    try {
      if (action === "export") {
        const result = await api(`/bacnet/cov/jobs/${id}`);
        if (mounted.current)
          saveBlob(
            new Blob([JSON.stringify(result, null, 2)], {
              type: "application/json",
            }),
            `${id}-cov-evidence.json`,
          );
      } else {
        const body =
          action === "start"
            ? {
                address:
                  mode === "routed"
                    ? `${Number(dnet)}:${Number(mac)}`
                    : address,
                router: mode === "routed" ? router : null,
                dnet: mode === "routed" ? Number(dnet) : null,
                device,
                object_id: object,
                lifetime: Number(lifetime),
                confirmed,
              }
            : { id };
        const changed = await api(`/bacnet/cov/${action}`, body);
        if (
          mounted.current &&
          action === "start" &&
          generation !== selection.current
        ) {
          setNotice(
            `Monitor started for the earlier selection: ${changed.config.device} at ${changed.config.address}. Its recorded source remains shown below.`,
          );
        }
        const result = await api("/bacnet/cov/status");
        if (mounted.current) setStatus(result);
      }
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      operation.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section className="card" role="region" aria-label="BACnet COV monitoring">
      <div className="card-header">
        <h3>Change-of-value monitoring</h3>
      </div>
      <div className="card-body">
        <p>
          Receive controller notifications directly over BACnet/IP or through an
          explicit NAE/router and DNET:MAC. Starting verifies the selected
          Device and point identities. No point values are written.
        </p>
        <p className="help-text">
          Finite leases require explicit renewal. Routed notifications must be
          unsegmented. No automatic reconnect, BBMD, direct serial, or BTCVT
          support in this profile. Device acceptance and sensor quality require
          separate verification.
        </p>
        <div className="form-grid">
          <label>
            COV source path
            <select
              aria-label="COV source path"
              value={mode}
              disabled={busy}
              onChange={(e) => {
                selection.current++;
                setMode(e.target.value);
                setDevice("");
                setObject("");
                setNotice("");
              }}
            >
              <option value="direct">Direct BACnet/IP</option>
              <option value="routed">Explicit NAE/router to MS/TP</option>
            </select>
          </label>
          {mode === "routed" && (
            <>
              <label>
                COV router IP / port
                <input
                  aria-label="COV router IP / port"
                  value={router}
                  onChange={(e) => setRouter(e.target.value)}
                  disabled={busy}
                />
              </label>
              <label>
                COV destination network
                <input
                  aria-label="COV destination network"
                  type="number"
                  min={1}
                  max={65534}
                  value={dnet}
                  onChange={(e) => setDnet(e.target.value)}
                  disabled={busy}
                />
              </label>
              <label>
                COV controller MAC
                <input
                  aria-label="COV controller MAC"
                  type="number"
                  min={0}
                  max={254}
                  value={mac}
                  onChange={(e) => setMac(e.target.value)}
                  disabled={busy}
                />
              </label>
            </>
          )}
          {mode === "direct" && (
            <label>
              COV device IP / port
              <input
                aria-label="COV device IP / port"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                disabled={busy}
              />
            </label>
          )}
          <label>
            Expected COV Device
            <input
              aria-label="Expected COV Device"
              placeholder="device,12345"
              value={device}
              onChange={(e) => setDevice(e.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            COV monitored object
            <input
              aria-label="COV monitored object"
              value={object}
              onChange={(e) => setObject(e.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            COV lease seconds
            <input
              aria-label="COV lease seconds"
              type="number"
              min={5}
              max={3600}
              step={1}
              value={lifetime}
              onChange={(e) => setLifetime(e.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Notification mode
            <select
              aria-label="COV notification mode"
              value={confirmed ? "confirmed" : "unconfirmed"}
              onChange={(e) => setConfirmed(e.target.value === "confirmed")}
              disabled={busy}
            >
              <option value="confirmed">Confirmed notifications</option>
              <option value="unconfirmed">Unconfirmed notifications</option>
            </select>
          </label>
        </div>
        <button
          disabled={
            busy ||
            !connected ||
            (mode === "direct"
              ? !address.trim()
              : !router.trim() ||
                !dnet ||
                !mac ||
                !Number.isInteger(Number(dnet)) ||
                Number(dnet) < 1 ||
                Number(dnet) > 65534 ||
                !Number.isInteger(Number(mac)) ||
                Number(mac) < 0 ||
                Number(mac) > 254) ||
            !device.trim() ||
            !object.trim()
          }
          onClick={() => void act("start")}
        >
          Start verified COV monitor
        </button>
        {!connected && (
          <p className="help-text">
            Connect a BACnet/IPv4 interface without BBMD or direct serial to
            start a monitor.
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
        {status && (
          <p role="status">
            {status.jobs.filter((j: any) => j.active).length} active monitors ·
            Last 3 notifications shown per monitor · Up to{" "}
            {status.maximum_events_per_job} retained; older events counted as
            dropped. Retired monitor records evicted:{" "}
            {status.retired_jobs_evicted}.
          </p>
        )}
        {[...(status?.jobs || [])].reverse().map((job: any) => (
          <section key={job.id} aria-label={`COV monitor ${job.id}`}>
            <h4>
              {job.config.device} · {job.config.object_id} · {job.state}
            </h4>
            <p>
              {job.config.address}{" "}
              {job.config.router ? `via ${job.config.router}` : "direct"} ·{" "}
              {job.config.confirmed ? "Confirmed" : "Unconfirmed"} · Lease
              remaining: {job.lease_seconds_remaining}s · Received:{" "}
              {job.received} · Dropped: {job.dropped} · Ignored: {job.ignored}
            </p>
            <p>
              {job.remote_outcome} {job.reason}
            </p>
            {job.last_ignored && (
              <p className="help-text">
                Last ignored notification: {job.last_ignored}
              </p>
            )}
            <div className="button-row">
              <button
                disabled={busy || !job.active}
                onClick={() => void act("renew", job.id)}
              >
                Renew COV lease
              </button>
              <button
                disabled={busy || !job.active}
                onClick={() => void act("stop", job.id)}
              >
                Stop COV monitor
              </button>
              <button
                disabled={busy}
                onClick={() => void act("export", job.id)}
              >
                Export COV evidence
              </button>
            </div>
            {job.events.map((event: any) => (
              <details key={event.sequence}>
                <summary>
                  Notification {event.sequence} · {event.received_at} ·{" "}
                  {event.values.length} properties
                </summary>
                <p>{event.quality}</p>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Property</th>
                        <th>Array index</th>
                        <th>Priority</th>
                        <th>Value</th>
                        <th>Decoding</th>
                      </tr>
                    </thead>
                    <tbody>
                      {event.values.map((value: any, i: number) => (
                        <tr key={i}>
                          <td>{value.property}</td>
                          <td>{value.array_index ?? "—"}</td>
                          <td>{value.priority ?? "—"}</td>
                          <td>
                            <code>{JSON.stringify(value.value)}</code>
                          </td>
                          <td>{value.decode_status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <details>
                  <summary>Notification evidence</summary>
                  <pre>{JSON.stringify(event, null, 2)}</pre>
                </details>
              </details>
            ))}
          </section>
        ))}
      </div>
    </section>
  );
}
