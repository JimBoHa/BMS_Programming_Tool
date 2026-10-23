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
} from "./maddMzAhuContract";
import type { Program } from "./types";
import "./equipment-wizard.css";

export function MaddMzAhuWizard({
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
          project_id: "maddmz_" + crypto.randomUUID().replaceAll("-", ""),
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
      "Current editor changed. Preview again before creating a dual-deck AHU project.",
    );
  }, [sourceKey]);
  function patch(field: string, value: any) {
    if (!draft || !catalog) return;
    epoch.current++;
    setPreview(null);
    setError("");
    setBusy(false);
    if (field === "economizer")
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
          "Dual-deck AHU export changed after this exact preview. Review again.",
        );
      if (current(generation, owned))
        saveBlob(
          result.blob,
          `madd-mz-ahu-review-${value.program_sha256}.json`,
        );
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
        `Replace the editor contents of “${source.name}” with a separate new dual-deck AHU project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
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
    configured = Boolean(draft?.economizer);
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="MADD-MZ AHU wizard"
        className="equipment-wizard"
      >
        <h1>MADD-MZ AHU-only independent hot/cold decks</h1>
        <p>
          Create an editable ordinary graph for one single-speed supply fan,
          separate hot/cold deck temperatures and independently adjustable fixed
          target inputs, separate heating/cooling valves, and a common mixing
          command. Hot heating may run with any cold-deck cooling state. Target
          identities remain declarations; native compilation, allocation and
          deployment are unverified. Zone dampers and room control are absent.
        </p>
        <p>
          Minimum outside air is a position command, not measured airflow. Good
          false permission or out-of-range runtime targets inhibit commands and
          reset readiness. Bad required input quality instead rolls back the
          whole scan, retaining both decks and fan. Neither behavior establishes
          physical shutdown, native JCI, Title 24 or safety acceptance.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <h2>Project and declared target</h2>
            <div className="wizard-fields">
              {text("name", "Dual-deck AHU project name", 200)}
              {select("family", "Dual-deck AHU declared controller family", [
                ["universal-runtime", "Portable runtime"],
                ["johnson-fx", "Johnson Controls FX"],
                ["johnson-metasys", "Johnson Controls Metasys"],
              ])}
              {text("model", "Dual-deck AHU declared model")}
              {text("firmware", "Dual-deck AHU declared firmware")}
              {text("release_mode", "Dual-deck AHU declared release mode")}
              {number(
                "scan_seconds",
                "Dual-deck AHU scan interval (seconds)",
                true,
              )}
              <label>
                Dual-deck AHU temperature units
                <select
                  aria-label="Dual-deck AHU temperature units"
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
              <p>
                Configuration: Dual-deck AHU only. Supply fan: single speed.
                Return, variable-speed and zone fans are outside this profile.
              </p>
              {number(
                "proof_seconds",
                "Dual-deck AHU continuous proof interval (seconds)",
                true,
              )}
              {number(
                "stabilize_seconds",
                "Dual-deck AHU stabilization interval (seconds)",
                true,
              )}
              {number(
                "startup_timeout_seconds",
                "Dual-deck AHU startup deadline (seconds)",
                true,
              )}
              {number(
                "recovery_timeout_seconds",
                "Dual-deck AHU proof-loss recovery deadline (seconds)",
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
            <h2>Independent hot and cold deck feedback</h2>
            <div className="wizard-fields">
              {number(
                "hot_deck_default",
                "Dual-deck AHU default hot-deck temperature",
              )}
              {number(
                "hot_deck_setpoint",
                "Dual-deck AHU hot-deck target input default",
              )}
              {number(
                "cold_deck_default",
                "Dual-deck AHU default cold-deck temperature",
              )}
              {number(
                "cold_deck_setpoint",
                "Dual-deck AHU cold-deck target input default",
              )}
              {number(
                "hot_entry_delta",
                "Dual-deck AHU hot-deck entry difference",
              )}
              {number(
                "hot_release_delta",
                "Dual-deck AHU hot-deck release difference",
              )}
              {number(
                "cold_entry_delta",
                "Dual-deck AHU cold-deck entry difference",
              )}
              {number(
                "cold_release_delta",
                "Dual-deck AHU cold-deck release difference",
              )}
              {number(
                "hot_kp",
                "Dual-deck AHU hot-deck proportional gain (%/degree)",
              )}
              {number(
                "hot_ki",
                "Dual-deck AHU hot-deck integral gain (%/(degree·s))",
              )}
              {number(
                "cold_kp",
                "Dual-deck AHU cold-deck proportional gain (%/degree)",
              )}
              {number(
                "cold_ki",
                "Dual-deck AHU cold-deck integral gain (%/(degree·s))",
              )}
              {number(
                "low_threshold_percent",
                "Dual-deck AHU low-command release threshold (%)",
              )}
              {number(
                "release_seconds",
                "Dual-deck AHU low-command release interval (seconds)",
                true,
              )}
            </div>
            <p>
              Each deck has its own temperature, target, entry/release
              differences and P/PI gains. A fixed target has no reset curve; it
              remains an adjustable logical input. Hot heating and cold cooling
              may operate together, including cold economizer operation. Active
              PI retains a needed nonzero command at its own target. Inactive
              integrals hold memory; low prior command plus the release
              condition/dwell releases that deck. No hot-deck cooling or
              cold-deck preheat is generated.
            </p>
            <p>
              Good finite runtime targets outside -100..200 °C equivalents
              inhibit all commands and reset readiness without a new proof trip.
              Equal or reversed targets and measured deck temperatures do not
              inhibit; spread/order outputs are engineering diagnostics only. An
              existing proof fault still needs its explicit reset while the
              operator run request is off. These are authored software policies.
            </p>
            <h2>Position-only minimum outside air and economizer</h2>
            <div className="wizard-fields">
              {number(
                "minimum_oa_percent",
                "Dual-deck AHU minimum outside-air position command (%)",
              )}
              {select(
                "economizer",
                "Dual-deck AHU economizer suitability",
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
                    "Dual-deck AHU default outdoor-air temperature",
                  )}
                  {number(
                    "economizer_control.enable_below",
                    "Dual-deck AHU economizer enable below temperature",
                  )}
                  {number(
                    "economizer_control.disable_above",
                    "Dual-deck AHU economizer disable above temperature",
                  )}
                  {draft.economizer === "differential-drybulb" && (
                    <>
                      {number(
                        "economizer_control.ra_default",
                        "Dual-deck AHU default return-air temperature",
                      )}
                      {number(
                        "economizer_control.differential_on",
                        "Dual-deck AHU return-minus-outdoor enable difference",
                      )}
                      {number(
                        "economizer_control.differential_off",
                        "Dual-deck AHU return-minus-outdoor disable difference",
                      )}
                    </>
                  )}
                  {number(
                    "economizer_control.kp",
                    "Dual-deck AHU economizer proportional gain (%/degree)",
                  )}
                  {number(
                    "economizer_control.ki",
                    "Dual-deck AHU economizer integral gain (%/(degree·s))",
                  )}
                  {number(
                    "economizer_control.assist_seconds",
                    "Dual-deck AHU economizer high-command assist interval (seconds)",
                    true,
                  )}
                  {number(
                    "economizer_control.high_threshold_percent",
                    "Dual-deck AHU economizer high selected-position threshold (%)",
                  )}
                  {flag(
                    "economizer_control.enable_default",
                    "Dual-deck AHU default economizer enabled",
                  )}
                </div>
                <p>
                  Cold-deck economizer cooling precedes mechanical assist. Warm
                  cold-deck air with a prior high selected damper command for
                  the assist interval admits integrated cooling at 100%
                  outside-air command. A high minimum-position floor can satisfy
                  that command test; no actuator position or airflow is
                  measured. Hot-deck heating does not disable cold-deck
                  economizing. Dry-bulb suitability omits humidity/enthalpy and
                  freeze protection.
                </p>
              </>
            )}
            <p>
              Select economizer before converting units. Conversion couples both
              deck/OA/RA absolute temperatures, differences and reciprocal
              degree-based gains. Percentages, flags and seconds stay unchanged.
              Branch changes remove irrelevant economizer/return-air fields and
              restore defaults for the selected units. Coupled F/C parameters do
              not guarantee identical finite-precision PI/state trajectories.
            </p>
            <p>
              The cold_economizer_active indicator means the cold-deck
              economizer PI is active in state 1. In integrated state 2 that
              PI is inactive while the mixing command stays at 100% and
              mechanical cooling regulates the cold deck. This flag does not
              report physical damper operation or outdoor airflow.
            </p>
            <h2>Initial logical inputs</h2>
            <div className="wizard-fields">
              {defaultFlags.map((field, i) =>
                flag(
                  field,
                  [
                    "Dual-deck AHU default occupied",
                    "Dual-deck AHU default unit enabled",
                    "Dual-deck AHU default energy holdoff",
                    "Dual-deck AHU default fan proven",
                    "Dual-deck AHU default fan reset",
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
        {busy && <p role="status">Preparing local dual-deck AHU evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="Dual-deck AHU preview">
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
              <table key={group} aria-label={`Dual-deck AHU ${group}`}>
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
              Export original Dual-deck AHU review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable Dual-deck AHU project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>Cancel Dual-deck AHU wizard</button>
          <button onClick={onBack}>Back to equipment wizard</button>
          {busy && (
            <button
              onClick={() => {
                epoch.current++;
                setBusy(false);
                setPreview(null);
                setError(
                  "Pending dual-deck AHU response ignored. Local generation may finish; no field operation was started.",
                );
              }}
            >
              Discard pending Dual-deck AHU response
            </button>
          )}
          <button
            disabled={busy || !draft || !configured}
            onClick={() => void review()}
          >
            Preview Dual-deck AHU project
          </button>
        </div>
      </section>
    </div>
  );
}
