import { useCallback, useEffect, useRef, useState } from "react";
import {
  Download,
  Network,
  RefreshCw,
  Usb,
  Radio,
  Search,
  PlugZap,
} from "lucide-react";
import { api, programJsonDocument, saveBlob } from "./api";
import {
  parseBacnetCommandIntent,
  verifyBacnetCommandPlan,
} from "./commandIntent";
import {
  RoutedDiscoveryPanel,
  type RoutedScanResult,
} from "./RoutedDiscoveryPanel";
import {
  DeviceScanPanel,
  type ScanTarget,
  type NamedScanTarget,
} from "./DeviceScanPanel";
import { BacnetFilesPanel } from "./BacnetFilesPanel";
import { BbmdTablesPanel } from "./BbmdTablesPanel";
import { BbmdAdminPanel } from "./BbmdAdminPanel";
import { ControllerProbePanel } from "./ControllerProbePanel";
import { HardwareSurveyPanel } from "./HardwareSurveyPanel";
import { EnumMappingPanel } from "./EnumMappingPanel";
import { ScheduleInventoryPanel } from "./ScheduleInventoryPanel";
import { PointStatusPanel } from "./PointStatusPanel";
import { BacnetCovPanel } from "./BacnetCovPanel";
import { BacnetEventsPanel } from "./BacnetEventsPanel";
import { EventReceptionPanel } from "./EventReceptionPanel";
import { NetworkNumberPlanPanel } from "./NetworkNumberPlanPanel";
import { BusPreflightPanel } from "./BusPreflightPanel";
import { OperationPowerPanel } from "./OperationPowerPanel";
import { DeviceInstancePanel } from "./DeviceInstancePanel";
import {
  BoundControllerContext,
  ControllerExplorer,
  ControllerOverview,
  TaskMount,
} from "./ControllerWorkspace";
import { WorkflowToolTabs } from "./WorkflowChrome";
import { ControllerProgram, LiveControllerPoints } from "./LiveController";
import {
  type ConnectionView,
  type ControllerContext,
  type ControllerTarget,
  type WorkspaceArea,
  controllerKey,
} from "./workflow";

