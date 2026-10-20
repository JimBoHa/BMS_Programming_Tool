import { useEffect, useRef, useState } from "react";
import { Download, FileCode2, Upload } from "lucide-react";
import { api, download, saveBlob } from "./api";
import "./hardware-definitions.css";

type Point = {
  id: string;
  name: string;
  description: string;
  direction: string;
  object_type: number;
  instance: number;
  update_rate: number | null;
  write_strategy: string | null;
  value: {
    type: string;
    parameters: Record<string, any>;
    enum_resolution?: string;
    enum_reference?: string;
    enum_entries?: Record<string, string> | null;
  };
  attributes: {
    id: string;
    name: string;
    property_id: number;
    linked: boolean;
    value: unknown;
  }[];
};
type Definition = {
  sha256: string;
  name: string;
  revision: number;
  description: string;
  vendor: { name: string; number: number };
  buses: {
    bus: string;
    protocol: string;
    min_address: number;
    max_address: number;
  }[];
  measurement_system: string;
  points: Point[];
  point_errors: { id: string; error: string }[];
  presets: Record<string, { name: string; points: string[] }>;
  alias_groups: {
    object_type: number;
    instance: number;
    point_ids: string[];
  }[];
  unknown_records: unknown[];
  scope: string;
};
type Migration = {
  interface_changes: Record<string, { old: unknown; new: unknown }>;
  changes: {
    id: string;
    fields: Record<string, { old: unknown; new: unknown }>;
    requires_rebinding: boolean;
    requires_program_review: boolean;
  }[];
  blocking: { id: string; reason: string }[];
  requires_review: boolean;
  can_apply: false;
  old_sha256: string;
  new_sha256: string;
  old_revision: number;
  new_revision: number;
};

