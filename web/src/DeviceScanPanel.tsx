import { useEffect, useMemo, useRef, useState } from "react";
import { Download, ListRestart, Radar, Square, Search } from "lucide-react";
import { api, saveBlob } from "./api";
import type { RoutedScanResult } from "./RoutedDiscoveryPanel";
import "./device-scan.css";

export type ScanTarget = {
  source: "ip" | "routed";
  address: string;
  device: string;
  router?: string;
  dnet?: number;
  mac_hex?: string;
  mstp_mac?: number | null;
};
export type NamedScanTarget = { target: ScanTarget; name: string | null };
type Status = {
  status: string;
  error: string | null;
  received_at: string | null;
};
type DeviceDetails = {
  identity_verified: boolean;
  properties: Record<string, string | number | null>;
  property_status: Record<string, Status>;
  programs: {
    object: string;
    name: string | null;
    description: string | null;
    state: number | null;
    property_status: Record<string, Status>;
  }[];
  program_names: string[];
  programs_status: string;
  errors: { object: string; property: string; status: string; error: string }[];
  complete: boolean;
  started_at: string;
  finished_at: string;
  object_list: { complete: boolean; [key: string]: unknown };
  [key: string]: unknown;
};
type Evidence = {
  request: Record<string, unknown>;
  window: Record<string, unknown>;
  observation: Record<string, unknown>;
  latest: boolean;
};
type Row = {
  key: string;
  target: ScanTarget;
  discoveries: Record<string, Evidence>;
  version: number;
  state: "pending" | "reading" | "complete" | "partial" | "error";
  details: DeviceDetails | null;
  detail_error: string | null;
};
type ScanReport = Record<string, unknown> & {
  devices: Record<string, unknown>[];
  request?: Record<string, unknown>;
  connector_config?: Record<string, unknown>;
};
const PAGE_SIZE = 20;
const MAX_ROWS = 2048;
const MAX_SCOPES = 32;
const MAX_REPORT_PAGES = 512;
type ScopeReports = {
  source: string;
  pages: { request: Record<string, unknown>; report: ScanReport }[];
};
function integer(text: string, minimum: number, maximum: number, name: string) {
  const number = Number(text);
  if (
    !text.trim() ||
    !Number.isInteger(number) ||
    number < minimum ||
    number > maximum
  )
    throw new Error(
      `${name} must be an integer from ${minimum} to ${maximum}.`,
    );
  return number;
}
function ipv4(text: string) {
  const value = text.trim(),
    parts = value.split(".");
  if (
    parts.length !== 4 ||
    parts.some(
      (part) =>
        !/^\d{1,3}$/.test(part) ||
        Number(part) > 255 ||
        String(Number(part)) !== part,
    )
  )
    throw new Error(
      "Enter literal IPv4 addresses, without hostnames or port suffixes.",
    );
  return value;
}
function addressNumber(value: string) {
  return value
    .split(".")
    .reduce((number, part) => number * 256 + Number(part), 0);
}
function rowKey(target: ScanTarget) {
  return JSON.stringify([
    target.source,
    target.router ?? null,
    target.dnet ?? null,
    target.address,
    target.device,
  ]);
}
function latest(row: Row) {
  return Object.values(row.discoveries).some((item) => item.latest);
}
function lastObservation(row: Row) {
  return Object.values(row.discoveries).at(-1)?.observation ?? {};
}
function property(row: Row, name: string) {
  return row.details?.properties[name] ?? "";
}
function vendorIdentifier(row: Row) {
  return (
    row.details?.properties["vendor-identifier"] ??
    lastObservation(row).vendor ??
    "Unknown"
  );
}
function programLabel(row: Row) {
  if (!row.details) return row.state === "error" ? "Unavailable" : "Not read";
  if (row.details.program_names.length)
    return row.details.program_names.join("; ");
  if (
    row.details.programs_status === "not_exposed" &&
    !row.details.object_list?.complete
  )
    return "No complete Program inventory";
  return (
    (
      {
        not_exposed: "Not exposed",
        exposed: "Program objects exposed; names unavailable",
        partial: "Partial inventory",
        unavailable: "Unavailable",
        not_read: "Not read",
        limit_exceeded: "Inventory limit exceeded",
      } as Record<string, string>
    )[row.details.programs_status] ?? row.details.programs_status
  );
}
function csvCell(value: unknown) {
  let text =
    value === null || value === undefined
      ? ""
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  if (typeof value === "string" && /^[\s]*[=+@-]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}

export function DeviceScanPanel({
  connected,
  localAddress,
  routedResult,
  onSelect,
  onInventory,
}: {
  connected: boolean;
  localAddress: string;
  routedResult?: RoutedScanResult | null;
  onSelect: (target: ScanTarget) => void;
  onInventory?: (devices: NamedScanTarget[]) => void;
}) {
  const [mode, setMode] = useState("local"),
    [ip, setIp] = useState(""),
    [startIp, setStartIp] = useState(""),
    [endIp, setEndIp] = useState("");
  const [port, setPort] = useState("47808"),
    [seconds, setSeconds] = useState("3"),
    [low, setLow] = useState("0"),
    [high, setHigh] = useState("4194302"),
    [limit, setLimit] = useState("256");
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [lastIpScan, setLastIpScan] = useState<{
    request: Record<string, unknown>;
    report: ScanReport;
  } | null>(null);
  const [rows, setRows] = useState<Row[]>([]),
    [reports, setReports] = useState<Record<string, ScopeReports>>({});
  const [query, setQuery] = useState(""),
    [source, setSource] = useState("all"),
    [sort, setSort] = useState("address"),
    [ascending, setAscending] = useState(true),
    [earlier, setEarlier] = useState(false),
    [viewRevision, setViewRevision] = useState(0),
    [page, setPage] = useState(0);
  const [scanBusy, setScanBusy] = useState(false),
    [metadataBusy, setMetadataBusy] = useState(false),
    [paused, setPaused] = useState(false),
    [kick, setKick] = useState(0);
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [selected, setSelected] = useState<string | null>(null);
  const mounted = useRef(false),
    profileEpoch = useRef(0),
    scanActive = useRef(false),
    scanEpoch = useRef(0),
    metadataActive = useRef(false),
    metadataEpoch = useRef(0),
    metadataContext = useRef("");
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const connectedRef = useRef(connected);
  connectedRef.current = connected;
  const rowsRef = useRef(new Map<string, Row>()),
    reportsRef = useRef<Record<string, ScopeReports>>({}),
    seenRouted = useRef<RoutedScanResult | null>(null);
  useEffect(() => {
    onInventory?.(
      rows.map((row) => ({
        target: row.target,
        name:
          row.details?.identity_verified &&
          typeof row.details.properties["object-name"] === "string"
            ? row.details.properties["object-name"]
            : null,
      })),
    );
  }, [rows, onInventory]);
  function publish() {
    if (mounted.current) setRows(Array.from(rowsRef.current.values()));
  }
  function changeRow(key: string, version: number, change: (row: Row) => Row) {
    const current = rowsRef.current.get(key);
    if (current?.version === version) {
      rowsRef.current.set(key, change(current));
      publish();
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      scanEpoch.current++;
      metadataEpoch.current++;
      profileEpoch.current++;
    };
  }, []);
  useEffect(() => {
    const owner = ++profileEpoch.current;
    api("/bacnet/ip-scan-profile")
      .then((value) => {
        if (mounted.current && owner === profileEpoch.current)
          setProfile(value);
      })
      .catch((error) => {
        if (mounted.current && owner === profileEpoch.current)
          setError(String(error));
      });
  }, [connected, localAddress]);
  useEffect(() => {
    scanEpoch.current++;
  }, [connected, localAddress]);

  function receive(
    sourceKind: "ip" | "routed",
    request: Record<string, unknown>,
    report: ScanReport,
  ) {
    const router =
      sourceKind === "routed"
        ? String(report.router ?? request.router)
        : undefined;
    const dnet =
      sourceKind === "routed" ? Number(report.dnet ?? request.dnet) : undefined;
    const scopeKey = JSON.stringify([
      sourceKind,
      router ?? null,
      dnet ?? null,
      request.mode ?? null,
      request.ip ?? null,
      request.start_ip ?? null,
      request.end_ip ?? null,
      request.udp_port ?? null,
      request.low ?? null,
      request.high ?? null,
      report.connector_config ?? null,
    ]);
    const targets = report.devices.map((observation) => ({
      observation,
      target: {
        source: sourceKind,
        address: String(observation.address),
        device: String(observation.device),
        ...(sourceKind === "routed"
          ? {
              router,
              dnet,
              mac_hex:
                typeof observation.mac_hex === "string"
                  ? observation.mac_hex
                  : undefined,
              mstp_mac:
                typeof observation.mstp_mac === "number"
                  ? observation.mstp_mac
                  : null,
            }
          : {}),
      } as ScanTarget,
    }));
    const newKeys = new Set(targets.map(({ target }) => rowKey(target)));
    const count = Array.from(newKeys).filter(
      (key) => !rowsRef.current.has(key),
    ).length;
    const continuation =
      sourceKind === "ip" && typeof request.cursor_ip === "string";
    const pages = continuation
      ? (reportsRef.current[scopeKey]?.pages ?? [])
      : [];
    const retainedPages =
      Object.entries(reportsRef.current)
        .filter(([key]) => key !== scopeKey)
        .reduce((count, [, scope]) => count + scope.pages.length, 0) +
      pages.length +
      1;
    if (
      rowsRef.current.size + count > MAX_ROWS ||
      retainedPages > MAX_REPORT_PAGES ||
      (!(scopeKey in reportsRef.current) &&
        Object.keys(reportsRef.current).length >= MAX_SCOPES)
    )
      throw new Error(
        `Scan workspace capacity reached (${MAX_ROWS} identities / ${MAX_SCOPES} scopes / ${MAX_REPORT_PAGES} response pages). Export and clear results before adding another report.`,
      );
    const { devices: _, ...window } = report;
    for (const [key, row] of rowsRef.current) {
      const old = row.discoveries[scopeKey];
      if (old && !newKeys.has(key) && !continuation)
        rowsRef.current.set(key, {
          ...row,
          discoveries: {
            ...row.discoveries,
            [scopeKey]: { ...old, latest: false },
          },
        });
    }
    for (const { target, observation } of targets) {
      const key = rowKey(target),
        old = rowsRef.current.get(key);
      rowsRef.current.set(key, {
        key,
        target,
        discoveries: {
          ...old?.discoveries,
          [scopeKey]: { request, window, observation, latest: true },
        },
        version: (old?.version ?? 0) + 1,
        state: "pending",
        details: null,
        detail_error: null,
      });
    }
    reportsRef.current = {
      ...reportsRef.current,
      [scopeKey]: {
        source: sourceKind,
        pages: [...pages, { request, report }],
      },
    };
    setReports(reportsRef.current);
    publish();
    setPage(0);
    setError("");
    setMessage(
      "Discovery observations received. Device details are read sequentially for the shown page.",
    );
    setPaused(false);
    pausedRef.current = false;
    setKick((n) => n + 1);
  }
  useEffect(() => {
    if (!routedResult || seenRouted.current === routedResult) return;
    seenRouted.current = routedResult;
    try {
      receive(
        "routed",
        routedResult.request,
        routedResult.report as ScanReport,
      );
    } catch (error) {
      setError(String(error));
    }
  }, [routedResult]);

  // Metadata must not move unread rows into the current page. Rank the received
  // identities at discovery/view changes, then render their current row values.
  const discoveryRevision = JSON.stringify(
    rows.map((row) => [row.key, row.version, latest(row)]),
  );
  const rankedKeys = useMemo(() => {
    const term = query.toLocaleLowerCase();
    const found = Array.from(rowsRef.current.values()).filter(
      (row) =>
        (earlier || latest(row)) &&
        (source === "all" || row.target.source === source) &&
        (!term ||
          JSON.stringify([
            row.target,
            row.details?.properties,
            row.details?.program_names,
            lastObservation(row),
          ])
            .toLocaleLowerCase()
            .includes(term)),
    );
    const field = (row: Row) =>
      sort === "name"
        ? property(row, "object-name")
        : sort === "model"
          ? property(row, "model-name")
          : sort === "vendor"
            ? property(row, "vendor-name") || vendorIdentifier(row)
            : sort === "device"
              ? row.target.device
              : sort === "program"
                ? programLabel(row)
                : `${row.target.router ?? ""}/${row.target.dnet ?? ""}/${row.target.address}`;
    return found
      .sort(
        (a, b) =>
          (ascending ? 1 : -1) *
          (String(field(a)).localeCompare(String(field(b)), undefined, {
            numeric: true,
          }) || a.key.localeCompare(b.key)),
      )
      .map((row) => row.key);
  }, [
    discoveryRevision,
    query,
    source,
    sort,
    ascending,
    earlier,
    viewRevision,
  ]);
  const filtered = rankedKeys
    .map((key) => rowsRef.current.get(key))
    .filter((row): row is Row => !!row);
  const maxPage = Math.max(0, Math.ceil(filtered.length / PAGE_SIZE) - 1),
    currentPage = Math.min(page, maxPage);
  const shown = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  const visibleKey = JSON.stringify(shown.map((row) => [row.key, row.version]));
  const shownRef = useRef(shown);
  shownRef.current = shown;
  useEffect(() => {
    const context = JSON.stringify([connected, localAddress, visibleKey]);
    if (metadataContext.current !== context) {
      metadataContext.current = context;
      metadataEpoch.current++;
    }
    if (
      !connected ||
      paused ||
      scanBusy ||
      metadataActive.current ||
      !shownRef.current.some((row) => row.state === "pending")
    )
      return;
    const owner = metadataEpoch.current,
      keys = shownRef.current.map((row) => ({
        key: row.key,
        version: row.version,
      }));
    metadataActive.current = true;
    setMetadataBusy(true);
    void (async () => {
      try {
        for (const { key, version } of keys) {
          if (
            !mounted.current ||
            owner !== metadataEpoch.current ||
            pausedRef.current ||
            !connectedRef.current
          )
            break;
          const row = rowsRef.current.get(key);
          if (!row || row.version !== version || row.state !== "pending")
            continue;
          changeRow(key, version, (current) => ({
            ...current,
            state: "reading",
            detail_error: null,
          }));
          try {
            const target = row.target;
            const details = await api("/bacnet/device-details", {
              address: target.address,
              device: target.device,
              ...(target.source === "routed"
                ? { router: target.router, dnet: target.dnet }
                : {}),
            });
            if (mounted.current && owner === metadataEpoch.current)
              changeRow(key, version, (current) => ({
                ...current,
                state: details.complete ? "complete" : "partial",
                details,
                detail_error: null,
              }));
          } catch (error) {
            if (mounted.current && owner === metadataEpoch.current)
              changeRow(key, version, (current) => ({
                ...current,
                state: "error",
                detail_error: String(error),
              }));
          } finally {
            const current = rowsRef.current.get(key);
            if (current?.version === version && current.state === "reading")
              changeRow(key, version, (value) => ({
                ...value,
                state: "pending",
              }));
          }
        }
      } finally {
        metadataActive.current = false;
        if (mounted.current) {
          setMetadataBusy(false);
          setKick((n) => n + 1);
        }
      }
    })();
  }, [connected, localAddress, visibleKey, paused, scanBusy, kick]);

  function edit(change: () => void) {
    if (scanActive.current) return;
    scanEpoch.current++;
    change();
    setLastIpScan(null);
    setError("");
    setMessage("");
  }
  async function scan(continueRange = false) {
    if (scanActive.current || metadataActive.current || !connected) return;
    scanActive.current = true;
    const owner = ++scanEpoch.current;
    setScanBusy(true);
    setError("");
    setMessage("");
    try {
      let request: Record<string, unknown> = {
        mode,
        udp_port: integer(port, 1, 65535, "UDP port"),
        low: integer(low, 0, 4194302, "Minimum Device instance"),
        high: integer(high, 0, 4194302, "Maximum Device instance"),
        max_devices: integer(limit, 1, 256, "Device limit"),
      };
      const timeout = Number(seconds);
      if (
        !seconds.trim() ||
        !Number.isFinite(timeout) ||
        timeout < 1 ||
        timeout > 10
      )
        throw new Error(
          "Discovery response window must be from 1 to 10 seconds.",
        );
      request.timeout_seconds = timeout;
      if (Number(request.low) > Number(request.high))
        throw new Error("Minimum Device instance must not exceed maximum.");
      if (mode === "single") request.ip = ipv4(ip);
      if (mode === "range") {
        const start = ipv4(startIp),
          end = ipv4(endIp),
          size = addressNumber(end) - addressNumber(start) + 1;
        if (size < 1 || size > 65536)
          throw new Error(
            "Choose an increasing inclusive IPv4 range of at most 65,536 hosts.",
          );
        request.start_ip = start;
        request.end_ip = end;
      }
      if (continueRange) {
        if (
          !lastIpScan ||
          lastIpScan.request.mode !== "range" ||
          typeof lastIpScan.report.next_ip !== "string"
        )
          throw new Error("No remaining IP range cursor is available.");
        request = {
          ...lastIpScan.request,
          cursor_ip: lastIpScan.report.next_ip,
        };
      }
      const result = await api("/bacnet/scan-ip", request);
      if (mounted.current && owner === scanEpoch.current) {
        receive("ip", request, result);
        setLastIpScan({ request, report: result });
      }
    } catch (error) {
      if (mounted.current && owner === scanEpoch.current)
        setError(String(error));
    } finally {
      scanActive.current = false;
      if (mounted.current) setScanBusy(false);
    }
  }
  function stop() {
    pausedRef.current = true;
    setPaused(true);
    setMessage(
      "Metadata queue stopped. The current bounded request may finish; no further device is queued.",
    );
  }
  function resume() {
    pausedRef.current = false;
    setPaused(false);
    setKick((n) => n + 1);
    setMessage("");
  }
  function retryPage() {
    if (scanActive.current || metadataActive.current) return;
    for (const row of shown)
      changeRow(row.key, row.version, (value) => ({
        ...value,
        state: "pending",
        details: null,
        detail_error: null,
      }));
    resume();
  }
  function clear() {
    if (scanActive.current || metadataActive.current) return;
    scanEpoch.current++;
    metadataEpoch.current++;
    rowsRef.current.clear();
    reportsRef.current = {};
    setReports({});
    publish();
    setLastIpScan(null);
    setSelected(null);
    setPage(0);
    setError("");
    setMessage("");
  }
  function choose(row: Row) {
    if (
      scanActive.current ||
      metadataActive.current ||
      !connected ||
      rowsRef.current.get(row.key) !== row
    )
      return;
    onSelect({ ...row.target });
  }
  function exportData(kind: "json" | "csv") {
    if (scanActive.current || metadataActive.current || !mounted.current)
      return;
    const currentRows = Array.from(rowsRef.current.values());
    if (kind === "json")
      saveBlob(
        new Blob(
          [
            JSON.stringify(
              {
                format: "bms-device-scan/1",
                exported_at: new Date().toISOString(),
                scope:
                  "Received discovery and device metadata observations; no controller program upload or current liveness guarantee.",
                reports: reportsRef.current,
                rows: currentRows,
              },
              null,
              2,
            ),
          ],
          { type: "application/json" },
        ),
        "bacnet-device-scan.json",
      );
    else {
      const header = [
        "row_type",
        "scope_key",
        "report_page",
        "request_json",
        "report_json",
        "source",
        "router",
        "dnet",
        "address",
        "device",
        "device_instance",
        "name",
        "description",
        "vendor_identifier",
        "vendor_name",
        "model",
        "firmware",
        "application_software_version",
        "program_names",
        "programs_status",
        "metadata_status",
        "metadata_error",
        "metadata_finished_at",
        "latest_window",
        "discovery_evidence_json",
        "metadata_json",
      ];
      const records: unknown[][] = currentRows.map((row) => [
        "device",
        null,
        null,
        null,
        null,
        row.target.source,
        row.target.router,
        row.target.dnet,
        row.target.address,
        row.target.device,
        Number(row.target.device.split(",")[1]),
        property(row, "object-name"),
        property(row, "description"),
        vendorIdentifier(row),
        property(row, "vendor-name"),
        property(row, "model-name"),
        property(row, "firmware-revision"),
        property(row, "application-software-version"),
        row.details?.program_names ?? [],
        row.details?.programs_status ?? "not_read",
        row.state,
        row.detail_error,
        row.details?.finished_at,
        latest(row),
        row.discoveries,
        row.details,
      ]);
      for (const [scopeKey, scope] of Object.entries(reportsRef.current))
        scope.pages.forEach(({ request, report }, index) => {
          const record: unknown[] = Array(header.length).fill(null);
          record[0] = "report";
          record[1] = scopeKey;
          record[2] = index + 1;
          record[3] = request;
          record[4] = report;
          record[5] = scope.source;
          records.push(record);
        });
      saveBlob(
        new Blob(
          [
            [header, ...records]
              .map((record) => record.map(csvCell).join(","))
              .join("\r\n") + "\r\n",
          ],
          { type: "text/csv;charset=utf-8" },
        ),
        "bacnet-device-scan.csv",
      );
    }
  }
  const busy = scanBusy || metadataBusy;
  const inspected = selected ? rows.find((row) => row.key === selected) : null;
  const pending = shown.filter((row) => row.state === "pending").length;
  return (
    <section
      id="bacnet-device-scan"
      className="card device-scan"
      aria-label="BACnet device scan"
    >
      <div className="card-header">
        <h3>
          <Radar size={18} /> Scan
        </h3>
        <span className="pill">READ ONLY</span>
      </div>
      <div className="card-body">
        <p>
          Discover local BACnet/IP devices, one IP address, or a bounded IP
          range. Routed discovery results join this list. Device names and
          metadata load sequentially for the shown 20-row page. Program names
          come only from exposed BACnet Program objects.
        </p>
        <p className="muted">
          Bind address: {localAddress || "not selected"}. No interface opens
          automatically. Discovery observations are timestamped; silence does
          not prove an address is unused.
        </p>
        <div className="form-grid">
          <label>
            IP scan mode
            <select
              aria-label="IP scan mode"
              disabled={busy}
              value={mode}
              onChange={(event) => edit(() => setMode(event.target.value))}
            >
              <option value="local">Local network</option>
              <option value="single">Single IP address</option>
              <option value="range">IP address range</option>
            </select>
          </label>
          {mode === "single" && (
            <label>
              Scan IP address
              <input
                aria-label="Scan IP address"
                disabled={busy}
                value={ip}
                placeholder="192.168.1.10"
                onChange={(event) => edit(() => setIp(event.target.value))}
              />
            </label>
          )}
          {mode === "range" && (
            <>
              <label>
                First scan IP address
                <input
                  aria-label="First scan IP address"
                  disabled={busy}
                  value={startIp}
                  onChange={(event) =>
                    edit(() => setStartIp(event.target.value))
                  }
                />
              </label>
              <label>
                Last scan IP address
                <input
                  aria-label="Last scan IP address"
                  disabled={busy}
                  value={endIp}
                  onChange={(event) => edit(() => setEndIp(event.target.value))}
                />
              </label>
            </>
          )}
          <label>
            Scan UDP port
            <input
              aria-label="Scan UDP port"
              type="number"
              min="1"
              max="65535"
              disabled={busy}
              value={port}
              onChange={(event) => edit(() => setPort(event.target.value))}
            />
          </label>
          <label>
            Discovery response seconds
            <input
              aria-label="Discovery response seconds"
              type="number"
              min="1"
              max="10"
              step="0.5"
              disabled={busy}
              value={seconds}
              onChange={(event) => edit(() => setSeconds(event.target.value))}
            />
          </label>
          <div className="device-scan-action">
            <button
              className="primary"
              disabled={busy || !connected}
              onClick={() => void scan()}
            >
              <Search size={15} /> Scan BACnet/IP devices
            </button>
          </div>
        </div>
        {mode === "local" && (
          <p className="muted">
            Local discovery uses the opened interface's actual subnet, or its
            existing foreign-device registration when applicable. It does not
            forward discovery onto every routed MS/TP network.
          </p>
        )}
        <details>
          <summary>Discovery bounds and interface profile</summary>
          <div className="form-grid">
            <label>
              Scan minimum Device instance
              <input
                aria-label="Scan minimum Device instance"
                type="number"
                disabled={busy}
                value={low}
                onChange={(event) => edit(() => setLow(event.target.value))}
              />
            </label>
            <label>
              Scan maximum Device instance
              <input
                aria-label="Scan maximum Device instance"
                type="number"
                disabled={busy}
                value={high}
                onChange={(event) => edit(() => setHigh(event.target.value))}
              />
            </label>
            <label>
              Scan device limit
              <input
                aria-label="Scan device limit"
                type="number"
                min="1"
                max="256"
                disabled={busy}
                value={limit}
                onChange={(event) => edit(() => setLimit(event.target.value))}
              />
            </label>
          </div>
          <p>
            Selected IP ranges contain at most 65,536 hosts; each explicit page
            sends to at most 256 targets and is bounded by the service deadline.
            This workspace retains at most {MAX_ROWS} identities, {MAX_SCOPES}{" "}
            scopes and {MAX_REPORT_PAGES} response pages, with visible capacity
            errors.
          </p>
          <pre>{JSON.stringify(profile, null, 2)}</pre>
        </details>
        {lastIpScan && (
          <section aria-label="Last IP discovery response">
            <p>
              {lastIpScan.report.mode as string} ·{" "}
              {(lastIpScan.report.page_targets_requested as number) ??
                (lastIpScan.report.targets_requested as number)}{" "}
              targets requested this page /{" "}
              {lastIpScan.report.targets_requested as number} selected ·{" "}
              {(lastIpScan.report.targets_sent as unknown[]).length} targets
              sent · {lastIpScan.report.devices.length} identities received.
            </p>
            <p className="muted">
              {String(lastIpScan.report.started_at)} /{" "}
              {String(lastIpScan.report.finished_at)} ·{" "}
              {String(lastIpScan.report.scope)}
              {!!lastIpScan.report.broadcast_scope && (
                <> · {String(lastIpScan.report.broadcast_scope)}</>
              )}
            </p>
            {((lastIpScan.report.warnings as string[]) ?? []).map(
              (warning, index) => (
                <p key={index} className="muted">
                  {warning}
                </p>
              ),
            )}
            {typeof lastIpScan.report.next_ip === "string" && (
              <button
                disabled={busy || !connected}
                onClick={() => void scan(true)}
              >
                Continue IP range from {lastIpScan.report.next_ip}
              </button>
            )}
            <p>
              {lastIpScan.report.complete
                ? "Requested discovery page finished; this is not a complete controller inventory."
                : "Discovery has remaining targets or stopped within its bounds. Continue explicitly when a cursor is available."}
            </p>
          </section>
        )}
        {scanBusy && (
          <p role="status">
            Discovering devices in the requested response window…
          </p>
        )}
        {metadataBusy && (
          <p role="status">
            Reading device details sequentially. {pending} pending on the shown
            page.
          </p>
        )}
        {paused && (
          <p role="status">
            Automatic device details paused. Pending rows remain unread.
          </p>
        )}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        {message && <p role="status">{message}</p>}
        <div className="device-scan-toolbar">
          <label>
            Search discovered devices
            <input
              aria-label="Search discovered devices"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(0);
              }}
            />
          </label>
          <label>
            Discovery source
            <select
              aria-label="Discovery source"
              value={source}
              onChange={(event) => {
                setSource(event.target.value);
                setPage(0);
              }}
            >
              <option value="all">All sources</option>
              <option value="ip">BACnet/IP</option>
              <option value="routed">Routed</option>
            </select>
          </label>
          <label>
            Sort discovered devices
            <select
              aria-label="Sort discovered devices"
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
                setPage(0);
              }}
            >
              <option value="address">Address / route</option>
              <option value="name">Controller name</option>
              <option value="device">Device identifier</option>
              <option value="model">Model</option>
              <option value="vendor">Vendor</option>
              <option value="program">Program name/status</option>
            </select>
          </label>
          <button
            onClick={() => setAscending((value) => !value)}
            aria-label="Reverse device sort"
          >
            {ascending ? "Ascending" : "Descending"}
          </button>
          <button
            disabled={busy}
            onClick={() => setViewRevision((value) => value + 1)}
          >
            Refresh search and sort
          </button>
          <label className="device-scan-check">
            <input
              type="checkbox"
              checked={earlier}
              onChange={(event) => {
                setEarlier(event.target.checked);
                setPage(0);
              }}
            />{" "}
            Include earlier response windows
          </label>
        </div>
        <div className="button-row">
          <button disabled={!metadataBusy || paused} onClick={stop}>
            <Square size={14} /> Stop device details
          </button>
          <button disabled={busy || !connected || !pending} onClick={resume}>
            Resume shown-page details
          </button>
          <button
            disabled={busy || !connected || !shown.length}
            onClick={retryPage}
          >
            <ListRestart size={15} /> Read shown-page details again
          </button>
          <button
            disabled={busy || (!rows.length && !Object.keys(reports).length)}
            onClick={() => exportData("json")}
          >
            <Download size={15} /> Export all received JSON
          </button>
          <button
            disabled={busy || (!rows.length && !Object.keys(reports).length)}
            onClick={() => exportData("csv")}
          >
            <Download size={15} /> Export all received CSV
          </button>
          <button
            disabled={busy || (!rows.length && !Object.keys(reports).length)}
            onClick={clear}
          >
            Clear scan results
          </button>
        </div>
        <p>
          {filtered.length} matching identities · {rows.length} retained ·{" "}
          {Object.keys(reports).length} latest discovery reports. Address,
          router, destination network and Device identifier are preserved
          together.
        </p>
        <p className="muted">
          Search and sort keep the same page members while details arrive.
          Refresh search and sort to apply newly read names and values. CSV
          includes device rows and complete report rows, including empty pages.
        </p>
        <div className="device-scan-table">
          <table>
            <thead>
              <tr>
                <th>Controller</th>
                <th>Address / route</th>
                <th>Vendor / model</th>
                <th>Firmware</th>
                <th>Application software</th>
                <th>Program objects</th>
                <th>Read status / time</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.key} data-device-key={row.key}>
                  <td>
                    <strong>
                      {property(row, "object-name") ||
                        (row.state === "pending" || row.state === "reading"
                          ? "Name pending"
                          : "Name unavailable")}
                    </strong>
                    <br />
                    {property(row, "description") ||
                      "Description not exposed/read"}
                    <br />
                    {row.target.device}
                  </td>
                  <td>
                    {row.target.address}
                    <br />
                    {row.target.source === "routed"
                      ? `${row.target.router} · DNET ${row.target.dnet} · MAC ${row.target.mstp_mac ?? row.target.mac_hex ?? "unknown"}`
                      : "BACnet/IP"}
                    <br />
                    <span className="muted">
                      {latest(row)
                        ? "Observed in latest scope window"
                        : "Earlier response window"}
                    </span>
                  </td>
                  <td>
                    {property(row, "vendor-name") || "Vendor name unavailable"}{" "}
                    · {String(vendorIdentifier(row))}
                    <br />
                    {property(row, "model-name") || "Model unavailable"}
                  </td>
                  <td>
                    {property(row, "firmware-revision") ||
                      "Firmware unavailable"}
                  </td>
                  <td>
                    {property(row, "application-software-version") ||
                      "Unavailable"}
                  </td>
                  <td>
                    {programLabel(row)}
                    <br />
                    <span className="muted">
                      {row.details?.programs_status ?? "not_read"}
                    </span>
                  </td>
                  <td>
                    {row.state}
                    {row.details &&
                      !row.details.identity_verified &&
                      " · identity not verified"}
                    <br />
                    Discovery:{" "}
                    {String(
                      lastObservation(row).last_received_at ??
                        lastObservation(row).received_at ??
                        "See response window evidence",
                    )}
                    <br />
                    Details: {row.details?.finished_at ?? "Not read"}
                    <br />
                    {row.detail_error && (
                      <span className="inline-error">{row.detail_error}</span>
                    )}
                    {!!row.details?.errors.length && (
                      <span>{row.details.errors.length} metadata issues</span>
                    )}
                  </td>
                  <td>
                    <div className="button-row">
                      <button
                        disabled={busy || !connected}
                        aria-label={`Use controller ${row.target.router ?? "IP"}/${row.target.address}/${row.target.device}`}
                        onClick={() => choose(row)}
                      >
                        Use controller
                      </button>
                      <button
                        onClick={() => setSelected(row.key)}
                        aria-label={`Inspect device evidence ${row.target.router ?? "IP"}/${row.target.address}/${row.target.device}`}
                      >
                        Evidence
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!shown.length && (
          <p>
            No matching devices received. Unanswered addresses are not proved
            empty.
          </p>
        )}
        <div className="pagination">
          <button
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            Previous scan page
          </button>
          <span>
            Page {currentPage + 1} of {maxPage + 1} · {PAGE_SIZE} rows per page
          </span>
          <button
            disabled={currentPage === maxPage}
            onClick={() => setPage(currentPage + 1)}
          >
            Next scan page
          </button>
        </div>
        {inspected && (
          <section aria-label="Discovered device evidence">
            <h3>
              {inspected.target.device} · {inspected.target.address}
            </h3>
            <p>
              Property and program statuses distinguish unexposed values,
              partial inventories and failed reads. Observations are
              timestamped, not a guarantee of present liveness.
            </p>
            {inspected.details && (
              <>
                <div className="device-scan-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Property</th>
                        <th>Received value</th>
                        <th>Status</th>
                        <th>Received at</th>
                        <th>Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(inspected.details.property_status).map(
                        ([name, status]) => (
                          <tr key={name}>
                            <td>{name}</td>
                            <td>
                              {String(
                                inspected.details?.properties[name] ??
                                  "No value received",
                              )}
                            </td>
                            <td>{status.status}</td>
                            <td>{status.received_at ?? "Not received"}</td>
                            <td>{status.error ?? ""}</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
                <p>
                  Program inventory: {inspected.details.programs_status}.{" "}
                  {inspected.details.programs.length} Program objects received.
                </p>
              </>
            )}
            <pre>{JSON.stringify(inspected, null, 2)}</pre>
          </section>
        )}
        {!!Object.keys(reports).length && (
          <details>
            <summary>Latest discovery reports and provenance</summary>
            <pre>{JSON.stringify(reports, null, 2)}</pre>
          </details>
        )}
      </div>
    </section>
  );
}