export function Connections({
  visible = true,
  view = "setup",
  onControllerChange,
  onControllerOpened,
  onNavigate,
  onBusyChange,
  onConnectionSetup,
  onOpenLocalFile,
}: {
  visible?: boolean;
  view?: ConnectionView;
  onControllerChange?: (controller: ControllerContext | null) => void;
  onControllerOpened?: () => void;
  onNavigate?: (area: WorkspaceArea) => void;
  onBusyChange?: (busy: boolean) => void;
  onConnectionSetup?: () => void;
  onOpenLocalFile?: () => void;
}) {
  const [controller, setController] = useState<ControllerContext | null>(null);
  const [setupStep, setSetupStep] = useState<
    "connection" | "discovery" | "known"
  >("connection");
  const [transport, setTransport] = useState("interface");
  const [discovery, setDiscovery] = useState("routed");
  const [toolChoice, setToolChoice] = useState({ view, tool: "" });
  const controllerEpoch = useRef(0);
  const groups: Record<ConnectionView, { id: string; label: string }[]> = {
    setup: [],
    overview: [
      { id: "summary", label: "Identity & status" },
      { id: "instance", label: "Instance settings" },
    ],
    points: [
      { id: "live-points", label: "Live points & configuration" },
      { id: "status", label: "Detailed point evidence" },
      { id: "property", label: "Read properties" },
      { id: "commands", label: "Commands & overrides" },
      { id: "hardware", label: "Hardware survey" },
      { id: "enum", label: "State mapping" },
    ],
    program: [{ id: "application", label: "Controller application" }],
    schedules: [{ id: "schedules", label: "Schedules & calendars" }],
    monitor: [
      { id: "cov", label: "Live COV monitor" },
      { id: "events", label: "Controller events" },
      { id: "receiver", label: "Event reception" },
    ],
    changes: [
      { id: "commands", label: "Owned commands" },
      { id: "instance", label: "Instance receipts" },
      { id: "files", label: "File captures" },
    ],
    settings: [
      { id: "interface", label: "BACnet/IP connection" },
      { id: "mstp", label: "Direct serial" },
      { id: "modbus", label: "Modbus" },
      { id: "network-plan", label: "Network plan" },
      { id: "bus-plan", label: "Bus planning" },
      { id: "bbmd-read", label: "BBMD inspection" },
      { id: "bbmd-admin", label: "BBMD administration" },
      { id: "probe", label: "Address probes" },
      { id: "power", label: "Operation power" },
    ],
  };
  const currentTool =
    view === "setup"
      ? setupStep === "connection"
        ? transport
        : setupStep === "known"
          ? "known"
          : discovery
      : toolChoice.view === view && toolChoice.tool
        ? toolChoice.tool
        : groups[view][0].id;
  const showTool = (tool: string) =>
    visible &&
    currentTool === tool &&
    (view === "setup" ||
      view === "settings" ||
      !!controller ||
      (view === "changes" && tool === "commands"));
  const discoverActive =
    visible && view === "setup" && setupStep === "discovery";
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
    [scanNames, setScanNames] = useState<NamedScanTarget[]>([]),
    [interfaceEpoch, setInterfaceEpoch] = useState(0),
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
    [plan, setPlan] = useState<{ receipt: any; text: string } | null>(null),
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
  const mergeScanNames = useCallback((incoming: NamedScanTarget[]) => {
    setScanNames((current) => {
      const entries = new Map(
        current.map((item) => [controllerKey(item.target), item]),
      );
      for (const item of incoming)
        entries.set(controllerKey(item.target), item);
      return Array.from(entries.values());
    });
  }, []);
  const mounted = useRef(false),
    statusEpoch = useRef(0),
    previewEpoch = useRef(0),
    previewSource = useRef(""),
    ipDirty = useRef(false);
  const interfaceIdentity = JSON.stringify({
    connected: status.connected,
    config: status.config,
    epoch: interfaceEpoch,
  });
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
  const statusKey = JSON.stringify(status.config ?? null);
  const controllerReady =
    !!controller && status.connected && controller.interfaceKey === statusKey;
  const deviceObject =
    controller?.address === target
      ? controller.device
      : object.trim().startsWith("device,")
        ? object
        : "";
  const pointReady =
    controllerReady &&
    status.connected &&
    selectedRouteReady &&
    !!target.trim() &&
    !!object.trim();
  previewSource.current = JSON.stringify({
    visible,
    view,
    target,
    object,
    command,
    priority,
    ready: pointReady,
    config: status.config,
  });
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
    void openController(device);
  }
  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);
  useEffect(() => {
    onControllerChange?.(
      controller
        ? {
            ...controller,
            interfaceOpen: controllerReady,
            ownedCommands: status.commands?.length || 0,
          }
        : null,
    );
  }, [
    controller,
    controllerReady,
    status.commands?.length,
    onControllerChange,
  ]);
  useEffect(() => {
    previewEpoch.current++;
    controllerEpoch.current++;
    setPlan(null);
  }, [view, visible]);

  async function openController(candidate: ControllerTarget) {
    if (busy || !visible || !status.connected) return;
    const epoch = ++controllerEpoch.current;
    previewEpoch.current++;
    setPlan(null);
    await action(async () => {
      let next = status;
      const route = candidate.router || null,
        dnet = candidate.dnet ?? null;
      if (
        status.config?.transport !== "mstp" &&
        (routerKey(status.config?.router) !== routerKey(route || "") ||
          (status.config?.dnet ?? null) !== dnet)
      ) {
        if (status.commands.length)
          throw new Error(
            "Release or resolve owned commands before changing the interface route.",
          );
        setController((current) =>
          current ? { ...current, interfaceKey: "" } : null,
        );
        setInterfaceEpoch((value) => value + 1);
        await api("/bacnet/connect", {
          ...status.config,
          router: route,
          dnet,
        });
        next = await api("/bacnet/status");
        if (epoch !== controllerEpoch.current) return;
        setStatus(next);
        ipDirty.current = false;
      }
      let device = candidate.device;
      if (!device) {
        const response = await api("/bacnet/read", {
          address: candidate.address,
          object_id: "device,4194303",
          property_id: "object-identifier",
        });
        const value = response.value;
        device =
          typeof value === "string"
            ? value
            : Array.isArray(value)
              ? `${value[0] === 8 ? "device" : value[0]},${value[1]}`
              : "";
        if (
          !/^device,(0|[1-9][0-9]*)$/.test(device) ||
          Number(device.split(",")[1]) > 4194302
        )
          throw new Error(
            "The station did not return a valid Device identifier.",
          );
      }
      let details: any;
      if (next.config?.transport === "mstp") {
        const properties: Record<string, unknown> = {};
        for (const property of [
          "object-identifier",
          "object-name",
          "model-name",
          "firmware-revision",
        ]) {
          const response = await api("/bacnet/read", {
            address: candidate.address,
            object_id: device,
            property_id: property,
          });
          properties[property] = response.value;
        }
        const value = properties["object-identifier"];
        const actual =
          typeof value === "string"
            ? value
            : Array.isArray(value)
              ? `${value[0] === 8 ? "device" : value[0]},${value[1]}`
              : "";
        if (actual !== device)
          throw new Error(
            "Serial controller identity changed during verification.",
          );
        details = {
          identity_verified: true,
          properties,
          finished_at: new Date().toISOString(),
        };
      } else
        details = await api("/bacnet/device-details", {
          address: candidate.address,
          device,
          router: route,
          dnet,
        });
      if (epoch !== controllerEpoch.current) return;
      if (!details.identity_verified || !details.properties["object-name"])
        throw new Error(
          "Controller identity could not be verified. Review the station and try again.",
        );
      const confirmedAddress = details.address || candidate.address;
      const confirmedRouter = details.router ?? route;
      const confirmedNetwork = details.dnet ?? dnet;
      setTarget(confirmedAddress);
      setObject(device);
      setProperty("object-name");
      clearPointResults(true);
      if (confirmedRouter && confirmedNetwork != null)
        setSelectedRoute({ router: confirmedRouter, dnet: confirmedNetwork });
      const active: ControllerContext = {
        address: confirmedAddress,
        device,
        router: confirmedRouter,
        dnet: confirmedNetwork,
        name: String(details.properties["object-name"]),
        model: String(details.properties["model-name"] || "Not exposed"),
        firmware: String(
          details.properties["firmware-revision"] || "Not exposed",
        ),
        verifiedAt: details.finished_at,
        interfaceKey: JSON.stringify(next.config ?? null),
        interfaceOpen: true,
        ownedCommands: next.commands?.length || 0,
      };
      setController(active);
      setToolChoice({ view: "overview", tool: "summary" });
      onControllerOpened?.();
    });
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
      previewEpoch.current++;
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
        onFocus={() => {
          // Claim the draft before text selection/typing: late status hydration
          // must not replace a focused value or move its insertion point.
          ipDirty.current = true;
        }}
        onChange={(e) => {
          setPlan(null);
          ipDirty.current = true;
          const value =
            type === "number" && name !== "dnet"
              ? Number(e.target.value)
              : e.target.value;
          setConfig((current) => ({
            ...current,
            [name]: value,
          }));
        }}
      />
    </label>
  );
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <span className="eyebrow">COMMISSIONING</span>
          <h1>
            {view === "setup"
              ? "Connect to a controller"
              : view === "settings"
                ? "Communications & network"
                : view === "overview"
                  ? "Controller"
                  : groups[view][0].label}
          </h1>
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
                  setInterfaceEpoch((value) => value + 1);
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
      {view === "setup" && (
        <>
          <nav
            className="workflow-setup-steps"
            aria-label="Controller connection steps"
          >
            <button
              disabled={busy}
              className={setupStep === "connection" ? "active" : ""}
              onClick={() => setSetupStep("connection")}
            >
              1 · Connection
            </button>
            <button
              disabled={busy || !status.connected}
              className={setupStep === "discovery" ? "active" : ""}
              onClick={() => setSetupStep("discovery")}
            >
              2 · Discover & select
            </button>
            <button
              disabled={busy || !status.connected}
              className={setupStep === "known" ? "active" : ""}
              onClick={() => setSetupStep("known")}
            >
              Known controller address
            </button>
          </nav>
          {setupStep === "connection" && (
            <WorkflowToolTabs
              label="Connection transport"
              disabled={busy}
              items={[
                { id: "interface", label: "BACnet/IP" },
                { id: "mstp", label: "Direct MS/TP" },
                { id: "modbus", label: "Modbus" },
              ]}
              value={transport}
              onChange={setTransport}
            />
          )}
          {setupStep === "discovery" && (
            <WorkflowToolTabs
              label="Discovery method"
              disabled={busy}
              items={[
                { id: "routed", label: "Router & trunk" },
                { id: "ip", label: "Direct BACnet/IP" },
              ]}
              value={discovery}
              onChange={setDiscovery}
            />
          )}
          {setupStep === "known" && (
            <section
              className="workflow-identity"
              aria-label="Known controller connection"
            >
              <h2>Open a known controller</h2>
              <p>
                Enter the exact station. Leave Device blank to read its actual
                identifier at that address.
              </p>
              <div className="form-grid">
                <label>
                  Controller address
                  <input
                    aria-label="Known controller address"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    disabled={busy}
                  />
                </label>
                <label>
                  Device object (optional)
                  <input
                    aria-label="Known Device object"
                    value={object.startsWith("device,") ? object : ""}
                    onChange={(event) => setObject(event.target.value)}
                    disabled={busy}
                  />
                </label>
                <label>
                  Router for routed target
                  <input
                    aria-label="Known router"
                    value={config.router}
                    onChange={(event) =>
                      setConfig({ ...config, router: event.target.value })
                    }
                    disabled={busy}
                  />
                </label>
                <label>
                  Network for routed target
                  <input
                    aria-label="Known network"
                    value={config.dnet}
                    onChange={(event) =>
                      setConfig({ ...config, dnet: event.target.value })
                    }
                    disabled={busy}
                  />
                </label>
                <button
                  className="primary"
                  disabled={busy || !target}
                  onClick={() =>
                    void openController({
                      address: target,
                      device: object.startsWith("device,") ? object : "",
                      router: config.router || null,
                      dnet:
                        config.router && config.dnet
                          ? Number(config.dnet)
                          : null,
                    })
                  }
                >
                  Open controller
                </button>
              </div>
            </section>
          )}
        </>
      )}
      {view !== "setup" && groups[view].length > 1 && (
        <WorkflowToolTabs
          label="Controller task tools"
          disabled={busy}
          items={groups[view]}
          value={currentTool}
          onChange={(tool) => {
            previewEpoch.current++;
            setPlan(null);
            setToolChoice({ view, tool });
          }}
        />
      )}
      <div className="workflow-controller-layout">
        <ControllerExplorer
          devices={scanNames}
          current={controller}
          busy={busy}
          onOpen={(target) => void openController(target)}
          onConnect={() => {
            setSetupStep(status.connected ? "discovery" : "connection");
            onConnectionSetup?.();
          }}
          onProgram={() => onNavigate?.("program")}
        />
        <div className="workflow-task-body">
          {!controller &&
            view !== "setup" &&
            view !== "settings" &&
            view !== "overview" &&
            view !== "changes" && (
              <ControllerOverview
                controller={null}
                connected={status.connected}
                busy={busy}
                onEditInstance={() => {}}
                onRefresh={() => {}}
                onConnect={() => onConnectionSetup?.()}
              />
            )}
          {view === "overview" && currentTool === "summary" && (
            <ControllerOverview
              controller={
                controller
                  ? { ...controller, interfaceOpen: controllerReady }
                  : null
              }
              connected={status.connected}
              busy={busy}
              onEditInstance={() =>
                setToolChoice({ view: "overview", tool: "instance" })
              }
              onRefresh={() => controller && void openController(controller)}
              onConnect={() => {
                setSetupStep(status.connected ? "discovery" : "connection");
                onConnectionSetup?.();
              }}
            />
          )}
          {controller && view !== "setup" && currentTool !== "summary" && (
            <div className="workflow-target-row">
              <strong>{controller.name}</strong>
              <span>
                {controller.address} · {controller.device}
                {controller.router ? ` via ${controller.router}` : ""}
              </span>
              <span>
                {controllerReady
                  ? "Selected controller"
                  : "Matching interface is not open"}
              </span>
            </div>
          )}
          <BoundControllerContext.Provider value={!!controller}>
            <TaskMount active={showTool("live-points")}>
              {controller && (
                <LiveControllerPoints
                  key={controllerKey(controller) + controller.interfaceKey}
                  controller={controller}
                  connected={!!controllerReady}
                  onVerified={(when) =>
                    setController((current) =>
                      current &&
                      controllerKey(current) === controllerKey(controller)
                        ? { ...current, verifiedAt: when }
                        : current,
                    )
                  }
                  onCommand={(selected) => {
                    setObject(selected);
                    setPlan(null);
                    setToolChoice({ view: "points", tool: "commands" });
                  }}
                />
              )}
            </TaskMount>
            <TaskMount active={showTool("application")}>
              {controller && (
                <ControllerProgram
                  key={controllerKey(controller) + controller.interfaceKey}
                  controller={controller}
                  connected={!!controllerReady}
                  onVerified={(when) =>
                    setController((current) =>
                      current &&
                      controllerKey(current) === controllerKey(controller)
                        ? { ...current, verifiedAt: when }
                        : current,
                    )
                  }
                  onLocalFile={onOpenLocalFile}
                />
              )}
            </TaskMount>
            <TaskMount active={showTool("power")} preserve={false}>
              <OperationPowerPanel />
            </TaskMount>
            <div className="two-column">
              <TaskMount active={showTool("interface")} preserve={false}>
                <section className="card">
                  <div className="card-header">
                    <h3>
                      <Network size={18} /> BACnet/IP interface
                    </h3>
                  </div>
                  <div className="card-body form-grid">
                    {field("local_address", "Local bind address / UDP port")}
                    <details className="full workflow-advanced">
                      <summary>Advanced connection settings</summary>
                      <div className="form-grid">
                        {field("instance", "Client device instance", "number")}
                        {field("router", "Router IP (optional)")}
                        {field(
                          "dnet",
                          "MS/TP destination network (optional)",
                          "number",
                        )}
                        {field(
                          "bbmd_address",
                          "BBMD address / UDP port (optional)",
                        )}
                        {config.bbmd_address &&
                          field(
                            "foreign_ttl",
                            "Foreign registration TTL (seconds)",
                            "number",
                          )}
                      </div>
                    </details>
                    <div className="full">
                      <button
                        disabled={busy}
                        className="primary"
                        onClick={() =>
                          action(async () => {
                            setController((current) =>
                              current ? { ...current, interfaceKey: "" } : null,
                            );
                            setInterfaceEpoch((value) => value + 1);
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
                            setSetupStep("discovery");
                            setPlan(null);
                          })
                        }
                      >
                        <PlugZap size={15} /> Open interface
                      </button>
                      <p className="help-text">
                        Routed targets use network:MAC, for example 2001:4. An
                        NAE must expose a usable BACnet routing path;
                        reachability of its web page alone does not prove
                        routing.
                      </p>
                      <p className="help-text">
                        BBMD registration enables broadcast discovery across IP
                        subnets when the BBMD accepts foreign devices. Addressed
                        controller services use the selected router directly.
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
                            {status.foreign_device.lease_remaining_seconds ?? 0}
                            s
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
              </TaskMount>
              <TaskMount active={showTool("property")} preserve={false}>
                <section className="card">
                  <div className="card-header">
                    <h3>
                      <Search size={18} /> Device and point services
                    </h3>
                  </div>
                  <div className="card-body form-grid">
                    <label className="full">
                      Controller address
                      <input
                        readOnly={!!controller}
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
                              await api("/bacnet/discover-foreign", {
                                low,
                                high,
                              }),
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
                              await api("/bacnet/discover", {
                                address: target,
                              }),
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
                        Selected routed target requires router{" "}
                        {selectedRoute?.router} and network{" "}
                        {selectedRoute?.dnet}. Review the connection draft and
                        choose Open interface before point services.
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
                          · Offset {objectPage.offset} ·{" "}
                          {objectPage.objects.length} received · Device total{" "}
                          {objectPage.total ?? "unknown"}
                        </p>
                        <p>
                          {objectPage.complete
                            ? "Page request completed"
                            : "Page request incomplete"}
                          {objectPage.truncated
                            ? " · Further indices remain"
                            : ""}
                          . This page is not an application backup or a verified
                          complete inventory.
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
                            <Download size={14} /> Download shown object-list
                            JSON
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
                        {objectDownloaded && (
                          <p role="status">{objectDownloaded}</p>
                        )}
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
              </TaskMount>
            </div>
            <TaskMount active={showTool("network-plan")} preserve={false}>
              <NetworkNumberPlanPanel />
            </TaskMount>
            <TaskMount active={showTool("bus-plan")} preserve={false}>
              <BusPreflightPanel />
            </TaskMount>
            <TaskMount active={showTool("ip")} preserve={true}>
              <DeviceScanPanel
                connected={
                  status.connected &&
                  !busy &&
                  discoverActive &&
                  showTool("ip") &&
                  status.config?.transport !== "mstp"
                }
                localAddress={
                  status.config?.local_address || config.local_address
                }
                routedResult={routedResult}
                onSelect={selectScannedDevice}
                onInventory={mergeScanNames}
                interfaceIdentity={interfaceIdentity}
              />
            </TaskMount>
            <TaskMount active={showTool("routed")} preserve={true}>
              <RoutedDiscoveryPanel
                connected={
                  status.connected &&
                  !busy &&
                  discoverActive &&
                  showTool("routed") &&
                  status.config?.transport !== "mstp"
                }
                onDiscovered={setRoutedResult}
                knownDevices={scanNames}
                onNamesDiscovered={mergeScanNames}
                interfaceIdentity={interfaceIdentity}
                connectorConfig={status.config ?? null}
                localDiscoveryAvailable={!status.config?.bbmd_address}
                onSelectionCleared={() => {
                  previewEpoch.current++;
                  setPlan(null);
                }}
                onSelect={(device, router, dnet) => {
                  void openController({
                    address: device.address,
                    device: device.device,
                    router,
                    dnet,
                  });
                }}
              />
            </TaskMount>
            <TaskMount active={showTool("instance")} preserve={false}>
              <DeviceInstancePanel
                connected={
                  visible &&
                  controllerReady &&
                  status.config?.transport !== "mstp" &&
                  !status.config?.bbmd_address
                }
                interfaceIdentity={interfaceIdentity}
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultRouter={
                  selectedRoute?.router ||
                  (/^\d+:/.test(target) ? config.router : "")
                }
                defaultDnet={
                  selectedRoute?.dnet ??
                  (/^\d+:/.test(target) ? probeDnet : null)
                }
                parentBusy={busy}
                onBusy={setBusy}
                onVerified={(result) => {
                  if (
                    !controller ||
                    controller.address !== result.target.address ||
                    controller.device !== `device,${result.old_instance}` ||
                    (controller.router || null) !==
                      (result.target.router || null) ||
                    (controller.dnet ?? null) !== (result.target.dnet ?? null)
                  )
                    return;
                  setController((current) =>
                    current &&
                    current.address === result.target.address &&
                    current.device === `device,${result.old_instance}` &&
                    (current.router || null) ===
                      (result.target.router || null) &&
                    (current.dnet ?? null) === (result.target.dnet ?? null)
                      ? {
                          ...current,
                          device: `device,${result.new_instance}`,
                          verifiedAt: new Date().toISOString(),
                        }
                      : current,
                  );
                  setObject((current) =>
                    current === `device,${result.old_instance}`
                      ? `device,${result.new_instance}`
                      : current,
                  );
                }}
              />
            </TaskMount>
            <TaskMount active={showTool("cov")} preserve={false}>
              <BacnetCovPanel
                connected={
                  visible &&
                  controllerReady &&
                  !busy &&
                  status.config?.transport !== "mstp" &&
                  !status.config?.bbmd_address
                }
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultObject={object}
                defaultRouter={
                  selectedRoute?.router || status.config?.router || ""
                }
                defaultDnet={selectedRoute?.dnet || status.config?.dnet}
              />
            </TaskMount>
            <TaskMount active={showTool("receiver")} preserve={false}>
              <EventReceptionPanel
                connected={
                  visible &&
                  controllerReady &&
                  !busy &&
                  status.config?.transport !== "mstp" &&
                  !status.config?.bbmd_address
                }
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultRouter={
                  selectedRoute?.router ||
                  (/^\d+:/.test(target) ? config.router : "")
                }
                defaultDnet={
                  selectedRoute?.dnet ??
                  (/^\d+:/.test(target) ? probeDnet : null)
                }
              />
            </TaskMount>
            <TaskMount active={showTool("status")} preserve={false}>
              <PointStatusPanel
                connected={
                  visible &&
                  controllerReady &&
                  !busy &&
                  status.config?.transport !== "mstp" &&
                  !status.config?.bbmd_address
                }
                interfaceIdentity={JSON.stringify(status.config ?? null)}
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultObject={object}
                defaultRouter={
                  selectedRoute?.router ||
                  (/^\d+:/.test(target) ? config.router : "")
                }
                defaultDnet={
                  selectedRoute?.dnet ??
                  (/^\d+:/.test(target) ? probeDnet : null)
                }
              />
            </TaskMount>
            <TaskMount active={showTool("enum")} preserve={false}>
              <EnumMappingPanel />
            </TaskMount>
            <TaskMount active={showTool("schedules")} preserve={false}>
              <ScheduleInventoryPanel
                connected={
                  visible &&
                  controllerReady &&
                  !busy &&
                  status.config?.transport !== "mstp" &&
                  !status.config?.bbmd_address
                }
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultRouter={
                  selectedRoute?.router ||
                  (/^\d+:/.test(target) ? config.router : "")
                }
                defaultDnet={
                  selectedRoute?.dnet ??
                  (/^\d+:/.test(target) ? probeDnet : null)
                }
              />
            </TaskMount>
            <TaskMount active={showTool("events")} preserve={false}>
              <BacnetEventsPanel
                connected={
                  visible &&
                  controllerReady &&
                  !busy &&
                  visible &&
                  status.config?.transport !== "mstp"
                }
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultRouter={
                  selectedRoute?.router ||
                  (/^\d+:/.test(target) ? config.router : "")
                }
                defaultDnet={
                  selectedRoute?.dnet ??
                  (/^\d+:/.test(target) ? probeDnet : null)
                }
              />
            </TaskMount>
            <TaskMount active={showTool("bbmd-read")} preserve={false}>
              <BbmdTablesPanel
                connected={
                  !!status.connected &&
                  !busy &&
                  visible &&
                  status.config?.transport !== "mstp"
                }
                defaultEndpoint={
                  status.config?.bbmd_address ||
                  selectedRoute?.router ||
                  (target.includes(".") ? target : "")
                }
              />
            </TaskMount>
            <TaskMount active={showTool("bbmd-admin")} preserve={false}>
              <BbmdAdminPanel
                connected={
                  !!status.connected &&
                  !busy &&
                  status.config?.transport !== "mstp" &&
                  !status.config?.bbmd_address
                }
                defaultEndpoint={
                  status.config?.bbmd_address ||
                  selectedRoute?.router ||
                  (target.includes(".") ? target : "")
                }
              />
            </TaskMount>
            <TaskMount active={showTool("files")} preserve={false}>
              <BacnetFilesPanel
                connected={!!pointReady && !busy}
                defaultAddress={target}
                defaultDevice={deviceObject}
              />
            </TaskMount>
            <TaskMount active={showTool("hardware")} preserve={false}>
              <HardwareSurveyPanel
                connected={!!pointReady && !busy}
                defaultTransport={
                  status.config?.transport === "mstp"
                    ? "direct-mstp"
                    : "bacnet-ip"
                }
                interfaceConfig={status.config}
                defaultAddress={target}
                defaultDevice={deviceObject}
                defaultRouter={
                  status.config?.transport === "mstp"
                    ? ""
                    : selectedRoute?.router ||
                      (/^\d+(?::\d+)?$/.test(target.trim())
                        ? status.config?.router || ""
                        : "")
                }
                defaultDnet={
                  status.config?.transport === "mstp"
                    ? null
                    : (selectedRoute?.dnet ??
                      (/^\d+(?::\d+)?$/.test(target.trim())
                        ? (status.config?.dnet ?? null)
                        : null))
                }
              />
            </TaskMount>
            <TaskMount active={showTool("probe")} preserve={false}>
              <ControllerProbePanel
                connected={!!probeReady}
                router={config.router}
                dnet={probeDnet}
                onSelect={(report) => {
                  if (
                    !probeReady ||
                    !report.live_verified ||
                    routerKey(report.router) !==
                      routerKey(status.config?.router) ||
                    report.dnet !== Number(status.config?.dnet)
                  )
                    return;
                  void openController({
                    address: report.address,
                    device: report.device,
                    router: report.router,
                    dnet: report.dnet,
                  });
                }}
              />
            </TaskMount>
            <TaskMount
              active={
                visible &&
                view === "setup" &&
                setupStep === "known" &&
                status.config?.transport === "mstp"
              }
              preserve={false}
            >
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
                            void openController({
                              address: d.address,
                              device: d.device,
                            });
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
            </TaskMount>
            <TaskMount active={showTool("commands")} preserve={false}>
              <section className="card">
                <div className="card-header">
                  <h3>Command preview and relinquish</h3>
                  <span className="pill">POINT VALUES</span>
                </div>
                <div className="card-body">
                  <p className="help-text">
                    A point command does not change the application program or
                    add a physical input. Preview checks an unused priority
                    slot; relinquish clears the command owned by this session.
                  </p>
                  <p className="help-text">
                    Integer tokens must be exactly representable in binary64.
                    Decimal and exponent tokens use finite binary64 semantics.
                    Preview shows requested_value separately from value, the
                    native BACnet wire value; Real32 rounding can differ. Use
                    quoted strings or bare enum labels such as active and
                    inactive, or JSON true and false.
                  </p>
                  <div className="form-grid">
                    <label>
                      Point object
                      <input
                        aria-label="Command point object"
                        disabled={busy}
                        value={object}
                        onChange={(event) => {
                          setObject(event.target.value);
                          setPlan(null);
                        }}
                      />
                    </label>
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
                          setPlan(null);
                          const value = parseBacnetCommandIntent(command),
                            request = {
                              address: target,
                              object_id: object,
                              value,
                              priority,
                            },
                            epoch = ++previewEpoch.current,
                            source = previewSource.current,
                            result = await programJsonDocument(
                              "/bacnet/write-plan",
                              request,
                            ),
                            text = await result.blob.text();
                          if (
                            !mounted.current ||
                            epoch !== previewEpoch.current ||
                            source !== previewSource.current
                          )
                            return;
                          verifyBacnetCommandPlan(request, result.data, text);
                          setPlan({ receipt: result.data, text });
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
                              await api("/bacnet/write-apply", {
                                token: plan.receipt.token,
                              }),
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
                    <section
                      className="workflow-command-review"
                      aria-label="BACnet command preview"
                    >
                      <h3>Review point command</h3>
                      <dl className="workflow-identity-grid">
                        {[
                          [
                            "Controller",
                            `${controller?.name || plan.receipt.address} · ${plan.receipt.address}`,
                          ],
                          [
                            "Point",
                            `${plan.receipt.name} · ${plan.receipt.object}`,
                          ],
                          [
                            "Present value before command",
                            JSON.stringify(plan.receipt.before),
                          ],
                          ["Requested value", command],
                          [
                            "Native wire value",
                            JSON.stringify(plan.receipt.value),
                          ],
                          ["Priority", plan.receipt.priority],
                        ].map(([label, value]) => (
                          <div key={label}>
                            <dt>{label}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                      <details>
                        <summary>Protocol evidence</summary>
                        <pre className="result">{plan.text}</pre>
                      </details>
                    </section>
                  )}
                  {status.commands.map((c: any) => (
                    <div className="owned-command" key={c.id}>
                      <span>
                        {c.address} · {c.object} · priority {c.priority} ·{" "}
                        {c.status}
                      </span>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(() => api("/bacnet/release", { token: c.id }))
                        }
                      >
                        Release override
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            </TaskMount>
            <div className="two-column">
              <TaskMount active={showTool("modbus")} preserve={false}>
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
                            setModbus({
                              ...modbus,
                              [k]: Number(e.target.value),
                            })
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
              </TaskMount>
              <TaskMount active={showTool("mstp")} preserve={false}>
                <section className="card">
                  <div className="card-header">
                    <h3>
                      <Radio size={18} /> Direct BACnet MS/TP
                    </h3>
                    <span className="pill">SERIAL MASTER</span>
                  </div>
                  <div className="card-body form-grid">
                    <p className="help-text full">
                      Fixed-address legacy MS/TP master with token handling.
                      Requires an automatic-direction RS-485 adapter without
                      echo. Select an unused master MAC. Physical bus timing and
                      adapters remain unverified; this driver does not implement
                      the BTCVT Bluetooth protocol.
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
                        <option value="">
                          Select a detected serial interface
                        </option>
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
                          setMstp({
                            ...mstp,
                            baudrate: Number(e.target.value),
                          });
                        }}
                      >
                        {[9600, 19200, 38400, 57600, 76800, 115200].map(
                          (rate) => (
                            <option key={rate} value={rate}>
                              {rate}
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                    {(
                      [
                        ["mac", "MS/TP master MAC", 0, 127],
                        [
                          "instance",
                          "MS/TP client device instance",
                          0,
                          4194302,
                        ],
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
                          busy ||
                          !serialPorts.some((p) => p.device === mstp.port)
                        }
                        onClick={() =>
                          action(async () => {
                            setController((current) =>
                              current ? { ...current, interfaceKey: "" } : null,
                            );
                            setInterfaceEpoch((value) => value + 1);
                            await api("/bacnet/connect-mstp", mstp);
                            setSetupStep("known");
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
                      Enter the target's decimal MAC in point services after
                      opening. Point reads and owned priority commands use this
                      interface. Application download is a separate, unsupported
                      vendor service. BACnet/IP routing remains available above.
                    </p>
                    {status.serial_link && (
                      <pre
                        className="result full"
                        aria-label="MS/TP link status"
                      >
                        {JSON.stringify(status.serial_link, null, 2)}
                      </pre>
                    )}
                  </div>
                </section>
              </TaskMount>
            </div>
          </BoundControllerContext.Provider>
        </div>
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
