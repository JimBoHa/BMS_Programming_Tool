import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ControllerApplicationPanel } from "./ControllerApplication";
import { controllerKey, type ControllerContext } from "./workflow";

type RecordValue = Record<string, any>;
const base = "/bacnet/controller/";
const target = (controller: ControllerContext) => ({
  address: controller.address,
  device: controller.device,
  router: controller.router || null,
  dnet: controller.dnet ?? null,
});
function check(report: RecordValue, controller: ControllerContext) {
  if (
    !report.identity_verified ||
    controllerKey(report.target) !== controllerKey(controller)
  )
    throw new Error(
      report.errors?.join(" ") ||
        "The selected controller identity was not verified.",
    );
}
export function nativeText(value: any): string {
  if (value == null) return "—";
  if (typeof value === "object") {
    if (typeof value.name === "string") return value.name;
    if (value.native_datatype && "value" in value)
      return nativeText(value.value);
    return JSON.stringify(value);
  }
  return String(value);
}
const field = (properties: RecordValue | undefined, name: string) => {
  const row = properties?.[name];
  return row?.status === "ok"
    ? nativeText(row.value)
    : row
      ? `Unavailable (${row.status})`
      : "Reading…";
};

export function ControllerProgram({
  controller,
  connected,
  onLocalFile,
  onVerified,
}: {
  controller: ControllerContext;
  connected: boolean;
  onLocalFile?: () => void;
  onVerified?: (when: string) => void;
}) {
  const [profile, setProfile] = useState<RecordValue | null>(null);
  const [inventory, setInventory] = useState<RecordValue | null>(null);
  const [programs, setPrograms] = useState<RecordValue[]>([]);
  const [offset, setOffset] = useState(0),
    [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const generation = useRef(0);
  const verified = useRef(onVerified);
  verified.current = onVerified;
  const source = controllerKey(controller) + controller.interfaceKey;
  useEffect(() => {
    setOffset(0);
    setProfile(null);
    setInventory(null);
    setPrograms([]);
  }, [source]);
  useEffect(() => {
    const epoch = ++generation.current;
    setError("");
    if (!connected) {
      setBusy(false);
      return;
    }
    setBusy(true);
    void (async () => {
      try {
        const evidence = await api(base + "profile", target(controller));
        if (epoch !== generation.current) return;
        check(evidence, controller);
        verified.current?.(evidence.finished_at);
        setProfile(evidence);
        const list = await api(base + "inventory", {
          ...target(controller),
          offset,
          limit: 64,
        });
        if (epoch !== generation.current) return;
        check(list, controller);
        setInventory(list);
        const objects = list.objects.filter(
          (row: RecordValue) => row.object_type === 16,
        );
        if (objects.length) {
          const rows: RecordValue[] = [];
          for (let index = 0; index < objects.length; index += 16) {
            const result = await api(base + "properties", {
              ...target(controller),
              object_ids: objects
                .slice(index, index + 16)
                .map((row: RecordValue) => row.object),
              properties: [
                "object-name",
                "description",
                "program-state",
                "reason-for-halt",
                "program-location",
              ],
            });
            if (epoch !== generation.current) return;
            check(result, controller);
            rows.push(...result.objects);
          }
          setPrograms(rows);
        } else setPrograms([]);
      } catch (failure) {
        if (epoch === generation.current) setError(String(failure));
      } finally {
        if (epoch === generation.current) setBusy(false);
      }
    })();
    return () => {
      generation.current++;
    };
  }, [source, connected, offset, refresh]);
  return (
    <section className="card" aria-label="Connected controller application">
      <div className="card-header">
        <h2>{controller.name} · Application</h2>
        <span className="pill">CONTROLLER DATA</span>
      </div>
      <div className="card-body">
        <ControllerApplicationPanel
          controller={controller}
          connected={connected}
          onVerified={onVerified}
        />
        <details>
          <summary>Controller identity, protocol and Program objects</summary>
          <div className="button-row">
            <button
              disabled={!connected || busy}
              onClick={() => setRefresh((value) => value + 1)}
            >
              Read controller application information
            </button>
            <span>
              {busy
                ? "Reading the selected controller…"
                : profile
                  ? `Read at ${profile.finished_at}`
                  : "No application information read"}
            </span>
          </div>
          {!connected && (
            <p role="status">
              The matching controller interface is closed. Displayed information
              is last known.
            </p>
          )}
          {error && (
            <p className="inline-error" role="alert">
              {error}
            </p>
          )}
          {profile && (
            <>
              <dl className="workflow-identity-grid">
                {[
                  ["Controller name", "object-name"],
                  ["Manufacturer", "vendor-name"],
                  ["Model", "model-name"],
                  ["Firmware", "firmware-revision"],
                  [
                    "Application software version",
                    "application-software-version",
                  ],
                  ["Configured BACnet objects", "object-list"],
                ].map(([label, prop]) => (
                  <div key={prop}>
                    <dt>{label}</dt>
                    <dd>{field(profile.properties, prop)}</dd>
                  </div>
                ))}
              </dl>
              <details>
                <summary>Discovered protocol capabilities</summary>
                <pre>
                  {JSON.stringify(
                    profile.properties["protocol-services-supported"],
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          )}
          <h3>Program objects exposed by the controller</h3>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Object</th>
                <th>Actual state</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {programs.map((row) => (
                <tr key={row.object}>
                  <td>{field(row.properties, "object-name")}</td>
                  <td>{row.object}</td>
                  <td>{field(row.properties, "program-state")}</td>
                  <td>{field(row.properties, "description")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {inventory && !programs.length && (
            <p>
              No standard Program objects were returned in this inventory page.
              A controller can run native application logic without exposing
              BACnet Program objects.
            </p>
          )}
          {inventory && (
            <div className="button-row">
              <span>
                Objects {inventory.offset + 1}–
                {inventory.offset + inventory.objects.length} of{" "}
                {inventory.total}
              </span>
              <button
                disabled={busy || !offset}
                onClick={() => setOffset(Math.max(0, offset - 64))}
              >
                Previous application inventory
              </button>
              <button
                disabled={busy || inventory.next_offset == null}
                onClick={() => setOffset(inventory.next_offset)}
              >
                Next application inventory
              </button>
            </div>
          )}
        </details>
        {onLocalFile && (
          <button onClick={onLocalFile}>Open a local application file</button>
        )}
      </div>
    </section>
  );
}

export function LiveControllerPoints({
  controller,
  connected,
  onCommand,
  onVerified,
}: {
  controller: ControllerContext;
  connected: boolean;
  onCommand: (object: string) => void;
  onVerified?: (when: string) => void;
}) {
  const [inventory, setInventory] = useState<RecordValue | null>(null),
    [values, setValues] = useState<Record<string, RecordValue>>({});
  const [offset, setOffset] = useState(0),
    [page, setPage] = useState(0),
    [reload, setReload] = useState(0);
  const [query, setQuery] = useState(""),
    [allObjects, setAllObjects] = useState(false),
    [live, setLive] = useState(true);
  const [interval, setIntervalSeconds] = useState(10),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [readAt, setReadAt] = useState(""),
    [selected, setSelected] = useState<RecordValue | null>(null),
    [detail, setDetail] = useState<RecordValue | null>(null);
  const [propertyId, setPropertyId] = useState("");
  const verified = useRef(onVerified);
  verified.current = onVerified;
  const inventoryEpoch = useRef(0),
    valueEpoch = useRef(0),
    detailEpoch = useRef(0);
  const source = controllerKey(controller) + controller.interfaceKey;
  useEffect(() => {
    setOffset(0);
    setPage(0);
    setInventory(null);
    setValues({});
    setSelected(null);
    setDetail(null);
    setReadAt("");
  }, [source]);
  useEffect(() => {
    const epoch = ++inventoryEpoch.current;
    setError("");
    setPage(0);
    setInventory(null);
    setValues({});
    if (!connected) {
      setBusy(false);
      return;
    }
    setBusy(true);
    api(base + "inventory", { ...target(controller), offset, limit: 64 })
      .then((result) => {
        if (epoch !== inventoryEpoch.current) return;
        check(result, controller);
        setInventory(result);
        if (result.errors.length) setError(result.errors.join(" "));
      })
      .catch((failure) => {
        if (epoch === inventoryEpoch.current) setError(String(failure));
      })
      .finally(() => {
        if (epoch === inventoryEpoch.current) setBusy(false);
      });
    return () => {
      inventoryEpoch.current++;
    };
  }, [source, connected, offset, reload]);
  const objects: RecordValue[] =
    inventory?.objects.filter(
      (row: RecordValue) =>
        allObjects || row.has_present_value || row.structured_group,
    ) ?? [];
  const shown = objects.slice(page * 8, page * 8 + 8);
  const pageKey = JSON.stringify(shown.map((row) => row.object));
  useEffect(() => {
    const epoch = ++valueEpoch.current;
    let timer: number | undefined;
    if (!connected || !shown.length) return;
    const configured = new Set<string>();
    const read = async () => {
      const identifiers = JSON.parse(pageKey) as string[];
      const failures: string[] = [];
      try {
        for (const identifier of identifiers) {
          if (epoch !== valueEpoch.current) return;
          const configuration = !configured.has(identifier);
          try {
            const report = await api(base + "properties", {
              ...target(controller),
              object_ids: [identifier],
              properties: configuration
                ? [
                    "object-name",
                    "description",
                    "present-value",
                    "units",
                    "status-flags",
                    "reliability",
                    "out-of-service",
                  ]
                : [
                    "present-value",
                    "status-flags",
                    "reliability",
                    "out-of-service",
                  ],
            });
            if (epoch !== valueEpoch.current) return;
            check(report, controller);
            verified.current?.(report.finished_at);
            if (configuration && report.complete) configured.add(identifier);
            setValues((prior) => {
              const next = { ...prior };
              for (const row of report.objects)
                if (row.identity_verified)
                  next[row.object] = {
                    ...row,
                    properties: {
                      ...prior[row.object]?.properties,
                      ...row.properties,
                    },
                  };
              return next;
            });
            setReadAt(report.finished_at);
            failures.push(...report.errors);
            if (!report.complete)
              failures.push(
                "Partial read: some properties were not refreshed; their displayed values remain last known.",
              );
          } catch (failure) {
            if (epoch !== valueEpoch.current) return;
            failures.push(`${identifier}: ${String(failure)}`);
          }
        }
        if (epoch === valueEpoch.current)
          setError(Array.from(new Set(failures)).join(" "));
      } finally {
        if (epoch === valueEpoch.current && live)
          timer = window.setTimeout(() => void read(), interval * 1000);
      }
    };
    void read();
    return () => {
      valueEpoch.current++;
      window.clearTimeout(timer);
    };
  }, [source, connected, pageKey, live, interval, reload]);
  useEffect(() => {
    const epoch = ++detailEpoch.current;
    setDetail(null);
    if (!connected || !selected) return;
    const properties = selected.structured_group
      ? [
          "object-name",
          "description",
          "node-type",
          "subordinate-list",
          "subordinate-annotations",
          "subordinate-node-types",
          "property-list",
        ]
      : [
          "object-name",
          "description",
          "property-list",
          "device-type",
          "units",
          "resolution",
          "min-pres-value",
          "max-pres-value",
          "polarity",
          "number-of-states",
          "state-text",
          "out-of-service",
        ];
    api(base + "properties", {
      ...target(controller),
      object_ids: [selected.object],
      properties,
    })
      .then((report) => {
        if (epoch !== detailEpoch.current) return;
        check(report, controller);
        if (!report.objects[0]?.identity_verified)
          throw new Error("Selected object identity was not verified.");
        setDetail(report.objects[0]);
      })
      .catch((failure) => {
        if (epoch === detailEpoch.current) setError(String(failure));
      });
    return () => {
      detailEpoch.current++;
    };
  }, [source, connected, selected?.object]);
  const filtered = shown.filter((row) =>
    [
      row.object,
      field(values[row.object]?.properties, "object-name"),
      field(values[row.object]?.properties, "description"),
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <section className="card" aria-label="Connected controller points">
      <div className="card-header">
        <h2>{controller.name} · Points & I/O</h2>
        <span className="pill">
          {connected
            ? live
              ? "LIVE CONTROLLER READS"
              : "PAUSED"
            : "INTERFACE CLOSED"}
        </span>
      </div>
      <div className="card-body">
        <p>
          Objects and configuration are read from this controller’s own
          inventory. Exposed I/O groups and module references are retained;
          physical module counts and wiring are not inferred from a model name.
        </p>
        <div className="button-row">
          <button
            disabled={busy || !connected}
            onClick={() => setReload((value) => value + 1)}
          >
            Reload controller inventory
          </button>
          <label>
            <input
              type="checkbox"
              checked={live}
              onChange={(event) => setLive(event.target.checked)}
            />{" "}
            Live values
          </label>
          <label>
            Refresh interval
            <select
              aria-label="Controller value refresh interval"
              value={interval}
              onChange={(event) =>
                setIntervalSeconds(Number(event.target.value))
              }
            >
              <option value={5}>5 seconds</option>
              <option value={10}>10 seconds</option>
              <option value={30}>30 seconds</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={allObjects}
              onChange={(event) => {
                setAllObjects(event.target.checked);
                setPage(0);
              }}
            />{" "}
            Show all BACnet objects
          </label>
        </div>
        <p role="status">
          {busy
            ? "Reading the selected controller’s configured object list…"
            : readAt
              ? `Values read at ${readAt}. ${error || !connected ? "Displayed values are last known." : ""}`
              : "Waiting for actual controller data…"}
        </p>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <label>
          Find points
          <input
            type="search"
            aria-label="Find controller points"
            value={query}
            placeholder="Name, description or object on this page"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Point name</th>
                <th>Object</th>
                <th>Native value</th>
                <th>Units</th>
                <th>Reliability</th>
                <th>Status flags</th>
                <th>Out of service</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const props = values[row.object]?.properties;
                return (
                  <tr key={row.object}>
                    <td>
                      <strong>{field(props, "object-name")}</strong>
                    </td>
                    <td>{row.object}</td>
                    <td>{field(props, "present-value")}</td>
                    <td>{field(props, "units")}</td>
                    <td>{field(props, "reliability")}</td>
                    <td>{field(props, "status-flags")}</td>
                    <td>{field(props, "out-of-service")}</td>
                    <td>
                      <button onClick={() => setSelected(row)}>
                        Configuration
                      </button>
                      {row.has_present_value && (
                        <button
                          disabled={!connected}
                          onClick={() => onCommand(row.object)}
                        >
                          Review point command
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {inventory && !objects.length && (
          <p>
            No standard value or structured I/O objects were returned in this
            page. Show all objects or continue through the device inventory.
          </p>
        )}
        {inventory && (
          <div className="button-row">
            <span>
              Controller inventory {offset + 1}–
              {offset + inventory.objects.length} of {inventory.total} ·{" "}
              {objects.length} value/group objects in this inventory page
            </span>
            <button disabled={busy || !page} onClick={() => setPage(page - 1)}>
              Previous points
            </button>
            <button
              disabled={busy || (page + 1) * 8 >= objects.length}
              onClick={() => setPage(page + 1)}
            >
              Next points
            </button>
            <button
              disabled={busy || !offset}
              onClick={() => setOffset(Math.max(0, offset - 64))}
            >
              Previous inventory page
            </button>
            <button
              disabled={busy || inventory.next_offset == null}
              onClick={() => setOffset(inventory.next_offset)}
            >
              Next inventory page
            </button>
          </div>
        )}
        {selected && (
          <section aria-label="Actual point configuration">
            <h3>{selected.object} · Controller configuration</h3>
            <button onClick={() => setSelected(null)}>
              Close configuration
            </button>
            <div className="button-row">
              <label>
                Additional property name or number
                <input
                  aria-label="Controller configuration property"
                  value={propertyId}
                  onChange={(event) => setPropertyId(event.target.value)}
                />
              </label>
              <button
                disabled={!connected || !propertyId.trim()}
                onClick={() => {
                  const epoch = ++detailEpoch.current;
                  void api(base + "properties", {
                    ...target(controller),
                    object_ids: [selected.object],
                    properties: [propertyId.trim()],
                  })
                    .then((report) => {
                      if (epoch !== detailEpoch.current) return;
                      check(report, controller);
                      if (!report.objects[0]?.identity_verified)
                        throw new Error(
                          "Selected object identity was not verified.",
                        );
                      setDetail((current) => ({
                        ...report.objects[0],
                        properties: {
                          ...current?.properties,
                          ...report.objects[0].properties,
                        },
                      }));
                    })
                    .catch((failure) => {
                      if (epoch === detailEpoch.current)
                        setError(String(failure));
                    });
                }}
              >
                Read controller property
              </button>
            </div>
            {detail ? (
              <table>
                <thead>
                  <tr>
                    <th>Property</th>
                    <th>Actual value</th>
                    <th>Read outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(detail.properties).map(([prop, evidence]) => (
                    <tr key={prop}>
                      <td>{prop}</td>
                      <td>{nativeText((evidence as any).value)}</td>
                      <td>
                        {(evidence as any).status}
                        <details>
                          <summary>Native evidence</summary>
                          <pre>{JSON.stringify(evidence, null, 2)}</pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p>Reading exposed configuration and property metadata…</p>
            )}
          </section>
        )}
      </div>
    </section>
  );
}
