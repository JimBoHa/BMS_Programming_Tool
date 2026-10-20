import { useEffect, useRef, useState } from "react";
import { Download, Fingerprint, Search } from "lucide-react";
import { api, saveBlob } from "./api";
import "./controller-probe.css";

export type ControllerProbeReport = {
  router: string;
  dnet: number;
  mac: number;
  address: string;
  device: string;
  device_instance: number;
  properties: Record<string, string | number>;
  errors: { property: string; error: string }[];
  complete: boolean;
  live_verified: boolean;
  started_at: string;
  finished_at: string;
  connector_config: Record<string, unknown>;
  scope: string;
};
type TrunkProbeReport = {
  router: string;
  dnet: number;
  request: {
    mac_low: number;
    mac_high: number;
    per_mac_timeout_seconds: number;
    spacing_seconds: number;
    timeout_seconds: number;
  };
  devices: {
    router: string;
    dnet: number;
    mac: number;
    address: string;
    device: string;
    device_instance: number;
    live_verified: boolean;
    received_at: string;
  }[];
  attempts: {
    mac: number;
    address: string;
    outcome: "identified" | "timeout" | "error";
    window_seconds: number;
    error?: string;
  }[];
  next_mac: number | null;
  complete: boolean;
  truncated: boolean;
  scope: string;
  warnings: string[];
  errors: unknown[];
  no_response: unknown[];
  connector_config: Record<string, unknown>;
  started_at: string;
  finished_at: string;
};

