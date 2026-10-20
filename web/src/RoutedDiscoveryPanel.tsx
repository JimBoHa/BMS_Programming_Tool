import { useEffect, useRef, useState } from "react";
import { Download, Network, Search } from "lucide-react";
import { api, saveBlob } from "./api";
import "./routed-discovery.css";

export type RoutedDevice = {
  address: string;
  device: string;
  vendor: number;
  max_apdu: number;
  router: string;
  [key: string]: unknown;
};
type WindowReport = {
  router: string;
  complete: boolean;
  truncated: boolean;
  warnings: string[];
  started_at: string;
  received_at: string | null;
  finished_at?: string;
  scope: string;
};
type NetworkReport = WindowReport & { networks: number[] };
type BindingReport = WindowReport & {
  device: number;
  networks: number[];
  bindings: {
    address: string;
    dnet: number;
    mac_hex: string;
    mstp_mac: number | null;
    device_instance: number | null;
    device: string | null;
    cached: boolean;
    live_verified: boolean;
  }[];
};
type ScanRequest = {
  router: string;
  dnet: number;
  low: number;
  high: number;
  timeout_seconds: number;
  max_devices: number;
};
type Scan = {
  request: ScanRequest;
  report: WindowReport & { dnet: number; devices: RoutedDevice[] };
};

function integer(value: string, low: number, high: number, label: string) {
  const parsed = Number(value);
  if (
    !value.trim() ||
    !Number.isInteger(parsed) ||
    parsed < low ||
    parsed > high
  )
    throw new Error(`${label} must be an integer from ${low} to ${high}.`);
  return parsed;
}

