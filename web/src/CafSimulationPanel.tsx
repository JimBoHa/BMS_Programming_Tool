import { useEffect, useRef, useState } from "react";
import { Download, FileArchive, RotateCcw, Upload } from "lucide-react";
import { api, download, saveBlob } from "./api";
import "./caf-simulation.css";
import { CafLocalScenarios } from "./CafLocalScenarios";

type SimulationRecord = {
  ref: string;
  class_id: string | null;
  class_version: string | null;
  class_name: string;
  name: string;
  property_id: string;
  kind: "simulationProperty";
  native_type: string | null;
  attributes: Record<string, string> | null;
  old: string | null;
  value: string | null;
  editable: boolean;
  reason: string;
};
type Profile = {
  format: "bms.caf-simulation-profile";
  version: 1;
  source_sha256: string;
  entries: SimulationRecord[];
};
type Summary = {
  sha256: string;
  records: SimulationRecord[];
  counts: { total: number; editable: number; read_only: number };
  validation: string;
};

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function signature(profile: Profile | null): string {
  return stable(
    profile?.entries.map(({ ref, property_id, value }) => ({
      ref,
      property_id,
      value,
    })) || [],
  );
}

function importProfile(value: unknown, original: Profile): Profile {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("Choose a saved CAF simulation profile JSON object.");
  const next = value as Record<string, unknown>;
  if (
    stable(Object.keys(next).sort()) !==
      stable(["entries", "format", "source_sha256", "version"]) ||
    next.format !== original.format ||
    next.version !== 1 ||
    next.source_sha256 !== original.source_sha256 ||
    !Array.isArray(next.entries) ||
    next.entries.length !== original.entries.length
  )
    throw new Error(
      "Profile must match this exact CAF SHA-256, format, version and complete record count.",
    );
  const expected = new Map(
    original.entries.map((row) => [stable([row.ref, row.property_id]), row]),
  );
  const seen = new Set<string>();
  const values = new Map<string, string | null>();
  for (const candidate of next.entries) {
    if (
      candidate === null ||
      typeof candidate !== "object" ||
      Array.isArray(candidate)
    )
      throw new Error("Profile contains an invalid native record.");
    const row = candidate as SimulationRecord;
    const key = stable([row.ref, row.property_id]);
    const prior = expected.get(key);
    if (!prior || seen.has(key))
      throw new Error("Profile contains duplicate or unknown native records.");
    seen.add(key);
    const { value: replacement, ...guards } = row;
    const { value: previous, ...expectedGuards } = prior;
    void previous;
    if (stable(guards) !== stable(expectedGuards))
      throw new Error(
        "Profile identity, native type or old-value guard changed.",
      );
    if (!prior.editable && replacement !== prior.old)
      throw new Error("Profile attempted to edit a read-only native record.");
    if (prior.editable && typeof replacement !== "string")
      throw new Error("Editable profile values must use native scalar text.");
    values.set(key, replacement);
  }
  return {
    ...original,
    entries: original.entries.map((row) => ({
      ...row,
      value: values.get(stable([row.ref, row.property_id]))!,
    })),
  };
}