export function ControllerProbePanel({
  connected,
  router,
  dnet,
  onSelect,
}: {
  connected: boolean;
  router: string;
  dnet: number | null;
  onSelect: (result: ControllerProbeReport) => void;
}) {
  const [mac, setMac] = useState("7");
  const [report, setReport] = useState<ControllerProbeReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState("single");
  const [macLow, setMacLow] = useState("0");
  const [macHigh, setMacHigh] = useState("31");
  const [responseSeconds, setResponseSeconds] = useState("0.75");
  const [spacingSeconds, setSpacingSeconds] = useState("0.1");
  const [deadlineSeconds, setDeadlineSeconds] = useState("30");
  const [trunk, setTrunk] = useState<TrunkProbeReport | null>(null);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState("");
  const mounted = useRef(false);
  const active = useRef(false);
  const epoch = useRef(0);
  const currentReport = useRef(report);
  const currentTrunk = useRef(trunk);
  currentReport.current = report;
  currentTrunk.current = trunk;
  const ready =
    connected && !!router.trim() && dnet !== null && dnet >= 1 && dnet <= 65534;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    currentReport.current = null;
    currentTrunk.current = null;
    setReport(null);
    setTrunk(null);
    setError("");
    setOutcome("");
  }, [connected, router, dnet]);

  async function probe(selectedMac = mac) {
    if (active.current || !ready) return;
    active.current = true;
    const request = ++epoch.current;
    setBusy(true);
    setBusyKind("single");
    setError("");
    setOutcome("");
    currentReport.current = null;
    setReport(null);
    try {
      if (!/^\d{1,3}$/.test(selectedMac) || Number(selectedMac) > 254)
        throw new Error("Enter one MS/TP MAC address from 0 to 254.");
      setMac(selectedMac);
      const result = await api("/bacnet/probe-controller", {
        router: router.trim(),
        dnet,
        mac: Number(selectedMac),
      });
      if (mounted.current && request === epoch.current) {
        currentReport.current = result;
        setReport(result);
      }
    } catch (error) {
      if (mounted.current && request === epoch.current) setError(String(error));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function editPageDraft(change: () => void) {
    if (active.current) return;
    epoch.current++;
    change();
    currentTrunk.current = null;
    setTrunk(null);
    setError("");
    setOutcome("");
  }
  function editPage(low: string, high: string) {
    editPageDraft(() => {
      setMacLow(low);
      setMacHigh(high);
    });
  }
  async function probePage() {
    if (active.current || !ready) return;
    active.current = true;
    const request = ++epoch.current;
    setBusy(true);
    setBusyKind("page");
    setError("");
    setOutcome("");
    currentTrunk.current = null;
    setTrunk(null);
    try {
      const low = Number(macLow),
        high = Number(macHigh);
      if (
        !/^\d{1,3}$/.test(macLow) ||
        !/^\d{1,3}$/.test(macHigh) ||
        low > high ||
        high > 254 ||
        high - low >= 32
      )
        throw new Error(
          "Choose an increasing MAC range within 0 to 254, with at most 32 addresses per page.",
        );
      const timing = (
        text: string,
        minimum: number,
        maximum: number,
        label: string,
      ) => {
        const value = Number(text);
        if (
          !text.trim() ||
          !Number.isFinite(value) ||
          value < minimum ||
          value > maximum
        )
          throw new Error(
            `${label} must be from ${minimum} to ${maximum} seconds.`,
          );
        return value;
      };
      const result = await api("/bacnet/probe-trunk", {
        router: router.trim(),
        dnet,
        mac_low: low,
        mac_high: high,
        per_mac_timeout_seconds: timing(
          responseSeconds,
          0.5,
          2,
          "Per-MAC response window",
        ),
        spacing_seconds: timing(spacingSeconds, 0.1, 1, "Request spacing"),
        timeout_seconds: timing(deadlineSeconds, 1, 30, "Page deadline"),
      });
      if (mounted.current && request === epoch.current) {
        currentTrunk.current = result;
        setTrunk(result);
      }
    } catch (error) {
      if (mounted.current && request === epoch.current) setError(String(error));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function nextPage() {
    if (active.current || !trunk || currentTrunk.current !== trunk) return;
    const next = trunk.next_mac ?? trunk.request.mac_high + 1;
    if (next > 254) return;
    editPage(String(next), String(Math.min(254, next + 31)));
    setOutcome("Next page is a draft. Start it explicitly when ready.");
  }
  function exportPage() {
    if (active.current || !trunk || currentTrunk.current !== trunk) return;
    saveBlob(
      new Blob([JSON.stringify(trunk, null, 2)], { type: "application/json" }),
      `bacnet-trunk-${trunk.dnet}-${trunk.request.mac_low}-${trunk.request.mac_high}.json`,
    );
  }
  function useController() {
    if (
      active.current ||
      !ready ||
      !report ||
      !report.live_verified ||
      currentReport.current !== report
    )
      return;
    onSelect(report);
    if (mounted.current)
      setOutcome(
        "Selected the verified Device identifier and routed address. No controller value was changed.",
      );
  }
  function exportReport() {
    if (active.current || !report || currentReport.current !== report) return;
    saveBlob(
      new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
      `bacnet-controller-${report.dnet}-${report.mac}-identity.json`,
    );
  }

  return (
    <section
      className="card controller-probe"
      aria-label="Single controller address probe"
    >
      <div className="card-header">
        <h3>
          <Fingerprint size={18} /> Identify one controller
        </h3>
      </div>
      <div className="card-body">
        <p>
          Query one explicit MS/TP address through the already open router and
          network. A wildcard Device ReadProperty discovers its actual Device
          identifier, then reads identity metadata. No Who-Is, bus scan,
          automatic connection or controller write is sent.
        </p>
        <p className="muted">
          Selected route: {router || "No router"} · network{" "}
          {dnet ?? "not selected"}
        </p>
        <div className="form-grid">
          <label>
            Controller MS/TP MAC address
            <input
              aria-label="Controller MS/TP MAC address"
              value={mac}
              inputMode="numeric"
              disabled={busy}
              placeholder="7"
              onChange={(event) => {
                if (active.current) return;
                epoch.current++;
                currentReport.current = null;
                setMac(event.target.value);
                setReport(null);
                setError("");
                setOutcome("");
              }}
            />
          </label>
          <div className="controller-probe-action">
            <button
              className="primary"
              disabled={busy || !ready}
              onClick={() => void probe()}
            >
              <Search size={15} /> Discover controller by address
            </button>
          </div>
        </div>
        {!ready && (
          <p className="muted">
            Open an interface with this exact router and destination network
            before probing. Changing a route draft does not reconnect it.
          </p>
        )}
        {busy && (
          <p role="status">
            {busyKind === "single"
              ? "Reading one controller identity…"
              : "Reading one bounded MAC address page…"}
          </p>
        )}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        {outcome && <p role="status">{outcome}</p>}
        {report && (
          <section aria-label="Probed controller identity">
            <div className="controller-probe-heading">
              <h3>
                {report.device} · {report.address}
              </h3>
              <span className={"pill " + (report.complete ? "" : "pending")}>
                {report.complete
                  ? "Identity metadata complete"
                  : "Identity verified · metadata incomplete"}
              </span>
            </div>
            <dl className="controller-probe-evidence">
              <dt>Object name</dt>
              <dd>{report.properties["object-name"] ?? "Unavailable"}</dd>
              <dt>Vendor identifier</dt>
              <dd>{report.properties["vendor-identifier"] ?? "Unavailable"}</dd>
              <dt>Model</dt>
              <dd>{report.properties["model-name"] ?? "Unavailable"}</dd>
              <dt>Firmware</dt>
              <dd>{report.properties["firmware-revision"] ?? "Unavailable"}</dd>
              <dt>Application software</dt>
              <dd>
                {report.properties["application-software-version"] ??
                  "Unavailable"}
              </dd>
              <dt>Route</dt>
              <dd>
                {report.router} · network {report.dnet} · MAC {report.mac}
              </dd>
              <dt>Started / finished</dt>
              <dd>
                {report.started_at} / {report.finished_at}
              </dd>
            </dl>
            {report.errors.length > 0 && (
              <div aria-label="Controller identity metadata errors">
                <p>
                  Device identity responded; these metadata properties could not
                  be read:
                </p>
                <ul>
                  {report.errors.map((row, index) => (
                    <li key={index}>
                      <strong>{row.property}</strong>: {row.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="muted">{report.scope}</p>
            <div className="button-row">
              <button
                disabled={busy || !ready || !report.live_verified}
                onClick={useController}
              >
                Use identified controller
              </button>
              <button disabled={busy} onClick={exportReport}>
                <Download size={15} /> Download probe JSON
              </button>
            </div>
            <details>
              <summary>Complete identity evidence</summary>
              <pre>{JSON.stringify(report, null, 2)}</pre>
            </details>
          </section>
        )}
        <section aria-label="Bounded controller address page">
          <h3>Find controller addresses without broadcasts</h3>
          <p>
            Explicitly read Device identifiers at up to 32 consecutive MAC
            addresses. Adjust the response window for slower controllers and
            choose request spacing and a bounded page deadline. Silence remains
            unknown; it does not prove an address is unused. The deadline may
            stop a page early. Metadata is read separately.
          </p>
          <div className="form-grid">
            <label>
              First MAC in page
              <input
                aria-label="First MAC in page"
                inputMode="numeric"
                disabled={busy}
                value={macLow}
                onChange={(event) => editPage(event.target.value, macHigh)}
              />
            </label>
            <label>
              Last MAC in page
              <input
                aria-label="Last MAC in page"
                inputMode="numeric"
                disabled={busy}
                value={macHigh}
                onChange={(event) => editPage(macLow, event.target.value)}
              />
            </label>
            <label>
              Per-MAC response seconds
              <input
                aria-label="Per-MAC response seconds"
                type="number"
                min="0.5"
                max="2"
                step="0.05"
                disabled={busy}
                value={responseSeconds}
                onChange={(event) =>
                  editPageDraft(() => setResponseSeconds(event.target.value))
                }
              />
            </label>
            <label>
              Request spacing seconds
              <input
                aria-label="Request spacing seconds"
                type="number"
                min="0.1"
                max="1"
                step="0.05"
                disabled={busy}
                value={spacingSeconds}
                onChange={(event) =>
                  editPageDraft(() => setSpacingSeconds(event.target.value))
                }
              />
            </label>
            <label>
              Page deadline seconds
              <input
                aria-label="Page deadline seconds"
                type="number"
                min="1"
                max="30"
                step="0.5"
                disabled={busy}
                value={deadlineSeconds}
                onChange={(event) =>
                  editPageDraft(() => setDeadlineSeconds(event.target.value))
                }
              />
            </label>
            <div className="controller-probe-action">
              <button
                disabled={busy || !ready}
                onClick={() => void probePage()}
              >
                <Search size={15} /> Probe one MAC address page
              </button>
            </div>
          </div>
          {trunk && (
            <section aria-label="Controller address page results">
              <div className="controller-probe-heading">
                <h3>
                  {trunk.router} · network {trunk.dnet} · MAC{" "}
                  {trunk.request.mac_low}–{trunk.request.mac_high}
                </h3>
                <span className="pill">
                  {trunk.complete
                    ? "Requested page attempted"
                    : "Page stopped before all addresses"}
                </span>
              </div>
              <p>
                {trunk.devices.length} identities returned;{" "}
                {trunk.attempts.length} addresses attempted. This is not an
                exhaustive controller inventory.
              </p>
              <p className="muted">
                Response window {trunk.request.per_mac_timeout_seconds}s ·
                minimum request spacing {trunk.request.spacing_seconds}s · page
                deadline {trunk.request.timeout_seconds}s
              </p>
              <p className="muted">
                {trunk.started_at} / {trunk.finished_at}
              </p>
              {trunk.warnings.map((warning, index) => (
                <p key={index} className="muted">
                  {warning}
                </p>
              ))}
              <div className="controller-probe-table">
                <table>
                  <thead>
                    <tr>
                      <th>Address</th>
                      <th>Observation</th>
                      <th>Device identifier</th>
                      <th>Explicit metadata read</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trunk.attempts.map((attempt) => {
                      const found = trunk.devices.find(
                        (row) => row.mac === attempt.mac,
                      );
                      return (
                        <tr
                          key={`${trunk.router}/${trunk.dnet}/${attempt.mac}`}
                        >
                          <td>{attempt.address}</td>
                          <td>
                            {attempt.outcome === "timeout"
                              ? "No response · unknown"
                              : attempt.outcome}
                            {attempt.error && (
                              <>
                                <br />
                                {attempt.error}
                              </>
                            )}
                          </td>
                          <td>
                            {found?.device ?? "Unknown"}
                            {found && (
                              <>
                                <br />
                                <span className="muted">
                                  {found.received_at}
                                </span>
                              </>
                            )}
                          </td>
                          <td>
                            {found && (
                              <button
                                disabled={busy || !ready}
                                aria-label={`Read metadata for ${found.address}`}
                                onClick={() => {
                                  if (currentTrunk.current === trunk)
                                    void probe(String(found.mac));
                                }}
                              >
                                Read controller metadata
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="muted">{trunk.scope}</p>
              <div className="button-row">
                <button disabled={busy} onClick={exportPage}>
                  <Download size={15} /> Download address page JSON
                </button>
                <button
                  disabled={
                    busy ||
                    (trunk.next_mac === null && trunk.request.mac_high >= 254)
                  }
                  onClick={nextPage}
                >
                  Prepare next MAC page
                </button>
              </div>
              <details>
                <summary>Complete address page evidence</summary>
                <pre>{JSON.stringify(trunk, null, 2)}</pre>
              </details>
            </section>
          )}
        </section>
      </div>
    </section>
  );
}
