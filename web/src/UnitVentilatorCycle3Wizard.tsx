import { useEffect, useRef, useState } from "react";
import {
  api,
  programApi,
  programJsonDocument,
  saveBlob,
  sourceApi,
} from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  UV_BASE,
  blobSha256,
  catalogResult,
  previewResult,
  unitResult,
  type Data,
} from "./unitVentilatorCycle3Contract";
import type { Program } from "./types";
import "./equipment-wizard.css";

export function UnitVentilatorCycle3Wizard({
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
    api(UV_BASE + "/catalog")
      .then(async (value) => {
        const checked = await catalogResult(value);
        if (!mounted.current || epoch.current !== generation) return;
        setCatalog(checked);
        setDraft({
          ...checked.defaults,
          project_id: "uv_cycle3_" + crypto.randomUUID().replaceAll("-", ""),
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
      "Current editor changed. Preview again before creating a unit ventilator Cycle III project.",
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
      const value = await programApi(UV_BASE + "/units", {
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
        await sourceApi(UV_BASE + "/preview", {
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
      const result = await programJsonDocument(
          UV_BASE + "/export",
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
          "Unit ventilator Cycle III export changed after this exact preview. Review again.",
        );
      if (current(generation, owned))
        saveBlob(result.blob, `uv-cycle3-review-${value.program_sha256}.json`);
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
        `Replace the editor contents of “${source.name}” with a separate new unit ventilator Cycle III project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
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
          value={Object.is(v, -0) ? "-0" : Number.isNaN(v) ? "" : (v ?? "")}
          onChange={(e) => {
            const entered =
              e.target.value === "" ? NaN : Number(e.target.value);
            // Preserve authored signed zero; opaque Program/source atoms arrive
            // separately from the server and are never normalized.
            patch(field, entered);
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
    configured =
      draft &&
      ["disable-cooling", "shutdown-unit"].includes(draft.condensate_policy);
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Unit ventilator Cycle III wizard"
        className="equipment-wizard"
      >
        <h1>Occupied unit ventilator Cycle III composer</h1>
        <p>
          Create a separate editable ordinary graph for a single-speed unit
          ventilator, separate proportional hydronic heating and cooling coils,
          and mixed-air temperature control of one outdoor-air damper.
          Increasing outdoor-air command is assumed to cool mixed air. This
          cold-outdoor action needs engineering verification. No measured
          ventilation, native JCI/CAF transfer, physical protection, Guideline
          36 or Title 24 acceptance is established.
        </p>
        <p>
          Required bad input quality rolls back the complete scan, retaining
          prior timers, modes, integrals and commands, potentially including
          positive outputs. Before the first successful scan, existing host
          outputs can be empty or zero; no safe startup command set is
          preseeded. Logical commands are not physical protections.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <h2>Project and declared target</h2>
            <div className="wizard-fields">
              {text("name", "UV Cycle III project name", 200)}
              {select("family", "UV Cycle III declared controller family", [
                ["universal-runtime", "Portable runtime"],
                ["johnson-fx", "Johnson Controls FX"],
                ["johnson-metasys", "Johnson Controls Metasys"],
              ])}
              {text("model", "UV Cycle III declared model")}
              {text("firmware", "UV Cycle III declared firmware")}
              {text("release_mode", "UV Cycle III declared release mode")}
              {number(
                "scan_seconds",
                "UV Cycle III scan interval (seconds)",
                true,
              )}
              {select(
                "condensate_policy",
                "UV condensate policy",
                [
                  [
                    "disable-cooling",
                    "Disable cooling; keep fan, heating and MAT control permitted",
                  ],
                  ["shutdown-unit", "Shut down unit commands and readiness"],
                ],
                true,
              )}
              <label>
                UV Cycle III temperature units
                <select
                  aria-label="UV Cycle III temperature units"
                  value={draft.temperature_unit}
                  disabled={!configured}
                  onChange={(e) => void units(e.target.value)}
                >
                  <option value="degF">Degrees Fahrenheit</option>
                  <option value="degC">Degrees Celsius</option>
                </select>
              </label>
            </div>
            <p>
              Choose condensate behavior explicitly before converting units or
              previewing. Both policies inhibit cooling during alarm. Shutdown
              also inhibits fan, mixed-air and heating commands, resets startup
              timing, and cannot impersonate raw operator off for fault reset.
              The alarm adds no separate latch.
            </p>
            <p>
              Fixed topology: occupied-only · one owned single-speed fan ·
              authored Cycle III · separate proportional hydronic coils ·
              cold-outdoor mixing action. Cycles I/II/W, variable fans,
              electric/DX/staged coils and unoccupied recovery remain separate
              work.
            </p>
            <h2>Required logical temperatures and held zone modes</h2>
            <div className="wizard-fields">
              {number("zone_default", "Zone temperature default")}
              {number("mixed_air_default", "Mixed-air temperature default")}
              {number("heating_setpoint", "Heating setpoint default")}
              {number("cooling_setpoint", "Cooling setpoint default")}
              {number("mixed_air_setpoint", "Mixed-air setpoint default")}
              {number("entry_delta", "Entry difference")}
              {number("release_delta", "Release difference")}
              {number("heating_kp", "Heating proportional gain")}
              {number("heating_ki", "Heating integral gain")}
              {number("cooling_kp", "Cooling proportional gain")}
              {number("cooling_ki", "Cooling integral gain")}
            </div>
            <p>
              All five temperatures are required logical inputs; these are
              simulation defaults. The heating target also supplies the zone
              low-limit target. No external setpoint link is created
              automatically. Good temperatures and targets require -50..100 °C
              equivalents, with heating below cooling. Invalid good values
              inhibit commands and restart startup without clearing a fault
              latch. Entry difference must exceed nonnegative release
              difference.
            </p>
            <p>
              Heating and cooling modes exclude one another. A held mode can
              retain nonzero command at setpoint; release also requires its
              previous selected coil command to reach zero. Availability gates
              the selected command, not the held request mode. Inactive PIs
              retain integrals through zero error. Gains are percent per degree
              difference; integral gains additionally per second. Zero integral
              gain selects P control.
            </p>
            <h2>Mixed-air control and zone outdoor-air limit</h2>
            <div className="wizard-fields">
              {number(
                "minimum_outdoor_position",
                "Minimum outdoor-air position (percent)",
              )}
              {number("mixed_air_kp", "Mixed-air proportional gain")}
              {number("mixed_air_ki", "Mixed-air integral gain")}
              {number("zone_limit_kp", "Zone-limit proportional gain")}
              {number("zone_limit_ki", "Zone-limit integral gain")}
            </div>
            <p>
              While ready, the reverse MAT loop maps demand to minimum
              outdoor-air position through 100 percent. This is a position
              floor, not measured outdoor-air volume or ventilation compliance.
              Minimum 100 percent is defined and permitted. Cooling
              unavailability does not disable mixed-air control.
            </p>
            <p>
              In heating mode, a cold zone selects the damper limiter when the
              previous selected heating valve reached 100 percent or heating is
              unavailable. The forward zone loop computes correction and
              allowance; selected OA is the lower of MAT demand and allowance,
              clamped to the declared minimum. This damper limit never boosts
              zone heat. Cold MAT by itself does not request zone heating.
              Latent correction and allowance may remain nonzero when inactive;
              restricting means the final OA command is actually below the
              mapped MAT demand.
            </p>
            <h2>Proof, deadline and required logical permissions</h2>
            <div className="wizard-fields">
              {number("proof_seconds", "Stable proof interval (seconds)", true)}
              {number(
                "startup_timeout_seconds",
                "Startup deadline (seconds)",
                true,
              )}
              {flag("occupied_default", "Initial occupied")}
              {flag("unit_enable_default", "Initial unit enabled")}
              {flag("energy_holdoff_default", "Initial energy holdoff")}
              {flag("airflow_proven_default", "Initial airflow proven")}
              {flag("fan_reset_default", "Initial fan reset")}
              {flag("condensate_alarm_default", "Initial condensate alarm")}
              {flag("heating_available_default", "Initial heating available")}
              {flag("cooling_available_default", "Initial cooling available")}
            </div>
            <p>
              Raw request is occupied AND unit enable AND NOT energy holdoff.
              There is no damper-close estimate. The first requested successful
              scan commands the fan and counts one proof/deadline interval.
              Default five-second stable proof becomes ready on scan five with
              one-second scans and continuous proof. The independent 60-second
              deadline spans chatter; stable proof at the exact deadline wins.
              Good running proof loss immediately latches all ordinary commands
              off.
            </p>
            <p>
              Fault reset requires raw request off and a fresh rising fan-reset
              edge. Value inhibition and condensate shutdown cannot authorize
              that reset. Durations are positive whole seconds aligned to the
              declared scan, and deadline cannot precede proof. Unit conversion
              couples all absolute temperatures, differences and inverse-degree
              gains. Binary64/native REAL and nonlinear antiwindup can differ;
              converted parameters do not promise identical trajectories.
            </p>
          </fieldset>
        )}
        {busy && <p role="status">Preparing local unit ventilator evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="Unit ventilator Cycle III preview">
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
                  "Thirteen required logical inputs; defaults are simulated",
                ],
                [
                  "outputs",
                  "Logical commands, retained demands and authored state indicators",
                ],
              ] as const
            ).map(([group, label]) => (
              <table
                key={group}
                aria-label={`Unit ventilator Cycle III ${group}`}
              >
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
              unit_state: 0 off, 1 fan-start, 2 run, 3 fault. thermal_state: 0
              neutral, 1 heating, 2 cooling, 3 zone-limited heating. These are
              authored codes, not native enumerations. Requested flags are held
              modes; active flags mean loop permission, possibly with zero
              command. Reset accepted denotes an eligible edge even without a
              prior latch. Stable proof and deadline are logical timing
              evidence, not physical safety.
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
              Export original unit ventilator Cycle III review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable unit ventilator Cycle III project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>
            Cancel unit ventilator Cycle III wizard
          </button>
          <button onClick={onBack}>Back to equipment wizard</button>
          {busy && (
            <button
              onClick={() => {
                epoch.current++;
                setBusy(false);
                setPreview(null);
                setError(
                  "Pending unit ventilator response ignored. Local generation may finish; no field operation was started.",
                );
              }}
            >
              Discard pending unit ventilator Cycle III response
            </button>
          )}
          <button
            disabled={busy || !draft || !configured}
            onClick={() => void review()}
          >
            Preview unit ventilator Cycle III project
          </button>
        </div>
      </section>
    </div>
  );
}
