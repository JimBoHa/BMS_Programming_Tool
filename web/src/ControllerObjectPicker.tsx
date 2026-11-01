import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { controllerKey, type ControllerTarget } from "./workflow";
import "./controller-object-picker.css";

type Choice = { object: string; name: string };
type Page = {
  source: string;
  offset: number;
  total: number | null;
  next: number | null;
  rows: Choice[];
  message: string;
};

function configurationKey(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(configurationKey).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${configurationKey(item)}`)
      .join(",")}}`;
  return JSON.stringify(value) ?? "null";
}

/** Bounded, read-only choices from the selected controller's actual object list. */
export function ControllerObjectPicker({
  target,
  interfaceKey,
  connected,
  value,
  onChange,
  kind,
  label,
  disabled = false,
}: {
  target: ControllerTarget;
  interfaceKey?: string;
  connected: boolean;
  value: string;
  onChange: (objectId: string) => void;
  kind: "value" | "trend-log";
  label: string;
  disabled?: boolean;
}) {
  const source = JSON.stringify([
    controllerKey(target),
    interfaceKey ?? null,
    connected,
    kind,
  ]);
  let configuration: Record<string, unknown> | null = null;
  try {
    const parsed = interfaceKey ? JSON.parse(interfaceKey) : null;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
      configuration = parsed;
  } catch {
    // An unavailable context must not be replaced with the latest interface.
  }
  const available =
    connected && !!configuration && configuration.transport !== "mstp";
  const [position, setPosition] = useState({ source, offset: 0 });
  const offset = position.source === source ? position.offset : 0;
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<{ source: string; text: string } | null>(
    null,
  );
  const [search, setSearch] = useState({ source, value: "" });
  const epoch = useRef(0);
  const currentSource = useRef(source);
  if (currentSource.current !== source) {
    currentSource.current = source;
    epoch.current++;
  }
  const current =
    page?.source === source && page.offset === offset ? page : null;
  const query = search.source === source ? search.value : "";
  const loading = pending === source;

  useEffect(() => {
    const generation = ++epoch.current;
    const active = () =>
      generation === epoch.current && currentSource.current === source;
    if (!available || disabled) return;
    setPending(source);
    setError(null);
    const pinned: ControllerTarget = {
      address: target.address,
      device: target.device,
      router: target.router || null,
      dnet: target.dnet ?? null,
    };
    function verify(report: any) {
      if (
        !report?.identity_verified ||
        !report.target ||
        controllerKey(report.target) !== controllerKey(pinned) ||
        configurationKey(report.connector_config) !==
          configurationKey(configuration)
      )
        throw new Error(
          report?.errors?.join(" ") ||
            "The selected controller's inventory identity or interface context was not verified.",
        );
    }
    void (async () => {
      try {
        const inventory = await api("/bacnet/controller/inventory", {
          ...pinned,
          offset,
          limit: 16,
        });
        if (!active()) return;
        verify(inventory);
        const objects = inventory.objects.filter((row: any) =>
          kind === "trend-log"
            ? row.object_type === 20
            : row.has_present_value === true,
        );
        const choices: Choice[] = objects.map((row: any) => ({
          object: row.object,
          name: "",
        }));
        let message = (inventory.errors || []).join(" ");
        if (choices.length) {
          try {
            const names = await api("/bacnet/controller/properties", {
              ...pinned,
              object_ids: choices.map((row) => row.object),
              properties: ["object-name"],
            });
            if (!active()) return;
            verify(names);
            for (const choice of choices) {
              const observed = names.objects.find(
                (row: any) => row.object === choice.object,
              );
              const property =
                observed?.identity_verified &&
                observed.properties?.["object-name"];
              const native = property?.status === "ok" ? property.value : null;
              choice.name =
                typeof native === "string"
                  ? native
                  : native?.native_datatype && typeof native.value === "string"
                    ? native.value
                    : "";
            }
          } catch (failure) {
            if (!active()) return;
            message =
              `${message} Names unavailable: ${String(failure)}. Object identities remain from the verified inventory.`.trim();
          }
        }
        if (!active()) return;
        setPage({
          source,
          offset,
          total: inventory.total,
          next: inventory.next_offset,
          rows: choices,
          message,
        });
      } catch (failure) {
        if (active()) {
          setPage(null);
          setError({ source, text: String(failure) });
        }
      } finally {
        if (active()) setPending(null);
      }
    })();
    return () => {
      epoch.current++;
    };
  }, [source, offset, revision, kind, available, disabled]);

  const rows =
    current?.rows.filter((row) =>
      `${row.name} ${row.object}`.toLowerCase().includes(query.toLowerCase()),
    ) || [];
  return (
    <fieldset className="controller-object-picker" aria-label={label}>
      <legend>{label}</legend>
      {!available ? (
        <p className="help-text">
          {!connected
            ? "Open the matching controller interface to discover objects. Saved evidence remains available offline."
            : configuration?.transport === "mstp"
              ? "Selected-controller object choices currently require BACnet/IPv4, directly or through an IP router. Standalone serial acquisition is a separate profile."
              : "Reopen and verify the controller to obtain its interface context."}
        </p>
      ) : (
        <>
          <p className="help-text">
            Objects are read from {target.address} · {target.device}
            {target.router
              ? ` · router ${target.router} · network ${target.dnet}`
              : ""}
            . This list does not infer objects from a controller model.
          </p>
          <div className="form-grid">
            <label>
              Search this inventory page
              <input
                aria-label={`${label} search`}
                value={query}
                disabled={disabled || loading}
                onChange={(event) =>
                  setSearch({ source, value: event.target.value })
                }
              />
            </label>
            <label>
              {kind === "trend-log"
                ? "Discovered Trend Log"
                : "Discovered value object"}
              <select
                aria-label={`${label} object`}
                value={value}
                disabled={disabled || loading || !current}
                onChange={(event) => {
                  if (
                    !disabled &&
                    available &&
                    !loading &&
                    (!event.target.value ||
                      rows.some((row) => row.object === event.target.value))
                  )
                    onChange(event.target.value);
                }}
              >
                <option value="">Choose a discovered object</option>
                {value && !rows.some((row) => row.object === value) && (
                  <option value={value}>
                    {value} · not on this shown page
                  </option>
                )}
                {rows.map((row) => (
                  <option key={row.object} value={row.object}>
                    {row.name
                      ? `${row.name} · ${row.object}`
                      : `${row.object} · name unavailable`}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="button-row">
            <button
              disabled={disabled || loading || offset === 0}
              onClick={() =>
                setPosition({ source, offset: Math.max(0, offset - 16) })
              }
            >
              Previous objects
            </button>
            <button
              disabled={disabled || loading || current?.next == null}
              onClick={() => setPosition({ source, offset: current!.next! })}
            >
              Next objects
            </button>
            <button
              disabled={disabled || loading}
              onClick={() => setRevision((value) => value + 1)}
            >
              Reload object choices
            </button>
          </div>
          {loading && (
            <p role="status">
              Reading the selected controller's object choices…
            </p>
          )}
          {current && (
            <p className="help-text">
              Inventory offset {current.offset} of {current.total ?? "unknown"}{" "}
              objects; {current.rows.length} eligible choices on this page.
              {!current.rows.length &&
                " No eligible objects were returned on this page; another page may contain them."}
              {current.message && ` ${current.message}`}
            </p>
          )}
          {error?.source === source && <p role="alert">{error.text}</p>}
        </>
      )}
    </fieldset>
  );
}
