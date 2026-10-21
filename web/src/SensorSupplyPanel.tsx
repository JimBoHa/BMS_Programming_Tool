import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";
import "./sensor-supply.css";

type AnyRecord = Record<string, any>;
type Domain = "ac" | "dc";
const blankDemand = () => ({ amount: null, unit: "mA", basis: "unknown" });
const blankDomain = () => ({
  min_v: 24,
  max_v: 24,
  steady: blankDemand(),
  startup: blankDemand(),
});
const blankRail = () => ({
  id: crypto.randomUUID(),
  name: "External supply",
  unit_id: "Supply 1",
  profile_id: null,
  profile_sha256: null,
  spec: {
    domain: "dc",
    nominal_v: 24,
    current_limit_ma: null,
    source_output: true,
    terminals: [{ id: "A", current_limit_ma: null }],
  },
  operating_min_v: null,
  operating_max_v: null,
  loads_complete: false,
  notes: "",
});
const blankLoad = () => ({
  id: crypto.randomUUID(),
  name: "Sensor or existing load",
  rail_id: "",
  terminal_id: "",
  quantity: 1,
  profile_id: null,
  profile_sha256: null,
  spec: { dc: blankDomain(), ac: null },
  notes: "",
});
const optional = (value: string) => (value.trim() ? Number(value) : null);
const show = (value: unknown) =>
  value == null
    ? "Unknown"
    : typeof value === "number"
      ? Number(value.toPrecision(8)).toString()
      : String(value);

