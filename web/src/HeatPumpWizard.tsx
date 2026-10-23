import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, sourceApi, saveBlob } from "./api";
import { sourceEqual, sourceStringify } from "./programSource";
import type { Program } from "./types";
import "./equipment-wizard.css";

type Data = Record<string, any>;
const BASE = "/heat-pump-wizard";
const PROFILE = "studio-single-compressor-heat-pump/1";
const roles = [
  "compressor",
  "reversing_valve",
  "fan",
  "heating_request",
  "cooling_request",
  "heating_mode",
  "heating_active",
  "cooling_active",
  "minimum_on_hold",
  "minimum_off_ready",
  "valve_settled",
  "unit_permitted",
];
const numeric = [
  "zone_default",
  "heating_setpoint",
  "cooling_setpoint",
  "demand_on_delta",
  "demand_off_delta",
];
const timing = [
  "minimum_on_seconds",
  "minimum_off_seconds",
  "valve_off_seconds",
  "valve_settle_seconds",
  "scan_seconds",
];
const flags = [
  "occupied_default",
  "unit_enable_default",
  "energy_holdoff_default",
  "airflow_proven_default",
  "condensate_default",
];
const textFields = ["project_id", "name", "model", "firmware", "release_mode"];
const selections: Record<string, string[]> = {
  family: ["universal-runtime", "johnson-fx", "johnson-metasys"],
  temperature_unit: ["degF", "degC"],
  setpoints: ["fixed", "inputs"],
  reversing_polarity: ["", "on-for-heating", "on-for-cooling"],
  initial_mode: ["", "heating", "cooling"],
  fan_policy: ["", "continuous-occupied", "cycle-on-demand"],
  condensate: ["", "none", "disable-cooling", "shutdown-unit"],
};
const object = (value: any): value is Data =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: any) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
function declaredChoices(value: any) {
  return (
    object(value) &&
    textFields.every((key) => typeof value[key] === "string") &&
    numeric.every((key) => Number.isFinite(value[key])) &&
    timing.every((key) => Number.isSafeInteger(value[key])) &&
    flags.every((key) => typeof value[key] === "boolean") &&
    Object.entries(selections).every(([key, values]) =>
      values.includes(value[key]),
    )
  );
}
function catalogResult(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.heat-pump-wizard-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== PROFILE ||
    !hash(value.profile_sha256) ||
    !object(value.profile.source) ||
    !hash(value.profile.source.sha256) ||
    typeof value.profile.source.url !== "string" ||
    !value.profile.source.url.startsWith("https://docs.johnsoncontrols.com/") ||
    !["title", "document", "edition", "scope"].every(
      (key) => typeof value.profile.source[key] === "string",
    ) ||
    !Array.isArray(value.profile.source.pdf_pages) ||
    !value.profile.source.pdf_pages.every(
      (page: any) => Number.isSafeInteger(page) && page > 0,
    ) ||
    !object(value.profile.semantics) ||
    !Object.values(value.profile.semantics).every(
      (row) => typeof row === "string",
    ) ||
    !Array.isArray(value.profile.gaps) ||
    !value.profile.gaps.every((row: any) => typeof row === "string") ||
    !object(value.limits) ||
    value.limits.nodes !== 200 ||
    !sourceEqual(value.limits.scan_seconds, [1, 60]) ||
    !sourceEqual(value.limits.timing_seconds, [1, 3600]) ||
    !sourceEqual(value.profile.limits, value.limits) ||
    !declaredChoices(value.defaults)
  ) {
    throw new Error(
      "Heat-pump catalog is malformed or uses an unsupported profile.",
    );
  }
  return value;
}
function previewResult(value: any, choices: Data, catalog: Data) {
  const provenance = value?.program?.metadata?.heat_pump_wizard;
  if (
    !object(value) ||
    value.format !== "bms.heat-pump-wizard-preview" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(value.profile, catalog.profile) ||
    !sourceEqual(value.choices, choices) ||
    !hash(value.choices_sha256) ||
    !hash(value.program_sha256) ||
    value.program?.id !== choices.project_id ||
    value.program?.name !== choices.name ||
    !sourceEqual(value.program.target, {
      family: choices.family,
      model: choices.model,
      firmware: choices.firmware,
      release_mode: choices.release_mode,
      max_nodes: 2000,
      physical_inputs: null,
      physical_outputs: null,
    }) ||
    !sourceEqual(provenance?.choices, choices) ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    !sourceEqual(provenance.source, catalog.profile.source) ||
    !sourceEqual(provenance.unimplemented, catalog.profile.gaps) ||
    !sourceEqual(provenance.outputs, value.outputs) ||
    value.program.metadata.native_deployment_verified !== false ||
    !Array.isArray(value.program.nodes) ||
    value.program.nodes.length > 200 ||
    !Array.isArray(value.program.edges) ||
    value.program.edges.length > 8000 ||
    !object(value.outputs) ||
    Object.keys(value.outputs).length !== roles.length ||
    !roles.every(
      (role) =>
        value.outputs[role] === role &&
        value.program.nodes.some(
          (node: any) =>
            node.id === role &&
            node.kind === "Output" &&
            node.value_type === "boolean",
        ),
    ) ||
    value.native_compile !== false ||
    value.controller_writes !== false ||
    typeof value.can_create !== "boolean" ||
    !Array.isArray(value.diagnostics) ||
    !value.diagnostics.every(
      (row: any) =>
        object(row) &&
        ["warning", "error"].includes(row.level) &&
        typeof row.code === "string" &&
        typeof row.message === "string",
    ) ||
    !Array.isArray(value.inactive_choices) ||
    !sourceEqual(provenance.inactive_choices, value.inactive_choices) ||
    !value.inactive_choices.every((row: any) => typeof row === "string")
  ) {
    throw new Error(
      "Heat-pump preview does not match these exact choices, source profile or logical outputs.",
    );
  }
  return value;
}

