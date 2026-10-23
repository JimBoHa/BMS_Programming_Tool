import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, sourceApi, saveBlob } from "./api";
import { sourceEqual, sourceStringify } from "./programSource";
import type { Program } from "./types";
import "./equipment-wizard.css";

type Group = {
  id: string;
  label: string;
  timezone: string;
  mode: string;
  days: number[];
  start: string;
  end: string;
  lead_minutes: number;
};
type Choices = {
  project_id: string;
  name: string;
  ahu_label: string;
  scan_seconds: number;
  groups: Group[];
};
type Data = Record<string, any>;
const BASE = "/schedule-coordination",
  PROFILE = "studio-weekly-zone-group-occupancy/1";
const weekdays = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
const hash = (value: any) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const object = (value: any): value is Data =>
  value !== null && typeof value === "object" && !Array.isArray(value);
function catalogResult(value: any) {
  const draft = value?.defaults;
  if (
    !object(value) ||
    value.profile?.profile !== PROFILE ||
    !hash(value.profile_sha256) ||
    !object(value.profile.source) ||
    !Array.isArray(value.profile.gaps) ||
    !value.profile.gaps.every((x: any) => typeof x === "string") ||
    !object(value.profile.semantics) ||
    !Object.values(value.profile.semantics).every(
      (x) => typeof x === "string",
    ) ||
    !hash(value.profile.source.sha256) ||
    typeof value.profile.source.url !== "string" ||
    !value.profile.source.url.startsWith("https://docs.johnsoncontrols.com/") ||
    !Array.isArray(value.profile.source.pdf_pages) ||
    !value.profile.source.pdf_pages.every(
      (x: any) => Number.isSafeInteger(x) && x > 0,
    ) ||
    !["title", "document", "edition", "scope"].every(
      (key) => typeof value.profile.source[key] === "string",
    ) ||
    value.limits?.groups !== 8 ||
    value.limits?.clocks !== 128 ||
    !object(draft) ||
    typeof draft.name !== "string" ||
    typeof draft.ahu_label !== "string" ||
    !Number.isFinite(draft.scan_seconds) ||
    !Array.isArray(draft.groups) ||
    draft.groups.length !== 1 ||
    !draft.groups.every(
      (g: any) =>
        object(g) &&
        ["id", "label", "timezone", "mode", "start", "end"].every(
          (key) => typeof g[key] === "string",
        ) &&
        Number.isSafeInteger(g.lead_minutes) &&
        Array.isArray(g.days) &&
        g.days.every((d: any) => Number.isInteger(d) && d >= 0 && d <= 6),
    )
  ) {
    throw new Error(
      "Schedule coordination catalog is malformed or uses an unsupported profile.",
    );
  }
  return value;
}
function windows(value: any) {
  return (
    Array.isArray(value) &&
    value.length <= 32 &&
    value.every(
      (w: any) =>
        object(w) &&
        typeof w.start === "string" &&
        typeof w.end === "string" &&
        Array.isArray(w.days) &&
        w.days.length <= 7 &&
        w.days.every((d: any) => Number.isInteger(d) && d >= 0 && d <= 6),
    )
  );
}
function previewResult(
  value: any,
  request: { choices: Choices; clocks: string[] },
  catalog: Data,
) {
  const provenance = value?.program?.metadata?.schedule_coordination;
  const expectedOutputs = [
    "ahu_occupied",
    ...request.choices.groups.flatMap((_, i) =>
      ["occupied", "pre_or_occupied", "pre_only"].map(
        (role) => `zg${i + 1}_${role}`,
      ),
    ),
  ];
  if (
    !object(value) ||
    value.format !== "bms.schedule-coordination-preview" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(value.profile, catalog.profile) ||
    !sourceEqual(value.choices, request.choices) ||
    !hash(value.choices_sha256) ||
    !hash(value.program_sha256) ||
    value.program?.id !== request.choices.project_id ||
    value.program?.name !== request.choices.name ||
    !sourceEqual(provenance?.choices, request.choices) ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    !sourceEqual(provenance.source, catalog.profile.source) ||
    !sourceEqual(provenance.unimplemented, catalog.profile.gaps) ||
    !Array.isArray(value.program.nodes) ||
    value.program.nodes.length > 1000 ||
    !Array.isArray(value.program.edges) ||
    value.program.edges.length > 4000 ||
    value.program.metadata.native_deployment_verified !== false ||
    value.program.target?.physical_inputs !== null ||
    value.program.target?.physical_outputs !== null ||
    !expectedOutputs.every((id) =>
      value.program.nodes.some(
        (n: any) =>
          n.id === id && n.kind === "Output" && n.value_type === "boolean",
      ),
    ) ||
    value.native_compile !== false ||
    value.controller_writes !== false ||
    typeof value.can_create !== "boolean" ||
    !Array.isArray(value.issues) ||
    !value.issues.every(
      (r: any) =>
        object(r) &&
        ["warning", "error"].includes(r.level) &&
        typeof r.message === "string",
    ) ||
    !Array.isArray(value.groups) ||
    value.groups.length !== request.choices.groups.length ||
    !sourceEqual(provenance.groups, value.groups) ||
    !value.groups.every(
      (g: any, i: number) =>
        object(g) &&
        g.id === request.choices.groups[i].id &&
        g.label === request.choices.groups[i].label &&
        g.timezone === request.choices.groups[i].timezone &&
        windows(g.occupied_windows) &&
        windows(g.pre_windows) &&
        Number.isInteger(g.occupied_week_minutes) &&
        g.occupied_week_minutes >= 0 &&
        g.occupied_week_minutes <= 10080 &&
        Number.isInteger(g.pre_week_minutes) &&
        g.pre_week_minutes >= g.occupied_week_minutes &&
        g.pre_week_minutes <= 10080 &&
        sourceEqual(g.outputs, {
          occupied: `zg${i + 1}_occupied`,
          pre_or_occupied: `zg${i + 1}_pre_or_occupied`,
          pre_only: `zg${i + 1}_pre_only`,
        }) &&
        Array.isArray(g.inactive_choices) &&
        g.inactive_choices.every((key: any) => typeof key === "string"),
    ) ||
    !Array.isArray(value.evaluation) ||
    value.evaluation.length !== request.clocks.length ||
    !value.evaluation.every(
      (r: any, i: number) =>
        object(r) &&
        r.requested_clock === request.clocks[i] &&
        typeof r.clock === "string" &&
        object(r.outputs) &&
        Object.keys(r.outputs).length === expectedOutputs.length &&
        expectedOutputs.every((id) => typeof r.outputs[id] === "boolean"),
    )
  ) {
    throw new Error(
      "Schedule preview does not match these exact choices, source profile or logical outputs.",
    );
  }
  return value;
}
function windowText(rows: any[]) {
  return rows.length
    ? rows
        .map(
          (w) =>
            `${w.days.map((d: number) => weekdays[d]).join(", ")} ${w.start}–${w.end}`,
        )
        .join("; ")
    : "Empty";
}