export function SensorSupplyPanel({
  reference,
}: {
  reference?: { id: string; content_sha256: string } | null;
}) {
  const [catalog, setCatalog] = useState<AnyRecord | null>(null);
  const [template, setTemplate] = useState<AnyRecord | null>(null);
  const [draft, setDraft] = useState<AnyRecord | null>(null);
  const [saved, setSaved] = useState<AnyRecord[]>([]);
  const [selected, setSelected] = useState("");
  const [identity, setIdentity] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [savedSignature, setSavedSignature] = useState("");
  const [rail, setRail] = useState<AnyRecord>(blankRail);
  const [load, setLoad] = useState<AnyRecord>(blankLoad);
  const [editingRail, setEditingRail] = useState(false);
  const [editingLoad, setEditingLoad] = useState(false);
  const [analysis, setAnalysis] = useState<AnyRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const importer = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLElement>(null);
  const mounted = useRef(false);
  const signature = JSON.stringify(draft);
  const liveSignature = useRef(signature);
  liveSignature.current = signature;
  const dirty = !!draft && signature !== savedSignature;

  useEffect(() => {
    mounted.current = true;
    setBusy(true);
    Promise.all([api("/sensor-supply/catalog"), api("/sensor-supply/plans")])
      .then(([data, plans]) => {
        if (!mounted.current) return;
        setCatalog(data.catalog);
        setTemplate(data.template);
        setDraft(data.template);
        setSavedSignature(JSON.stringify(data.template));
        setSaved(plans);
      })
      .catch((e) => {
        if (mounted.current) setError(String(e.message || e));
      })
      .finally(() => {
        if (mounted.current) setBusy(false);
      });
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function update(next: AnyRecord) {
    setDraft(next);
    setAnalysis(null);
    setError("");
    setMessage("");
  }
  function discard() {
    return !dirty || window.confirm("Discard unsaved supply-plan changes?");
  }
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function refresh() {
    const rows = await api("/sensor-supply/plans");
    if (mounted.current) setSaved(rows);
  }
  function newPlan() {
    if (!template || busy || !discard()) return;
    update(structuredClone(template));
    setSavedSignature(JSON.stringify(template));
    setIdentity(null);
    setRevision(0);
    setSelected("");
    setRail(blankRail());
    setLoad(blankLoad());
    setEditingRail(false);
    setEditingLoad(false);
  }
  async function save(copy = false) {
    if (!draft) return;
    const snapshot = draft;
    await perform(async () => {
      const result = await api("/sensor-supply/save", {
        plan: snapshot,
        id: copy ? null : identity,
        expected_revision: copy ? 0 : revision,
      });
      if (!mounted.current) return;
      setDraft(result.plan);
      setSavedSignature(JSON.stringify(result.plan));
      setIdentity(result.id);
      setRevision(result.revision);
      setSelected(result.id);
      await refresh();
      if (mounted.current)
        setMessage(`Saved supply plan locally, revision ${result.revision}.`);
    });
  }
  async function reopen() {
    if (!selected || !discard()) return;
    await perform(async () => {
      const result = await api(`/sensor-supply/plans/${selected}`);
      if (!mounted.current) return;
      update(result.plan);
      setSavedSignature(JSON.stringify(result.plan));
      setIdentity(result.id);
      setRevision(result.revision);
      setRail(blankRail());
      setLoad(blankLoad());
      setEditingRail(false);
      setEditingLoad(false);
      setMessage(
        "Saved plan reopened with exact profile and survey guards. No field reads started.",
      );
    });
  }
  async function removeSaved() {
    const item = saved.find((row) => row.id === selected);
    if (
      !item ||
      !window.confirm(
        "Delete this selected saved supply plan? Controller settings and the current draft are unchanged.",
      )
    )
      return;
    await perform(async () => {
      await api(
        `/sensor-supply/plans/${item.id}`,
        { expected_revision: item.revision },
        "DELETE",
      );
      if (!mounted.current) return;
      if (identity === item.id) {
        setIdentity(null);
        setRevision(0);
        setSavedSignature("");
      }
      setSelected("");
      await refresh();
      if (mounted.current)
        setMessage("Saved supply plan deleted. Draft retained.");
    });
  }
  async function importPlan(file?: File) {
    if (!file || !discard()) return;
    await perform(async () => {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Supply plan exceeds 2 MiB.");
      const result = await api("/sensor-supply/validate", {
        plan: JSON.parse(await file.text()),
      });
      if (!mounted.current) return;
      update(result.plan);
      setSavedSignature("");
      setIdentity(null);
      setRevision(0);
      setSelected("");
      setRail(blankRail());
      setLoad(blankLoad());
      setEditingRail(false);
      setEditingLoad(false);
      setMessage(
        "Imported source-checked supply plan. Save locally to retain it after restart.",
      );
    });
  }
  async function evaluate(exportKind?: "plan" | "report") {
    if (!draft) return;
    const snapshot = draft,
      expected = signature;
    await perform(async () => {
      const result = await api(
        exportKind === "plan"
          ? "/sensor-supply/validate"
          : "/sensor-supply/evaluate",
        { plan: snapshot },
      );
      if (!mounted.current || expected !== liveSignature.current) return;
      if (exportKind) {
        if (
          !panel.current ||
          panel.current.closest("details:not([open])") ||
          !panel.current.getClientRects().length
        )
          return;
        saveBlob(
          new Blob(
            [
              JSON.stringify(
                exportKind === "plan" ? result.plan : result,
                null,
                2,
              ) + "\n",
            ],
            { type: "application/json" },
          ),
          `sensor-supply-${exportKind}.json`,
        );
        setMessage(
          "Validated local JSON download requested. This plan does not configure wiring or a controller.",
        );
      } else {
        setAnalysis(result);
        setMessage(
          `Budget status: ${result.status}. Engineering review remains required.`,
        );
      }
    });
  }
  function selectRailProfile(id: string) {
    if (!id) {
      setRail({ ...rail, profile_id: null, profile_sha256: null });
      return;
    }
    const profile = catalog!.rails.find((row: AnyRecord) => row.id === id);
    setRail({
      ...rail,
      name: profile.name,
      profile_id: id,
      profile_sha256: profile.profile_sha256,
      spec: structuredClone(profile.spec),
      operating_min_v: null,
      operating_max_v: null,
    });
  }
  function selectLoadProfile(id: string) {
    if (!id) {
      setLoad({ ...load, profile_id: null, profile_sha256: null });
      return;
    }
    const profile = catalog!.loads.find((row: AnyRecord) => row.id === id);
    setLoad({
      ...load,
      name: profile.name,
      profile_id: id,
      profile_sha256: profile.profile_sha256,
      spec: structuredClone(profile.spec),
    });
  }
  function commitRail() {
    if (!draft || busy) return;
    if (!editingRail && draft.rails.length >= 32) {
      setError("At most 32 rails per plan.");
      return;
    }
    update({
      ...draft,
      rails: editingRail
        ? draft.rails.map((row: AnyRecord) =>
            row.id === rail.id ? structuredClone(rail) : row,
          )
        : [...draft.rails, structuredClone(rail)],
    });
    setLoad((prior) => ({
      ...prior,
      rail_id: rail.id,
      terminal_id: rail.spec.terminals[0]?.id || "",
    }));
    setRail(blankRail());
    setEditingRail(false);
  }
  function commitLoad() {
    if (!draft || busy) return;
    if (!editingLoad && draft.loads.length >= 256) {
      setError("At most 256 load records per plan.");
      return;
    }
    update({
      ...draft,
      loads: editingLoad
        ? draft.loads.map((row: AnyRecord) =>
            row.id === load.id ? structuredClone(load) : row,
          )
        : [...draft.loads, structuredClone(load)],
    });
    setLoad({
      ...blankLoad(),
      rail_id: load.rail_id,
      terminal_id: load.terminal_id,
    });
    setEditingLoad(false);
  }
  function domainChange(domain: Domain, field: string, value: unknown) {
    setLoad({
      ...load,
      spec: {
        ...load.spec,
        [domain]: { ...load.spec[domain], [field]: value },
      },
    });
  }
  function demandChange(
    domain: Domain,
    phase: "steady" | "startup",
    field: string,
    value: unknown,
  ) {
    const next = { ...load.spec[domain][phase], [field]: value };
    if (field === "basis" && value === "unknown") next.amount = null;
    if (field === "amount" && value === null) next.basis = "unknown";
    domainChange(domain, phase, next);
  }
  const selectedRail = draft?.rails.find(
    (row: AnyRecord) => row.id === load.rail_id,
  );
  const selectedSaved = saved.find((row) => row.id === selected);

  return (
    <section
      ref={panel}
      className="sensor-supply"
      aria-label="Sensor supply budgeting"
    >
      <h3>Sensor supply budgeting</h3>
      <p>
        Review shared and per-terminal current budgets, AC/DC type and operating
        voltage. This local plan does not verify installed models, wiring, COM,
        jumpers or native configuration.
      </p>
      <p>
        Controller auxiliary +15 V, SA bus power and an external 24 VAC supply
        are separate. One combined temperature/humidity sensor is one powered
        load, even when it has two signal outputs.
      </p>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {!draft || !catalog ? (
        <p>Loading guarded supply profiles…</p>
      ) : (
        <>
          <div className="button-row">
            <button disabled={busy} onClick={newPlan}>
              New supply plan
            </button>
            <select
              aria-label="Saved supply plans"
              disabled={busy}
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">Choose saved plan</option>
              {saved.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} · revision {row.revision} · {row.id.slice(0, 8)}
                  {row.available === false ? " · unavailable" : ""}
                </option>
              ))}
            </select>
            <button
              disabled={busy || !selected || selectedSaved?.available === false}
              onClick={() => void reopen()}
            >
              Reopen supply plan
            </button>
            <button
              disabled={busy || !selected}
              onClick={() => void removeSaved()}
            >
              Delete selected supply plan
            </button>
            <button disabled={busy} onClick={() => void perform(refresh)}>
              Refresh saved supply plans
            </button>
          </div>
          {selectedSaved?.error && <p>{selectedSaved.error}</p>}
          <label>
            Plan name
            <input
              aria-label="Supply plan name"
              value={draft.name}
              maxLength={120}
              disabled={busy}
              onChange={(e) => update({ ...draft, name: e.target.value })}
            />
          </label>
          <p>
            {identity ? `Saved revision ${revision}` : "New local plan"}
            {dirty ? " · unsaved changes" : ""}
          </p>
          <div className="button-row">
            <button
              disabled={busy || !reference?.content_sha256}
              onClick={() => update({ ...draft, source_report: reference })}
            >
              Bind current hardware survey
            </button>
            <button
              disabled={busy || !draft.source_report}
              onClick={() => update({ ...draft, source_report: null })}
            >
              Clear survey binding
            </button>
          </div>
          <p>
            Survey binding:{" "}
            {draft.source_report ? (
              <code>
                {draft.source_report.id} · SHA-256{" "}
                {draft.source_report.content_sha256}
              </code>
            ) : (
              "None; standalone user-declared engineering plan."
            )}
          </p>
          <fieldset disabled={busy}>
            <legend>
              {editingRail ? "Edit supply rail" : "Add supply rail"}
            </legend>
            <div className="supply-grid">
              <label>
                Rail source
                <select
                  aria-label="Supply rail profile"
                  value={rail.profile_id || ""}
                  onChange={(e) => selectRailProfile(e.target.value)}
                >
                  <option value="">User-declared external/custom supply</option>
                  {catalog.rails.map((row: AnyRecord) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Rail name
                <input
                  aria-label="Supply rail name"
                  value={rail.name}
                  onChange={(e) => setRail({ ...rail, name: e.target.value })}
                />
              </label>
              <label>
                Physical supply instance
                <input
                  aria-label="Supply physical instance"
                  value={rail.unit_id}
                  onChange={(e) =>
                    setRail({ ...rail, unit_id: e.target.value })
                  }
                />
              </label>
              <label>
                Power type
                <select
                  aria-label="Supply power type"
                  disabled={!!rail.profile_id}
                  value={rail.spec.domain}
                  onChange={(e) =>
                    setRail({
                      ...rail,
                      spec: { ...rail.spec, domain: e.target.value },
                    })
                  }
                >
                  <option value="dc">DC</option>
                  <option value="ac">AC RMS</option>
                </select>
              </label>
              <label>
                Nominal voltage
                <input
                  aria-label="Supply nominal voltage"
                  type="number"
                  step="any"
                  value={rail.spec.nominal_v}
                  disabled={!!rail.profile_id}
                  onChange={(e) =>
                    setRail({
                      ...rail,
                      spec: { ...rail.spec, nominal_v: Number(e.target.value) },
                    })
                  }
                />
              </label>
              <label>
                Shared current limit, mA
                <input
                  aria-label="Supply shared current limit"
                  type="number"
                  step="any"
                  value={rail.spec.current_limit_ma ?? ""}
                  disabled={!!rail.profile_id}
                  placeholder="Unknown"
                  onChange={(e) =>
                    setRail({
                      ...rail,
                      spec: {
                        ...rail.spec,
                        current_limit_ma: optional(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label>
                User-declared minimum operating volts
                <input
                  aria-label="Supply operating minimum"
                  type="number"
                  step="any"
                  value={rail.operating_min_v ?? ""}
                  placeholder="Unknown tolerance"
                  onChange={(e) =>
                    setRail({
                      ...rail,
                      operating_min_v: optional(e.target.value),
                    })
                  }
                />
              </label>
              <label>
                User-declared maximum operating volts
                <input
                  aria-label="Supply operating maximum"
                  type="number"
                  step="any"
                  value={rail.operating_max_v ?? ""}
                  placeholder="Unknown tolerance"
                  onChange={(e) =>
                    setRail({
                      ...rail,
                      operating_max_v: optional(e.target.value),
                    })
                  }
                />
              </label>
            </div>
            <p>
              Use one record per physical shared supply. Documented profiles
              lock published ratings. Operating bounds are user declarations,
              not manufacturer verification. Blank limits remain unknown.
            </p>
            {rail.spec.terminals.map((terminal: AnyRecord, index: number) => (
              <div className="supply-grid" key={index}>
                <label>
                  Terminal identifier
                  <input
                    aria-label={`Supply terminal ${index + 1}`}
                    disabled={!!rail.profile_id}
                    value={terminal.id}
                    onChange={(e) =>
                      setRail({
                        ...rail,
                        spec: {
                          ...rail.spec,
                          terminals: rail.spec.terminals.map(
                            (row: AnyRecord, i: number) =>
                              i === index
                                ? { ...row, id: e.target.value }
                                : row,
                          ),
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Separate terminal limit, mA
                  <input
                    aria-label={`Supply terminal limit ${index + 1}`}
                    type="number"
                    step="any"
                    disabled={!!rail.profile_id}
                    value={terminal.current_limit_ma ?? ""}
                    placeholder="No separate rating"
                    onChange={(e) =>
                      setRail({
                        ...rail,
                        spec: {
                          ...rail.spec,
                          terminals: rail.spec.terminals.map(
                            (row: AnyRecord, i: number) =>
                              i === index
                                ? {
                                    ...row,
                                    current_limit_ma: optional(e.target.value),
                                  }
                                : row,
                          ),
                        },
                      })
                    }
                  />
                </label>
                {!rail.profile_id && rail.spec.terminals.length > 1 && (
                  <button
                    onClick={() =>
                      setRail({
                        ...rail,
                        spec: {
                          ...rail.spec,
                          terminals: rail.spec.terminals.filter(
                            (_: unknown, i: number) => i !== index,
                          ),
                        },
                      })
                    }
                  >
                    Remove terminal
                  </button>
                )}
              </div>
            ))}
            <div className="button-row">
              <button
                disabled={!!rail.profile_id || rail.spec.terminals.length >= 32}
                onClick={() =>
                  setRail({
                    ...rail,
                    spec: {
                      ...rail.spec,
                      terminals: [
                        ...rail.spec.terminals,
                        {
                          id: `T${rail.spec.terminals.length + 1}`,
                          current_limit_ma: null,
                        },
                      ],
                    },
                  })
                }
              >
                Add shared terminal
              </button>
              <button onClick={commitRail}>
                {editingRail ? "Update supply rail" : "Add supply rail"}
              </button>
              <button
                onClick={() => {
                  setRail(blankRail());
                  setEditingRail(false);
                }}
              >
                Reset rail form
              </button>
            </div>
            <label>
              <input
                type="checkbox"
                aria-label="Supply all loads included"
                checked={rail.loads_complete}
                onChange={(e) =>
                  setRail({ ...rail, loads_complete: e.target.checked })
                }
              />
              All existing and planned loads on this physical supply are
              included
            </label>
            <label>
              Rail evidence/notes
              <textarea
                aria-label="Supply rail notes"
                value={rail.notes}
                maxLength={2000}
                onChange={(e) => setRail({ ...rail, notes: e.target.value })}
              />
            </label>
            {rail.profile_id && (
              <details>
                <summary>Documented rail evidence</summary>
                <pre>
                  {JSON.stringify(
                    catalog.rails.find(
                      (row: AnyRecord) => row.id === rail.profile_id,
                    ),
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
          </fieldset>
          <div className="supply-table">
            <table aria-label="Supply rail records">
              <thead>
                <tr>
                  <th>Physical source</th>
                  <th>Type / nominal</th>
                  <th>Shared limit</th>
                  <th>Provenance / coverage</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {draft.rails.map((row: AnyRecord) => (
                  <tr key={row.id}>
                    <td>
                      {row.name}
                      <small>{row.unit_id}</small>
                    </td>
                    <td>
                      {row.spec.domain.toUpperCase()} {row.spec.nominal_v} V
                    </td>
                    <td>{show(row.spec.current_limit_ma)} mA</td>
                    <td>
                      {row.profile_id
                        ? "Documented profile; installed model unverified"
                        : "User-declared supply"}
                      <small>
                        {row.loads_complete
                          ? "All loads declared included"
                          : "Existing load coverage unknown"}
                      </small>
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() => {
                          setRail(structuredClone(row));
                          setEditingRail(true);
                        }}
                      >
                        Edit rail
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              "Remove this rail and all assigned load records from the local plan?",
                            )
                          )
                            update({
                              ...draft,
                              rails: draft.rails.filter(
                                (item: AnyRecord) => item.id !== row.id,
                              ),
                              loads: draft.loads.filter(
                                (item: AnyRecord) => item.rail_id !== row.id,
                              ),
                            });
                        }}
                      >
                        Remove rail
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <fieldset disabled={busy || !draft.rails.length}>
            <legend>
              {editingLoad ? "Edit sensor/load" : "Add sensor or existing load"}
            </legend>
            <div className="supply-grid">
              <label>
                Load source
                <select
                  aria-label="Supply load profile"
                  value={load.profile_id || ""}
                  onChange={(e) => selectLoadProfile(e.target.value)}
                >
                  <option value="">User-declared custom load</option>
                  {catalog.loads.map((row: AnyRecord) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Load name
                <input
                  aria-label="Supply load name"
                  value={load.name}
                  onChange={(e) => setLoad({ ...load, name: e.target.value })}
                />
              </label>
              <label>
                Rail
                <select
                  aria-label="Supply load rail"
                  value={load.rail_id}
                  onChange={(e) => {
                    const next = draft.rails.find(
                      (row: AnyRecord) => row.id === e.target.value,
                    );
                    setLoad({
                      ...load,
                      rail_id: e.target.value,
                      terminal_id: next?.spec.terminals[0]?.id || "",
                    });
                  }}
                >
                  <option value="">Choose rail</option>
                  {draft.rails.map((row: AnyRecord) => (
                    <option key={row.id} value={row.id}>
                      {row.name} · {row.unit_id}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Terminal
                <select
                  aria-label="Supply load terminal"
                  value={load.terminal_id}
                  onChange={(e) =>
                    setLoad({ ...load, terminal_id: e.target.value })
                  }
                >
                  <option value="">Choose terminal</option>
                  {selectedRail?.spec.terminals.map((row: AnyRecord) => (
                    <option key={row.id}>{row.id}</option>
                  ))}
                </select>
              </label>
              <label>
                Physical sensor/load quantity
                <input
                  aria-label="Supply load quantity"
                  type="number"
                  min={1}
                  max={100}
                  value={load.quantity}
                  onChange={(e) =>
                    setLoad({ ...load, quantity: Number(e.target.value) })
                  }
                />
              </label>
            </div>
            {(["dc", "ac"] as Domain[]).map((domain) => (
              <div key={domain} className="supply-domain">
                <label>
                  <input
                    type="checkbox"
                    aria-label={`Load supports ${domain.toUpperCase()}`}
                    checked={!!load.spec[domain]}
                    disabled={!!load.profile_id}
                    onChange={(e) =>
                      setLoad({
                        ...load,
                        spec: {
                          ...load.spec,
                          [domain]: e.target.checked ? blankDomain() : null,
                        },
                      })
                    }
                  />
                  Supports {domain.toUpperCase()}
                  {domain === "ac" ? " RMS" : ""}
                </label>
                {load.spec[domain] && (
                  <div className="supply-grid">
                    <label>
                      Required minimum volts
                      <input
                        aria-label={`Load ${domain} minimum voltage`}
                        type="number"
                        step="any"
                        disabled={!!load.profile_id}
                        value={load.spec[domain].min_v}
                        onChange={(e) =>
                          domainChange(domain, "min_v", Number(e.target.value))
                        }
                      />
                    </label>
                    <label>
                      Required maximum volts
                      <input
                        aria-label={`Load ${domain} maximum voltage`}
                        type="number"
                        step="any"
                        disabled={!!load.profile_id}
                        value={load.spec[domain].max_v}
                        onChange={(e) =>
                          domainChange(domain, "max_v", Number(e.target.value))
                        }
                      />
                    </label>
                    {(["steady", "startup"] as const).map((phase) => (
                      <div key={phase} className="supply-demand">
                        <strong>
                          {phase === "steady"
                            ? "Steady demand"
                            : "Startup demand"}
                        </strong>
                        <label>
                          Rating basis
                          <select
                            aria-label={`Load ${domain} ${phase} basis`}
                            disabled={!!load.profile_id}
                            value={load.spec[domain][phase].basis}
                            onChange={(e) =>
                              demandChange(
                                domain,
                                phase,
                                "basis",
                                e.target.value,
                              )
                            }
                          >
                            {[
                              "unknown",
                              "maximum",
                              "typical",
                              "published-unspecified",
                              "user-estimate",
                            ].map((item) => (
                              <option key={item}>{item}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Amount
                          <input
                            aria-label={`Load ${domain} ${phase} amount`}
                            type="number"
                            step="any"
                            disabled={
                              !!load.profile_id ||
                              load.spec[domain][phase].basis === "unknown"
                            }
                            value={load.spec[domain][phase].amount ?? ""}
                            placeholder="Unknown"
                            onChange={(e) =>
                              demandChange(
                                domain,
                                phase,
                                "amount",
                                optional(e.target.value),
                              )
                            }
                          />
                        </label>
                        <label>
                          Unit
                          <select
                            aria-label={`Load ${domain} ${phase} unit`}
                            disabled={!!load.profile_id}
                            value={load.spec[domain][phase].unit}
                            onChange={(e) =>
                              demandChange(
                                domain,
                                phase,
                                "unit",
                                e.target.value,
                              )
                            }
                          >
                            <option>mA</option>
                            <option>W</option>
                            <option>VA</option>
                          </select>
                        </label>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <p>
              Maximum, typical and startup ratings stay distinct. DC W/V and AC
              VA/V can estimate current. AC watts require power factor and are
              not converted. Published Belimo consumption does not establish
              maximum or inrush current.
            </p>
            <label>
              Load evidence/notes
              <textarea
                aria-label="Supply load notes"
                maxLength={2000}
                value={load.notes}
                onChange={(e) => setLoad({ ...load, notes: e.target.value })}
              />
            </label>
            <div className="button-row">
              <button onClick={commitLoad}>
                {editingLoad ? "Update supply load" : "Add supply load"}
              </button>
              <button
                onClick={() => {
                  setLoad(blankLoad());
                  setEditingLoad(false);
                }}
              >
                Reset load form
              </button>
            </div>
            {load.profile_id && (
              <details>
                <summary>Documented load evidence</summary>
                <pre>
                  {JSON.stringify(
                    catalog.loads.find(
                      (row: AnyRecord) => row.id === load.profile_id,
                    ),
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
          </fieldset>
          <div className="supply-table">
            <table aria-label="Supply load records">
              <thead>
                <tr>
                  <th>Load</th>
                  <th>Quantity</th>
                  <th>Source</th>
                  <th>Terminal</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {draft.loads.map((row: AnyRecord) => (
                  <tr key={row.id}>
                    <td>
                      {row.name}
                      <small>
                        {row.profile_id
                          ? "Documented profile; installation unverified"
                          : "User-declared load"}
                      </small>
                    </td>
                    <td>{row.quantity}</td>
                    <td>
                      {draft.rails.find(
                        (item: AnyRecord) => item.id === row.rail_id,
                      )?.name || "Missing rail"}
                    </td>
                    <td>{row.terminal_id}</td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() => {
                          setLoad(structuredClone(row));
                          setEditingLoad(true);
                        }}
                      >
                        Edit load
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          update({
                            ...draft,
                            loads: draft.loads.filter(
                              (item: AnyRecord) => item.id !== row.id,
                            ),
                          })
                        }
                      >
                        Remove load
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button disabled={busy} onClick={() => void evaluate()}>
              Calculate supply budget
            </button>
            <button disabled={busy} onClick={() => void save()}>
              Save supply plan
            </button>
            <button
              disabled={busy || !identity}
              onClick={() => void save(true)}
            >
              Save supply plan copy
            </button>
            <button disabled={busy} onClick={() => void evaluate("plan")}>
              Export supply plan JSON
            </button>
            <button disabled={busy} onClick={() => importer.current?.click()}>
              Import supply plan JSON
            </button>
            <button disabled={busy} onClick={() => void evaluate("report")}>
              Export budget report JSON
            </button>
          </div>
          <input
            ref={importer}
            hidden
            type="file"
            accept=".json,application/json"
            aria-label="Supply plan JSON"
            onChange={(e) => {
              void importPlan(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {analysis && (
            <section aria-label="Supply budget results">
              <h4>Budget status: {analysis.status}</h4>
              <p>{analysis.scope}</p>
              <p>
                Captured {analysis.evaluated_at} · plan SHA-256{" "}
                <code>{analysis.plan_sha256}</code>
              </p>
              {analysis.rails.map((row: AnyRecord) => (
                <div key={row.id} className="supply-result">
                  <h4>
                    {row.name}: {row.status}
                  </h4>
                  <p>
                    {row.domain.toUpperCase()} {row.nominal_v} V nominal ·
                    declared range {show(row.operating_range.min_v)}…
                    {show(row.operating_range.max_v)} V
                  </p>
                  {row.issues.map((issue: string) => (
                    <p key={issue}>{issue}</p>
                  ))}
                  <div className="supply-table">
                    <table>
                      <thead>
                        <tr>
                          <th>Budget scope</th>
                          <th>Phase</th>
                          <th>Known subtotal</th>
                          <th>Limit / remaining from known</th>
                          <th>Confidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {row.budgets.flatMap((budget: AnyRecord) =>
                          ["steady", "startup"].map((phase) => (
                            <tr key={`${budget.terminal_id}:${phase}`}>
                              <td>
                                {budget.scope}
                                {budget.terminal_id
                                  ? ` ${budget.terminal_id}`
                                  : ""}
                              </td>
                              <td>{phase}</td>
                              <td>
                                {show(budget.phases[phase].known_total_ma)} mA
                                <small>
                                  {budget.phases[phase].unknown_loads} loads
                                  without numeric demand
                                </small>
                              </td>
                              <td>
                                {show(budget.phases[phase].limit_ma)} /{" "}
                                {show(
                                  budget.phases[phase].remaining_from_known_ma,
                                )}{" "}
                                mA
                              </td>
                              <td>
                                {budget.phases[phase].status}
                                <small>
                                  {budget.phases[phase].maximum_unknown_loads}{" "}
                                  devices without established maximum
                                </small>
                              </td>
                            </tr>
                          )),
                        )}
                      </tbody>
                    </table>
                  </div>
                  {row.loads.map((item: AnyRecord) => (
                    <p key={item.id}>
                      {item.name}: {item.voltage_status}; steady{" "}
                      {show(item.steady.ma)} mA ({item.steady.basis}); startup{" "}
                      {show(item.startup.ma)} mA ({item.startup.basis})
                    </p>
                  ))}
                  <p>
                    {row.terminal_scope} {row.startup_scope}
                  </p>
                  <details>
                    <summary>Budget provenance</summary>
                    <pre>{JSON.stringify(row, null, 2)}</pre>
                  </details>
                </div>
              ))}
            </section>
          )}
          <p>
            <code>Catalog SHA-256 {draft.catalog_sha256}</code>. Source
            snapshots distinguish publisher PDF bytes from publisher
            text-extraction captures. Unknown model suffixes receive no guessed
            rating. Save/import revalidate every documented specification and
            optional survey hash.
          </p>
        </>
      )}
    </section>
  );
}
