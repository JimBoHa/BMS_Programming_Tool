import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, saveBlob } from "./api";
import {
  checkPowerStatus,
  powerBlobSha256,
  type PowerLease,
  type PowerStatus,
} from "./operationPowerStatus";
import "./operation-power.css";

type Evidence = {
  data: PowerStatus;
  blob: Blob;
  sha256: string;
  observed: string;
  generation: number;
};
export function OperationPowerPanel() {
  const [report, setReport] = useState<Evidence | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    active = useRef(false),
    latest = useRef<Evidence | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
      active.current = false;
      latest.current = null;
    };
  }, []);
  async function refresh() {
    if (!mounted.current || active.current) return;
    const generation = ++epoch.current;
    active.current = true;
    latest.current = null;
    setReport(null);
    setBusy(true);
    setError("");
    try {
      const next = await apiJsonDocument("/operation-power"),
        data = await checkPowerStatus(next.data, next.blob),
        sha256 = await powerBlobSha256(next.blob);
      if (!mounted.current || epoch.current !== generation) return;
      const accepted = {
        data,
        blob: next.blob,
        sha256,
        observed: new Date().toISOString(),
        generation,
      };
      latest.current = accepted;
      setReport(accepted);
    } catch (e) {
      if (mounted.current && epoch.current === generation) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === generation) {
        active.current = false;
        setBusy(false);
      }
    }
  }
  function retire() {
    epoch.current++;
    active.current = false;
    latest.current = null;
    setReport(null);
    setBusy(false);
    setError(
      "Pending power response ignored. This read never acquired, renewed or released an OS request.",
    );
  }
  function table(rows: PowerLease[], label: string) {
    return rows.length ? (
      <div className="power-table">
        <table aria-label={label}>
          <caption>
            {label}; states and times are the backend’s saved response, not a
            live countdown.
          </caption>
          <thead>
            <tr>
              <th>Lease / operation</th>
              <th>Provider</th>
              <th>Lifecycle</th>
              <th>Idle request active</th>
              <th>Cleanup confirmed</th>
              <th>Lifetime and UTC timestamps</th>
              <th>Advisory error</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <code>{row.id}</code>
                  <br />
                  {row.operation}
                </td>
                <td>{row.provider}</td>
                <td>{row.state}</td>
                <td>
                  {row.request_active ? "Yes, as reported" : "No, as reported"}
                </td>
                <td>
                  {row.cleanup_confirmed ? "Yes, as reported" : "Unconfirmed"}
                </td>
                <td>
                  {row.seconds} seconds
                  <br />
                  Created: {row.created_at}
                  <br />
                  Expires: {row.expires_at}
                  <br />
                  Finished: {row.finished_at ?? "Not reported"}
                </td>
                <td>{row.error ?? "None reported"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ) : (
      <p>No {label.toLowerCase()} reported.</p>
    );
  }
  return (
    <section
      className="card operation-power"
      aria-label="Operation power status"
    >
      <div className="card-header">
        <h3>Operation power status</h3>
        <button disabled={busy} onClick={() => void refresh()}>
          Refresh operation power status
        </button>
      </div>
      <div className="card-body">
        <p>
          Read-only snapshots of advisory idle-sleep requests owned by this
          backend. Refresh is explicit; this panel never acquires, renews or
          releases a request and does not poll.
        </p>
        <p>
          Only App-managed Temco native apply and its owned recovery currently
          integrate this feature. Studio tabs, connections, plans and idle
          simulators acquire no request. Native JCI compilation and transfer are
          not supported by this integration.
        </p>
        <p>
          A request affects this backend OS only. A Windows guest request does
          not keep its physical Mac host awake; it does not protect remote
          computers. Explicit Sleep, lid closure, shutdown, power loss and OS
          policy are not prevented. Availability means a provider can be
          attempted, not that a computer is protected.
        </p>
        {!report && !busy && !error && (
          <p>
            No snapshot requested. Other OS power requests are not inventoried
            here.
          </p>
        )}
        {busy && <p role="status">Reading operation power status…</p>}
        {error && <p role="alert">{error}</p>}
        {busy && (
          <button onClick={retire}>Discard pending power response</button>
        )}
        {report && (
          <>
            <dl>
              <dt>Backend provider</dt>
              <dd>{report.data.provider}</dd>
              <dt>Provider available for request attempts</dt>
              <dd>{report.data.provider_available ? "Yes" : "No"}</dd>
              <dt>Manager accepting new requests</dt>
              <dd>{report.data.accepting ? "Yes" : "No"}</dd>
              <dt>Snapshot received locally (UTC)</dt>
              <dd>{report.observed}</dd>
            </dl>
            {table(report.data.active, "Active power leases")}
            {table(report.data.recent, "Recent power leases")}
            <p>
              Unconfirmed cleanup may leave an OS request active. A failed or
              expired request does not cancel, retry or authorize controller
              work. Expiry releases the power request only; an operation can
              continue without protection.
            </p>
            <p>
              Original response SHA-256, computed locally:{" "}
              <code>{report.sha256}</code>. This is body integrity, not a server
              signature or proof of physical awake state.
            </p>
            <details>
              <summary>Advisory profile and limits</summary>
              <pre>{JSON.stringify(report.data.profile, null, 2)}</pre>
              <p>
                Profile SHA-256: <code>{report.data.profile_sha256}</code>
              </p>
            </details>
            <button
              onClick={() => {
                if (
                  mounted.current &&
                  !active.current &&
                  latest.current === report &&
                  epoch.current === report.generation
                )
                  saveBlob(
                    report.blob,
                    `operation-power-${report.sha256}.json`,
                  );
              }}
            >
              Export original power status JSON
            </button>
          </>
        )}
      </div>
    </section>
  );
}
