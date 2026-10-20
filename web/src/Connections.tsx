import { useEffect, useRef, useState } from "react";
import {
  Download,
  Network,
  RefreshCw,
  Usb,
  Radio,
  Search,
  PlugZap,
} from "lucide-react";
import { api, saveBlob } from "./api";
import {
  RoutedDiscoveryPanel,
  type RoutedScanResult,
} from "./RoutedDiscoveryPanel";
import { DeviceScanPanel, type ScanTarget } from "./DeviceScanPanel";
import { BacnetFilesPanel } from "./BacnetFilesPanel";
import { ControllerProbePanel } from "./ControllerProbePanel";

export function Connections() {
  const [config, setConfig] = useState({
      local_address: "127.0.0.1:47809",
      instance: 4190001,
      router: "",
      dnet: "",
      bbmd_address: "",
      foreign_ttl: 60,
    }),
    [target, setTarget] = useState("127.0.0.1:47808"),
    [object, setObject] = useState("analog-value,1"),
    [property, setProperty] = useState("present-value"),
    [devices, setDevices] = useState<any[]>([]),
    [routedResult, setRoutedResult] = useState<RoutedScanResult | null>(null),
    [foreignLow, setForeignLow] = useState("0"),
    [foreignHigh, setForeignHigh] = useState("4194302"),
    [value, setValue] = useState<any>(null),
    [objectPage, setObjectPage] = useState<any>(null),
    [objectOffset, setObjectOffset] = useState("0"),
    [objectLimit, setObjectLimit] = useState("100"),
    [objectTimeout, setObjectTimeout] = useState("15"),
    [objectDownloaded, setObjectDownloaded] = useState(""),
    [selectedRoute, setSelectedRoute] = useState<{
      router: string;
      dnet: number;
    } | null>(null),
    [status, setStatus] = useState<any>({ connected: false, commands: [] }),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [command, setCommand] = useState("50"),
    [priority, setPriority] = useState(16),
    [plan, setPlan] = useState<any>(null),
    [serialPorts, setSerialPorts] = useState<any[]>([]),
    [mstp, setMstp] = useState({
      port: "",
      mac: 120,
      instance: 4190001,
      baudrate: 38400,
      max_master: 127,
      max_info_frames: 1,
    }),
    [modbus, setModbus] = useState({
      transport: "tcp",
      address: "127.0.0.1",
      port: 502,
      unit: 1,
      register: 0,
      count: 1,
      table: "holding",
      baud: 38400,
      parity: "N",
    }),
    [modbusResult, setModbusResult] = useState<any>(null);
  const mounted = useRef(false),
    statusEpoch = useRef(0),
    ipDirty = useRef(false);
  const routerKey = (address?: string) =>
    address?.trim()
      ? address.trim().includes(":")
        ? address.trim()
        : address.trim() + ":47808"
      : "";
  const selectedRouteReady =
    !selectedRoute ||
    (status.config?.transport !== "mstp" &&
      routerKey(status.config?.router) === routerKey(selectedRoute.router) &&
      Number(status.config?.dnet) === selectedRoute.dnet);
  const pointReady = status.connected && selectedRouteReady;
  const probeNetwork = Number(config.dnet);
  const probeDnet =
    Number.isInteger(probeNetwork) && probeNetwork >= 1 && probeNetwork <= 65534
      ? probeNetwork
      : null;
  const probeReady =
    status.connected &&
    !busy &&
    status.config?.transport !== "mstp" &&
    !!config.router.trim() &&
    probeDnet !== null &&
    routerKey(config.router) === routerKey(status.config?.router) &&
    probeDnet === Number(status.config?.dnet);
  function clearPointResults(clearRoute = false) {
    setPlan(null);
    setValue(null);
    setObjectPage(null);
    setObjectOffset("0");
    setObjectDownloaded("");
    if (clearRoute) setSelectedRoute(null);
  }
  function selectScannedDevice(device: ScanTarget) {
    if (busy) return;
    setTarget(device.address);
    setObject(device.device);
    setProperty("object-name");
    clearPointResults(true);
    if (
      device.source === "routed" &&
      device.router &&
      device.dnet !== undefined
    ) {
      ipDirty.current = true;
      setConfig((current) => ({
        ...current,
        router: device.router!,
        dnet: String(device.dnet),
      }));
      setSelectedRoute({ router: device.router, dnet: device.dnet });
    }
  }
  function objectInteger(
    value: string,
    min: number,
    max: number,
    label: string,
  ) {
    const parsed = Number(value);
    if (
      !value.trim() ||
      !Number.isInteger(parsed) ||
      parsed < min ||
      parsed > max
    )
      throw new Error(`${label} must be an integer from ${min} to ${max}.`);
    return parsed;
  }
  async function readObjectPage(offset = objectOffset) {
    if (!pointReady) return;
    await action(async () => {
      const payload = {
        address: target,
        object_id: object,
        offset: objectInteger(offset, 0, 20000, "Object-list offset"),
        limit: objectInteger(objectLimit, 1, 200, "Object-list page size"),
        timeout_seconds: objectInteger(
          objectTimeout,
          1,
          30,
          "Object-list deadline",
        ),
      };
      setObjectPage(null);
      setObjectDownloaded("");
      setValue(null);
      setObjectOffset(String(payload.offset));
      setObjectPage(await api("/bacnet/objects", payload));
    });
  }
  function exportObjectPage() {
    if (!objectPage || busy) return;
    const filename = `bacnet-objects-${String(objectPage.device).replace(/[^A-Za-z0-9_-]/g, "_")}-${objectPage.offset}.json`;
    saveBlob(
      new Blob([JSON.stringify(objectPage, null, 2)], {
        type: "application/json",
      }),
      filename,
    );
    setObjectDownloaded(
      `Downloaded the displayed object-list page for ${objectPage.address} / ${objectPage.device}. Completeness and error evidence are preserved.`,
    );
  }
  async function refresh() {
    const epoch = ++statusEpoch.current;
    const [next, ports] = await Promise.all([
      api("/bacnet/status"),
      api("/ports"),
    ]);
    if (mounted.current && epoch === statusEpoch.current) {
      setStatus(next);
      setSerialPorts(ports);
    }
  }
  useEffect(() => {
    mounted.current = true;
    refresh().catch((e) => setError(e.message));
    return () => {
      mounted.current = false;
      statusEpoch.current++;
    };
  }, []);
  useEffect(() => {
    const saved = status.config;
    if (!saved?.local_address || saved.transport === "mstp" || ipDirty.current)
      return;
    setConfig({
      local_address: saved.local_address,
      instance: saved.instance,
      router: saved.router || "",
      dnet:
        saved.dnet === null || saved.dnet === undefined
          ? ""
          : String(saved.dnet),
      bbmd_address: saved.bbmd_address || "",
      foreign_ttl: saved.foreign_ttl || 60,
    });
  }, [
    status.config?.local_address,
    status.config?.instance,
    status.config?.router,
    status.config?.dnet,
    status.config?.bbmd_address,
    status.config?.foreign_ttl,
    status.config?.transport,
  ]);
  useEffect(() => {
    if (status.config?.transport === "mstp") {
      const saved = status.config;
      setMstp({
        port: saved.port,
        mac: saved.mac,
        instance: saved.instance,
        baudrate: saved.baudrate,
        max_master: saved.max_master,
        max_info_frames: saved.max_info_frames,
      });
      setTarget(saved.mac === 5 ? "6" : "5");
      clearPointResults(true);
    }
  }, [status.config?.transport]);
  useEffect(() => {
    if (!status.connected) setPlan(null);
  }, [status.connected]);
  useEffect(() => {
    if (status.config?.transport !== "mstp" && !status.config?.bbmd_address)
      return;
    let live = true;
    const timer = setInterval(() => {
      const epoch = ++statusEpoch.current;
      api("/bacnet/status")
        .then((next) => {
          if (live && mounted.current && epoch === statusEpoch.current)
            setStatus(next);
        })
        .catch((e) => {
          if (live) setError(e.message);
        });
    }, 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [status.config?.transport, status.config?.bbmd_address]);
  async function action(fn: () => Promise<any>) {
    if (busy) return;
    statusEpoch.current++;
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const field = (name: keyof typeof config, title: string, type = "text") => (
    <label>
      {title}
      <input
        type={type}
        disabled={busy}
        value={config[name]}
        onChange={(e) => {
          setPlan(null);
          ipDirty.current = true;
          setConfig({
            ...config,
            [name]:
              type === "number" && name !== "dnet"
                ? Number(e.target.value)
                : e.target.value,
          });
        }}
      />
    </label>
  );
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <span className="eyebrow">COMMISSIONING</span>
          <h1>Connections</h1>
          <p>
            Scan BACnet/IP networks and routed controllers, read device details,
            and work with selected points. Network interfaces open when you
            connect.
          </p>
        </div>
        <div className="button-row">
          <span
            className={
              "connection-badge " + (status.connected ? "connected" : "")
            }
          >
            <span className="status-dot" />
            {status.connected
              ? "BACnet interface open"
              : "No BACnet interface open"}
          </span>
          {(status.connected ||
            status.foreign_device ||
            status.serial_link) && (
            <button
              disabled={busy || !!status.commands.length}
              title={
                status.commands.length
                  ? "Relinquish owned BACnet commands before closing"
                  : "Close the selected BACnet interface"
              }
              onClick={() =>
                action(async () => {
                  const result = await api("/bacnet/disconnect", {});
                  if (result.audit_error) setError(result.audit_error);
                  setPlan(null);
                })
              }
            >
              Close BACnet interface
            </button>
          )}
        </div>
      </div>
      <div className="two-column">
        <section className="card">
          <div className="card-header">
            <h3>
              <Network size={18} /> BACnet/IP interface
            </h3>
          </div>
          <div className="card-body form-grid">
            {field("local_address", "Local bind address / UDP port")}
            {field("instance", "Client device instance", "number")}
            {field("router", "Router IP (optional)")}
            {field("dnet", "MS/TP destination network (optional)", "number")}
            {field("bbmd_address", "BBMD address / UDP port (optional)")}
            {config.bbmd_address &&
              field(
                "foreign_ttl",
                "Foreign registration TTL (seconds)",
                "number",
              )}
            <div className="full">
              <button
                disabled={busy}
                className="primary"
                onClick={() =>
                  action(async () => {
                    await api("/bacnet/connect", {
                      ...config,
                      router: config.router || null,
                      dnet: config.dnet ? Number(config.dnet) : null,
                      bbmd_address: config.bbmd_address.trim() || null,
                      foreign_ttl: config.bbmd_address.trim()
                        ? config.foreign_ttl
                        : 60,
                    });
                    ipDirty.current = false;
                    setPlan(null);
                  })
                }
              >
                <PlugZap size={15} /> Open interface
              </button>
              <p className="help-text">
                Routed targets use network:MAC, for example 2001:4. An NAE must
                expose a usable BACnet routing path; reachability of its web
                page alone does not prove routing.
              </p>
              <p className="help-text">
                BBMD registration enables broadcast discovery across IP subnets
                when the BBMD accepts foreign devices. Addressed controller
                services use the selected router directly.
              </p>
              {status.foreign_device && (
                <div
                  aria-label="BACnet foreign registration status"
                  role="status"
                >
                  <b>
                    {status.foreign_device.registered
                      ? "Foreign registration active"
                      : "Foreign registration unavailable"}
                  </b>
                  <p>
                    {status.foreign_device.bbmd_address} · TTL{" "}
                    {status.foreign_device.ttl}s · lease remaining{" "}
                    {status.foreign_device.lease_remaining_seconds ?? 0}s
                  </p>
                  {status.foreign_device.error && (
                    <p className="inline-error">
                      {status.foreign_device.error}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-header">
            <h3>
              <Search size={18} /> Device and point services
            </h3>
          </div>
          <div className="card-body form-grid">
            <label className="full">
              Unicast target
              <input
                disabled={busy}
                value={target}
                onChange={(e) => {
                  setTarget(e.target.value);
                  clearPointResults(true);
                }}
              />
            </label>
            <label>
              Object identifier
              <input
                disabled={busy}
                value={object}
                onChange={(e) => {
                  setObject(e.target.value);
                  clearPointResults();
                }}
              />
            </label>
            <label>
              Property
              <input
                disabled={busy}
                value={property}
                onChange={(e) => setProperty(e.target.value)}
              />
            </label>
            <div className="button-row full">
              <button
                disabled={
                  busy ||
                  !status.connected ||
                  !status.foreign_device?.registered
                }
                onClick={() =>
                  action(async () => {
                    const low = Number(foreignLow),
                      high = Number(foreignHigh);
                    if (
                      !foreignLow ||
                      !foreignHigh ||
                      !Number.isInteger(low) ||
                      !Number.isInteger(high) ||
                      low < 0 ||
                      high > 4194302 ||
                      low > high
                    )
                      throw new Error(
                        "BBMD discovery requires an ordered instance range from 0 to 4194302.",
                      );
                    setDevices(
                      await api("/bacnet/discover-foreign", { low, high }),
                    );
                  })
                }
              >
                Discover through BBMD
              </button>
              <button
                disabled={busy || !pointReady}
                onClick={() =>
                  action(async () =>
                    setDevices(
                      await api("/bacnet/discover", { address: target }),
                    ),
                  )
                }
              >
                Who-Is target
              </button>
              <button
                disabled={busy || !pointReady}
                onClick={() =>
                  action(async () =>
                    setValue(
                      await api("/bacnet/read", {
                        address: target,
                        object_id: object,
                        property_id: property,
                      }),
                    ),
                  )
                }
              >
                Read property
              </button>
              <button
                disabled={busy || !pointReady}
                onClick={() => readObjectPage()}
              >
                Read object list
              </button>
            </div>
            {!selectedRouteReady && (
              <p className="help-text full" role="status">
                Selected routed target requires router {selectedRoute?.router}{" "}
                and network {selectedRoute?.dnet}. Review the connection draft
                and choose Open interface before point services.
              </p>
            )}
            <div
              className="form-grid full"
              aria-label="Object-list page request"
            >
              {(
                [
                  [
                    "Object-list offset",
                    objectOffset,
                    setObjectOffset,
                    0,
                    20000,
                  ],
                  [
                    "Object-list page size",
                    objectLimit,
                    setObjectLimit,
                    1,
                    200,
                  ],
                  [
                    "Object-list deadline seconds",
                    objectTimeout,
                    setObjectTimeout,
                    1,
                    30,
                  ],
                ] as const
              ).map(([label, current, setter, min, max]) => (
                <label key={label}>
                  {label}
                  <input
                    type="number"
                    aria-label={label}
                    min={min}
                    max={max}
                    disabled={busy}
                    value={current}
                    onChange={(event) => {
                      setter(event.target.value);
                      setObjectPage(null);
                      setObjectDownloaded("");
                    }}
                  />
                </label>
              ))}
            </div>
            {objectPage && (
              <div
                className="full"
                role="region"
                aria-label="BACnet object-list page"
              >
                <p>
                  <b>
                    {objectPage.address} / {objectPage.device}
                  </b>{" "}
                  · Offset {objectPage.offset} · {objectPage.objects.length}{" "}
                  received · Device total {objectPage.total ?? "unknown"}
                </p>
                <p>
                  {objectPage.complete
                    ? "Page request completed"
                    : "Page request incomplete"}
                  {objectPage.truncated ? " · Further indices remain" : ""}.
                  This page is not an application backup or a verified complete
                  inventory.
                </p>
                {objectPage.error && (
                  <p className="inline-error" role="alert">
                    {objectPage.error}
                  </p>
                )}
                <p className="help-text">{objectPage.scope}</p>
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Index</th>
                        <th>Object</th>
                      </tr>
                    </thead>
                    <tbody>
                      {objectPage.objects.map((item: any) => (
                        <tr key={item.index}>
                          <td>{item.index}</td>
                          <td>{item.object}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="button-row">
                  <button disabled={busy} onClick={exportObjectPage}>
                    <Download size={14} /> Download shown object-list JSON
                  </button>
                  {objectPage.next_offset !== null &&
                    objectPage.next_offset !== undefined && (
                      <button
                        disabled={busy || !pointReady}
                        onClick={() =>
                          readObjectPage(String(objectPage.next_offset))
                        }
                      >
                        Read next object-list page
                      </button>
                    )}
                </div>
                {objectDownloaded && <p role="status">{objectDownloaded}</p>}
              </div>
            )}
            {config.bbmd_address && (
              <>
                <label>
                  BBMD discovery minimum instance
                  <input
                    type="number"
                    min={0}
                    max={4194302}
                    disabled={busy}
                    value={foreignLow}
                    onChange={(e) => setForeignLow(e.target.value)}
                  />
                </label>
                <label>
                  BBMD discovery maximum instance
                  <input
                    type="number"
                    min={0}
                    max={4194302}
                    disabled={busy}
                    value={foreignHigh}
                    onChange={(e) => setForeignHigh(e.target.value)}
                  />
                </label>
              </>
            )}
            {value && (
              <pre className="result full">
                {JSON.stringify(value, null, 2)}
              </pre>
            )}
          </div>
        </section>
      </div>
      <DeviceScanPanel
        connected={
          status.connected && !busy && status.config?.transport !== "mstp"
        }
        localAddress={status.config?.local_address || config.local_address}
        routedResult={routedResult}
        onSelect={selectScannedDevice}
      />
      <RoutedDiscoveryPanel
        connected={
          status.connected && !busy && status.config?.transport !== "mstp"
        }
        onDiscovered={setRoutedResult}
        onSelect={(device, router, dnet) => {
          if (busy) return;
          ipDirty.current = true;
          setConfig((current) => ({ ...current, router, dnet: String(dnet) }));
          setTarget(device.address);
          setObject(device.device);
          setProperty("object-name");
          clearPointResults();
          setSelectedRoute({ router, dnet });
        }}
      />
      <BacnetFilesPanel
        connected={!!pointReady && !busy}
        defaultAddress={target}
        defaultDevice={object.trim().startsWith("device,") ? object : ""}
      />
      <ControllerProbePanel
        connected={!!probeReady}
        router={config.router}
        dnet={probeDnet}
        onSelect={(report) => {
          if (
            !probeReady ||
            !report.live_verified ||
            routerKey(report.router) !== routerKey(status.config?.router) ||
            report.dnet !== Number(status.config?.dnet)
          )
            return;
          ipDirty.current = true;
          setConfig((current) => ({
            ...current,
            router: report.router,
            dnet: String(report.dnet),
          }));
          setTarget(report.address);
          setObject(report.device);
          setProperty("object-name");
          clearPointResults();
          setSelectedRoute({ router: report.router, dnet: report.dnet });
        }}
      />
      {!!devices.length && (
        <section className="card">
          <div className="card-header">
            <h3>Discovered devices</h3>
          </div>
          <table>
            <thead>
              <tr>
                <th>Address</th>
                <th>Device</th>
                <th>Vendor</th>
                <th>Max APDU</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d, i) => (
                <tr
                  key={i}
                  aria-disabled={busy}
                  onClick={() => {
                    if (busy) return;
                    setTarget(d.address);
                    setObject(d.device);
                    setProperty("object-name");
                    clearPointResults(true);
                  }}
                >
                  <td>{d.address}</td>
                  <td>{d.device}</td>
                  <td>{d.vendor}</td>
                  <td>{d.max_apdu}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <section className="card">
        <div className="card-header">
          <h3>Command preview and relinquish</h3>
          <span className="pill">POINT VALUES</span>
        </div>
        <div className="card-body">
          <p className="help-text">
            A point command does not change the application program or add a
            physical input. Preview checks an unused priority slot; relinquish
            clears the command owned by this session.
          </p>
          <div className="form-grid">
            <label>
              Command value
              <input
                disabled={busy}
                value={command}
                onChange={(e) => {
                  setCommand(e.target.value);
                  setPlan(null);
                }}
              />
            </label>
            <label>
              BACnet priority
              <input
                disabled={busy}
                type="number"
                min={8}
                max={16}
                value={priority}
                onChange={(e) => {
                  setPriority(Number(e.target.value));
                  setPlan(null);
                }}
              />
            </label>
          </div>
          <div className="button-row">
            <button
              disabled={busy || !pointReady}
              onClick={() =>
                action(async () => {
                  let v: any;
                  try {
                    v = JSON.parse(command);
                  } catch {
                    v = command;
                  }
                  setPlan(
                    await api("/bacnet/write-plan", {
                      address: target,
                      object_id: object,
                      value: v,
                      priority,
                    }),
                  );
                })
              }
            >
              Preview command
            </button>
            {plan && (
              <button
                className="primary"
                disabled={busy || !pointReady}
                onClick={() =>
                  action(async () => {
                    setValue(
                      await api("/bacnet/write-apply", { token: plan.token }),
                    );
                    setPlan(null);
                  })
                }
              >
                Apply previewed command
              </button>
            )}
          </div>
          {plan && (
            <pre className="result">{JSON.stringify(plan, null, 2)}</pre>
          )}
          {status.commands.map((c: any) => (
            <div className="owned-command" key={c.id}>
              <span>
                {c.address} · {c.object} · priority {c.priority} · {c.status}
              </span>
              <button
                disabled={busy}
                onClick={() =>
                  action(() => api("/bacnet/release", { token: c.id }))
                }
              >
                Relinquish
              </button>
            </div>
          ))}
        </div>
      </section>
      <div className="two-column">
        <section className="card">
          <div className="card-header">
            <h3>
              <Usb size={18} /> Modbus TCP / USB serial
            </h3>
            <button
              disabled={busy}
              onClick={() => action(refresh)}
              title="Refresh serial ports"
            >
              <RefreshCw size={15} />
            </button>
          </div>
          <div className="card-body form-grid">
            <label>
              Transport
              <select
                disabled={busy}
                value={modbus.transport}
                onChange={(e) =>
                  setModbus({
                    ...modbus,
                    transport: e.target.value,
                    address:
                      e.target.value === "rtu"
                        ? serialPorts[0]?.device || ""
                        : "127.0.0.1",
                  })
                }
              >
                <option value="tcp">Modbus TCP</option>
                <option value="rtu">Modbus RTU / serial</option>
              </select>
            </label>
            <label>
              Address or serial port
              {modbus.transport === "rtu" ? (
                <select
                  disabled={busy}
                  value={modbus.address}
                  onChange={(e) =>
                    setModbus({ ...modbus, address: e.target.value })
                  }
                >
                  <option value="">Choose port</option>
                  {serialPorts.map((p) => (
                    <option key={p.device} value={p.device}>
                      {p.device} · {p.description}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  disabled={busy}
                  value={modbus.address}
                  onChange={(e) =>
                    setModbus({ ...modbus, address: e.target.value })
                  }
                />
              )}
            </label>
            {(
              [
                "unit",
                "register",
                "count",
                ...(modbus.transport === "tcp" ? ["port"] : ["baud"]),
              ] as const
            ).map((k) => (
              <label key={k}>
                {k === "register" ? "Register (zero based)" : k}
                <input
                  disabled={busy}
                  type="number"
                  value={modbus[k as keyof typeof modbus]}
                  onChange={(e) =>
                    setModbus({ ...modbus, [k]: Number(e.target.value) })
                  }
                />
              </label>
            ))}
            <label>
              Table
              <select
                disabled={busy}
                value={modbus.table}
                onChange={(e) =>
                  setModbus({ ...modbus, table: e.target.value })
                }
              >
                {["holding", "input", "coils", "discrete"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            {modbus.transport === "rtu" && (
              <label>
                Parity
                <select
                  disabled={busy}
                  value={modbus.parity}
                  onChange={(e) =>
                    setModbus({ ...modbus, parity: e.target.value })
                  }
                >
                  {["N", "E", "O"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
            )}
            <div className="full">
              <button
                disabled={busy}
                onClick={() =>
                  action(async () =>
                    setModbusResult(await api("/modbus/read", modbus)),
                  )
                }
              >
                Read registers
              </button>
              {modbusResult && (
                <pre className="result">
                  {JSON.stringify(modbusResult, null, 2)}
                </pre>
              )}
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-header">
            <h3>
              <Radio size={18} /> Direct BACnet MS/TP
            </h3>
            <span className="pill">SERIAL MASTER</span>
          </div>
          <div className="card-body form-grid">
            <p className="help-text full">
              Fixed-address legacy MS/TP master with token handling. Requires an
              automatic-direction RS-485 adapter without echo. Select an unused
              master MAC. Physical bus timing and adapters remain unverified;
              this driver does not implement the BTCVT Bluetooth protocol.
            </p>
            <label className="full">
              MS/TP serial port
              <select
                disabled={busy}
                value={mstp.port}
                onChange={(e) => {
                  setPlan(null);
                  setMstp({ ...mstp, port: e.target.value });
                }}
              >
                <option value="">Select a detected serial interface</option>
                {serialPorts.map((p) => (
                  <option key={p.device} value={p.device}>
                    {p.device} — {p.description}
                  </option>
                ))}
              </select>
            </label>
            <label>
              MS/TP baud rate
              <select
                disabled={busy}
                value={mstp.baudrate}
                onChange={(e) => {
                  setPlan(null);
                  setMstp({ ...mstp, baudrate: Number(e.target.value) });
                }}
              >
                {[9600, 19200, 38400, 57600, 76800, 115200].map((rate) => (
                  <option key={rate} value={rate}>
                    {rate}
                  </option>
                ))}
              </select>
            </label>
            {(
              [
                ["mac", "MS/TP master MAC", 0, 127],
                ["instance", "MS/TP client device instance", 0, 4194302],
                ["max_master", "Maximum master MAC", 0, 127],
                ["max_info_frames", "Maximum frames per token", 1, 255],
              ] as const
            ).map(([key, title, min, max]) => (
              <label key={key}>
                {title}
                <input
                  disabled={busy}
                  type="number"
                  min={min}
                  max={max}
                  value={mstp[key]}
                  onChange={(e) => {
                    setPlan(null);
                    setMstp({ ...mstp, [key]: Number(e.target.value) });
                  }}
                />
              </label>
            ))}
            <div className="button-row full">
              <button disabled={busy} onClick={() => action(refresh)}>
                <RefreshCw size={15} /> Refresh serial interfaces
              </button>
              <button
                className="primary"
                disabled={
                  busy || !serialPorts.some((p) => p.device === mstp.port)
                }
                onClick={() =>
                  action(async () => {
                    await api("/bacnet/connect-mstp", mstp);
                    setTarget(mstp.mac === 5 ? "6" : "5");
                    setDevices([]);
                    clearPointResults(true);
                  })
                }
              >
                <PlugZap size={15} /> Open MS/TP interface
              </button>
            </div>
            <p className="help-text full">
              Enter the target's decimal MAC in point services after opening.
              Point reads and owned priority commands use this interface.
              Application download is a separate, unsupported vendor service.
              BACnet/IP routing remains available above.
            </p>
            {status.serial_link && (
              <pre className="result full" aria-label="MS/TP link status">
                {JSON.stringify(status.serial_link, null, 2)}
              </pre>
            )}
          </div>
        </section>
      </div>
      {busy && (
        <div className="busy-indicator">Waiting for device response…</div>
      )}
      {error && (
        <div role="alert" className="inline-error">
          {error}
        </div>
      )}
    </div>
  );
}