export function CafSimulationPanel({ visible = true }: { visible?: boolean }) {
  const [scenarioDirty, setScenarioDirty] = useState(false);
  const [scenarioEpoch, setScenarioEpoch] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [original, setOriginal] = useState<Profile | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [filename, setFilename] = useState("controller.caf");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [opening, setOpening] = useState(false);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [saved, setSaved] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const profileInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(false);
  const openRequest = useRef(0);
  const importRequest = useRef(0);
  const exportRequest = useRef(0);
  const active = useRef<string | null>(null);
  const visibleNow = useRef(visible);
  visibleNow.current = visible;
  const draft = signature(profile);
  const liveDraft = useRef(draft);
  liveDraft.current = draft;
  const changed =
    profile?.entries.filter((row) => row.value !== row.old).length || 0;
  const unsaved = changed > 0 && saved !== draft;
  const busy = opening || importing || exporting;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      openRequest.current++;
      importRequest.current++;
      exportRequest.current++;
    };
  }, []);
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  async function open(file?: File) {
    if (!file || !visible || importing || exporting) return;
    if (
      (unsaved || scenarioDirty) &&
      !window.confirm(
        "Discard unexported simulation draft and unsaved local scenario changes, then open another CAF?",
      )
    )
      return;
    const request = ++openRequest.current;
    setOpening(true);
    setError("");
    setMessage("");
    try {
      const data = new FormData();
      data.append("file", file);
      const archive = await api("/caf", data);
      const [inventory, exportedProfile] = await Promise.all([
        api(`/caf/${archive.sha256}/simulation`),
        api(`/caf/${archive.sha256}/simulation/profile`),
      ]);
      if (!mounted.current || request !== openRequest.current) return;
      active.current = archive.sha256;
      importRequest.current++;
      exportRequest.current++;
      setSummary(inventory);
      setScenarioEpoch((prior) => prior + 1);
      setOriginal(exportedProfile);
      setProfile(exportedProfile);
      setSaved(signature(exportedProfile));
      setFilename(file.name);
      setQuery("");
    } catch (e) {
      if (mounted.current && request === openRequest.current)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && request === openRequest.current) setOpening(false);
    }
  }

  async function loadProfile(file?: File) {
    if (!file || !original || busy || !visible) return;
    if (
      unsaved &&
      !window.confirm(
        "Discard unexported simulation draft and import this profile?",
      )
    )
      return;
    const request = ++importRequest.current;
    const archive = active.current;
    setImporting(true);
    setError("");
    setMessage("");
    try {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Simulation profile JSON exceeds 2 MiB.");
      const imported = importProfile(JSON.parse(await file.text()), original);
      if (
        !mounted.current ||
        request !== importRequest.current ||
        archive !== active.current
      )
        return;
      setProfile(imported);
      setMessage(
        "Profile loaded into the draft. Native scalar ranges are checked when exporting the CAF copy.",
      );
    } catch (e) {
      if (mounted.current && request === importRequest.current)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && request === importRequest.current)
        setImporting(false);
    }
  }

  function change(index: number, value: string) {
    setProfile((prior) =>
      prior
        ? {
            ...prior,
            entries: prior.entries.map((row, i) =>
              i === index ? { ...row, value } : row,
            ),
          }
        : prior,
    );
    setError("");
    setMessage("");
  }

  function saveProfile() {
    if (!profile || busy || !visible) return;
    const name = filename.replace(/\.caf$/i, "") + "-simulation-profile.json";
    saveBlob(
      new Blob([JSON.stringify(profile) + "\n"], {
        type: "application/json",
      }),
      name,
    );
    setSaved(draft);
    setMessage(`Browser download requested for ${name}.`);
  }

  async function saveNative() {
    if (!profile || busy || !visible) return;
    const request = ++exportRequest.current;
    const archive = active.current;
    const snapshot = profile;
    const snapshotSignature = signature(snapshot);
    const current = () =>
      mounted.current &&
      visibleNow.current &&
      request === exportRequest.current &&
      active.current === archive &&
      liveDraft.current === snapshotSignature;
    const name = filename.replace(/\.caf$/i, "") + "-simulation.caf";
    setExporting(true);
    setError("");
    setMessage("");
    try {
      const saved = await download(
        `/caf/${archive}/simulation`,
        { profile: snapshot },
        name,
        current,
      );
      if (!saved || !current()) return;
      setSaved(snapshotSignature);
      setMessage(
        `Browser download requested for ${name}. Only saved simulation records changed. This view retains the original CAF and draft; JCI execution remains unverified.`,
      );
    } catch (e) {
      if (current()) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && request === exportRequest.current)
        setExporting(false);
    }
  }

  function reset() {
    if (!original || busy || !visible || !changed) return;
    if (
      !window.confirm(
        "Discard simulation draft and restore original saved values?",
      )
    )
      return;
    setProfile(original);
    setSaved(signature(original));
    setError("");
    setMessage("Original saved simulation values restored to the draft.");
  }

  const filter = query.toLocaleLowerCase();
  const shown = (profile?.entries || [])
    .map((row, index) => ({ row, index }))
    .filter(({ row }) =>
      [row.ref, row.name, row.class_name, row.native_type, row.reason]
        .join(" ")
        .toLocaleLowerCase()
        .includes(filter),
    );

  return (
    <div className="workspace-page caf-simulation">
      <div className="page-intro">
        <div>
          <span className="eyebrow">
            JOHNSON CONTROLS · SAVED SIMULATION VALUES
          </span>
          <h1>CAF simulation profiles</h1>
          <p>
            Prepare guarded simulation values in a separate native CAF copy.
          </p>
        </div>
        <button
          className="primary"
          disabled={importing || exporting || !visible}
          onClick={() => input.current?.click()}
        >
          <Upload size={16} />{" "}
          {opening ? "Opening CAF…" : "Open simulation CAF"}
        </button>
      </div>
      <input
        ref={input}
        hidden
        type="file"
        accept=".caf"
        aria-label="Simulation CAF file"
        onChange={(e) => {
          void open(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        ref={profileInput}
        hidden
        type="file"
        accept=".json,application/json"
        aria-label="Simulation profile JSON"
        onChange={(e) => {
          void loadProfile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <div className="caf-simulation-scope">
        <strong>
          Offline saved values. Native JCI logic is not executed here.
        </strong>
        <p>
          Existing float and Boolean simulation records support guarded edits.
          Ordinary program properties stay unchanged. Enum domains and unknown
          records remain read-only. Exported CAFs need validation in matching
          CCT/PCT before use.
        </p>
      </div>
      {error && (
        <div role="alert" className="caf-simulation-error">
          {error}
        </div>
      )}
      {message && (
        <div role="status" className="caf-simulation-message">
          {message}
        </div>
      )}
      {!summary ? (
        <div className="caf-simulation-empty">
          <FileArchive size={32} />
          <h2>Open a CAF to inspect saved simulation records</h2>
          <p>
            Profiles bind to the exact source SHA-256 and retain original native
            identities, types and values. CAFs without saved simulation records
            remain inspectable and export unchanged.
          </p>
        </div>
      ) : (
        <>
          <section
            className="caf-simulation-summary"
            aria-label="Simulation file summary"
          >
            <strong>{filename}</strong>
            <span>{summary.counts.total} records</span>
            <span>{summary.counts.editable} editable</span>
            <span>{summary.counts.read_only} read-only</span>
            <span>
              {changed} draft changes{unsaved ? " · unexported" : ""}
            </span>
            <code title={summary.sha256}>SHA-256 {summary.sha256}</code>
          </section>
          <div className="caf-simulation-toolbar">
            <button disabled={busy || !visible} onClick={saveProfile}>
              <Download size={15} /> Export profile JSON
            </button>
            <button
              disabled={busy || !visible}
              onClick={() => profileInput.current?.click()}
            >
              <Upload size={15} /> Import profile JSON
            </button>
            <button
              className="primary"
              disabled={busy || !visible}
              onClick={() => void saveNative()}
            >
              <Download size={15} />{" "}
              {exporting ? "Validating copy…" : "Export simulation CAF"}
            </button>
            <button disabled={busy || !changed || !visible} onClick={reset}>
              <RotateCcw size={15} /> Reset simulation draft
            </button>
            <input
              type="search"
              aria-label="Search simulation records"
              placeholder="Search native records"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {!summary.counts.total ? (
            <div className="caf-simulation-empty">
              No saved simulation records in this CAF. Profile export and native
              CAF export preserve the unchanged archive.
            </div>
          ) : (
            <div className="caf-simulation-table">
              <table>
                <thead>
                  <tr>
                    <th>Native record</th>
                    <th>Type</th>
                    <th>Original</th>
                    <th>Draft value</th>
                    <th>Scope</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(({ row, index }) => (
                    <tr key={`${row.ref}:${row.property_id}`}>
                      <td>
                        <strong>{row.name || row.class_name}</strong>
                        <code>{row.ref}</code>
                        <small>
                          simulationProperty {row.property_id} · class{" "}
                          {row.class_id} / {row.class_version}
                        </small>
                      </td>
                      <td>
                        {row.native_type || "Opaque"}
                        {row.attributes?.set && (
                          <small>set {row.attributes.set}</small>
                        )}
                      </td>
                      <td>
                        <code>{row.old ?? "Opaque native structure"}</code>
                      </td>
                      <td>
                        {row.editable ? (
                          <input
                            type="text"
                            aria-label={`Simulation value ${row.ref}`}
                            value={row.value || ""}
                            disabled={busy || !visible}
                            onChange={(e) => change(index, e.target.value)}
                          />
                        ) : (
                          <span>Read-only</span>
                        )}
                      </td>
                      <td>
                        <small>{row.reason}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!shown.length && <p>No simulation records match this search.</p>}
            </div>
          )}
          <p className="caf-simulation-validation">{summary.validation}</p>
          <CafLocalScenarios
            key={`${summary.sha256}:${scenarioEpoch}`}
            sha={summary.sha256}
            filename={filename}
            visible={visible}
            parentBusy={busy}
            onDirtyChange={setScenarioDirty}
          />
        </>
      )}
    </div>
  );
}