export function RoutedDiscoveryPanel({
  connected,
  onSelect,
}: {
  connected: boolean;
  onSelect?: (device: RoutedDevice, router: string, dnet: number) => void;
}) {
  const [router, setRouter] = useState("");
  const [dnet, setDnet] = useState("");
  const [routerDevice, setRouterDevice] = useState("");
  const [low, setLow] = useState("0"),
    [high, setHigh] = useState("4194302");
  const [seconds, setSeconds] = useState("3"),
    [limit, setLimit] = useState("128");
  const [networks, setNetworks] = useState<NetworkReport | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [bindings, setBindings] = useState<BindingReport | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [outcome, setOutcome] = useState("");
  const mounted = useRef(false),
    active = useRef(false),
    epoch = useRef(0);
  const currentScan = useRef(scan);
  currentScan.current = scan;
  const currentBindings = useRef(bindings);
  currentBindings.current = bindings;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
  }, [connected]);

  function edit(change: () => void, all = false) {
    if (active.current) return;
    epoch.current++;
    setScan(null);
    if (all) {
      setNetworks(null);
      setBindings(null);
    }
    setOutcome("");
    setError("");
    change();
  }
  async function action(work: (request: number) => Promise<void>) {
    if (active.current || !connected) return;
    active.current = true;
    const request = ++epoch.current;
    setBusy(true);
    setError("");
    setOutcome("");
    try {
      await work(request);
    } catch (error) {
      if (mounted.current && request === epoch.current) setError(String(error));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  const current = (request: number) =>
    mounted.current && request === epoch.current;

  async function discover() {
    await action(async (request) => {
      if (!router.trim())
        throw new Error("Enter an explicit router IPv4 address and UDP port.");
      setNetworks(null);
      const report = await api("/bacnet/router-networks", {
        router: router.trim(),
        timeout_seconds: 2,
        max_networks: 64,
      });
      if (current(request)) setNetworks(report);
    });
  }
  async function scanTrunk() {
    await action(async (request) => {
      const payload = {
        router: router.trim(),
        dnet: integer(dnet, 1, 65534, "Destination network"),
        low: integer(low, 0, 4194302, "Minimum device instance"),
        high: integer(high, 0, 4194302, "Maximum device instance"),
        timeout_seconds: integer(seconds, 1, 10, "Response window"),
        max_devices: integer(limit, 1, 256, "Device limit"),
      };
      if (!payload.router)
        throw new Error("Enter an explicit router IPv4 address and UDP port.");
      if (payload.low > payload.high)
        throw new Error("Minimum device instance must not exceed maximum.");
      setScan(null);
      const report = await api("/bacnet/scan-trunk", payload);
      if (current(request)) setScan({ request: payload, report });
    });
  }
  async function readBindings() {
    await action(async (request) => {
      if (!router.trim())
        throw new Error("Enter an explicit router IPv4 address and UDP port.");
      const device = integer(
        routerDevice,
        0,
        4194302,
        "Router device instance",
      );
      setBindings(null);
      const report = await api("/bacnet/router-bindings", {
        router: router.trim(),
        device,
        max_bindings: 2048,
      });
      if (current(request)) setBindings(report);
    });
  }
  async function exportBindings() {
    if (!bindings || active.current) return;
    const snapshot = bindings;
    active.current = true;
    setBusy(true);
    setError("");
    setOutcome("");
    try {
      const raw = JSON.stringify(snapshot);
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(raw),
      );
      if (!mounted.current || currentBindings.current !== snapshot) return;
      const sha = Array.from(new Uint8Array(digest), (value) =>
        value.toString(16).padStart(2, "0"),
      ).join("");
      saveBlob(
        new Blob(
          [
            JSON.stringify(
              {
                format: "bms-router-binding-cache/1",
                exported_at: new Date().toISOString(),
                report_sha256: sha,
                hash_encoding: "UTF-8 JSON.stringify(report)",
                report: snapshot,
              },
              null,
              2,
            ),
          ],
          { type: "application/json" },
        ),
        `bacnet-router-${snapshot.device}-cached-bindings.json`,
      );
      setOutcome(
        "Downloaded cached address bindings. Device liveness and controller type remain unverified.",
      );
    } catch (error) {
      if (mounted.current) setError(String(error));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function exportScan() {
    if (!scan || active.current) return;
    const snapshot = scan;
    active.current = true;
    setBusy(true);
    setError("");
    setOutcome("");
    try {
      const raw = JSON.stringify(snapshot.report);
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(raw),
      );
      if (!mounted.current || currentScan.current !== snapshot) return;
      const sha = Array.from(new Uint8Array(digest), (v) =>
        v.toString(16).padStart(2, "0"),
      ).join("");
      saveBlob(
        new Blob(
          [
            JSON.stringify(
              {
                format: "bms-routed-bacnet-discovery/1",
                exported_at: new Date().toISOString(),
                request: snapshot.request,
                report_sha256: sha,
                hash_encoding: "UTF-8 JSON.stringify(report)",
                report: snapshot.report,
              },
              null,
              2,
            ),
          ],
          { type: "application/json" },
        ),
        `bacnet-network-${snapshot.report.dnet}.json`,
      );
      setOutcome(
        `Downloaded network ${snapshot.report.dnet} response report with request bounds and source hash.`,
      );
    } catch (error) {
      if (mounted.current) setError(String(error));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section
      className="card routed-discovery"
      aria-label="Routed BACnet discovery"
    >
      <div className="card-header">
        <h3>
          <Network size={18} /> Routed BACnet discovery
        </h3>
        <span className="pill">EXPLICIT READ-ONLY REQUESTS</span>
      </div>
      <div className="card-body">
        <p>
          Ask a selected BACnet/IP router for networks, then send Who-Is only
          onto one selected destination network. Devices that do not answer
          during the response window can be absent. Discovery does not upload a
          controller program.
        </p>
        {!connected && (
          <p className="help-text">
            Open the intended BACnet interface before issuing a request.
          </p>
        )}
        <div className="form-grid">
          <label>
            Router IPv4 address / UDP port
            <input
              aria-label="Discovery router address"
              disabled={busy}
              value={router}
              placeholder="192.0.2.10:47808"
              onChange={(event) =>
                edit(() => setRouter(event.target.value), true)
              }
            />
          </label>
          <div className="routed-action">
            <button
              disabled={busy || !connected || !router.trim()}
              onClick={discover}
            >
              <Search size={14} /> Read router networks
            </button>
          </div>
        </div>
        <div className="form-grid">
          <label>
            Router device instance (optional cached-binding read)
            <input
              aria-label="Discovery router device instance"
              type="number"
              min={0}
              max={4194302}
              disabled={busy}
              value={routerDevice}
              onChange={(event) =>
                edit(() => {
                  setRouterDevice(event.target.value);
                  setBindings(null);
                })
              }
            />
          </label>
          <div className="routed-action">
            <button
              disabled={busy || !connected || !router.trim() || !routerDevice}
              onClick={readBindings}
            >
              Read router cached bindings
            </button>
          </div>
        </div>
        {bindings && (
          <div role="region" aria-label="Router cached address bindings">
            <div className="routed-report-heading">
              <b>Cached bindings from router device {bindings.device}</b>
              <button disabled={busy} onClick={exportBindings}>
                <Download size={14} /> Download cached bindings JSON
              </button>
            </div>
            <p>
              Cached addresses are discovery leads. Liveness, manufacturer and
              controller type have not been verified; unknown device instances
              remain unknown.
            </p>
            <WindowDetails report={bindings} cached />
            <div className="routed-networks">
              {bindings.networks.map((network) => (
                <button
                  key={network}
                  disabled={busy}
                  onClick={() => edit(() => setDnet(String(network)))}
                >
                  Select cached network {network}
                </button>
              ))}
            </div>
            <div className="routed-table">
              <table>
                <thead>
                  <tr>
                    <th>Cached address</th>
                    <th>Network</th>
                    <th>MAC bytes</th>
                    <th>Device identity</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {bindings.bindings.slice(0, 100).map((binding, index) => (
                    <tr key={index}>
                      <td>{binding.address}</td>
                      <td>{binding.dnet}</td>
                      <td>{binding.mac_hex}</td>
                      <td>
                        {binding.device ||
                          (binding.device_instance === null
                            ? "Unknown device instance"
                            : `device,${binding.device_instance}`)}
                      </td>
                      <td>Cached · liveness unverified</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {bindings.bindings.length > 100 && (
              <p>
                Showing 100 of {bindings.bindings.length} cached bindings.
                Download JSON for the complete returned set.
              </p>
            )}
            {!bindings.bindings.length && (
              <p>
                No cached bindings were returned. This does not prove downstream
                networks are empty.
              </p>
            )}
          </div>
        )}
        {networks && (
          <div role="region" aria-label="Router network response">
            <WindowDetails report={networks} />
            <div className="routed-networks">
              {networks.networks.map((network) => (
                <button
                  key={network}
                  disabled={busy}
                  onClick={() => edit(() => setDnet(String(network)))}
                >
                  Select network {network}
                </button>
              ))}
            </div>
            {!networks.networks.length && (
              <p>No networks were received during this response window.</p>
            )}
          </div>
        )}
        <div className="form-grid">
          {(
            [
              ["Routed destination network", dnet, setDnet, 1, 65534],
              ["Routed minimum device instance", low, setLow, 0, 4194302],
              ["Routed maximum device instance", high, setHigh, 0, 4194302],
              ["Routed response window seconds", seconds, setSeconds, 1, 10],
              ["Routed device result limit", limit, setLimit, 1, 256],
            ] as const
          ).map(([label, value, setter, min, max]) => (
            <label key={label}>
              {label}
              <input
                type="number"
                aria-label={label}
                min={min}
                max={max}
                disabled={busy}
                value={value}
                onChange={(event) => edit(() => setter(event.target.value))}
              />
            </label>
          ))}
          <div className="routed-action">
            <button
              className="primary"
              disabled={busy || !connected || !router.trim() || !dnet}
              onClick={scanTrunk}
            >
              <Search size={14} /> Scan selected routed network
            </button>
          </div>
        </div>
        {scan && (
          <div role="region" aria-label="Routed device response">
            <div className="routed-report-heading">
              <b>
                Network {scan.report.dnet} via {scan.report.router}
              </b>
              <button disabled={busy} onClick={exportScan}>
                <Download size={14} /> Download routed discovery JSON
              </button>
            </div>
            <WindowDetails report={scan.report} />
            <p>
              Requested instances {scan.request.low}–{scan.request.high} ·{" "}
              {scan.request.timeout_seconds}s · at most{" "}
              {scan.request.max_devices} devices
            </p>
            <div className="routed-table">
              <table>
                <thead>
                  <tr>
                    <th>Address</th>
                    <th>Device</th>
                    <th>Vendor</th>
                    <th>Max APDU</th>
                    <th>Use</th>
                  </tr>
                </thead>
                <tbody>
                  {scan.report.devices.map((device, index) => (
                    <tr
                      key={device.address + ":" + device.device + ":" + index}
                    >
                      <td>{device.address}</td>
                      <td>{device.device}</td>
                      <td>{device.vendor}</td>
                      <td>{device.max_apdu}</td>
                      <td>
                        {onSelect ? (
                          <button
                            disabled={busy || !connected}
                            onClick={() => {
                              if (!busy && connected)
                                onSelect(
                                  device,
                                  scan.report.router,
                                  scan.report.dnet,
                                );
                            }}
                          >
                            Use routed device {device.address}
                          </button>
                        ) : (
                          "Inspect only"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!scan.report.devices.length && (
              <p>
                No device replies were received. This does not prove the network
                is empty.
              </p>
            )}
            {onSelect && (
              <p className="help-text">
                Use a device to fill the connection draft. Review the exact
                router/network and open that interface explicitly before point
                reads.
              </p>
            )}
          </div>
        )}
        {outcome && <p role="status">{outcome}</p>}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}

function WindowDetails({
  report,
  cached = false,
}: {
  report: WindowReport;
  cached?: boolean;
}) {
  return (
    <div className="routed-window">
      <p>
        {cached
          ? report.complete
            ? "Cache read completed"
            : "Cache read incomplete"
          : report.complete
            ? "Response window completed"
            : "Response window incomplete"}
        {report.truncated ? " · Result truncated" : ""}. This is a response set,
        not a complete inventory.
      </p>
      <p>
        Started {report.started_at} · Last reply{" "}
        {report.received_at ?? "none within the response window"}
        {report.finished_at ? ` · Finished ${report.finished_at}` : ""}
      </p>
      <p className="help-text">{report.scope}</p>
      {!!report.warnings?.length && (
        <ul aria-label="Routed discovery warnings">
          {report.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
