import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob, sourceApi } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  AHU_BASE,
  blobSha256,
  catalogResult,
  defaultFlags,
  previewResult,
  unitResult,
  type Data,
} from "./masdAhuContract";
import type { Program } from "./types";
import "./equipment-wizard.css";

export function MasdAhuWizard({
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
  const [catalog, setCatalog] = useState<Data | null>(null),
    [draft, setDraft] = useState<Data | null>(null),
    [preview, setPreview] = useState<{
      data: Data;
      key: string;
      sourceKey: string;
      choices: Data;
    } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceStringify(source),
    key = JSON.stringify({
      draft,
      profile: catalog?.profile_sha256,
      sourceKey,
    }),
    live = useRef(key);
  live.current = key;
  const current = (generation: number, owned: string) =>
    mounted.current && epoch.current === generation && live.current === owned;
  useEffect(() => {
    mounted.current = true;
    const generation = ++epoch.current;
    setBusy(true);
    api(AHU_BASE + "/catalog")
      .then((value) => {
        const checked = catalogResult(value);
        if (!mounted.current || epoch.current !== generation) return;
        setCatalog(checked);
        setDraft({
          ...checked.defaults,
          project_id: "ahu_" + crypto.randomUUID().replaceAll("-", ""),
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
      "Current editor changed. Preview again before creating an AHU project.",
    );
  }, [sourceKey]);
  function patch(field: string, value: any) {
    if (!draft || !catalog) return;
    epoch.current++;
    setPreview(null);
    setError("");
    setBusy(false);
    if (field === "fan")
      setDraft({
        ...draft,
        fan: value,
        variable_fan:
          value === "variable-speed"
            ? structuredClone(
                catalog.branch_defaults[draft.temperature_unit].variable_fan,
              )
            : null,
      });
    else if (field === "economizer")
      setDraft({
        ...draft,
        economizer: value,
        economizer_control: value
          ? structuredClone(
              catalog.branch_defaults[draft.temperature_unit].economizers[
                value
              ],
            )
          : null,
      });
    else if (field.includes(".")) {
      const [group, name] = field.split(".");
      setDraft({ ...draft, [group]: { ...draft[group], [name]: value } });
    } else setDraft({ ...draft, [field]: value });
  }
  async function units(temperature_unit: string) {
    if (
      !draft ||
      !catalog ||
      busy ||
      draft.temperature_unit === temperature_unit
    )
      return;
    const generation = ++epoch.current,
      owned = key,
      original = draft;
    setBusy(true);
    setPreview(null);
    setError("");
    try {
      const value = await api(AHU_BASE + "/units", {
        choices: original,
        temperature_unit,
      });
      const converted = unitResult(value, original, temperature_unit, catalog);
      if (current(generation, owned)) setDraft(converted);
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
      const value = previewResult(
        await sourceApi(AHU_BASE + "/preview", {
          choices,
        }),
        choices,
        catalog,
      );
      if (current(generation, owned))
        setPreview({ data: value, key: owned, sourceKey: base, choices });
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
      const result = await apiJsonDocument(
          AHU_BASE + "/export",
          {
            choices: accepted.choices,
          },
          true,
        ),
        // Rehydrate the original Program token tree from the authoritative Blob.
        // The helper's ordinary JSON projection cannot preserve numeric spelling.
        value = previewResult(
          parseSourceDocument(await result.blob.text()),
          accepted.choices,
          catalog,
        );
      if (
        result.blob.size > 8 * 1024 * 1024 ||
        result.headers?.get("X-File-SHA256") !==
          (await blobSha256(result.blob)) ||
        value.program_sha256 !== accepted.data.program_sha256 ||
        value.choices_sha256 !== accepted.data.choices_sha256 ||
        ![
          "program",
          "inputs",
          "outputs",
          "diagnostics",
          "inactive_choices",
          "can_create",
        ].every((field) => sourceEqual(value[field], accepted.data[field]))
      )
        throw new Error(
          "AHU export changed after this exact preview. Review again.",
        );
      if (current(generation, owned))
        saveBlob(result.blob, `ahu-review-${value.program_sha256}.json`);
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
        `Replace the editor contents of “${source.name}” with a separate new AHU project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
      )
    )
      return;
    if (onCreate(preview.data.program, sourceKey)) onClose();
    else {
      setPreview(null);
      setError("Current editor changed. Preview again before replacing it.");
    }
  }
  function value(field: string) {
    return field.split(".").reduce<any>((v, k) => v?.[k], draft);
  }
  function number(field: string, label: string, whole = false) {
    const v = value(field);
    return (
      <label>
        {label}
        <input
          aria-label={label}
          type="number"
          step={whole ? "1" : "any"}
          value={Number.isNaN(v) ? "" : (v ?? "")}
          onChange={(e) => {
            const entered =
              e.target.value === "" ? NaN : Number(e.target.value);
            // Match the authored Choices normalization, never native/source atoms.
            patch(field, entered === 0 ? 0 : entered);
          }}
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
          maxLength={maxLength}
          value={value(field) ?? ""}
          onChange={(e) => patch(field, e.target.value)}
        />
      </label>
    );
  }
  function select(
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
          value={value(field) ?? ""}
          onChange={(e) => patch(field, e.target.value)}
        >
          {explicit && <option value="">Choose explicitly…</option>}
          {options.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
    );
  }
  function flag(field: string, label: string) {
    return (
      <label key={field}>
        <input
          type="checkbox"
          aria-label={label}
          checked={Boolean(value(field))}
          onChange={(e) => patch(field, e.target.checked)}
        />
        {label}
      </label>
    );
  }
  const displayed = preview?.key === key ? preview : null,
    configured = Boolean(draft?.fan && draft?.economizer);
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Mixed-air AHU wizard"
        className="equipment-wizard"
      >
        <h1>Mixed-air single-duct AHU foundation</h1>
        <p>
          Create an editable ordinary graph for one supply fan, downstream
          supply-air temperature, separate modulating heating/cooling valves and
          a common mixing-damper command. Target identities remain declarations;
          native compilation, allocation and deployment are unverified.
        </p>
        <p>
          Minimum outside air is a damper-position command, not measured airflow
          or ventilation acceptance. Good logical permission/proof loss gates
          commands; bad required input quality rolls back the whole scan and
          retains previous outputs. Physical shutdown, smoke/freeze protection
          and native JCI sequence equivalence are not established.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <h2>Project and declared target</h2>
            <div className="wizard-fields">
              {text("name", "AHU project name", 200)}
              {select("family", "AHU declared controller family", [
                ["universal-runtime", "Portable runtime"],
                ["johnson-fx", "Johnson Controls FX"],
                ["johnson-metasys", "Johnson Controls Metasys"],
              ])}
              {text("model", "AHU declared model")}
              {text("firmware", "AHU declared firmware")}
              {text("release_mode", "AHU declared release mode")}
              {number("scan_seconds", "AHU scan interval (seconds)", true)}
              <label>
                AHU temperature units
                <select
                  aria-label="AHU temperature units"
                  value={draft.temperature_unit}
                  disabled={!configured}
                  onChange={(e) => void units(e.target.value)}
                >
                  <option value="degF">Degrees Fahrenheit</option>
                  <option value="degC">Degrees Celsius</option>
                </select>
              </label>
            </div>
            <h2>Single supply fan and independent proof</h2>
            <div className="wizard-fields">
              {select(
                "fan",
                "AHU supply fan",
                [
                  ["constant-speed", "Single constant-speed fan"],
                  [
                    "variable-speed",
                    "Single variable-speed fan with Pa feedback",
                  ],
                ],
                true,
              )}
              {number(
                "proof_seconds",
                "AHU continuous proof interval (seconds)",
                true,
              )}
              {number(
                "stabilize_seconds",
                "AHU stabilization interval (seconds)",
                true,
              )}
              {number(
                "startup_timeout_seconds",
                "AHU startup deadline (seconds)",
                true,
              )}
              {number(
                "recovery_timeout_seconds",
                "AHU proof-loss recovery deadline (seconds)",
                true,
              )}
            </div>
            <p>
              The fan starts before separate proof. Coils and outside-air
              command stay closed until proof and stabilization complete. Proof
              chatter does not restart the overall deadline. Timeout latches a
              fault; only a rising reset with no run request clears it. Holding
              reset does not retry automatically.
            </p>
            {draft.variable_fan && (
              <>
                <h3>Variable-fan pressure loop; Pa only</h3>
                <div className="wizard-fields">
                  {number(
                    "variable_fan.pressure_default_pa",
                    "AHU default duct static pressure (Pa)",
                  )}
                  {number(
                    "variable_fan.setpoint_pa",
                    "AHU duct static setpoint (Pa)",
                  )}
                  {number(
                    "variable_fan.minimum_percent",
                    "AHU minimum fan command (%)",
                  )}
                  {number(
                    "variable_fan.startup_percent",
                    "AHU startup fan command (%)",
                  )}
                  {number(
                    "variable_fan.maximum_percent",
                    "AHU maximum fan command (%)",
                  )}
                  {number(
                    "variable_fan.kp",
                    "AHU pressure proportional gain (%/Pa)",
                  )}
                  {number(
                    "variable_fan.ki",
                    "AHU pressure integral gain (%/(Pa·s))",
                  )}
                </div>
                <p>
                  Startup speed applies before readiness. Ready operation uses
                  actual logical Pa feedback. Pressure settings do not change
                  with temperature units.
                </p>
              </>
            )}
            <h2>Supply temperature and separate valve loops</h2>
            <div className="wizard-fields">
              {number("sat_default", "AHU default supply-air temperature")}
              {number("sat_setpoint", "AHU supply-air center setpoint")}
              {number(
                "temperature_band",
                "AHU heating/cooling temperature band",
              )}
              {number("entry_delta", "AHU mode-entry temperature difference")}
              {number(
                "release_delta",
                "AHU mode-release temperature difference",
              )}
              {number("heating_kp", "AHU heating proportional gain (%/degree)")}
              {number("heating_ki", "AHU heating integral gain (%/(degree·s))")}
              {number("cooling_kp", "AHU cooling proportional gain (%/degree)")}
              {number("cooling_ki", "AHU cooling integral gain (%/(degree·s))")}
              {number(
                "low_threshold_percent",
                "AHU low-command release threshold (%)",
              )}
              {number(
                "release_seconds",
                "AHU low-command release interval (seconds)",
                true,
              )}
            </div>
            <p>
              Heating and cooling setpoints lie half the positive band
              below/above the center. The band must exceed twice the release
              difference. Active PI may hold a nonzero command at setpoint;
              release also needs a low prior command and the declared
              temperature/dwell condition. Inactive integrals hold memory. These
              authored modes do not encode native JCI state numbers.
            </p>
            <h2>Position-only minimum outside air and economizer</h2>
            <div className="wizard-fields">
              {number(
                "minimum_oa_percent",
                "AHU minimum outside-air position command (%)",
              )}
              {select(
                "economizer",
                "AHU economizer suitability",
                [
                  ["off", "Off"],
                  ["fixed-drybulb", "Fixed outdoor dry-bulb"],
                  [
                    "differential-drybulb",
                    "Outdoor versus return dry-bulb with absolute high limit",
                  ],
                ],
                true,
              )}
            </div>
            {draft.economizer_control && (
              <>
                <div className="wizard-fields">
                  {number(
                    "economizer_control.oa_default",
                    "AHU default outdoor-air temperature",
                  )}
                  {number(
                    "economizer_control.enable_below",
                    "AHU economizer enable below temperature",
                  )}
                  {number(
                    "economizer_control.disable_above",
                    "AHU economizer disable above temperature",
                  )}
                  {draft.economizer === "differential-drybulb" && (
                    <>
                      {number(
                        "economizer_control.ra_default",
                        "AHU default return-air temperature",
                      )}
                      {number(
                        "economizer_control.differential_on",
                        "AHU return-minus-outdoor enable difference",
                      )}
                      {number(
                        "economizer_control.differential_off",
                        "AHU return-minus-outdoor disable difference",
                      )}
                    </>
                  )}
                  {number(
                    "economizer_control.kp",
                    "AHU economizer proportional gain (%/degree)",
                  )}
                  {number(
                    "economizer_control.ki",
                    "AHU economizer integral gain (%/(degree·s))",
                  )}
                  {number(
                    "economizer_control.assist_seconds",
                    "AHU economizer high-command assist interval (seconds)",
                    true,
                  )}
                  {number(
                    "economizer_control.high_threshold_percent",
                    "AHU economizer high selected-position threshold (%)",
                  )}
                  {flag(
                    "economizer_control.enable_default",
                    "AHU default economizer enabled",
                  )}
                </div>
                <p>
                  Economizer cooling precedes mechanical assist. Warm supply air
                  with a prior high selected damper command for the assist
                  interval admits integrated cooling at 100% outside-air
                  command. A high minimum-position floor can satisfy that
                  command test; no actuator position or airflow is measured.
                  Dry-bulb suitability omits humidity/enthalpy and freeze
                  protection.
                </p>
              </>
            )}
            <p>
              Select fan and economizer before converting units. Conversion
              couples absolute temperatures, temperature differences and
              reciprocal degree-based gains; Pa, percentages, flags and seconds
              stay unchanged. Branch changes clear irrelevant
              pressure/return-air/economizer fields and restore source-qualified
              defaults for the selected units.
            </p>
            <h2>Initial logical inputs</h2>
            <div className="wizard-fields">
              {defaultFlags.map((field, i) =>
                flag(
                  field,
                  [
                    "AHU default occupied",
                    "AHU default unit enabled",
                    "AHU default energy holdoff",
                    "AHU default fan proven",
                    "AHU default fan reset",
                  ][i],
                ),
              )}
            </div>
            <p>
              These are initial simulator values, not live sensor readings or
              verified physical permissions. Unit enable and fan proof default
              false. All durations use whole seconds aligned to the scan;
              startup/recovery must allow proof plus stabilization and at least
              one more scan. A new process starts timers and latches fresh.
            </p>
          </fieldset>
        )}
        {busy && <p role="status">Preparing local AHU evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="AHU preview">
            <h2>{displayed.data.program.name}</h2>
            <p>
              {displayed.data.program.nodes.length} editable blocks ·{" "}
              {displayed.data.program.edges.length} connections. Native
              compilation and controller writes: false.
            </p>
            <p>
              Program SHA-256 <code>{displayed.data.program_sha256}</code>
              <br />
              Choices SHA-256 <code>{displayed.data.choices_sha256}</code>
            </p>
            <h3>Portable graph validation</h3>
            {displayed.data.diagnostics.length ? (
              displayed.data.diagnostics.map((r: any, i: number) => (
                <p key={i}>
                  {r.level}: {r.message}
                </p>
              ))
            ) : (
              <p>No portable graph errors.</p>
            )}
            {(
              [
                ["inputs", "Logical inputs; defaults are simulated"],
                [
                  "outputs",
                  "Logical output commands and authored state indicators",
                ],
              ] as const
            ).map(([group, label]) => (
              <table key={group} aria-label={`AHU ${group}`}>
                <caption>{label}</caption>
                <thead>
                  <tr>
                    <th>Editable ID / label</th>
                    <th>Type / unit</th>
                    {group === "inputs" && <th>Default</th>}
                  </tr>
                </thead>
                <tbody>
                  {displayed.data[group].map((r: any) => (
                    <tr key={r.id}>
                      <td>
                        {r.id} · {r.label}
                      </td>
                      <td>
                        {r.value_type} · {r.unit || "no unit"}
                      </td>
                      {group === "inputs" && <td>{String(r.default)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
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
            <h3>Separate engineering work</h3>
            <ul>
              {catalog?.profile.gaps.map((gap: string) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
            <button disabled={busy} onClick={() => void exportReview()}>
              Export original AHU review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable AHU project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>Cancel AHU wizard</button>
          <button onClick={onBack}>Back to equipment wizard</button>
          {busy && (
            <button
              onClick={() => {
                epoch.current++;
                setBusy(false);
                setPreview(null);
                setError(
                  "Pending AHU response ignored. Local generation may finish; no field operation was started.",
                );
              }}
            >
              Discard pending AHU response
            </button>
          )}
          <button
            disabled={busy || !draft || !configured}
            onClick={() => void review()}
          >
            Preview AHU project
          </button>
        </div>
      </section>
    </div>
  );
}
