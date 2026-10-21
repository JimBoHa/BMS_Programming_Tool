import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

export function BbmdTablesPanel({
  connected,
  defaultEndpoint = "",
}: {
  connected: boolean;
  defaultEndpoint?: string;
}) {
  const [endpoint, setEndpoint] = useState(defaultEndpoint);
  const [tables, setTables] = useState("both");
  const [timeout, setTimeoutSeconds] = useState("2");
  const [status, setStatus] = useState<any>(null);
  const [watch, setWatch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const operation = useRef(false);
  useEffect(() => {
    setEndpoint(defaultEndpoint);
  }, [defaultEndpoint]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function refresh() {
    const result = await api("/bacnet/bbmd-tables/status");
    if (mounted.current) {
      setStatus(result);
      setWatch(result.jobs.some((job: any) => job.active));
    }
  }
  useEffect(() => {
    if (!watch) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const result = await api("/bacnet/bbmd-tables/status");
        if (!stopped && mounted.current) {
          setStatus(result);
          if (result.jobs.some((job: any) => job.active))
            timer = setTimeout(tick, 500);
          else setWatch(false);
        }
      } catch (e) {
        if (!stopped && mounted.current) {
          setError(String(e));
          setWatch(false);
        }
      }
    }
    timer = setTimeout(tick, 100);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [watch]);

  async function act(action: string, id?: string) {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    try {
      if (action === "start") {
        await api("/bacnet/bbmd-tables/start", {
          endpoint,
          tables: tables === "both" ? ["bdt", "fdt"] : [tables],
          timeout_seconds: Number(timeout),
        });
      } else if (action === "cancel") {
        await api("/bacnet/bbmd-tables/cancel", { id });
      } else if (action === "export") {
        const result = await api(`/bacnet/bbmd-tables/jobs/${id}`);
        if (mounted.current)
          saveBlob(
            new Blob([JSON.stringify(result, null, 2)], {
              type: "application/json",
            }),
            `${id}-bbmd-tables.json`,
          );
      }
      await refresh();
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      operation.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  const active = status?.jobs.some((job: any) => job.active);
  return (
    <section className="card" role="region" aria-label="BBMD table inspection">
      <div className="card-header">
        <h3>Read BBMD administration tables</h3>
      </div>
      <div className="card-body">
        <p>
          Inspect one explicit IPv4 BBMD endpoint through the open BACnet/IP
          interface. Only Read-BDT and Read-FDT requests are sent.
        </p>
        <p className="help-text">
          These are separate configuration/lease snapshots, not detected live
          devices. Tables have no transaction identifiers or source timestamps;
          late replies from the same endpoint cannot be distinguished. Native
          NACK cannot distinguish unsupported service from policy denial. No
          writes, deletion, hosting, registration changes or automatic queries.
        </p>
        <div className="form-grid">
          <label>
            BBMD endpoint
            <input
              aria-label="BBMD inspection endpoint"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="192.0.2.10:47808"
            />
          </label>
          <label>
            Tables
            <select
              aria-label="BBMD tables to read"
              value={tables}
              onChange={(e) => setTables(e.target.value)}
            >
              <option value="both">BDT and FDT</option>
              <option value="bdt">Broadcast distribution table (BDT)</option>
              <option value="fdt">Foreign device table (FDT)</option>
            </select>
          </label>
          <label>
            Response deadline (seconds)
            <input
              aria-label="BBMD response deadline"
              type="number"
              min={0.1}
              max={5}
              step={0.1}
              value={timeout}
              onChange={(e) => setTimeoutSeconds(e.target.value)}
            />
          </label>
        </div>
        <div className="button-row">
          <button
            disabled={busy || !connected || active || !endpoint.trim()}
            onClick={() => void act("start")}
          >
            Inspect BBMD tables
          </button>
          <button disabled={busy} onClick={() => void act("load")}>
            Load table inspections
          </button>
        </div>
        {!connected && (
          <p className="help-text">
            Open a BACnet/IPv4 interface in Connect first. Direct serial/BTCVT
            and BACnet/SC are outside this profile.
          </p>
        )}
        {status && (
          <p>
            {status.maximum_entries_per_table} entries maximum per table ·{" "}
            {status.maximum_jobs} session snapshots retained · Evicted:{" "}
            {status.evicted_jobs}. Export snapshots before restarting.
          </p>
        )}
        {[...(status?.jobs || [])].reverse().map((job: any) => (
          <section key={job.id} aria-label={`BBMD inspection ${job.id}`}>
            <h4>
              {job.endpoint} · {job.state}
            </h4>
            <p>
              Created UTC {job.created_at} · Finished UTC{" "}
              {job.finished_at || "pending"} · Ignored other peers:{" "}
              {job.ignored_peers}
            </p>
            {job.reason && <p>{job.reason}</p>}
            <div className="button-row">
              <button
                disabled={busy || !job.active}
                onClick={() => void act("cancel", job.id)}
              >
                Cancel BBMD inspection
              </button>
              <button
                disabled={busy}
                onClick={() => void act("export", job.id)}
              >
                Export BBMD snapshot
              </button>
            </div>
            {Object.entries(job.tables).map(([name, value]: [string, any]) => (
              <section
                key={name}
                aria-label={`${name.toUpperCase()} snapshot ${job.id}`}
              >
                <h4>
                  {name.toUpperCase()} · {value.state} · {value.rows.length}{" "}
                  entries
                </h4>
                <p>
                  {value.reason} {value.result_hex || ""}
                </p>
                <p className="help-text">
                  Sent UTC {value.sent_at || "not sent"} · Received UTC{" "}
                  {value.response?.received_at || "no attributable reply"}
                </p>
                {value.state === "ok" && value.rows.length === 0 && (
                  <p>Native ACK returned an empty table.</p>
                )}
                {!!value.rows.length && (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Address</th>
                          {name === "bdt" ? (
                            <>
                              <th>Distribution mask</th>
                              <th>Mask contiguous</th>
                            </>
                          ) : (
                            <>
                              <th>Native TTL (s)</th>
                              <th>Native remaining lease (s)</th>
                            </>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {value.rows.map((row: any) => (
                          <tr key={row.index}>
                            <td>{row.address}</td>
                            {name === "bdt" ? (
                              <>
                                <td>{row.mask}</td>
                                <td>{row.mask_contiguous ? "yes" : "no"}</td>
                              </>
                            ) : (
                              <>
                                <td>{row.ttl_seconds}</td>
                                <td>{row.remaining_seconds}</td>
                              </>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {value.response && (
                  <details>
                    <summary>
                      {name.toUpperCase()} raw response evidence
                    </summary>
                    <pre>{JSON.stringify(value.response, null, 2)}</pre>
                  </details>
                )}
              </section>
            ))}
            <details>
              <summary>Inspection provenance and unattributed Results</summary>
              <pre>
                {JSON.stringify(
                  {
                    endpoint: job.endpoint,
                    interface: job.config,
                    interface_id: job.interface_id,
                    local_endpoint: job.local_endpoint,
                    scope: job.scope,
                    unattributed_results: job.unattributed_results,
                    unattributed_results_omitted:
                      job.unattributed_results_omitted,
                    audit_error: job.audit_error,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </section>
        ))}
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
