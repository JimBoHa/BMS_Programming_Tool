import { useEffect, useState } from "react";
import { Network, RefreshCw, Usb, Radio, Search, PlugZap } from "lucide-react";
import { api } from "./api";

export function Connections() {
  const [config, setConfig] = useState({
      local_address: "127.0.0.1:47809",
      instance: 4190001,
      router: "",
      dnet: "",
    }),
    [target, setTarget] = useState("127.0.0.1:47808"),
    [object, setObject] = useState("analog-value,1"),
    [property, setProperty] = useState("present-value"),
    [devices, setDevices] = useState<any[]>([]),
    [value, setValue] = useState<any>(null),
    [status, setStatus] = useState<any>({ connected: false, commands: [] }),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [command, setCommand] = useState("50"),
    [priority, setPriority] = useState(16),
    [plan, setPlan] = useState<any>(null),
    [serialPorts, setSerialPorts] = useState<any[]>([]),
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
  async function refresh() {
    setStatus(await api("/bacnet/status"));
    setSerialPorts(await api("/ports"));
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  async function action(fn: () => Promise<any>) {
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
        value={config[name]}
        onChange={(e) => {
          setPlan(null);
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
            Directed BACnet requests and Modbus reads. Network interfaces open
            when you connect.
          </p>
        </div>
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
                    });
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
                value={target}
                onChange={(e) => {
                  setTarget(e.target.value);
                  setPlan(null);
                }}
              />
            </label>
            <label>
              Object identifier
              <input
                value={object}
                onChange={(e) => {
                  setObject(e.target.value);
                  setPlan(null);
                }}
              />
            </label>
            <label>
              Property
              <input
                value={property}
                onChange={(e) => setProperty(e.target.value)}
              />
            </label>
            <div className="button-row full">
              <button
                disabled={busy || !status.connected}
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
                disabled={busy || !status.connected}
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
                disabled={busy || !status.connected}
                onClick={() =>
                  action(async () =>
                    setValue(
                      await api("/bacnet/objects", {
                        address: target,
                        object_id: object,
                      }),
                    ),
                  )
                }
              >
                Read object list
              </button>
            </div>
            {value && (
              <pre className="result full">
                {JSON.stringify(value, null, 2)}
              </pre>
            )}
          </div>
        </section>
      </div>
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
                  onClick={() => {
                    setTarget(d.address);
                    setObject(d.device);
                    setProperty("object-name");
                    setPlan(null);
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
              disabled={busy || !status.connected}
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
                disabled={busy}
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
              <Radio size={18} /> Bluetooth and direct MS/TP
            </h3>
            <span className="pill pending">ADAPTER REQUIRED</span>
          </div>
          <div className="card-body">
            <p>
              Enumerating a USB/Bluetooth serial port does not provide the BTCVT
              protocol or a BACnet MS/TP master.
            </p>
            <p>
              BTCVT support needs a verified protocol adapter and compatible
              controller firmware. Direct MS/TP also needs token handling and a
              supported RS-485 interface.
            </p>
            <p className="help-text">
              Use a verified BACnet/IP-to-MS/TP router with the BACnet interface
              above. CCT 14+ dropped BTCVT; older firmware and download paths
              have separate limits.
            </p>
            <div className="small-heading">AVAILABLE SERIAL PORTS</div>
            {serialPorts.length ? (
              serialPorts.map((p) => (
                <p className="mono" key={p.device}>
                  {p.device}
                  <small>{p.description}</small>
                </p>
              ))
            ) : (
              <p>No serial devices detected.</p>
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
