import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob, sourceApi } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  SERIES_BASE,
  blobSha256,
  catalogResult,
  previewResult,
  unitResult,
  type Data,
} from "./seriesFanVavContract";
import type { Program } from "./types";
import "./equipment-wizard.css";

export function SeriesFanVavWizard({
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
    api(SERIES_BASE + "/catalog")
      .then(async (value) => {
        const checked = await catalogResult(value);
        if (!mounted.current || epoch.current !== generation) return;
        setCatalog(checked);
        setDraft({
          ...checked.defaults,
          project_id: "series_vav_" + crypto.randomUUID().replaceAll("-", ""),
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
      "Current editor changed. Preview again before creating a series-fan VAV project.",
    );
  }, [sourceKey]);
  function patch(field: string, value: any) {
    if (!draft || !catalog) return;
    epoch.current++;
    setPreview(null);
    setError("");
    setBusy(false);
    setDraft({ ...draft, [field]: value });
  }

  async function units(temperature_unit: string, flow_unit: string) {
    if (
      !draft ||
      !catalog ||
      busy ||
      (draft.temperature_unit === temperature_unit &&
        draft.flow_unit === flow_unit)
    )
      return;
    const generation = ++epoch.current,
      owned = key,
      original = draft;
    setBusy(true);
    setPreview(null);
    setError("");
    try {
      const value = await api(SERIES_BASE + "/units", {
        choices: original,
        temperature_unit,
        flow_unit,
      });
      const converted = unitResult(
        value,
        original,
        temperature_unit,
        flow_unit,
        catalog,
      );
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
        await sourceApi(SERIES_BASE + "/preview", {
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
          SERIES_BASE + "/export",
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
          "Series-fan VAV export changed after this exact preview. Review again.",
        );
      if (current(generation, owned))
        saveBlob(
          result.blob,
          `series-fan-vav-review-${value.program_sha256}.json`,
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
        `Replace the editor contents of “${source.name}” with a separate new series-fan VAV project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
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
    configured = Boolean(draft);
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Series-fan VAV wizard"
        className="equipment-wizard"
      >
        <h1>Effective series-fan VAV composer</h1>
        <p>
          Create a separate editable ordinary graph for a real single-speed
          series fan, calibrated primary airflow, primary damper and
          proportional hot-water reheat. The fan is in the common discharge
          path. Inline reheat without a fan and parallel fan reheat remain
          separate applications. Cold primary air is assumed. Target identities
          do not establish native JCI compilation, CAF transfer, physical
          commissioning, Guideline 36 or Title 24 acceptance.
        </p>
        <p>
          Required bad input quality rolls back the complete scan, retaining
          prior timers, integrals and commands, potentially including positive
          outputs. Before the first successful scan, host outputs can be empty
          or zero; no safe startup set is preseeded. Logical commands are not
          physical protections.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <h2>Project and declared target</h2>
            <div className="wizard-fields">
              {text("name", "Series VAV project name", 200)}
              {select("family", "Series VAV declared controller family", [
                ["universal-runtime", "Portable runtime"],
                ["johnson-fx", "Johnson Controls FX"],
                ["johnson-metasys", "Johnson Controls Metasys"],
              ])}
              {text("model", "Series VAV declared model")}
              {text("firmware", "Series VAV declared firmware")}
              {text("release_mode", "Series VAV declared release mode")}
              {number(
                "scan_seconds",
                "Series VAV scan interval (seconds)",
                true,
              )}
              <label>
                Series VAV temperature units
                <select
                  aria-label="Series VAV temperature units"
                  value={draft.temperature_unit}
                  onChange={(e) => void units(e.target.value, draft.flow_unit)}
                >
                  <option value="degF">Degrees Fahrenheit</option>
                  <option value="degC">Degrees Celsius</option>
                </select>
              </label>
              <label>
                Series VAV primary flow units
                <select
                  aria-label="Series VAV primary flow units"
                  value={draft.flow_unit}
                  onChange={(e) =>
                    void units(draft.temperature_unit, e.target.value)
                  }
                >
                  <option value="cfm">cfm</option>
                  <option value="L/s">Liters per second</option>
                </select>
              </label>
            </div>
            <p>
              Fixed topology: occupied-only · single-speed series fan ·
              proportional hot water · calibrated primary-flow feedback. No
              variable fan, electric heat, primary pressure conversion or
              unoccupied recovery is generated.
            </p>
            <h2>Logical temperatures and held zone control</h2>
            <div className="wizard-fields">
              {number("zone_default", "Zone temperature default")}
              {number("heating_setpoint", "Heating setpoint default")}
              {number("cooling_setpoint", "Cooling setpoint default")}
              {number("entry_delta", "Entry difference")}
              {number("release_delta", "Release difference")}
              {number("heating_kp", "Heating proportional gain")}
              {number("heating_ki", "Heating integral gain")}
              {number("cooling_kp", "Cooling proportional gain")}
              {number("cooling_ki", "Cooling integral gain")}
            </div>
            <p>
              Heating and cooling setpoints are external required logical
              inputs; these values are their simulation defaults. Values from
              the Zone setpoint wizard may be supplied through ordinary graph
              edits or simulated inputs; no automatic link is made. Ordered
              setpoints and zone temperature must remain within -50..100 °C
              equivalents. Entry difference must exceed nonnegative release
              difference.
            </p>
            <p>
              Thermal modes are mutually exclusive. A mode can retain a nonzero
              integral command at setpoint; release also depends on the previous
              selected demand reaching zero. Inactive loops hold their integrals
              while selected outputs are zero. Gains are percent per temperature
              difference (integral gain additionally per second); zero integral
              gain selects proportional-only behavior.
            </p>
            <h2>Calibrated primary airflow and cascade</h2>
            <div className="wizard-fields">
              {number("primary_flow_min", "Primary minimum airflow")}
              {number("primary_flow_max", "Primary maximum airflow")}
              {number("primary_flow_default", "Primary default airflow")}
              {number("flow_kp", "Flow proportional gain")}
              {number("flow_ki", "Flow integral gain")}
            </div>
            <p>
              Cooling demand maps to minimum/maximum PRIMARY airflow. A forward
              primary-flow P/PI loop regulates the damper whenever ready,
              including neutral/heating operation. Flow gains are percent per
              selected flow unit (integral gain additionally per second). Values
              require separately calibrated feedback; broad authored limits do
              not certify physical operating ranges.
            </p>
            <p>
              Primary airflow can be zero while a real series fan recirculates.
              Hot-water reheat uses logical fan readiness/proof; primary airflow
              is not total coil airflow proof. Measured total flow, discharge
              limits, wiring and physical heater protections remain separate
              engineering work.
            </p>
            <h2>Close estimate, proof and latched fault</h2>
            <div className="wizard-fields">
              {number("close_seconds", "Damper close estimate (seconds)", true)}
              {number("proof_seconds", "Stable proof interval (seconds)", true)}
              {number(
                "startup_timeout_seconds",
                "Startup deadline (seconds)",
                true,
              )}
              {flag("occupied_default", "Initial occupied")}
              {flag("unit_enable_default", "Initial unit enabled")}
              {flag("energy_holdoff_default", "Initial energy holdoff")}
              {flag("fan_proven_default", "Initial fan proven")}
              {flag("fan_reset_default", "Initial fan reset")}
            </div>
            <p>
              Raw request is occupied AND unit enable AND NOT energy holdoff.
              Default 90-second close is a timing estimate, never measured
              closure. With one-second scans, requested scans 1–90 keep the fan
              off; scan 91 starts it. Stable proof counts only after fan
              request; default 15 seconds completes on scan 105 when proof stays
              true.
            </p>
            <p>
              The independent default 60-second startup deadline spans proof
              chatter. Stable proof completing at the exact deadline wins; a
              true deadline flag alone is not a trip. Good-quality proof loss
              after a ready scan immediately latches and stops ordinary
              commands. Reset requires RAW request off plus a fresh rising
              fan-reset edge. Invalid good-quality values inhibit
              commands/readiness and restart timing but cannot impersonate
              operator off or reset the latch.
            </p>
            <p>
              All durations are positive whole seconds aligned to the declared
              scan, and the startup deadline cannot precede stable proof.
              Conversion couples absolute temperatures, differences,
              inverse-temperature gains, primary flows and inverse-flow gains.
              Binary64 and current native REAL rounding differ; parameter
              conversion does not promise unit-invariant trajectories or native
              tuning equivalence.
            </p>
          </fieldset>
        )}
        {busy && <p role="status">Preparing local series-fan VAV evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="Series-fan VAV preview">
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
                [
                  "inputs",
                  "Nine required logical inputs; defaults are simulated",
                ],
                [
                  "outputs",
                  "Logical commands, primary feedback and authored state indicators",
                ],
              ] as const
            ).map(([group, label]) => (
              <table key={group} aria-label={`Series-fan VAV ${group}`}>
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
            <p>
              series_state: 0 off, 1 close, 2 fan-start, 3 run, 4 fault.
              thermal_state: 0 neutral, 1 heating, 2 cooling. These authored
              codes are not native enumerations. close_complete and
              fan_proof_stable are logical timer results; zone_range_valid is
              value range admission, distinct from quality. A deadline
              indication can be true on successful proof completion.
            </p>
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
              Export original series-fan VAV review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable series-fan VAV project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>Cancel series-fan VAV wizard</button>
          <button onClick={onBack}>Back to equipment wizard</button>
          {busy && (
            <button
              onClick={() => {
                epoch.current++;
                setBusy(false);
                setPreview(null);
                setError(
                  "Pending series-fan VAV response ignored. Local generation may finish; no field operation was started.",
                );
              }}
            >
              Discard pending series-fan VAV response
            </button>
          )}
          <button
            disabled={busy || !draft || !configured}
            onClick={() => void review()}
          >
            Preview series-fan VAV project
          </button>
        </div>
      </section>
    </div>
  );
}
