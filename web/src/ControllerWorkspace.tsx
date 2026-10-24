import { createContext, useContext, type ReactNode } from "react";
import { CircuitBoard, Network, RefreshCw, ArrowRight } from "lucide-react";
import {
  controllerKey,
  type ControllerContext,
  type ControllerTarget,
} from "./workflow";
import type { NamedScanTarget } from "./DeviceScanPanel";

export const BoundControllerContext = createContext(false);
export function TargetFields({ children }: { children: ReactNode }) {
  return useContext(BoundControllerContext) ? null : <>{children}</>;
}

export function ControllerExplorer({
  devices,
  current,
  busy,
  onOpen,
  onConnect,
  onProgram,
}: {
  devices: NamedScanTarget[];
  current: ControllerContext | null;
  busy: boolean;
  onOpen: (target: ControllerTarget) => void;
  onConnect: () => void;
  onProgram: () => void;
}) {
  const groups = new Map<string, NamedScanTarget[]>();
  const sameStation = (target: ControllerTarget) =>
    !!current &&
    target.address === current.address &&
    (target.router || null) === (current.router || null) &&
    (target.dnet ?? null) === (current.dnet ?? null);
  for (const item of devices) {
    const key = item.target.router
      ? `${item.target.router} / Network ${item.target.dnet}`
      : "Direct BACnet/IP";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(item);
  }
  return (
    <aside className="workflow-explorer" aria-label="Controller explorer">
      <h2>
        <Network size={16} /> Controllers
      </h2>
      <button onClick={onConnect} disabled={busy}>
        Connect / discover
      </button>
      {current && !devices.some((item) => sameStation(item.target)) && (
        <button
          className="active"
          disabled={busy}
          onClick={() => onOpen(current)}
        >
          <strong>{current.name}</strong>
          <small>
            {current.address} · {current.device}
          </small>
        </button>
      )}
      {Array.from(groups.entries()).map(([key, rows]) => (
        <details open key={key}>
          <summary>{key}</summary>
          {rows.map((item) => (
            <button
              key={controllerKey(item.target)}
              className={sameStation(item.target) ? "active" : ""}
              disabled={busy}
              onClick={() =>
                onOpen(sameStation(item.target) ? current! : item.target)
              }
            >
              <strong>
                {sameStation(item.target)
                  ? current!.name
                  : item.name || item.target.device}
              </strong>
              <small>
                {item.target.address} ·{" "}
                {sameStation(item.target)
                  ? current!.device
                  : item.target.device}
              </small>
            </button>
          ))}
        </details>
      ))}
      {!groups.size && !current && (
        <p className="help-text">
          Discovered controllers appear here. Open one to verify its identity.
        </p>
      )}
      <button onClick={onProgram} disabled={busy}>
        Application workspace <ArrowRight size={14} />
      </button>
    </aside>
  );
}

export function ControllerOverview({
  controller,
  connected,
  onEditInstance,
  onRefresh,
  onConnect,
  busy,
}: {
  controller: ControllerContext | null;
  connected: boolean;
  onEditInstance: () => void;
  onRefresh: () => void;
  onConnect: () => void;
  busy: boolean;
}) {
  if (!controller)
    return (
      <section className="workflow-identity" aria-label="No controller open">
        <CircuitBoard size={34} />
        <h1>Open a controller to begin</h1>
        <p className="workflow-lead">
          Connect, discover a router and trunk, then choose the exact
          controller. You can also enter a known address.
        </p>
        <button className="primary" onClick={onConnect}>
          Connect to a controller
        </button>
      </section>
    );
  return (
    <section className="workflow-identity" aria-label="Controller overview">
      <div className="button-row">
        <div>
          <span className="eyebrow">CONTROLLER OVERVIEW</span>
          <h1>{controller.name}</h1>
        </div>
        <button
          style={{ marginLeft: "auto" }}
          disabled={busy || !connected}
          onClick={onRefresh}
        >
          <RefreshCw size={15} />
          Refresh controller
        </button>
      </div>
      <p className="help-text">
        Identity was read at {controller.verifiedAt}.{" "}
        {controller.interfaceOpen
          ? "The matching interface is open."
          : "Reconnect the matching interface before field operations."}
      </p>
      <dl className="workflow-identity-grid">
        {[
          ["Device instance", controller.device],
          ["Controller address / MAC", controller.address],
          ["Router", controller.router || "Direct connection"],
          ["BACnet network", controller.dnet ?? "Local network"],
          ["Model", controller.model],
          ["Firmware", controller.firmware],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <button
        className="primary"
        disabled={busy || !controller.interfaceOpen}
        onClick={onEditInstance}
      >
        Edit instance number
      </button>
      <div className="workflow-capability" style={{ marginTop: 24 }}>
        Point values and supported settings are available in this workspace.
        Reading BACnet metadata does not establish native application upload or
        download support.
      </div>
    </section>
  );
}

export function TaskMount({
  active,
  preserve = false,
  children,
}: {
  active: boolean;
  preserve?: boolean;
  children: ReactNode;
}) {
  return active || preserve ? <div hidden={!active}>{children}</div> : null;
}
