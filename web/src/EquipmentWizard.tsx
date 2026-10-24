import { sourceEqual, sourceStringify } from "./programSource";
import { sourceApi } from "./api";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Program } from "./types";
import "./equipment-wizard.css";
import { ZoneGroupScheduleWizard } from "./ZoneGroupScheduleWizard";
import { HeatPumpWizard } from "./HeatPumpWizard";
import { MaddMzAhuWizard } from "./MaddMzAhuWizard";
import { MasdAhuWizard } from "./MasdAhuWizard";
import { ZoneSetpointWizard } from "./ZoneSetpointWizard";
import { SeriesFanVavWizard } from "./SeriesFanVavWizard";
import { UnitVentilatorCycle3Wizard } from "./UnitVentilatorCycle3Wizard";
type Data = Record<string, any>;
const same = (a: any, b: any): boolean => {
  return sourceEqual(a, b);
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
  const [scheduleMode, setScheduleMode] = useState(false);
  const [heatPumpMode, setHeatPumpMode] = useState(false);
  const [ahuMode, setAhuMode] = useState(false);
  const [maddMzMode, setMaddMzMode] = useState(false);
  const [zoneSetpointMode, setZoneSetpointMode] = useState(false);
  const [seriesFanMode, setSeriesFanMode] = useState(false);
  const [unitVentilatorMode, setUnitVentilatorMode] = useState(false);
  const [catalog, setCatalog] = useState<Data | null>(null),
    [draft, setDraft] = useState<Data | null>(null),
    [preview, setPreview] = useState<Data | null>(null),
    [step, setStep] = useState(1),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceStringify(source),
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
    if (key.startsWith("dual_duct.") || key.startsWith("fan_coil.")) {
      const [section, field] = key.split(".");
      setDraft({
        ...draft,
        [section]: { ...draft[section], [field]: value },
      });
    } else if (key === "equipment") {
      const rest = { ...draft };
      delete rest.dual_duct;
      delete rest.fan_coil;
      if (rest.control === "not-applicable") rest.control = "position";
      setDraft(
        value === "fan-coil"
          ? {
              ...rest,
              equipment: value,
              control: "not-applicable",
              fan_coil: { ...catalog?.fan_coil?.defaults },
            }
          : value === "dual-duct"
            ? {
                ...rest,
                equipment: value,
                dual_duct: { ...catalog?.dual_duct?.defaults },
              }
            : { ...rest, equipment: value },
      );
    } else if (key === "control" && draft.equipment === "dual-duct") {
      setDraft({
        ...draft,
        control: value,
        dual_duct: { ...draft.dual_duct, layout: "" },
      });
    } else setDraft({ ...draft, [key]: value });
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
        result.profile_sha256 !== selectedCatalog?.profile_sha256 ||
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
      const result = await sourceApi("/equipment-wizard/preview", draft);
      if (!current(gen, base, choices)) return;
      const provenance = result.program?.metadata?.equipment_wizard;
      if (
        result.format !== "bms.equipment-wizard-preview" ||
        result.version !== 1 ||
        result.profile_sha256 !== selectedCatalog?.profile_sha256 ||
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
        !same(result.profile, selectedCatalog?.profile) ||
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
    const value = key.includes(".")
      ? draft?.[key.split(".")[0]]?.[key.split(".")[1]]
      : draft?.[key];
    return (
      <label>
        {label}
        <input
          type="number"
          step="any"
          aria-label={label}
          value={Number.isNaN(value) ? "" : (value ?? "")}
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
    const value = key.includes(".")
      ? draft?.[key.split(".")[0]]?.[key.split(".")[1]]
      : draft?.[key];
    return (
      <label>
        {label}
        <select
          aria-label={label}
          value={value ?? ""}
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
  const dual = draft?.equipment === "dual-duct";
  const fanCoil = draft?.equipment === "fan-coil";
  const selectedCatalog = fanCoil
    ? catalog?.fan_coil
    : dual
      ? catalog?.dual_duct
      : catalog;
  if (unitVentilatorMode)
    return (
      <UnitVentilatorCycle3Wizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setUnitVentilatorMode(false)}
      />
    );
  if (seriesFanMode)
    return (
      <SeriesFanVavWizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setSeriesFanMode(false)}
      />
    );
  if (zoneSetpointMode)
    return (
      <ZoneSetpointWizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setZoneSetpointMode(false)}
      />
    );
  if (maddMzMode)
    return (
      <MaddMzAhuWizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setMaddMzMode(false)}
      />
    );
  if (ahuMode)
    return (
      <MasdAhuWizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setAhuMode(false)}
      />
    );
  if (heatPumpMode)
    return (
      <HeatPumpWizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setHeatPumpMode(false)}
      />
    );
  if (scheduleMode)
    return (
      <ZoneGroupScheduleWizard
        source={source}
        onCreate={onCreate}
        onClose={onClose}
        onBack={() => setScheduleMode(false)}
      />
    );
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Equipment and sequence wizard"
        className="equipment-wizard"
      >
        <h1>Equipment and sequence wizard</h1>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setScheduleMode(true);
          }}
        >
          Zone-group schedule wizard
        </button>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setHeatPumpMode(true);
          }}
        >
          Heat-pump wizard
        </button>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setAhuMode(true);
          }}
        >
          Mixed-air AHU wizard
        </button>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setMaddMzMode(true);
          }}
        >
          MADD-MZ AHU wizard
        </button>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setZoneSetpointMode(true);
          }}
        >
          Zone setpoint wizard
        </button>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setSeriesFanMode(true);
          }}
        >
          Series-fan VAV wizard
        </button>
        <button
          disabled={busy}
          onClick={() => {
            epoch.current++;
            setPreview(null);
            setBusy(false);
            setUnitVentilatorMode(true);
          }}
        >
          Unit ventilator Cycle III wizard
        </button>
        <p>
          Create a separate editable portable VAV or fan-coil project.
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
                  ["dual-duct", "Dual duct: declared hot and cold decks"],
                  [
                    "fan-coil",
                    "Fan coil: separate modulating heating/cooling coils",
                  ],
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
                  proof. Dual duct creates separate logical hot/cold percentage
                  commands; integrated, proportional and incremental hardware
                  are not allocated. Fan coil creates separate logical
                  modulating valve commands and an explicit occupied/off fan
                  policy; it does not allocate physical valves, fan outputs or
                  protective interlocks.
                </p>
              </div>
            )}
            {step === 2 && (
              <>
                {fanCoil && (
                  <section aria-label="Fan-coil declarations">
                    <h2>Explicit fan-coil foundation</h2>
                    <div className="wizard-fields">
                      {choice("fan_coil.coils", "Fan-coil coil arrangement", [
                        ["", "Choose coil arrangement…"],
                        [
                          "separate-modulating",
                          "Separate modulating heating and cooling valves",
                        ],
                      ])}
                      {choice("fan_coil.fan", "Fan-coil fan type", [
                        ["", "Choose fan type…"],
                        ["single-speed", "Single-speed logical enable"],
                        [
                          "variable-speed",
                          "Variable-speed logical enable and percentage",
                        ],
                      ])}
                      {choice(
                        "fan_coil.fan_policy",
                        "Fan-coil occupied fan policy",
                        [
                          ["", "Choose occupied fan policy…"],
                          [
                            "continuous-occupied",
                            "Continuous while occupied and permitted",
                          ],
                          [
                            "cycle-on-demand",
                            "Cycle only while selected valve demand is positive",
                          ],
                        ],
                      )}
                      {choice(
                        "fan_coil.condensate",
                        "Fan-coil condensate policy",
                        [
                          ["", "Choose condensate policy…"],
                          ["none", "No condensate alarm input in this graph"],
                          ["disable-cooling", "Alarm disables cooling only"],
                          [
                            "shutdown-unit",
                            "Alarm shuts down both coils and fan",
                          ],
                        ],
                      )}
                      {draft.fan_coil?.fan === "variable-speed" && (
                        <>
                          {number(
                            "fan_coil.fan_min",
                            "Minimum logical fan speed (%)",
                          )}
                          {number(
                            "fan_coil.fan_max",
                            "Maximum logical fan speed (%)",
                          )}
                        </>
                      )}
                      {[
                        ["occupied_default", "Fan-coil occupied input default"],
                        [
                          "unit_enable_default",
                          "Fan-coil unit-enable input default",
                        ],
                        [
                          "energy_holdoff_default",
                          "Fan-coil energy-holdoff input default",
                        ],
                        ...(draft.fan_coil?.condensate &&
                        draft.fan_coil.condensate !== "none"
                          ? [
                              [
                                "condensate_default",
                                "Fan-coil condensate-alarm input default",
                              ],
                            ]
                          : []),
                      ].map(([field, label]) => (
                        <label key={field}>
                          <input
                            type="checkbox"
                            aria-label={label}
                            checked={draft.fan_coil?.[field] === true}
                            onChange={(e) =>
                              patch(`fan_coil.${field}`, e.target.checked)
                            }
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                    <p>
                      Unoccupied means off: both valves and fan stop, without
                      setbacks or frost protection. Unit-enable must be true,
                      energy-holdoff false and setpoints ordered. Condensate
                      policy is an explicit software declaration, not a physical
                      safety interlock.
                    </p>
                    <p>
                      Logical fan enable does not prove fan operation. Variable
                      fan speed maps the larger selected valve demand to
                      declared percentage limits only while enabled. No fan
                      proof, minimum-run timing, native allocation or complete
                      vendor/Title 24 sequence is provided.
                    </p>
                  </section>
                )}
                <div className="wizard-fields">
                  {!fanCoil &&
                    choice("control", "Damper control strategy", [
                      [
                        "position",
                        "Damper-position demand mapping (no airflow measurement)",
                      ],
                      [
                        "flow-feedback",
                        "Measured-airflow feedback with a separate flow loop",
                      ],
                    ])}
                  {dual &&
                    choice(
                      "dual_duct.layout",
                      "Dual-duct airflow pickup layout",
                      draft.control === "position"
                        ? [
                            ["", "Choose explicit layout…"],
                            ["none", "No airflow pickups: positions only"],
                          ]
                        : [
                            ["", "Choose explicit layout…"],
                            ["hot-cold", "Measured hot and cold deck flow"],
                            ["hot-total", "Measured hot deck and total flow"],
                            ["cold-total", "Measured cold deck and total flow"],
                          ],
                    )}
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
                {!fanCoil &&
                  (draft.control === "position" ? (
                    <div className="wizard-fields">
                      {number(
                        "damper_min",
                        dual
                          ? "Cold-deck minimum damper position (%)"
                          : "Minimum damper position (%)",
                      )}
                      {number(
                        "damper_max",
                        dual
                          ? "Cold-deck maximum damper position (%)"
                          : "Maximum damper position (%)",
                      )}
                      {dual &&
                        number(
                          "dual_duct.hot_damper_min",
                          "Hot-deck minimum damper position (%)",
                        )}
                      {dual &&
                        number(
                          "dual_duct.hot_damper_max",
                          "Hot-deck maximum damper position (%)",
                        )}
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
                        `${dual ? "Cold-deck minimum" : "Minimum"} declared airflow (${draft.flow_unit})`,
                      )}
                      {number(
                        "flow_max",
                        `${dual ? "Cold-deck maximum" : "Maximum"} declared airflow (${draft.flow_unit})`,
                      )}
                      {(!dual || draft.dual_duct?.layout !== "hot-total") &&
                        number(
                          "flow_default",
                          `${dual ? "Measured cold-deck airflow" : "Measured-airflow"} input default (${draft.flow_unit})`,
                        )}
                      {dual && (
                        <>
                          {number(
                            "dual_duct.hot_flow_min",
                            `Hot-deck minimum declared airflow (${draft.flow_unit})`,
                          )}
                          {number(
                            "dual_duct.hot_flow_max",
                            `Hot-deck maximum declared airflow (${draft.flow_unit})`,
                          )}
                          {draft.dual_duct?.layout !== "cold-total" &&
                            number(
                              "dual_duct.hot_flow_default",
                              `Measured hot-deck airflow input default (${draft.flow_unit})`,
                            )}
                          {["hot-total", "cold-total"].includes(
                            draft.dual_duct?.layout,
                          ) &&
                            number(
                              "dual_duct.total_flow_default",
                              `Measured total airflow input default (${draft.flow_unit})`,
                            )}
                        </>
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
                        desired-airflow signal and separate flow PI. Input
                        values must already represent calibrated airflow.
                        Increasing damper command is assumed to increase
                        airflow; physical direction/wiring remain unverified.
                        {dual &&
                          " The declared flow-loop gains apply to both independent deck loops. Two selected calibrated inputs derive the third flow by sum/difference; raw derived values are preserved. Total-only pickup control is unsupported."}
                      </p>
                    </div>
                  ))}
                {dual && (
                  <p>
                    Hot/cold deck minima are independent explicit declarations
                    and can permit simultaneous minimum flow. This establishes
                    no ventilation, energy, Guideline 36 or Title 24 compliance.
                    The authored portable guard gives both commands zero if
                    setpoints cross or measured/derived deck flow becomes
                    negative; PI integrals hold through zero error. Inactive
                    temperature demand is zero while its integral is retained.
                    This is neither vendor adaptive tuning nor a physical safety
                    interlock.
                  </p>
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
                      {sourceStringify(
                        {
                          choices: preview.choices,
                          inactive:
                            preview.program.metadata.equipment_wizard
                              .inactive_choices,
                          units: preview.profile.units,
                          nodes: preview.program.nodes,
                          edges: preview.program.edges,
                        },
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
              {fanCoil ? "Preview fan-coil project" : "Preview VAV project"}
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
