import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob } from "./api";

type Pool = {
  id: string;
  count: number;
  modes: string[];
  terminal_identifiers: null;
};
type ModelProfile = {
  model: string;
  external_point_count: number;
  pools: Pool[];
  source_ids: string[];
  conflicts: { code: string; meaning: string; scope: string }[];
  notes: string[];
  onboard_features: string[];
  count_sections: string;
};
type Catalog = {
  profile: string;
  catalog_sha256: string;
  modes: Record<string, string>;
  models: ModelProfile[];
  sources: Record<
    string,
    {
      document: string;
      revision: string;
      sha256: string;
      sections: string;
      artifact: string;
      url: string;
    }
  >;
  scope: string;
};
type Survey = {
  id: string;
  content_sha256: string;
  models: { host: "base" | "sa"; sa_mac?: number; model: string }[];
};
type Binding = {
  id: string;
  content_sha256: string;
  host: "base" | "sa";
  sa_mac?: number | null;
};
type Row = { id: string; mode: string; quantity: string; label: string };
type Review = {
  format: string;
  content_sha256: string;
  status: string;
  normalized_model: string;
  request: {
    model: string;
    catalog_sha256: string;
    demands: unknown[];
    survey_reference: unknown;
  };
  matched_channels: number;
  declared_channels: number;
  source_conflicts_present: boolean;
  survey_binding: null | {
    source_conflicts: unknown[];
    source_unresolved: unknown[];
  };
  demands: {
    id: string;
    label: string;
    mode: string;
    quantity: number;
    matched: number;
    unmatched: number;
    pool_count_witness: { pool: string; quantity: number }[];
  }[];
  scope: string;
};
const HASH = /^[a-f0-9]{64}$/;
const BASE = "/hardware-capacity";
function object(value: unknown): value is Record<string, any> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function catalogResult(value: unknown): Catalog {
  if (
    !object(value) ||
    value.profile !== "jci-physical-counts/1" ||
    !HASH.test(value.catalog_sha256) ||
    !Array.isArray(value.models) ||
    value.models.length === 0 ||
    value.models.length > 64 ||
    new Set(value.models.map((row: any) => row?.model)).size !==
      value.models.length ||
    !object(value.modes) ||
    !object(value.sources) ||
    Object.keys(value.modes).length > 16 ||
    Object.keys(value.sources).length > 16 ||
    typeof value.scope !== "string" ||
    !Object.entries(value.modes).every(
      ([key, label]) => /^[a-z-]+$/.test(key) && typeof label === "string",
    ) ||
    !value.models.every(
      (row: any) =>
        object(row) &&
        typeof row.model === "string" &&
        row.model.length <= 100 &&
        typeof row.count_sections === "string" &&
        Number.isInteger(row.external_point_count) &&
        Array.isArray(row.pools) &&
        row.pools.length <= 7 &&
        new Set(row.pools.map((p: any) => p?.id)).size === row.pools.length &&
        row.pools.reduce((n: number, p: any) => n + p?.count, 0) ===
          row.external_point_count &&
        row.pools.every(
          (p: any) =>
            object(p) &&
            typeof p.id === "string" &&
            Number.isInteger(p.count) &&
            p.count > 0 &&
            p.count <= 64 &&
            p.terminal_identifiers === null &&
            Array.isArray(p.modes) &&
            p.modes.length > 0 &&
            p.modes.length <= 10 &&
            p.modes.every((m: any) => typeof value.modes[m] === "string"),
        ) &&
        Array.isArray(row.source_ids) &&
        row.source_ids.length > 0 &&
        row.source_ids.length <= 8 &&
        row.source_ids.every(
          (id: any) =>
            object(value.sources[id]) &&
            HASH.test(value.sources[id].sha256) &&
            ["document", "revision", "sections", "artifact"].every(
              (key) => typeof value.sources[id][key] === "string",
            ) &&
            typeof value.sources[id].url === "string" &&
            value.sources[id].url.startsWith(
              "https://docs.johnsoncontrols.com/",
            ),
        ) &&
        Array.isArray(row.conflicts) &&
        row.conflicts.every(
          (c: any) =>
            object(c) &&
            typeof c.code === "string" &&
            typeof c.meaning === "string",
        ) &&
        Array.isArray(row.notes) &&
        row.notes.every((n: any) => typeof n === "string") &&
        Array.isArray(row.onboard_features) &&
        row.onboard_features.every((n: any) => typeof n === "string"),
    )
  ) {
    throw new Error(
      "Capacity catalog is malformed or uses an unsupported profile. Current draft retained.",
    );
  }
  return value as Catalog;
}
function sameJson(a: unknown, b: unknown): boolean {
  const order = (v: any): any =>
    Array.isArray(v)
      ? v.map(order)
      : object(v)
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, order(v[k])]),
          )
        : v;
  return JSON.stringify(order(a)) === JSON.stringify(order(b));
}
function reviewResult(value: unknown, request: any): Review {
  if (
    !object(value) ||
    value.format !== "bms.jci-physical-capacity-review/1" ||
    !HASH.test(value.content_sha256) ||
    value.catalog_sha256 !== request.catalog_sha256 ||
    value.normalized_model !== request.model.trim().toUpperCase() ||
    !object(value.request) ||
    !sameJson(value.request.demands, request.demands) ||
    value.request.model !== request.model ||
    value.request.catalog_sha256 !== request.catalog_sha256 ||
    !sameJson(
      value.request.survey_reference,
      request.survey_reference ?? null,
    ) ||
    ![
      "unknown-model",
      "no-demand-declared",
      "count-mode-fit",
      "count-mode-shortfall",
    ].includes(value.status) ||
    typeof value.scope !== "string" ||
    typeof value.source_conflicts_present !== "boolean" ||
    (value.survey_binding !== null &&
      (!object(value.survey_binding) ||
        !Array.isArray(value.survey_binding.source_conflicts) ||
        !Array.isArray(value.survey_binding.source_unresolved))) ||
    !Number.isInteger(value.matched_channels) ||
    !Number.isInteger(value.declared_channels) ||
    !Array.isArray(value.demands) ||
    value.demands.length !== request.demands.length ||
    !value.demands.every(
      (r: any, i: number) =>
        object(r) &&
        r.id === request.demands[i].id &&
        r.mode === request.demands[i].mode &&
        r.label === request.demands[i].label &&
        r.quantity === request.demands[i].quantity &&
        Number.isInteger(r.matched) &&
        Number.isInteger(r.unmatched) &&
        r.matched >= 0 &&
        r.unmatched >= 0 &&
        r.matched + r.unmatched === r.quantity &&
        Array.isArray(r.pool_count_witness) &&
        r.pool_count_witness.every(
          (p: any) =>
            object(p) &&
            typeof p.pool === "string" &&
            Number.isInteger(p.quantity) &&
            p.quantity > 0,
        ),
    ) ||
    value.installed_verified !== false ||
    value.electrical_compatibility_verified !== false ||
    value.power_verified !== false ||
    value.field_queries !== false ||
    value.controller_writes !== false ||
    value.native_allocation_verified !== false ||
    value.terminal_assignment_verified !== false
  ) {
    throw new Error(
      "Capacity review is malformed or belongs to another source/draft. No export adopted.",
    );
  }
  return value as Review;
}