export function HeatPumpWizard({
  source,
  onCreate,
  onClose,
  onBack,
}: {
  source: Program;
  onCreate: (program: Program, sourceKey: string) => boolean;
  onClose: () => void;
  onBack: () => void;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null);
  const [draft, setDraft] = useState<Data | null>(null);
  const [preview, setPreview] = useState<{
    data: Data;
    key: string;
    sourceKey: string;
    choices: Data;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0);
  const sourceKey = sourceStringify(source),
    key = JSON.stringify({
      draft,
      profile: catalog?.profile_sha256,
      sourceKey,
    });
  const live = useRef(key);
  live.current = key;
  const current = (generation: number, owned: string) =>
    mounted.current && epoch.current === generation && live.current === owned;
  useEffect(() => {
    mounted.current = true;
    const generation = ++epoch.current;
    setBusy(true);
    api(BASE + "/catalog")
      .then((value) => {
        const checked = catalogResult(value);
        if (!mounted.current || epoch.current !== generation) return;
        setCatalog(checked);
        setDraft({
          ...checked.defaults,
          project_id: "heat_pump_" + crypto.randomUUID().replaceAll("-", ""),
        });
      })
      .catch((e) => {
        if (mounted.current && epoch.current === generation)
          setError(String(e));
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
      "Current editor changed. Preview again before creating a heat-pump project.",
    );
  }, [sourceKey]);
  function patch(field: string, value: any) {
    if (!draft) return;
    epoch.current++;
    setPreview(null);
    setError("");
    setBusy(false);
    setDraft({ ...draft, [field]: value });
  }
  async function units(temperature_unit: string) {
    if (
      !draft ||
      !catalog ||
      busy ||
      temperature_unit === draft.temperature_unit
    )
      return;
    const generation = ++epoch.current,
      owned = key,
      original = draft;
    setBusy(true);
    setPreview(null);
    setError("");
    try {
      const result = await api(BASE + "/units", {
        choices: original,
        temperature_unit,
      });
      if (!current(generation, owned)) return;
      const converted = result.choices;
      if (
        result.profile_sha256 !== catalog.profile_sha256 ||
        !hash(result.choices_sha256) ||
        !hash(result.source_choices_sha256) ||
        !sourceEqual(result.source_choices, original) ||
        !declaredChoices(converted) ||
        converted.temperature_unit !== temperature_unit ||
        !numeric.every((field) => {
          const absolute = [
            "zone_default",
            "heating_setpoint",
            "cooling_setpoint",
          ].includes(field);
          const expected =
            temperature_unit === "degC"
              ? ((original[field] - (absolute ? 32 : 0)) * 5) / 9
              : (original[field] * 9) / 5 + (absolute ? 32 : 0);
          return (
            Math.abs(converted[field] - expected) <=
            1e-10 * Math.max(1, Math.abs(expected))
          );
        }) ||
        Object.keys(original).length !== Object.keys(converted).length ||
        !Object.keys(original)
          .filter((field) => ![...numeric, "temperature_unit"].includes(field))
          .every((field) => sourceEqual(original[field], converted[field]))
      ) {
        throw new Error(
          "Unit conversion does not match this exact heat-pump draft and profile.",
        );
      }
      setDraft(converted);
    } catch (e) {
      if (current(generation, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === generation) setBusy(false);
    }
  }
  async function review() {
    if (!draft || !catalog || busy) return;
    const generation = ++epoch.current,
      owned = key,
      base = sourceKey,
      choices = draft;
    setBusy(true);
    setPreview(null);
    setError("");
    try {
      const data = previewResult(
        await sourceApi(BASE + "/preview", { choices }),
        choices,
        catalog,
      );
      if (current(generation, owned))
        setPreview({ data, key: owned, sourceKey: base, choices });
    } catch (e) {
      if (current(generation, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === generation) setBusy(false);
    }
  }
  async function exportReview() {
    if (!preview || preview.key !== key || !catalog || busy) return;
    const generation = ++epoch.current,
      owned = key,
      accepted = preview;
    setBusy(true);
    setError("");
    try {
      const result = await apiJsonDocument(BASE + "/export", {
        choices: accepted.choices,
      });
      const data = previewResult(result.data, accepted.choices, catalog);
      if (
        data.program_sha256 !== accepted.data.program_sha256 ||
        data.choices_sha256 !== accepted.data.choices_sha256 ||
        !sourceEqual(data.program, accepted.data.program) ||
        !sourceEqual(data.outputs, accepted.data.outputs) ||
        !sourceEqual(data.diagnostics, accepted.data.diagnostics) ||
        !sourceEqual(data.inactive_choices, accepted.data.inactive_choices) ||
        data.can_create !== accepted.data.can_create
      )
        throw new Error(
          "Heat-pump export changed after preview. Review the current source again.",
        );
      if (current(generation, owned))
        saveBlob(result.blob, `heat-pump-review-${data.program_sha256}.json`);
    } catch (e) {
      if (current(generation, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === generation) setBusy(false);
    }
  }
  function create() {
    if (
      !preview ||
      busy ||
      preview.key !== key ||
      preview.sourceKey !== sourceKey ||
      preview.data.can_create !== true
    )
      return;
    if (
      (source.nodes.length || source.revision) &&
      !window.confirm(
        `Replace the editor contents of “${source.name}” with a separate new heat-pump project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
      )
    )
      return;
    if (onCreate(preview.data.program, sourceKey)) onClose();
    else {
      setPreview(null);
      setError(
        "Current project changed. Preview again before replacing the editor.",
      );
    }
  }
  function number(field: string, label: string, whole = false) {
    return (
      <label>
        {label}
        <input
          aria-label={label}
          type="number"
          step={whole ? "1" : "any"}
          value={Number.isNaN(draft?.[field]) ? "" : (draft?.[field] ?? "")}
          onChange={(e) =>
            patch(field, e.target.value === "" ? NaN : Number(e.target.value))
          }
        />
      </label>
    );
  }
  function text(field: string, label: string, maxLength = 80) {
    return (
      <label>
        {label}
        <input
          aria-label={label}
          value={draft?.[field] ?? ""}
          maxLength={maxLength}
          onChange={(e) => patch(field, e.target.value)}
        />
      </label>
    );
  }
  function choice(
    field: string,
    label: string,
    options: [string, string][],
    explicit = false,
  ) {
    return (
      <label>
        {label}
        <select
          aria-label={label}
          value={draft?.[field] ?? ""}
          onChange={(e) => patch(field, e.target.value)}
        >
          {explicit && <option value="">Choose explicitly…</option>}
          {options.map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </label>
    );
  }
  const displayed = preview?.key === key ? preview : null;
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Heat-pump wizard"
        className="equipment-wizard"
      >
        <h1>Single-compressor heat-pump foundation</h1>
        <p>
          Create an editable portable graph with temperature hysteresis, one
          compressor, a single-speed fan and an explicitly declared reversing
          valve. Controller identity fields are declarations; native
          compilation, allocation and deployment are unverified.
        </p>
        <p>
          Timing is an authored uniform policy, not verified manufacturer
          protection. A bad-quality scan retains previous committed outputs; it
          does not guarantee an immediate physical shutdown. Logical airflow
          permission is not a physical airflow proof system.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <h2>Project and declared target</h2>
            <div className="wizard-fields">
              {text("name", "Heat-pump project name", 200)}
              {choice("family", "Heat-pump declared controller family", [
                ["universal-runtime", "Portable runtime"],
                ["johnson-fx", "Johnson Controls FX"],
                ["johnson-metasys", "Johnson Controls Metasys"],
              ])}
              {text("model", "Heat-pump declared model")}
              {text("firmware", "Heat-pump declared firmware")}
              {text("release_mode", "Heat-pump declared release mode")}
              {number(
                "scan_seconds",
                "Heat-pump scan interval (seconds)",
                true,
              )}
            </div>
            <h2>Temperature demand and declared mechanics</h2>
            <div className="wizard-fields">
              <label>
                Heat-pump temperature units
                <select
                  aria-label="Heat-pump temperature units"
                  value={draft.temperature_unit}
                  disabled={[
                    "reversing_polarity",
                    "initial_mode",
                    "fan_policy",
                    "condensate",
                  ].some((field) => !draft[field])}
                  onChange={(e) => units(e.target.value)}
                >
                  <option value="degF">Degrees Fahrenheit</option>
                  <option value="degC">Degrees Celsius</option>
                </select>
              </label>
              {choice("setpoints", "Heat-pump setpoint source", [
                ["fixed", "Fixed setpoints"],
                ["inputs", "Logical setpoint inputs"],
              ])}
              {number("zone_default", "Heat-pump default zone temperature")}
              {number("heating_setpoint", "Heat-pump heating setpoint")}
              {number("cooling_setpoint", "Heat-pump cooling setpoint")}
              {number("demand_on_delta", "Heat-pump demand on difference")}
              {number("demand_off_delta", "Heat-pump demand off difference")}
              {choice(
                "reversing_polarity",
                "Heat-pump reversing valve energized for",
                [
                  ["on-for-heating", "Heating"],
                  ["on-for-cooling", "Cooling"],
                ],
                true,
              )}
              {choice(
                "initial_mode",
                "Heat-pump initial mode",
                [
                  ["heating", "Heating"],
                  ["cooling", "Cooling"],
                ],
                true,
              )}
              {choice(
                "fan_policy",
                "Heat-pump fan policy",
                [
                  [
                    "continuous-occupied",
                    "Continuous while occupied and permitted",
                  ],
                  ["cycle-on-demand", "Cycle with demand"],
                ],
                true,
              )}
              {choice(
                "condensate",
                "Heat-pump condensate policy",
                [
                  ["none", "No condensate input"],
                  ["disable-cooling", "Disable cooling only"],
                  ["shutdown-unit", "Shut down the unit"],
                ],
                true,
              )}
            </div>
            <p>
              Choose reversing valve polarity, initial mode, fan and condensate
              policies before converting units. Heating and cooling setpoints
              stay ordered. Demand-on difference must exceed demand-off
              difference. Changing units converts absolute temperatures and both
              temperature differences together.
            </p>
            <h2>Whole-second compressor and reversing-valve timing</h2>
            <div className="wizard-fields">
              {number(
                "minimum_on_seconds",
                "Heat-pump minimum compressor on (seconds)",
                true,
              )}
              {number(
                "minimum_off_seconds",
                "Heat-pump minimum compressor off (seconds)",
                true,
              )}
              {number(
                "valve_off_seconds",
                "Heat-pump compressor-off before valve change (seconds)",
                true,
              )}
              {number(
                "valve_settle_seconds",
                "Heat-pump valve settling before restart (seconds)",
                true,
              )}
            </div>
            <p>
              Minimum on/off defaults are 120 seconds. The separate
              compressor-off and valve-settling dwells each default to 6
              seconds. Select 1–3600 whole seconds in exact multiples of the
              1–60 second scan interval. Startup, permit loss and reversal
              behavior are defined by the source-qualified authored profile
              below; no equipment rating or native protection is inferred.
            </p>
            <h2>Default logical input values</h2>
            <div className="wizard-fields">
              {[
                ["occupied_default", "Heat-pump default occupied"],
                ["unit_enable_default", "Heat-pump default unit enabled"],
                ["energy_holdoff_default", "Heat-pump default energy holdoff"],
                [
                  "airflow_proven_default",
                  "Heat-pump default airflow permission",
                ],
                ["condensate_default", "Heat-pump default condensate alarm"],
              ].map(([field, label]) => (
                <label key={field}>
                  <input
                    type="checkbox"
                    aria-label={label}
                    checked={draft[field]}
                    onChange={(e) => patch(field, e.target.checked)}
                  />
                  {label}
                </label>
              ))}
            </div>
            <p>
              These values initialize simulated logical inputs. They are not
              wiring, live field values or physical safety acceptance. The
              normal simulator lets you change input values and quality after
              creation.
            </p>
          </fieldset>
        )}
        {busy && <p role="status">Preparing local heat-pump evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="Heat-pump preview">
            <h2>{displayed.data.program.name}</h2>
            <p>
              {displayed.data.program.nodes.length} blocks ·{" "}
              {displayed.data.program.edges.length} connections · {roles.length}{" "}
              logical Boolean outputs.
            </p>
            <p>
              Program SHA-256 {displayed.data.program_sha256}
              <br />
              Choices SHA-256 {displayed.data.choices_sha256}
            </p>
            <h3>Portable graph validation</h3>
            {displayed.data.diagnostics.length ? (
              displayed.data.diagnostics.map((row: any, i: number) => (
                <p key={i}>
                  {row.level}: {row.message}
                </p>
              ))
            ) : (
              <p>No portable graph errors.</p>
            )}
            <table aria-label="Heat-pump logical outputs">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Editable output ID</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(displayed.data.outputs).map(([role, id]) => (
                  <tr key={role}>
                    <td>{role}</td>
                    <td>{String(id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!!displayed.data.inactive_choices.length && (
              <p>
                Retained inactive choices:{" "}
                {displayed.data.inactive_choices.join(", ")}
              </p>
            )}
            <details>
              <summary>
                Authored behavior, primary criteria and exact choices
              </summary>
              <a
                href={catalog?.profile.source.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {catalog?.profile.source.title} ·{" "}
                {catalog?.profile.source.document} ·{" "}
                {catalog?.profile.source.edition}
              </a>
              <p>
                PDF pages {catalog?.profile.source.pdf_pages.join(", ")} ·
                source SHA-256 {catalog?.profile.source.sha256}
              </p>
              <p>{catalog?.profile.source.scope}</p>
              <pre>
                {sourceStringify(
                  {
                    profile: catalog?.profile,
                    choices: displayed.data.choices,
                  },
                  2,
                )}
              </pre>
            </details>
            <p>
              The valve_settled output means off-state valve-settling time is
              ready; it is false while running and is not physical position
              feedback.
            </p>
            <h3>Separate engineering work</h3>
            <ul>
              {catalog?.profile.gaps.map((row: string) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
            <button disabled={busy} onClick={exportReview}>
              Export original heat-pump review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable heat-pump project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>Cancel heat-pump wizard</button>
          <button onClick={onBack}>Back to equipment wizard</button>
          <button disabled={busy || !draft} onClick={review}>
            Preview heat-pump project
          </button>
        </div>
      </section>
    </div>
  );
}
