import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Program } from "./types";
import "./equipment-wizard.css";
type Data = Record<string, any>;
const same = (a: any, b: any): boolean => {
  const ordered = (v: any): any =>
    Array.isArray(v)
      ? v.map(ordered)
      : v && typeof v === "object"
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, ordered(v[k])]),
          )
        : v;
  return JSON.stringify(ordered(a)) === JSON.stringify(ordered(b));
};
export function EquipmentWizard({
  source,
  onCreate,
  onClose,
}: {
  source: Program;
  onCreate: (program: Program, sourceKey: string) => boolean;
  onClose: () => void;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [draft, setDraft] = useState<Data | null>(null),
    [preview, setPreview] = useState<Data | null>(null),
    [step, setStep] = useState(1),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = JSON.stringify(source),
    draftKey = JSON.stringify(draft),
    live = useRef({ sourceKey, draftKey });
  live.current = { sourceKey, draftKey };
  useEffect(() => {
    mounted.current = true;
    const generation = ++epoch.current;
    setBusy(true);
    api("/equipment-wizard/catalog")
      .then((data) => {
        if (!mounted.current || epoch.current !== generation) return;
        setCatalog(data);
        setDraft({
          ...data.defaults,
          project_id: "vav-" + crypto.randomUUID().replaceAll("-", ""),
        });
      })
      .catch((e) => {
        if (mounted.current) setError(String(e));
      })
      .finally(() => {
        if (mounted.current && epoch.current === generation) setBusy(false);
      });
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  const previousSource = useRef(sourceKey);
  useEffect(() => {
    if (previousSource.current === sourceKey) return;
    previousSource.current = sourceKey;
    if (!draft) return;
    epoch.current++;
    setPreview(null);
    setBusy(false);
    setError(
      "Current editor changed. Preview again before creating a project.",
    );
  }, [sourceKey]);
  function patch(key: string, value: any) {
    if (!draft) return;
    epoch.current++;
    setDraft({ ...draft, [key]: value });
    setPreview(null);
    setError("");
  }
  function current(generation: number, sourceKey: string, draftKey: string) {
    return (
      mounted.current &&
      epoch.current === generation &&
      live.current.sourceKey === sourceKey &&
      live.current.draftKey === draftKey
    );
  }
  async function units(temperature_unit: string, flow_unit: string) {
    if (!draft || busy) return;
    const gen = ++epoch.current,
      base = sourceKey,
      choices = draftKey;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const result = await api("/equipment-wizard/units", {
        choices: draft,
        temperature_unit,
        flow_unit,
      });
      if (!current(gen, base, choices)) return;
      if (
        result.profile_sha256 !== catalog?.profile_sha256 ||
        !same(result.source_choices, draft) ||
        result.choices?.project_id !== draft.project_id ||
        result.choices?.temperature_unit !== temperature_unit ||
        result.choices?.flow_unit !== flow_unit
      )
        throw new Error("Unit conversion profile does not match this wizard.");
      setDraft(result.choices);
    } catch (e) {
      if (current(gen, base, choices)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === gen) setBusy(false);
    }
  }
  async function review() {
    if (!draft || busy) return;
    const gen = ++epoch.current,
      base = sourceKey,
      choices = draftKey;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const result = await api("/equipment-wizard/preview", draft);
      if (!current(gen, base, choices)) return;
      const provenance = result.program?.metadata?.equipment_wizard;
      if (
        result.format !== "bms.equipment-wizard-preview" ||
        result.version !== 1 ||
        result.profile_sha256 !== catalog?.profile_sha256 ||
        !same(result.choices, draft) ||
        result.program?.id !== draft.project_id ||
        result.program.name !== draft.name ||
        !same(result.program.target, {
          family: draft.family,
          model: draft.model,
          firmware: draft.firmware,
          release_mode: draft.release_mode,
          max_nodes: 2000,
          physical_inputs: null,
          physical_outputs: null,
        }) ||
        provenance?.choices_sha256 !== result.choices_sha256 ||
        provenance.profile_sha256 !== result.profile_sha256 ||
        !same(provenance.choices, draft) ||
        !Array.isArray(result.program.nodes) ||
        !Array.isArray(result.program.edges) ||
        !Array.isArray(result.points) ||
        !Array.isArray(result.issues) ||
        result.native_compile !== false ||
        result.controller_writes !== false ||
        !result.topology ||
        !same(result.profile, catalog?.profile) ||
        !Array.isArray(result.profile?.gaps) ||
        !result.points.every(
          (row: Data) =>
            row &&
            ["id", "label", "role", "type", "unit", "binding"].every(
              (key) => typeof row[key] === "string",
            ),
        ) ||
        !result.issues.every(
          (row: Data) =>
            row &&
            typeof row.message === "string" &&
            ["error", "warning"].includes(row.level),
        ) ||
        !/^[a-f0-9]{64}$/.test(result.program_sha256) ||
        !/^[a-f0-9]{64}$/.test(result.choices_sha256)
      )
        throw new Error(
          "Wizard preview does not match these exact choices/profile.",
        );
      setPreview({ ...result, sourceKey: base, draftKey: choices });
      setStep(3);
    } catch (e) {
      if (current(gen, base, choices)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === gen) setBusy(false);
    }
  }
  function create() {
    if (
      !preview ||
      !draft ||
      busy ||
      preview.sourceKey !== sourceKey ||
      preview.draftKey !== draftKey ||
      preview.can_create !== true
    )
      return;
    if (
      (source.nodes.length || source.revision) &&
      !window.confirm(
        `Replace the editor contents of “${source.name}” with a separate new project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
      )
    )
      return;
    if (onCreate(preview.program, sourceKey)) onClose();
    else {
      setPreview(null);
      setError(
        "Current project changed. Preview again before replacing the editor.",
      );
    }
  }
  function number(key: string, label: string, help?: string) {
    return (
      <label>
        {label}
        <input
          type="number"
          step="any"
          aria-label={label}
          value={Number.isNaN(draft?.[key]) ? "" : (draft?.[key] ?? "")}
          onChange={(e) =>
            patch(key, e.target.value === "" ? NaN : Number(e.target.value))
          }
        />
        {help && <small>{help}</small>}
      </label>
    );
  }
  function text(key: string, label: string, maxLength = 80) {
    return (
      <label>
        {label}
        <input
          aria-label={label}
          value={draft?.[key] ?? ""}
          maxLength={maxLength}
          onChange={(e) => patch(key, e.target.value)}
        />
      </label>
    );
  }
  function choice(key: string, label: string, options: [string, string][]) {
    return (
      <label>
        {label}
        <select
          aria-label={label}
          value={draft?.[key] ?? ""}
          onChange={(e) => {
            if (key === "temperature_loop" || key === "flow_loop") {
              const field =
                key === "temperature_loop" ? "temperature_ki" : "flow_ki";
              epoch.current++;
              setDraft({
                ...draft,
                [key]: e.target.value,
                [field]: e.target.value === "P" ? 0 : (draft?.[field] ?? 0),
              });
              setPreview(null);
              setError("");
            } else patch(key, e.target.value);
          }}
        >
          {options.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Equipment and sequence wizard"
        className="equipment-wizard"
      >
        <h1>Equipment and sequence wizard</h1>
        <p>
          Create a separate editable portable VAV project.
          Target/model/firmware/release mode are declarations. Native
          allocation, package compatibility and field deployment are not
          verified.
        </p>
        <p>
          Step {step} of 3 ·{" "}
          {step === 1
            ? "Equipment and target"
            : step === 2
              ? "Sensors, strategy and parameters"
              : "Preview generated project"}
        </p>
        {draft && (
          <fieldset disabled={busy}>
            {step === 1 && (
              <div className="wizard-fields">
                {text("name", "Wizard project name", 200)}
                {choice("equipment", "VAV equipment", [
                  ["cooling-only", "Cooling only"],
                  ["inline-reheat", "Inline hot-water reheat, no fan"],
                  ["parallel-fan-reheat", "Parallel fan with hot-water reheat"],
                ])}
                {choice("family", "Declared controller family", [
                  ["universal-runtime", "Portable runtime"],
                  ["johnson-fx", "Johnson Controls FX"],
                  ["johnson-metasys", "Johnson Controls Metasys"],
                ])}
                {text("model", "Declared controller model")}
                {text("firmware", "Declared controller firmware")}
                {text("release_mode", "Declared CAF release mode")}
                <p>
                  Model names do not select native terminal mappings or prove
                  package/firmware support. Inline reheat has no fan; parallel
                  fan control is illustrative demand hysteresis without fan
                  proof.
                </p>
              </div>
            )}
            {step === 2 && (
              <>
                <div className="wizard-fields">
                  {choice("control", "Damper control strategy", [
                    [
                      "position",
                      "Damper-position demand mapping (no airflow measurement)",
                    ],
                    [
                      "flow-feedback",
                      "Measured-airflow feedback with a separate flow loop",
                    ],
                  ])}
                  {choice("setpoints", "Setpoint sources", [
                    ["fixed", "Fixed declared setpoints"],
                    [
                      "inputs",
                      "Editable logical setpoint inputs (no network binding)",
                    ],
                  ])}
                  <label>
                    Temperature units
                    <select
                      aria-label="Wizard temperature units"
                      value={draft.temperature_unit}
                      onChange={(e) =>
                        void units(e.target.value, draft.flow_unit)
                      }
                    >
                      <option value="degF">degF</option>
                      <option value="degC">degC</option>
                    </select>
                  </label>
                  {number(
                    "zone_default",
                    `Zone temperature default (${draft.temperature_unit})`,
                  )}
                  {number(
                    "cooling_setpoint",
                    `Cooling setpoint (${draft.temperature_unit})`,
                  )}
                  {draft.equipment !== "cooling-only" &&
                    number(
                      "heating_setpoint",
                      `Heating setpoint (${draft.temperature_unit})`,
                    )}
                  {choice("temperature_loop", "Zone loop strategy", [
                    ["P", "Proportional only"],
                    ["PI", "Proportional plus integral"],
                  ])}
                  {number(
                    "temperature_kp",
                    `Zone proportional gain (%/delta-${draft.temperature_unit})`,
                  )}
                  {draft.temperature_loop === "PI" &&
                    number(
                      "temperature_ki",
                      `Zone integral gain (%/delta-${draft.temperature_unit}/s)`,
                    )}
                  {number("scan_seconds", "Scan interval (seconds)")}
                </div>
                {draft.control === "position" ? (
                  <div className="wizard-fields">
                    {number("damper_min", "Minimum damper position (%)")}
                    {number("damper_max", "Maximum damper position (%)")}
                    <p>
                      Position percentages are neither measured airflow nor
                      design ventilation. No airflow sensor or flow loop is
                      generated in this option.
                    </p>
                  </div>
                ) : (
                  <div className="wizard-fields">
                    <label>
                      Airflow units
                      <select
                        aria-label="Wizard airflow units"
                        value={draft.flow_unit}
                        onChange={(e) =>
                          void units(draft.temperature_unit, e.target.value)
                        }
                      >
                        <option value="cfm">cfm</option>
                        <option value="L/s">L/s</option>
                      </select>
                    </label>
                    {number(
                      "flow_min",
                      `Minimum declared airflow (${draft.flow_unit})`,
                    )}
                    {number(
                      "flow_max",
                      `Maximum declared airflow (${draft.flow_unit})`,
                    )}
                    {number(
                      "flow_default",
                      `Measured-airflow input default (${draft.flow_unit})`,
                    )}
                    {choice("flow_loop", "Airflow loop strategy", [
                      ["P", "Proportional only"],
                      ["PI", "Proportional plus integral"],
                    ])}
                    {number(
                      "flow_kp",
                      `Flow proportional gain (%/${draft.flow_unit})`,
                    )}
                    {draft.flow_loop === "PI" &&
                      number(
                        "flow_ki",
                        `Flow integral gain (%/${draft.flow_unit}/s)`,
                      )}
                    <p>
                      This adds a numeric measured-airflow Input,
                      desired-airflow signal and separate flow PI. Input values
                      must already represent calibrated airflow. Increasing
                      damper command is assumed to increase airflow; physical
                      direction/wiring remain unverified.
                    </p>
                  </div>
                )}
                {draft.equipment === "parallel-fan-reheat" && (
                  <div className="wizard-fields">
                    {number("fan_on", "Fan on heat-demand threshold (%)")}
                    {number("fan_off", "Fan off heat-demand threshold (%)")}
                  </div>
                )}
                <p>
                  Changing units converts absolute defaults/setpoints and both
                  proportional/integral inverse-unit gains together. Seconds and
                  demand percentages retain their meanings. External setpoint
                  inputs have no automatic runtime range/deadband enforcement.
                </p>
              </>
            )}
            {step === 3 &&
              preview &&
              preview.sourceKey === sourceKey &&
              preview.draftKey === draftKey && (
                <section aria-label="Wizard preview">
                  <h2>{preview.program.name}</h2>
                  <p>
                    {preview.topology.nodes} blocks · {preview.topology.edges}{" "}
                    connections · {preview.topology.control}
                  </p>
                  <p>
                    Project ID: {preview.program.id} · choices SHA256{" "}
                    <code>{preview.choices_sha256}</code> · program SHA256{" "}
                    <code>{preview.program_sha256}</code>
                  </p>
                  <table>
                    <thead>
                      <tr>
                        <th>Signal</th>
                        <th>Role</th>
                        <th>Type / units</th>
                        <th>Binding</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.points.map((row: Data) => (
                        <tr key={row.id}>
                          <td>
                            {row.label} ({row.id})
                          </td>
                          <td>{row.role}</td>
                          <td>
                            {row.type} / {row.unit || "none"}
                          </td>
                          <td>{row.binding}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <h3>Validation</h3>
                  {preview.issues.length ? (
                    preview.issues.map((row: Data, index: number) => (
                      <p key={index}>
                        {row.level}: {row.message}
                      </p>
                    ))
                  ) : (
                    <p>No portable graph errors.</p>
                  )}
                  <h3>Separate engineering work</h3>
                  <ul>
                    {preview.profile.gaps.map((item: string) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  <details>
                    <summary>
                      Source, topology and declared choice evidence
                    </summary>
                    <p>
                      <a
                        href={preview.profile.source.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {preview.profile.source.title}{" "}
                        {preview.profile.source.edition}
                      </a>
                      , PDF pages {preview.profile.source.pdf_pages.join(", ")};
                      SHA256 <code>{preview.profile.source.sha256}</code>
                    </p>
                    <p>{preview.profile.source.scope}</p>
                    <pre>
                      {JSON.stringify(
                        {
                          choices: preview.choices,
                          inactive:
                            preview.program.metadata.equipment_wizard
                              .inactive_choices,
                          units: preview.profile.units,
                          nodes: preview.program.nodes,
                          edges: preview.program.edges,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </section>
              )}
          </fieldset>
        )}
        {busy && <p role="status">Preparing local authoring preview…</p>}
        {error && <p role="alert">{error}</p>}
        <div className="button-row">
          <button onClick={onClose}>Cancel wizard</button>
          {step > 1 && (
            <button disabled={busy} onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
          {step === 1 && (
            <button disabled={busy || !draft} onClick={() => setStep(2)}>
              Next: parameters
            </button>
          )}
          {step === 2 && (
            <button disabled={busy} onClick={() => void review()}>
              Preview VAV project
            </button>
          )}
          {step === 3 && (
            <button
              className="primary"
              disabled={
                busy ||
                !preview ||
                preview.sourceKey !== sourceKey ||
                preview.draftKey !== draftKey ||
                preview.can_create !== true
              }
              onClick={create}
            >
              Create editable project
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
