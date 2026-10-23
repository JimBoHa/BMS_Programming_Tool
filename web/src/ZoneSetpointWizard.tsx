import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob, sourceApi } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  ZONE_BASE,
  blobSha256,
  catalogResult,
  previewResult,
  unitResult,
  type Data,
} from "./zoneSetpointContract";
import type { Program } from "./types";
import "./equipment-wizard.css";

export function ZoneSetpointWizard({
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
    api(ZONE_BASE + "/catalog")
      .then((value) => {
        const checked = catalogResult(value);
        if (!mounted.current || epoch.current !== generation) return;
        setCatalog(checked);
        setDraft({
          ...checked.defaults,
          project_id: "zone_sp_" + crypto.randomUUID().replaceAll("-", ""),
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
      "Current editor changed. Preview again before creating a zone-setpoint project.",
    );
  }, [sourceKey]);
  function patch(field: string, value: any) {
    if (!draft || !catalog) return;
    epoch.current++;
    setPreview(null);
    setError("");
    setBusy(false);
    if (["population", "window"].includes(field))
      setDraft({
        ...draft,
        [field]: value,
        [field + "_control"]: value
          ? structuredClone(
              catalog.branch_defaults[draft.temperature_unit][field][value],
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
      const value = await api(ZONE_BASE + "/units", {
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
        await sourceApi(ZONE_BASE + "/preview", {
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
          ZONE_BASE + "/export",
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
          "Zone-setpoint export changed after this exact preview. Review again.",
        );
      if (current(generation, owned))
        saveBlob(
          result.blob,
          `zone-setpoint-review-${value.program_sha256}.json`,
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
        `Replace the editor contents of “${source.name}” with a separate new zone-setpoint project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
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
    configured = Boolean(draft?.population && draft?.window);
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Zone setpoint wizard"
        className="equipment-wizard"
      >
        <h1>Effective zone target composer</h1>
        <p>
          Create a separate editable ordinary graph that selects heating/cooling
          targets. It does not generate unit enable, unoccupied equipment
          operation, sensor/MV allocation or airflow commands. Declared
          FX/Metasys target identities do not establish native compiler,
          deployment, Guideline 36 or Title 24 acceptance.
        </p>
        <p>
          Bad required input quality rolls back the complete scan and retains
          prior targets/timers, even during a window override. Before the first
          successful scan, existing host outputs may be empty or zero; no safe
          startup pair is preseeded. These targets do not establish physical
          shutdown or protection.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <h2>Project and declared target</h2>
            <div className="wizard-fields">
              {text("name", "Zone target project name", 200)}
              {select("family", "Zone target declared controller family", [
                ["universal-runtime", "Portable runtime"],
                ["johnson-fx", "Johnson Controls FX"],
                ["johnson-metasys", "Johnson Controls Metasys"],
              ])}
              {text("model", "Zone target declared model")}
              {text("firmware", "Zone target declared firmware")}
              {text("release_mode", "Zone target declared release mode")}
              {number(
                "scan_seconds",
                "Zone target scan interval (seconds)",
                true,
              )}
              <label>
                Zone target temperature units
                <select
                  aria-label="Zone target temperature units"
                  value={draft.temperature_unit}
                  disabled={!configured}
                  onChange={(e) => void units(e.target.value)}
                >
                  <option value="degF">Degrees Fahrenheit</option>
                  <option value="degC">Degrees Celsius</option>
                </select>
              </label>
            </div>
            <h2>Fixed occupied and unoccupied pairs</h2>
            <div className="wizard-fields">
              {number("occupied_heating_setpoint", "Occupied heating target")}
              {number("occupied_cooling_setpoint", "Occupied cooling target")}
              {number(
                "unoccupied_heating_setpoint",
                "Unoccupied heating target",
              )}
              {number(
                "unoccupied_cooling_setpoint",
                "Unoccupied cooling target",
              )}
              {flag("scheduled_occupied_default", "Initial scheduled occupied")}
            </div>
            <p>
              Scheduled occupancy selects one fixed absolute pair. This is a
              Boolean input, not a native occupancy-mode enumeration. Every
              reachable heating target must be below cooling and within -50..100
              °C equivalents.
            </p>
            <h2>Occupied but unpopulated offset</h2>
            <div className="wizard-fields">
              {select(
                "population",
                "Population target branch",
                [
                  ["off", "Off"],
                  ["timed-offset", "Timed deadband-expanding offset"],
                ],
                true,
              )}
              {draft.population_control && (
                <>
                  {number(
                    "population_control.offset",
                    "Population offset (temperature difference)",
                  )}
                  {number(
                    "population_control.entry_seconds",
                    "Population entry dwell (seconds)",
                    true,
                  )}
                  {number(
                    "population_control.release_seconds",
                    "Population release dwell (seconds)",
                    true,
                  )}
                  {flag(
                    "population_control.populated_default",
                    "Initial populated",
                  )}
                </>
              )}
            </div>
            <p>
              Continuous occupied/unpopulated time activates a positive delta
              that lowers heating and raises cooling. Continuous populated time
              clears it after the release dwell; unoccupied clears it
              immediately. Timers count successful scans only. All durations are
              positive whole seconds aligned to the declared scan.
            </p>
            <h2>Higher-priority window pair</h2>
            <div className="wizard-fields">
              {select(
                "window",
                "Window target branch",
                [
                  ["off", "Off"],
                  ["absolute-pair", "Absolute heating/cooling pair"],
                ],
                true,
              )}
              {draft.window_control && (
                <>
                  {number(
                    "window_control.heating_setpoint",
                    "Window-open heating target",
                  )}
                  {number(
                    "window_control.cooling_setpoint",
                    "Window-open cooling target",
                  )}
                  {flag("window_control.open_default", "Initial window open")}
                </>
              )}
            </div>
            <p>
              The window pair overrides both base and population-selected
              targets. Population timers continue behind it:
              population_setback_ready reports latent state, while
              population_offset_applied reports a delta actually selected. The
              applied delta is zero during the window override. Closing the
              window reveals current state; becoming unoccupied still clears
              latent state.
            </p>
            <p>
              occupied_base_selected identifies the occupied target family,
              including a selected population offset. It does not mean the
              unadjusted nominal occupied pair is being output.
            </p>
            <p>
              Select both branches explicitly before converting units.
              Conversion couples all absolute pairs and the population
              difference, preserving flags and seconds. Reference Fahrenheit
              values convert as chosen values; rounded manufacturer Celsius
              presets are not substituted. Branch changes restore that branch’s
              selected-unit defaults and remove irrelevant controls. Very small
              differences may round away when added to absolute targets;
              conversion and execution do not promise unit-invariant
              trajectories.
            </p>
          </fieldset>
        )}
        {busy && <p role="status">Preparing local zone-target evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="Zone target preview">
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
                  "Logical Boolean inputs; initial values are simulated",
                ],
                ["outputs", "Effective targets and authored state indicators"],
              ] as const
            ).map(([group, label]) => (
              <table key={group} aria-label={`Zone target ${group}`}>
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
              setpoint_profile codes are authored: 0 unoccupied, 1 occupied, 2
              occupied with population offset, 3 window. They are not native
              controller enumeration values.
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
              Export original zone target review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable zone target project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>Cancel zone setpoint wizard</button>
          <button onClick={onBack}>Back to equipment wizard</button>
          {busy && (
            <button
              onClick={() => {
                epoch.current++;
                setBusy(false);
                setPreview(null);
                setError(
                  "Pending zone-target response ignored. Local generation may finish; no field operation was started.",
                );
              }}
            >
              Discard pending zone target response
            </button>
          )}
          <button
            disabled={busy || !draft || !configured}
            onClick={() => void review()}
          >
            Preview zone target project
          </button>
        </div>
      </section>
    </div>
  );
}