export function ZoneGroupScheduleWizard({
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
    [draft, setDraft] = useState<Choices | null>(null),
    [clocks, setClocks] = useState(""),
    [preview, setPreview] = useState<{
      data: Data;
      key: string;
      sourceKey: string;
      request: { choices: Choices; clocks: string[] };
    } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    nextId = useRef(2);
  const sourceKey = sourceStringify(source),
    key = JSON.stringify({
      draft,
      clocks,
      catalog: catalog?.profile_sha256,
      sourceKey,
    });
  const live = useRef(key);
  live.current = key;
  const current = (generation: number, ownedKey: string) =>
    mounted.current &&
    epoch.current === generation &&
    live.current === ownedKey;
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
          project_id: "schedule_" + crypto.randomUUID().replaceAll("-", ""),
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
      "Current editor changed. Preview again before creating a schedule project.",
    );
  }, [sourceKey]);
  function change(action: () => void) {
    epoch.current++;
    setPreview(null);
    setError("");
    setBusy(false);
    action();
  }
  function patch(key: keyof Choices, value: any) {
    if (draft) change(() => setDraft({ ...draft, [key]: value }));
  }
  function group(index: number, key: keyof Group, value: any) {
    if (draft)
      change(() =>
        setDraft({
          ...draft,
          groups: draft.groups.map((g, i) =>
            i === index ? { ...g, [key]: value } : g,
          ),
        }),
      );
  }
  function add() {
    if (!draft || !catalog || draft.groups.length >= 8) return;
    let id = "";
    do {
      id = "group_" + nextId.current++;
    } while (draft.groups.some((g) => g.id === id));
    const base = catalog.defaults.groups[0];
    change(() =>
      setDraft({
        ...draft,
        groups: [
          ...draft.groups,
          {
            ...base,
            id,
            label: `Zone group ${draft.groups.length + 1}`,
            days: [...base.days],
          },
        ],
      }),
    );
  }
  function request() {
    if (!draft) throw new Error("Schedule draft is not ready.");
    const instants = clocks
      .split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean);
    if (instants.length > 128)
      throw new Error("Use at most 128 explicit UTC sample instants.");
    return { choices: draft, clocks: instants };
  }
  async function review() {
    if (!draft || !catalog || busy) return;
    const generation = ++epoch.current,
      ownedKey = key,
      base = sourceKey;
    setBusy(true);
    setPreview(null);
    setError("");
    try {
      const body = request();
      const data = previewResult(
        await sourceApi(BASE + "/preview", body),
        body,
        catalog,
      );
      if (current(generation, ownedKey))
        setPreview({ data, key: ownedKey, sourceKey: base, request: body });
    } catch (e) {
      if (current(generation, ownedKey)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === generation) setBusy(false);
    }
  }
  async function exportReview() {
    if (!preview || preview.key !== key || !catalog || busy) return;
    const owned = preview,
      generation = ++epoch.current,
      ownedKey = key;
    setBusy(true);
    setError("");
    try {
      const response = await apiJsonDocument(BASE + "/export", owned.request);
      const data = previewResult(response.data, owned.request, catalog);
      if (
        data.program_sha256 !== owned.data.program_sha256 ||
        data.choices_sha256 !== owned.data.choices_sha256 ||
        !sourceEqual(data.program, owned.data.program) ||
        !sourceEqual(data.groups, owned.data.groups) ||
        !sourceEqual(data.evaluation, owned.data.evaluation)
      )
        throw new Error(
          "Export changed after preview; review the current source again.",
        );
      if (current(generation, ownedKey))
        saveBlob(
          response.blob,
          `zone-group-schedule-${data.program_sha256}.json`,
        );
    } catch (e) {
      if (current(generation, ownedKey)) setError(String(e));
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
        `Replace the editor contents of “${source.name}” with a separate new schedule project? Save or export current edits first if needed. Undo can restore the previous editor contents.`,
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
  const displayed = preview?.key === key ? preview : null;
  return (
    <div className="equipment-wizard-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Zone-group schedule wizard"
        className="equipment-wizard"
      >
        <h1>Zone-group schedule coordination</h1>
        <p>
          Create an editable portable weekly graph. Each group keeps its
          original occupied schedule and end. Pre-or-occupied expands the start
          by the declared wall-clock lead; pre-only excludes occupied time.
        </p>
        <p>
          AHU occupied is the OR of original group occupancy only. Pre-only does
          not set AHU occupied. No countdown, dated exceptions, native occupancy
          codes, device mappings or complete G36/Title 24 sequence are
          generated.
        </p>
        {draft && (
          <fieldset disabled={busy}>
            <div className="wizard-fields">
              <label>
                Schedule project name
                <input
                  aria-label="Schedule project name"
                  maxLength={200}
                  value={draft.name}
                  onChange={(e) => patch("name", e.target.value)}
                />
              </label>
              <label>
                Logical AHU label
                <input
                  aria-label="Logical AHU label"
                  maxLength={140}
                  value={draft.ahu_label}
                  onChange={(e) => patch("ahu_label", e.target.value)}
                />
              </label>
              <label>
                Schedule scan interval (seconds)
                <input
                  aria-label="Schedule scan interval (seconds)"
                  type="number"
                  step="any"
                  value={
                    Number.isNaN(draft.scan_seconds) ? "" : draft.scan_seconds
                  }
                  onChange={(e) =>
                    patch(
                      "scan_seconds",
                      e.target.value === "" ? NaN : Number(e.target.value),
                    )
                  }
                />
              </label>
            </div>
            {draft.groups.map((g, index) => (
              <section key={index} aria-label={`Zone group ${index + 1}`}>
                <h2>Zone group {index + 1}</h2>
                <div className="wizard-fields">
                  <label>
                    Stable group ID
                    <input
                      aria-label={`Group ${index + 1} ID`}
                      maxLength={32}
                      value={g.id}
                      onChange={(e) => group(index, "id", e.target.value)}
                    />
                  </label>
                  <label>
                    Group label
                    <input
                      aria-label={`Group ${index + 1} label`}
                      maxLength={160}
                      value={g.label}
                      onChange={(e) => group(index, "label", e.target.value)}
                    />
                  </label>
                  <label>
                    Explicit IANA time zone
                    <input
                      aria-label={`Group ${index + 1} time zone`}
                      maxLength={128}
                      placeholder="America/Los_Angeles"
                      value={g.timezone}
                      onChange={(e) => group(index, "timezone", e.target.value)}
                    />
                  </label>
                  <label>
                    Weekly mode
                    <select
                      aria-label={`Group ${index + 1} mode`}
                      value={g.mode}
                      onChange={(e) => group(index, "mode", e.target.value)}
                    >
                      <option value="">Choose explicit weekly mode…</option>
                      <option value="window">Declared occupied window</option>
                      <option value="all-day">
                        All day on selected weekdays
                      </option>
                      <option value="disabled">
                        Disabled: empty occupancy and pre-start
                      </option>
                    </select>
                  </label>
                  {g.mode === "window" && (
                    <>
                      <label>
                        Original occupied start
                        <input
                          aria-label={`Group ${index + 1} start`}
                          type="time"
                          value={g.start}
                          onChange={(e) =>
                            group(index, "start", e.target.value)
                          }
                        />
                      </label>
                      <label>
                        Original occupied end
                        <input
                          aria-label={`Group ${index + 1} end`}
                          type="time"
                          value={g.end}
                          onChange={(e) => group(index, "end", e.target.value)}
                        />
                      </label>
                    </>
                  )}
                  <label>
                    Wall-clock pre-start lead (minutes)
                    <input
                      aria-label={`Group ${index + 1} lead minutes`}
                      type="number"
                      step="1"
                      value={Number.isNaN(g.lead_minutes) ? "" : g.lead_minutes}
                      onChange={(e) =>
                        group(
                          index,
                          "lead_minutes",
                          e.target.value === "" ? NaN : Number(e.target.value),
                        )
                      }
                    />
                  </label>
                </div>
                <fieldset>
                  <legend>Selected start weekdays, group {index + 1}</legend>
                  {weekdays.map((day, d) => (
                    <label
                      key={day}
                      style={{ display: "inline-flex", marginRight: "1rem" }}
                    >
                      <input
                        type="checkbox"
                        aria-label={`Group ${index + 1} ${day}`}
                        checked={g.days.includes(d)}
                        onChange={(e) =>
                          group(
                            index,
                            "days",
                            e.target.checked
                              ? [...g.days, d].sort((a, b) => a - b)
                              : g.days.filter((n) => n !== d),
                          )
                        }
                      />
                      {day}
                    </label>
                  ))}
                </fieldset>
                <p>
                  Overnight windows belong to their start weekday. Equal start
                  and end in window mode is empty; all-day is explicit. Disabled
                  or no selected days is empty. Lead is 0–1440 wall-clock
                  minutes, not elapsed time through DST.
                </p>
                <button
                  disabled={draft.groups.length <= 1}
                  onClick={() =>
                    change(() =>
                      setDraft({
                        ...draft,
                        groups: draft.groups.filter((_, i) => i !== index),
                      }),
                    )
                  }
                >
                  Remove zone group {index + 1}
                </button>
              </section>
            ))}
            <button disabled={draft.groups.length >= 8} onClick={add}>
              Add zone group
            </button>
            <label>
              Optional UTC sample instants, one per line
              <textarea
                aria-label="Schedule UTC sample instants"
                rows={5}
                maxLength={10500}
                placeholder="2026-01-05T15:00:00Z"
                value={clocks}
                onChange={(e) => change(() => setClocks(e.target.value))}
              />
            </label>
            <p>
              Samples use explicit UTC ISO8601 instants. Each group evaluates
              its own named local zone. Spring skipped minutes never occur;
              repeated autumn minutes evaluate in both folds. This is not a
              fixed elapsed lead or countdown.
            </p>
          </fieldset>
        )}
        {busy && <p role="status">Preparing local schedule evidence…</p>}
        {error && <p role="alert">{error}</p>}
        {displayed && (
          <section aria-label="Schedule coordination preview">
            <h2>{displayed.data.program.name}</h2>
            <p>
              {displayed.data.program.nodes.length} blocks ·{" "}
              {displayed.data.program.edges.length} connections. Native
              compilation and field deployment are unverified.
            </p>
            <p>
              Program SHA-256 {displayed.data.program_sha256}
              <br />
              Choices SHA-256 {displayed.data.choices_sha256}
            </p>
            <table aria-label="Generated schedule windows">
              <thead>
                <tr>
                  <th>Group / named time zone</th>
                  <th>Original occupied windows</th>
                  <th>Pre-or-occupied windows, original end retained</th>
                  <th>Logical outputs</th>
                </tr>
              </thead>
              <tbody>
                {displayed.data.groups.map((g: any) => (
                  <tr key={g.id}>
                    <td>
                      {g.label} / {g.timezone}
                    </td>
                    <td>{windowText(g.occupied_windows)}</td>
                    <td>{windowText(g.pre_windows)}</td>
                    <td>{Object.values(g.outputs).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {displayed.data.evaluation.length > 0 && (
              <table aria-label="Schedule sample results">
                <thead>
                  <tr>
                    <th>Requested UTC instant</th>
                    <th>Boolean logical outputs</th>
                  </tr>
                </thead>
                <tbody>
                  {displayed.data.evaluation.map((r: any, i: number) => (
                    <tr key={i}>
                      <td>{r.requested_clock}</td>
                      <td>
                        {Object.entries(r.outputs)
                          .map(([id, v]) => `${id}: ${v}`)
                          .join("; ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <h3>Portable graph validation</h3>
            {displayed.data.issues.length ? (
              displayed.data.issues.map((r: any, i: number) => (
                <p key={i}>
                  {r.level}: {r.message}
                </p>
              ))
            ) : (
              <p>No portable graph errors.</p>
            )}
            <h3>Separate engineering work</h3>
            <ul>
              {catalog?.profile.gaps.map((gap: string) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
            <details>
              <summary>Primary source and exact declared choices</summary>
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
                    groups: displayed.data.groups,
                  },
                  2,
                )}
              </pre>
            </details>
            <button disabled={busy} onClick={exportReview}>
              Export original schedule review JSON
            </button>
            <button
              className="primary"
              disabled={busy || displayed.data.can_create !== true}
              onClick={create}
            >
              Create editable schedule project
            </button>
          </section>
        )}
        <div className="button-row">
          <button onClick={onClose}>Cancel schedule wizard</button>
          <button onClick={onBack}>Back to equipment wizard</button>
          <button disabled={busy || !draft} onClick={review}>
            Preview zone-group schedule
          </button>
        </div>
      </section>
    </div>
  );
}
