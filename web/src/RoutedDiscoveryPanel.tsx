import { useEffect, useRef, useState } from "react";
import { Download, Network, Search } from "lucide-react";
import { api, saveBlob } from "./api";
import type { NamedScanTarget } from "./DeviceScanPanel";
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
type RouterChoice = {
  router: string;
  networks: number[];
  truncated?: boolean;
  cached?: boolean;
};
type RouterReport = {
  routers: RouterChoice[];
  complete: boolean;
  truncated: boolean;
  warnings: string[];
  scope: string;
};
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
type ScanName = {
  name: string | null;
  state: "reading" | "complete" | "unavailable";
  finishedAt?: string;
  error?: string;
};
type ScanRequest = {
  router: string;
  dnet: number;
  low: number;
  high: number;
  timeout_seconds: number;
  max_devices: number;
};
export type RoutedScanResult = {
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
  onDiscovered,
  knownDevices = [],
  interfaceIdentity = "",
  connectorConfig = null,
  localDiscoveryAvailable = true,
  onSelectionCleared,
  onNamesDiscovered,
}: {
  connected: boolean;
  onSelect?: (device: RoutedDevice, router: string, dnet: number) => void;
  onDiscovered?: (result: RoutedScanResult) => void;
  knownDevices?: NamedScanTarget[];
  interfaceIdentity?: string;
  connectorConfig?: unknown;
  localDiscoveryAvailable?: boolean;
  onSelectionCleared?: () => void;
  onNamesDiscovered?: (devices: NamedScanTarget[]) => void;
}) {
  const [router, setRouter] = useState("");
  const [dnet, setDnet] = useState("");
  const [routerDevice, setRouterDevice] = useState("");
  const [routers, setRouters] = useState<RouterChoice[]>([]);
  const [routerReport, setRouterReport] = useState<RouterReport | null>(null);
  const [discoveryPort, setDiscoveryPort] = useState("47808");
  const [controller, setController] = useState("");
  const [low, setLow] = useState("0"),
    [high, setHigh] = useState("4194302");
  const [seconds, setSeconds] = useState("3"),
    [limit, setLimit] = useState("128");
  const [networks, setNetworks] = useState<NetworkReport | null>(null);
  const [scan, setScan] = useState<RoutedScanResult | null>(null);
  const [bindings, setBindings] = useState<BindingReport | null>(null);
  const [nameResults, setNameResults] = useState<Record<string, ScanName>>({});
  const [nameBusy, setNameBusy] = useState(false);
  const [nameRetry, setNameRetry] = useState(0);
  const [controllerQuery, setControllerQuery] = useState("");
  const namesRef = useRef(nameResults);
  const namedScan = useRef<RoutedScanResult | null>(null);
  const nameEpoch = useRef(0);
  const namesCallback = useRef(onNamesDiscovered);
  namesCallback.current = onNamesDiscovered;
  const connectedRef = useRef(connected);
  connectedRef.current = connected;
  const networkChoices = Array.from(
    new Set([...(networks?.networks ?? []), ...(bindings?.networks ?? [])]),
  ).sort((a, b) => a - b);
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
  const previousInterface = useRef(interfaceIdentity);
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
  useEffect(() => {
    if (previousInterface.current !== interfaceIdentity) {
      previousInterface.current = interfaceIdentity;
      epoch.current++;
      setRouters([]);
      setRouterReport(null);
      setNetworks(null);
      setBindings(null);
      setScan(null);
      setController("");
    }
  }, [interfaceIdentity]);

  const endpointKey = (value: string) =>
    value.trim() &&
    (value.includes(":") ? value.trim() : value.trim() + ":47808");
  const configKey = (value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? JSON.stringify(
          Object.entries(value).sort(([a], [b]) => a.localeCompare(b)),
        )
      : null;
  const currentConfig = configKey(connectorConfig);
  const currentNames = knownDevices.filter(
    (item) =>
      !!interfaceIdentity &&
      item.observedInterface === interfaceIdentity &&
      currentConfig !== null &&
      configKey(item.connectorConfig) === currentConfig,
  );
  const routerName = (address: string) =>
    currentNames.find(
      (item) =>
        item.target.source === "ip" &&
        endpointKey(item.target.address) === endpointKey(address),
    )?.name;
  const nameKey = (device: RoutedDevice, result: RoutedScanResult) =>
    JSON.stringify([
      endpointKey(result.report.router),
      result.report.dnet,
      device.address,
      device.device,
    ]);
  const controllerName = (device: RoutedDevice, result: RoutedScanResult) =>
    nameResults[nameKey(device, result)]?.name;
  const nameLabel = (device: RoutedDevice, result: RoutedScanResult) =>
    controllerName(device, result) ||
    (nameResults[nameKey(device, result)]?.state === "unavailable"
      ? "Name unavailable"
      : "Reading name…");
  const controllerKey = (device: RoutedDevice) =>
    JSON.stringify([device.address, device.device]);
  useEffect(() => {
    const owner = ++nameEpoch.current;
    setNameBusy(false);
    if (namedScan.current !== scan) {
      namedScan.current = scan;
      namesRef.current = {};
      setNameResults({});
      setControllerQuery("");
    }
    if (!connected || !scan) return;
    const valid = () =>
      mounted.current &&
      connectedRef.current &&
      nameEpoch.current === owner &&
      currentScan.current === scan;
    setNameBusy(true);
    void (async () => {
      try {
        for (const device of scan.report.devices) {
          if (!valid()) break;
          const key = nameKey(device, scan);
          if (
            ["complete", "unavailable"].includes(namesRef.current[key]?.state)
          )
            continue;
          namesRef.current = {
            ...namesRef.current,
            [key]: { name: null, state: "reading" },
          };
          setNameResults(namesRef.current);
          try {
            const report = await api("/bacnet/device-name", {
              address: device.address,
              device: device.device,
              router: scan.report.router,
              dnet: scan.report.dnet,
            });
            if (!valid()) break;
            if (
              !report.identity_verified ||
              typeof report.name !== "string" ||
              !report.name.trim() ||
              report.address !== device.address ||
              report.device !== device.device ||
              endpointKey(report.router ?? "") !==
                endpointKey(scan.report.router) ||
              report.dnet !== scan.report.dnet
            )
              throw new Error(
                report.errors?.map((item: any) => item.error).join(" ") ||
                  "The device did not return a name verified for this exact scan identity.",
              );
            namesRef.current = {
              ...namesRef.current,
              [key]: {
                name: report.name,
                state: "complete",
                finishedAt: report.finished_at,
              },
            };
            setNameResults(namesRef.current);
            namesCallback.current?.([
              {
                target: {
                  source: "routed",
                  address: device.address,
                  device: device.device,
                  router: scan.report.router,
                  dnet: scan.report.dnet,
                },
                name: report.name,
                observedInterface: interfaceIdentity,
                connectorConfig: report.connector_config,
              },
            ]);
          } catch (failure) {
            if (!valid()) break;
            namesRef.current = {
              ...namesRef.current,
              [key]: {
                name: null,
                state: "unavailable",
                error: String(failure),
              },
            };
            setNameResults(namesRef.current);
          }
        }
      } finally {
        if (valid()) setNameBusy(false);
      }
    })();
    return () => {
      nameEpoch.current++;
    };
  }, [scan, connected, nameRetry]);
  const matchingControllers =
    scan?.report.devices.filter((device) =>
      [
        controllerName(device, scan),
        device.address,
        device.device,
        device.vendor,
      ]
        .join(" ")
        .toLowerCase()
        .includes(controllerQuery.trim().toLowerCase()),
    ) ?? [];
  const namesRead = Object.values(nameResults).filter(
    (item) => item.state === "complete",
  ).length;
  const namesUnavailable = Object.values(nameResults).filter(
    (item) => item.state === "unavailable",
  ).length;
  function clearSelection() {
    setController("");
    onSelectionCleared?.();
  }

  function edit(change: () => void, all = false) {
    if (active.current || !connected) return;
    epoch.current++;
    setScan(null);
    clearSelection();
    if (all) {
      setNetworks(null);
      setBindings(null);
      setDnet("");
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

  async function findRouters() {
    await action(async (request) => {
      setRouterReport(null);
      setNetworks(null);
      setBindings(null);
      setScan(null);
      setDnet("");
      clearSelection();
      const report = await api("/bacnet/discover-routers", {
        udp_port: integer(discoveryPort, 1, 65535, "Router discovery UDP port"),
        timeout_seconds: 2.0,
        max_routers: 64,
        max_networks: 128,
      });
      if (current(request)) {
        setRouters(report.routers);
        setRouterReport(report);
        setRouter("");
      }
    });
  }
  async function discover(selectedRouter = router) {
    await action(async (request) => {
      if (!selectedRouter.trim())
        throw new Error("Enter an explicit router IPv4 address and UDP port.");
      setRouter(selectedRouter);
      setRouterDevice("");
      setNetworks(null);
      setBindings(null);
      setScan(null);
      setDnet("");
      clearSelection();
      const report = await api("/bacnet/router-networks", {
        router: selectedRouter.trim(),
        timeout_seconds: 2,
        max_networks: 64,
      });
      if (current(request)) {
        setNetworks(report);
        setRouter(report.router);
        setRouters((choices) => [
          ...choices.filter(
            (item) => endpointKey(item.router) !== endpointKey(report.router),
          ),
          { router: report.router, networks: report.networks },
        ]);
        if (!report.networks.length) {
          try {
            const cached = await api("/bacnet/router-bindings", {
              router: report.router,
              max_bindings: 2048,
            });
            if (current(request)) {
              setBindings(cached);
              setRouterDevice(String(cached.device));
              setRouters((choices) =>
                choices.map((choice) =>
                  endpointKey(choice.router) === endpointKey(cached.router)
                    ? { ...choice, networks: cached.networks, cached: true }
                    : choice,
                ),
              );
            }
          } catch (failure) {
            if (current(request))
              setError(
                "The router did not advertise networks, and its cached network list could not be read. " +
                  String(failure),
              );
          }
        }
      }
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
      clearSelection();
      const report = await api("/bacnet/scan-trunk", payload);
      if (current(request)) {
        const result = { request: payload, report };
        setScan(result);
        onDiscovered?.(result);
      }
    });
  }
  function selectController(device: RoutedDevice, result: RoutedScanResult) {
    if (active.current || !connected || currentScan.current !== result) return;
    setController(controllerKey(device));
    onSelect?.(device, result.report.router, result.report.dnet);
    setOutcome(
      `Opening ${controllerName(device, result) || device.device} at ${device.address} via ${result.report.router}. Its identity will be read again before commissioning.`,
    );
    document
      .getElementById("controller-instance-commissioning")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function readBindings() {
    await action(async (request) => {
      if (!router.trim())
        throw new Error("Enter an explicit router IPv4 address and UDP port.");
      const device = routerDevice.trim()
        ? integer(routerDevice, 0, 4194302, "Router device instance")
        : undefined;
      setBindings(null);
      const report = await api("/bacnet/router-bindings", {
        router: router.trim(),
        device,
        max_bindings: 2048,
      });
      if (current(request)) {
        setBindings(report);
        setRouterDevice(String(report.device));
      }
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
    const nameSnapshot = snapshot.report.devices.map((device) => ({
      address: device.address,
      device: device.device,
      router: snapshot.report.router,
      dnet: snapshot.report.dnet,
      ...(namesRef.current[nameKey(device, snapshot)] ?? {
        name: null,
        state: "pending",
      }),
    }));
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
      const nameDigest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(JSON.stringify(nameSnapshot)),
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
                device_names: nameSnapshot,
                names_sha256: Array.from(new Uint8Array(nameDigest), (value) =>
                  value.toString(16).padStart(2, "0"),
                ).join(""),
                names_hash_encoding: "UTF-8 JSON.stringify(device_names)",
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
          Choose a router, select an advertised or cached network, scan that
          network, then choose a controller to modify. Devices that do not
          answer during the response window can be absent. Discovery does not
          upload a controller program.
        </p>
        {!connected && (
          <p className="help-text">
            Open the intended BACnet interface before issuing a request.
          </p>
        )}
        <h4>1. Select a router</h4>
        <div className="form-grid">
          <label>
            Router
            <select
              aria-label="Commissioning router"
              disabled={busy || !connected}
              value={
                routers.find(
                  (item) => endpointKey(item.router) === endpointKey(router),
                )?.router || ""
              }
              onChange={(event) => void discover(event.target.value)}
            >
              <option value="" disabled>
                Choose a router
              </option>
              {routers.map((item) => (
                <option key={item.router} value={item.router}>
                  {routerName(item.router)
                    ? `${routerName(item.router)} · `
                    : ""}
                  {item.router} · networks{" "}
                  {item.networks.join(", ") || "none advertised"}
                  {item.cached ? " (cached; scan required)" : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="routed-action">
            <button
              disabled={busy || !connected || !localDiscoveryAvailable}
              onClick={() => void findRouters()}
            >
              Find local routers
            </button>
          </div>
        </div>
        {routerReport && (
          <p role="status">
            {routerReport.routers.length} router(s) answered.
            {routerReport.truncated ? " Partial list." : ""}{" "}
            {routerReport.warnings.join(" ")}
          </p>
        )}
        <p className="help-text">
          Find local routers searches the open interface’s IPv4 subnet. For a
          known or remote router, enter its address and read its networks.
        </p>
        <details>
          <summary>Router discovery settings</summary>
          <label>
            Router discovery UDP port
            <input
              aria-label="Router discovery UDP port"
              disabled={busy || !connected}
              value={discoveryPort}
              onChange={(event) =>
                edit(() => setDiscoveryPort(event.target.value), true)
              }
            />
          </label>
        </details>
        <div className="form-grid">
          <label>
            Router IPv4 address / UDP port
            <input
              aria-label="Discovery router address"
              disabled={busy || !connected}
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
              onClick={() => void discover()}
            >
              <Search size={14} /> Read router networks
            </button>
          </div>
        </div>
        <details>
          <summary>Router identity and cached address evidence</summary>
          <div className="form-grid">
            <label>
              Router device instance (optional cached-binding read)
              <input
                aria-label="Discovery router device instance"
                type="number"
                min={0}
                max={4194302}
                disabled={busy || !connected}
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
                disabled={busy || !connected || !router.trim()}
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
                    disabled={busy || !connected}
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
                  No cached bindings were returned. This does not prove
                  downstream networks are empty.
                </p>
              )}
            </div>
          )}
        </details>
        {networks && (
          <details>
            <summary>Network advertisement evidence</summary>
            <div role="region" aria-label="Router network response">
              <WindowDetails report={networks} />
              <div className="routed-networks">
                {networks.networks.map((network) => (
                  <button
                    key={network}
                    disabled={busy || !connected}
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
          </details>
        )}
        {busy && networks && !networks.networks.length && (
          <p role="status">
            No network advertisement arrived. Reading the selected router’s
            cached network list…
          </p>
        )}
        {bindings && !networks?.networks.length && (
          <p role="status" aria-label="Cached network discovery">
            Router Device {bindings.device}: {bindings.networks.length} cached
            network choice(s). These are discovery leads; scan the selected
            network to verify responding controllers.
            {bindings.truncated ? " The cache result is partial." : ""}
          </p>
        )}
        <h4>2. Select and scan a trunk</h4>
        <label>
          Trunk / BACnet network
          <select
            aria-label="Commissioning trunk"
            disabled={busy || !connected || !networkChoices.length}
            value={networkChoices.includes(Number(dnet)) ? dnet : ""}
            onChange={(event) => edit(() => setDnet(event.target.value))}
          >
            <option value="" disabled>
              Choose a discovered network
            </option>
            {networkChoices.map((network) => (
              <option key={network} value={String(network)}>
                Network {network}
                {networks?.networks.includes(network)
                  ? " · advertised"
                  : " · cached; scan required"}
              </option>
            ))}
          </select>
        </label>
        <p className="help-text">
          Advertised and cached BACnet networks do not supply FC trunk names or
          verify the bus type. Cached choices do not establish current routing
          or controller liveness; a fresh scan is required.
        </p>
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
                disabled={busy || !connected}
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
            <h4>3. Select a controller to modify</h4>
            <p role="status" aria-label="Controller name lookup">
              {namesRead} of {scan.report.devices.length} controller names read.
              {nameBusy ? " Reading names sequentially…" : ""}
              {namesUnavailable ? ` ${namesUnavailable} unavailable.` : ""}
            </p>
            <div className="button-row">
              <label>
                Find controller
                <input
                  aria-label="Find scanned controller"
                  type="search"
                  placeholder="Name, address or instance — e.g. TB-3-201"
                  value={controllerQuery}
                  onChange={(event) => {
                    setControllerQuery(event.target.value);
                    setController("");
                  }}
                />
              </label>
              {!!namesUnavailable && (
                <button
                  disabled={busy || nameBusy || !connected}
                  onClick={() => {
                    namesRef.current = Object.fromEntries(
                      Object.entries(namesRef.current).filter(
                        ([, item]) => item.state === "complete",
                      ),
                    );
                    setNameResults(namesRef.current);
                    setNameRetry((value) => value + 1);
                  }}
                >
                  Retry unavailable names
                </button>
              )}
            </div>
            <div className="form-grid">
              <label>
                Controller
                <select
                  aria-label="Commissioning controller"
                  disabled={busy || !connected}
                  value={controller}
                  onChange={(event) => setController(event.target.value)}
                >
                  <option value="" disabled>
                    Choose a controller from this scan
                  </option>
                  {matchingControllers.map((device) => (
                    <option
                      key={controllerKey(device)}
                      value={controllerKey(device)}
                    >
                      {nameLabel(device, scan)} · {device.address} ·{" "}
                      {device.device}
                    </option>
                  ))}
                </select>
              </label>
              <div className="routed-action">
                <button
                  disabled={busy || !connected || !controller}
                  onClick={() => {
                    const device = scan.report.devices.find(
                      (item) => controllerKey(item) === controller,
                    );
                    if (device) selectController(device, scan);
                  }}
                >
                  Open controller
                </button>
              </div>
            </div>
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
                    <th>Controller name</th>
                    <th>Address / MAC</th>
                    <th>Device</th>
                    <th>Vendor</th>
                    <th>Max APDU</th>
                    <th>Use</th>
                  </tr>
                </thead>
                <tbody>
                  {matchingControllers.map((device, index) => (
                    <tr
                      key={device.address + ":" + device.device + ":" + index}
                    >
                      <td>
                        <strong>{nameLabel(device, scan)}</strong>
                        {nameResults[nameKey(device, scan)]?.error && (
                          <small>
                            {nameResults[nameKey(device, scan)].error}
                          </small>
                        )}
                      </td>
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
                                selectController(device, scan);
                            }}
                          >
                            Open{" "}
                            {controllerName(device, scan) || device.address}
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
            {!!scan.report.devices.length && !matchingControllers.length && (
              <p>No controllers match this search.</p>
            )}
            {onSelect && (
              <p className="help-text">
                Open a controller to verify its exact router, network, MAC and
                Device instance before commissioning. Reading names and opening
                a controller send no writes.
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