export function HardwareDefinitions() {
  const oldInput = useRef<HTMLInputElement>(null);
  const newInput = useRef<HTMLInputElement>(null);
  const [current, setCurrent] = useState<Definition | null>(null);
  const [replacement, setReplacement] = useState<Definition | null>(null);
  const [currentName, setCurrentName] = useState("");
  const [replacementName, setReplacementName] = useState("");
  const [system, setSystem] = useState("imperial");
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<any>(null);
  const [migration, setMigration] = useState<Migration | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setSelection(null);
    setMigration(null);
    setError("");
    setMessage("");
    if (!current && !replacement) return;
    setBusy(true);
    Promise.all([
      current ? api(`/jci/hardware/${current.sha256}?system=${system}`) : null,
      replacement
        ? api(`/jci/hardware/${replacement.sha256}?system=${system}`)
        : null,
    ])
      .then(([before, after]) => {
        if (!active) return;
        if (before) setCurrent(before);
        if (after) setReplacement(after);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
    // File changes are loaded explicitly below; this effect refreshes units only.
  }, [system]);

  async function open(file: File | undefined, slot: "current" | "replacement") {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    setSelection(null);
    setMigration(null);
    try {
      const form = new FormData();
      form.append("file", file);
      let result = await api("/jci/hardware/open", form);
      if (system !== "imperial")
        result = await api(`/jci/hardware/${result.sha256}?system=${system}`);
      if (slot === "current") {
        setCurrent(result);
        setCurrentName(file.name);
        setSelected([]);
      } else {
        setReplacement(result);
        setReplacementName(file.name);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (oldInput.current) oldInput.current.value = "";
      if (newInput.current) newInput.current.value = "";
    }
  }

  async function reviewSelection() {
    if (!current || !selected.length || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    setSelection(null);
    try {
      setSelection(
        await api(`/jci/hardware/${current.sha256}/selection`, {
          point_ids: selected,
          system,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function compare() {
    if (!current || !replacement || !selected.length || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    setMigration(null);
    try {
      setMigration(
        await api("/jci/hardware/migration", {
          old_sha: current.sha256,
          new_sha: replacement.sha256,
          point_ids: selected,
          system,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportOriginal(definition: Definition, name: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await download(
        `/jci/hardware/${definition.sha256}/export`,
        {},
        "original-" + (name.split(/[\\/]/).at(-1) || "hardware.xml"),
      );
      setMessage("Exported the exact original native XML bytes.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const points = (current?.points || []).filter((point) =>
    [
      point.id,
      point.name,
      point.description,
      point.value.type,
      point.object_type,
      point.instance,
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  function updateSelected(ids: string[]) {
    setSelected(ids);
    setSelection(null);
    setMigration(null);
    setError("");
    setMessage("");
  }

  return (
    <div
      className="workspace-page hardware-definitions"
      role="region"
      aria-label="JCI hardware definitions"
    >
      <div className="page-intro">
        <div>
          <span className="eyebrow">
            JOHNSON CONTROLS · NATIVE DEVICE SCHEMAS
          </span>
          <h1>Hardware definitions</h1>
          <p>
            Inspect native point types and build an engineering selection.
            Compare changed bindings before updating a device definition.
          </p>
        </div>
        <label>
          Measurement system
          <select
            aria-label="Hardware measurement system"
            value={system}
            disabled={busy}
            onChange={(e) => setSystem(e.target.value)}
          >
            <option value="imperial">Imperial</option>
            <option value="metric">Metric</option>
          </select>
        </label>
      </div>
      <div className="hardware-file-grid">
        {(["current", "replacement"] as const).map((slot) => {
          const definition = slot === "current" ? current : replacement;
          const filename = slot === "current" ? currentName : replacementName;
          const ref = slot === "current" ? oldInput : newInput;
          return (
            <section
              className="card hardware-file"
              key={slot}
              aria-label={
                slot === "current"
                  ? "Current hardware definition"
                  : "Replacement hardware definition"
              }
            >
              <div className="card-header">
                <h3>
                  <FileCode2 size={17} />
                  {slot === "current"
                    ? "Current definition"
                    : "Replacement definition"}
                </h3>
                <button disabled={busy} onClick={() => ref.current?.click()}>
                  <Upload size={14} />
                  {slot === "current"
                    ? "Open current definition"
                    : "Open replacement definition"}
                </button>
                <input
                  type="file"
                  accept=".xml"
                  aria-label={
                    slot === "current"
                      ? "Current hardware XML"
                      : "Replacement hardware XML"
                  }
                  hidden
                  ref={ref}
                  onChange={(e) => open(e.target.files?.[0], slot)}
                />
              </div>
              <div className="hardware-file-body">
                {definition ? (
                  <>
                    <h2>
                      {definition.name} · revision {definition.revision}
                    </h2>
                    <p>{definition.description}</p>
                    <dl>
                      <div>
                        <dt>Source file</dt>
                        <dd>{filename}</dd>
                      </div>
                      <div>
                        <dt>Vendor</dt>
                        <dd>
                          {definition.vendor.name} · {definition.vendor.number}
                        </dd>
                      </div>
                      <div>
                        <dt>Point profiles</dt>
                        <dd>
                          {definition.points.length} supported ·{" "}
                          {definition.point_errors.length} require
                          interpretation
                        </dd>
                      </div>
                      <div>
                        <dt>Bus</dt>
                        <dd>
                          {definition.buses
                            .map(
                              (bus) =>
                                `${bus.bus} / ${bus.protocol} · ${bus.min_address}–${bus.max_address}`,
                            )
                            .join(", ") || "No recognized bus"}
                        </dd>
                      </div>
                      <div>
                        <dt>SHA-256</dt>
                        <dd className="mono">{definition.sha256}</dd>
                      </div>
                    </dl>
                    <button
                      disabled={busy}
                      onClick={() => exportOriginal(definition, filename)}
                    >
                      <Download size={14} />
                      Export {slot === "current"
                        ? "current"
                        : "replacement"}{" "}
                      XML original
                    </button>
                  </>
                ) : (
                  <p>
                    {slot === "current"
                      ? "Open a native JCI Interface XML definition to inspect its points."
                      : "Open the newer definition when comparing revisions."}
                  </p>
                )}
              </div>
            </section>
          );
        })}
      </div>
      <p className="hardware-scope">
        Offline engineering only. Selections and migration reports do not modify
        CAF programs or field devices. Native controller object allocation,
        compilation and device acceptance remain unverified.
      </p>
      {current && (
        <>
          {!!current.alias_groups.length && (
            <div className="hardware-aliases">
              <b>Shared BACnet identities need an explicit choice</b>
              {current.alias_groups.map((group) => (
                <p key={`${group.object_type}:${group.instance}`}>
                  Type {group.object_type}, instance {group.instance}:{" "}
                  {group.point_ids.join(", ")}. Select one function from this
                  group.
                </p>
              ))}
            </div>
          )}
          {!!current.point_errors.length && (
            <details className="hardware-point-errors">
              <summary>
                Inspect {current.point_errors.length} unsupported point profiles
              </summary>
              {current.point_errors.map((point) => (
                <p key={point.id}>
                  <code>{point.id}</code>: {point.error}
                </p>
              ))}
            </details>
          )}
          <section
            className="card hardware-point-table"
            aria-label="Native hardware point catalog"
          >
            <div className="card-header">
              <h3>Native point catalog</h3>
              <input
                type="search"
                aria-label="Search native hardware points"
                placeholder="Search point, type or identity…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="hardware-selection-controls">
              <label>
                Application preset
                <select
                  aria-label="Native hardware preset"
                  disabled={busy}
                  value=""
                  onChange={(e) => {
                    if (e.target.value)
                      updateSelected(current.presets[e.target.value].points);
                  }}
                >
                  <option value="">Choose a declared preset…</option>
                  {Object.entries(current.presets).map(([id, preset]) => (
                    <option key={id} value={id}>
                      {preset.name || id}
                    </option>
                  ))}
                </select>
              </label>
              <b>{selected.length} selected points</b>
              <button
                disabled={busy || !selected.length}
                onClick={() => updateSelected([])}
              >
                Clear point selection
              </button>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Select</th>
                    <th>Point / native identity</th>
                    <th>Type / range / default</th>
                    <th>Native configuration</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((point) => (
                    <tr key={point.id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select hardware point ${point.id}`}
                          disabled={busy}
                          checked={selected.includes(point.id)}
                          onChange={(e) =>
                            updateSelected(
                              e.target.checked
                                ? [...selected, point.id]
                                : selected.filter((id) => id !== point.id),
                            )
                          }
                        />
                      </td>
                      <td>
                        <b>
                          {point.id} · {point.name}
                        </b>
                        <small>{point.description}</small>
                        <small className="mono">
                          {point.direction} · type {point.object_type}, instance{" "}
                          {point.instance}
                        </small>
                      </td>
                      <td>
                        <b>{point.value.type}</b>
                        <small>
                          Range: {point.value.parameters.min ?? "unspecified"}{" "}
                          to {point.value.parameters.max ?? "unspecified"}
                        </small>
                        <small>
                          Default:{" "}
                          {String(
                            point.value.parameters.default ?? "unspecified",
                          )}{" "}
                          · units{" "}
                          {point.value.parameters.units ?? "unspecified"}
                        </small>
                        {point.value.enum_reference && (
                          <small>
                            {point.value.enum_reference} ·{" "}
                            {point.value.enum_resolution}
                          </small>
                        )}
                      </td>
                      <td>
                        <small>
                          Update rate: {point.update_rate ?? "unspecified"}
                        </small>
                        <small>
                          Write strategy:{" "}
                          {point.write_strategy || "unspecified"}
                        </small>
                        {!!point.attributes.length && (
                          <details>
                            <summary>
                              {point.attributes.length} point attributes
                            </summary>
                            <pre>
                              {JSON.stringify(point.attributes, null, 2)}
                            </pre>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="hardware-actions">
              <button
                className="primary"
                disabled={busy || !selected.length}
                onClick={reviewSelection}
              >
                Review point selection
              </button>
              <button
                disabled={busy || !selected.length || !replacement}
                onClick={compare}
              >
                Compare selected point migration
              </button>
            </div>
          </section>
        </>
      )}
      {selection && (
        <section
          className="card hardware-selection-plan"
          aria-label="Hardware engineering selection"
        >
          <div className="card-header">
            <h3>Engineering selection · {selection.points.length} points</h3>
            <button
              onClick={() =>
                saveBlob(
                  new Blob([JSON.stringify(selection, null, 2)], {
                    type: "application/json",
                  }),
                  "hardware-engineering-plan.json",
                )
              }
            >
              <Download size={14} />
              Export engineering plan JSON
            </button>
          </div>
          <p>
            The selected native point identities are unambiguous. This plan
            cannot apply changes to a controller.
          </p>
          <pre>{JSON.stringify(selection, null, 2)}</pre>
        </section>
      )}
      {migration && (
        <section
          className="card hardware-migration"
          aria-label="Native hardware migration report"
        >
          <div className="card-header">
            <h3>
              Migration review · revision {migration.old_revision} to{" "}
              {migration.new_revision}
            </h3>
            <button
              onClick={() =>
                saveBlob(
                  new Blob([JSON.stringify(migration, null, 2)], {
                    type: "application/json",
                  }),
                  "hardware-migration-report.json",
                )
              }
            >
              <Download size={14} />
              Export migration report JSON
            </button>
          </div>
          <div className="hardware-migration-body">
            <p>
              {migration.changes.length} changed selected points ·{" "}
              {migration.blocking.length} blocking conditions. This report does
              not apply changes.
            </p>
            {migration.blocking.map((item, index) => (
              <div className="inline-error" key={index}>
                <b>{item.id}</b>: {item.reason}
              </div>
            ))}
            {Object.keys(migration.interface_changes).length > 0 && (
              <details open>
                <summary>Interface metadata changes</summary>
                <pre>
                  {JSON.stringify(migration.interface_changes, null, 2)}
                </pre>
              </details>
            )}
            {!migration.changes.length && !migration.blocking.length && (
              <p>Selected point profiles and bindings are unchanged.</p>
            )}
            {migration.changes.map((change) => (
              <details key={change.id} open>
                <summary>
                  {change.id}
                  {change.requires_rebinding ? " · rebinding required" : ""}
                  {change.requires_program_review
                    ? " · program review required"
                    : ""}
                </summary>
                <pre>{JSON.stringify(change.fields, null, 2)}</pre>
              </details>
            ))}
          </div>
        </section>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <p className="hardware-message" role="status">
          {message}
        </p>
      )}
    </div>
  );
}