export function PhysicalCapacityPanel({
  survey = null,
}: {
  survey?: Survey | null;
}) {
  const [opened, setOpened] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [model, setModel] = useState("FX-PCX3721-0");
  const [rows, setRows] = useState<Row[]>([
    {
      id: "demand-1",
      mode: "input-voltage",
      quantity: "1",
      label: "Declared signal",
    },
  ]);
  const [host, setHost] = useState("base");
  const [binding, setBinding] = useState<Binding | null>(null);
  const [result, setResult] = useState<{
    key: string;
    data: Review;
    blob: Blob;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const epoch = useRef(0);
  const nextId = useRef(2);
  const sourceKey = survey ? `${survey.id}:${survey.content_sha256}` : "";
  const key = JSON.stringify({
    sourceKey,
    catalog: catalog?.catalog_sha256,
    model,
    rows,
    binding,
  });
  const live = useRef(key);
  live.current = key;
  const bound =
    binding && `${binding.id}:${binding.content_sha256}` === sourceKey
      ? binding
      : null;
  const displayed = result?.key === key ? result : null;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    setBinding(null);
    setResult(null);
    setBusy(false);
  }, [sourceKey]);
  function change(action: () => void) {
    epoch.current++;
    setResult(null);
    setError("");
    setBusy(false);
    action();
  }
  async function load() {
    const ticket = ++epoch.current;
    setOpened(true);
    setBusy(true);
    setError("");
    try {
      const value = catalogResult(await api(BASE + "/catalog"));
      if (!alive.current || epoch.current !== ticket) return;
      setCatalog(value);
      setResult(null);
    } catch (e) {
      if (alive.current && epoch.current === ticket) setError(String(e));
    } finally {
      if (alive.current && epoch.current === ticket) setBusy(false);
    }
  }
  function useHost() {
    const selected = survey?.models.find(
      (item) => (item.host === "base" ? "base" : `sa:${item.sa_mac}`) === host,
    );
    if (!survey || !selected) {
      setError("Choose a survey host with explicit model evidence.");
      return;
    }
    change(() => {
      setModel(selected.model);
      setBinding({
        id: survey.id,
        content_sha256: survey.content_sha256,
        host: selected.host,
        sa_mac: selected.host === "sa" ? selected.sa_mac : null,
      });
    });
  }
  async function review() {
    if (!catalog) return;
    let request;
    try {
      request = {
        catalog_sha256: catalog.catalog_sha256,
        model,
        demands: rows.map((row) => {
          if (!/^(?:[1-9]|[1-5][0-9]|6[0-4])$/.test(row.quantity))
            throw new Error(
              "Each declared quantity must be an integer from 1 to 64.",
            );
          return { ...row, quantity: Number(row.quantity) };
        }),
        survey_reference: bound,
      };
    } catch (e) {
      setError(String(e));
      return;
    }
    const ticket = ++epoch.current,
      ownedKey = key;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await apiJsonDocument(BASE + "/review", request);
      const value = reviewResult(response.data, request);
      if (
        !alive.current ||
        epoch.current !== ticket ||
        live.current !== ownedKey
      )
        return;
      setResult({ key: ownedKey, data: value, blob: response.blob });
    } catch (e) {
      if (
        alive.current &&
        epoch.current === ticket &&
        live.current === ownedKey
      )
        setError(String(e));
    } finally {
      if (alive.current && epoch.current === ticket) setBusy(false);
    }
  }
  const profile = catalog?.models.find(
    (row) => row.model === model.trim().toUpperCase(),
  );
  return (
    <section aria-label="Physical capacity matrix" className="hardware-result">
      <h3>Exact physical capacity matrix</h3>
      <p className="help-text">
        Offline model facts and declared signal-family counts. Counts do not
        identify terminals, spare wiring, electrical suitability or native CAF
        allocation.
      </p>
      <button onClick={load} disabled={busy}>
        {catalog ? "Reload capacity catalog" : "Open capacity catalog"}
      </button>
      {error && <p role="alert">{error}</p>}
      {opened && catalog && (
        <>
          <p>
            {catalog.models.length} exact model profiles · catalog SHA-256{" "}
            {catalog.catalog_sha256}
          </p>
          <label>
            Documented capacity model
            <select
              aria-label="Documented capacity model"
              value={profile?.model || ""}
              onChange={(e) =>
                change(() => {
                  setModel(e.target.value);
                  setBinding(null);
                })
              }
            >
              <option value="">Exact model not in catalog</option>
              {catalog.models.map((row) => (
                <option key={row.model} value={row.model}>
                  {row.model}
                </option>
              ))}
            </select>
          </label>
          <label>
            Exact capacity model
            <input
              aria-label="Exact capacity model"
              value={model}
              maxLength={100}
              onChange={(e) =>
                change(() => {
                  setModel(e.target.value);
                  setBinding(null);
                })
              }
            />
          </label>
          {survey && (
            <fieldset>
              <legend>Optional stored survey evidence</legend>
              <p>
                Report {survey.id} · original SHA-256 {survey.content_sha256}
              </p>
              <label>
                Capacity survey host
                <select
                  aria-label="Capacity survey host"
                  value={host}
                  onChange={(e) =>
                    change(() => {
                      setHost(e.target.value);
                      setBinding(null);
                    })
                  }
                >
                  <option value="">Choose explicit host</option>
                  {survey.models.map((item) => {
                    const id =
                      item.host === "base" ? "base" : `sa:${item.sa_mac}`;
                    return (
                      <option key={id} value={id}>
                        {item.host === "base" ? "Base" : `SA ${item.sa_mac}`} ·{" "}
                        {item.model}
                      </option>
                    );
                  })}
                </select>
              </label>
              <button onClick={useHost} disabled={busy}>
                Use selected survey model
              </button>
              {bound && (
                <p>
                  Bound to original survey {bound.id} ·{" "}
                  {bound.host === "base" ? "base" : `SA ${bound.sa_mac}`}.
                  Configured evidence does not verify a physical label or spare
                  terminal.
                </p>
              )}
              {bound && (
                <button onClick={() => change(() => setBinding(null))}>
                  Use offline model declaration
                </button>
              )}
            </fieldset>
          )}
          {profile ? (
            <div aria-label="Documented physical pools">
              <h4>
                {profile.model}: {profile.external_point_count} external
                physical channels
              </h4>
              <table aria-label="Physical resource pools">
                <thead>
                  <tr>
                    <th>Physical pool</th>
                    <th>Count</th>
                    <th>Alternative signal families</th>
                    <th>Terminal numbering</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.pools.map((pool) => (
                    <tr key={pool.id}>
                      <td>{pool.id}</td>
                      <td>{pool.count}</td>
                      <td>
                        {pool.modes.map((m) => catalog.modes[m]).join("; ")}
                      </td>
                      <td>Not established by this count profile</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>
                Alternative modes share the same physical pool. Mode counts
                cannot be added together.
              </p>
              {profile.onboard_features.length > 0 && (
                <p>
                  Onboard features: {profile.onboard_features.join(", ")}. These
                  are not spare external I/O.
                </p>
              )}
              {profile.notes.map((note, i) => (
                <p key={i}>{note}</p>
              ))}
              {profile.conflicts.length > 0 && (
                <div role="note">
                  <strong>
                    Source conflicts retained; affected ratings remain
                    unresolved.
                  </strong>
                  {profile.conflicts.map((conflict) => (
                    <p key={conflict.code}>
                      {conflict.code}: {conflict.meaning}
                    </p>
                  ))}
                </div>
              )}
              <details>
                <summary>Capacity primary sources and hashes</summary>
                <p>{profile.count_sections}</p>
                {profile.source_ids.map((id) => {
                  const source = catalog.sources[id];
                  return (
                    <p key={id}>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {source.document} · {source.revision}
                      </a>
                      <br />
                      {source.sections}
                      <br />
                      {source.artifact} · SHA-256 {source.sha256}
                    </p>
                  );
                })}
              </details>
            </div>
          ) : (
            <p role="status">
              Unknown exact model. No suffix, brand or housing inference;
              declared channels remain unmatched.
            </p>
          )}
          <fieldset>
            <legend>Explicit declared signal demand</legend>
            <p>
              This uses whole-device counts. Existing occupied points are not
              subtracted.
            </p>
            {rows.map((row, i) => (
              <div key={row.id} className="hardware-form-grid">
                <label>
                  Demand label {i + 1}
                  <input
                    aria-label={`Capacity demand label ${i + 1}`}
                    value={row.label}
                    maxLength={120}
                    onChange={(e) =>
                      change(() =>
                        setRows(
                          rows.map((r) =>
                            r.id === row.id
                              ? { ...r, label: e.target.value }
                              : r,
                          ),
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Signal family {i + 1}
                  <select
                    aria-label={`Capacity signal family ${i + 1}`}
                    value={row.mode}
                    onChange={(e) =>
                      change(() =>
                        setRows(
                          rows.map((r) =>
                            r.id === row.id
                              ? { ...r, mode: e.target.value }
                              : r,
                          ),
                        ),
                      )
                    }
                  >
                    {Object.entries(catalog.modes).map(([id, label]) => (
                      <option key={id} value={id}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Quantity {i + 1}
                  <input
                    aria-label={`Capacity quantity ${i + 1}`}
                    inputMode="numeric"
                    value={row.quantity}
                    onChange={(e) =>
                      change(() =>
                        setRows(
                          rows.map((r) =>
                            r.id === row.id
                              ? { ...r, quantity: e.target.value }
                              : r,
                          ),
                        ),
                      )
                    }
                  />
                </label>
                <button
                  onClick={() =>
                    change(() => setRows(rows.filter((r) => r.id !== row.id)))
                  }
                >
                  Remove capacity demand {i + 1}
                </button>
              </div>
            ))}
            <button
              disabled={rows.length >= 32}
              onClick={() =>
                change(() =>
                  setRows([
                    ...rows,
                    {
                      id: `demand-${nextId.current++}`,
                      mode: "input-voltage",
                      quantity: "1",
                      label: "Declared signal",
                    },
                  ]),
                )
              }
            >
              Add capacity demand
            </button>
          </fieldset>
          <button onClick={review} disabled={busy}>
            Review physical count fit
          </button>
          {displayed && (
            <section aria-label="Capacity count review">
              <h4>Count review: {displayed.data.status}</h4>
              <p>
                {displayed.data.matched_channels} /{" "}
                {displayed.data.declared_channels} declared channels matched by
                signal family.
              </p>
              {displayed.data.source_conflicts_present && (
                <p>
                  Source conflicts remain unresolved even when channel counts
                  fit.
                </p>
              )}
              {displayed.data.survey_binding && (
                <p>
                  Stored survey corroboration:{" "}
                  {displayed.data.survey_binding.source_conflicts.length}{" "}
                  conflicts,{" "}
                  {displayed.data.survey_binding.source_unresolved.length}{" "}
                  unresolved checks. Count fit does not resolve them.
                </p>
              )}
              <table aria-label="Capacity demand results">
                <thead>
                  <tr>
                    <th>Demand</th>
                    <th>Matched</th>
                    <th>Unmatched</th>
                    <th>Pool-count witness, no terminal allocation</th>
                  </tr>
                </thead>
                <tbody>
                  {displayed.data.demands.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.label} · {catalog.modes[row.mode]}
                      </td>
                      <td>{row.matched}</td>
                      <td>{row.unmatched}</td>
                      <td>
                        {row.pool_count_witness
                          .map((part) => `${part.pool}: ${part.quantity}`)
                          .join(", ") || "none"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>{displayed.data.scope}</p>
              <p>Review SHA-256 {displayed.data.content_sha256}</p>
              <button
                onClick={() => {
                  if (alive.current && live.current === displayed.key)
                    saveBlob(
                      displayed.blob,
                      `physical-capacity-${displayed.data.content_sha256}.json`,
                    );
                }}
              >
                Export original capacity review JSON
              </button>
            </section>
          )}
        </>
      )}
    </section>
  );
}
