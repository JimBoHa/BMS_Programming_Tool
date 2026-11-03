import { useEffect, useRef, useState } from "react";
import { Download, FileArchive, RotateCcw, Upload } from "lucide-react";
import { api, apiBlobDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import "./caf-simulation.css";
import { CafLocalScenarios } from "./CafLocalScenarios";
import type { FileRequest } from "./workflow";

import {
  admitSimulationSource,
  carryLegacySimulation,
  importProfile,
  signature,
  simulationRequestSha256,
  type Profile,
  type Summary,
} from "./cafSimulationProfile";

export function CafSimulationPanel({
  visible = true,
  incomingFile,
}: {
  visible?: boolean;
  incomingFile?: FileRequest | null;
}) {
  const handledFile = useRef("");
  useEffect(() => {
    if (!visible || !incomingFile || handledFile.current === incomingFile.id)
      return;
    handledFile.current = incomingFile.id;
    void open(incomingFile.file);
  }, [visible, incomingFile]);
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
    const retire = () => {
      openRequest.current++;
      importRequest.current++;
      exportRequest.current++;
      setOpening(false);
      setImporting(false);
      setExporting(false);
    };
    const hidden = () => {
      if (document.hidden) retire();
    };
    if (!visible) retire();
    window.addEventListener("pagehide", retire);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pagehide", retire);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [visible]);
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
      const sourceSha = await sha256Blob(file);
      if (
        !mounted.current ||
        !visibleNow.current ||
        request !== openRequest.current
      )
        return;
      const data = new FormData();
      data.append("file", file);
      const archive = await api("/caf", data);
      if (archive.sha256 !== sourceSha)
        throw new Error(
          "Opened simulation archive does not match the selected file bytes.",
        );
      const [inventory, exportedProfile] = await Promise.all([
        api(`/caf/${archive.sha256}/simulation?profile_version=2`),
        api(`/caf/${archive.sha256}/simulation/profile?profile_version=2`),
      ]);
      if (
        !mounted.current ||
        !visibleNow.current ||
        request !== openRequest.current
      )
        return;
      admitSimulationSource(inventory, exportedProfile, archive.sha256, 2);
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
      const parsed = JSON.parse(await file.text());
      let imported: Profile;
      const legacy = parsed?.version === 1 && original.version === 2;
      if (legacy) {
        const [inventory, baseline] = await Promise.all([
          api(`/caf/${archive}/simulation`),
          api(`/caf/${archive}/simulation/profile`),
        ]);
        admitSimulationSource(inventory, baseline, archive!, 1);
        imported = carryLegacySimulation(
          importProfile(parsed, baseline),
          original,
        );
      } else imported = importProfile(parsed, original);
      if (
        !mounted.current ||
        !visibleNow.current ||
        request !== importRequest.current ||
        archive !== active.current
      )
        return;
      setProfile(imported);
      setMessage(
        legacy
          ? "Legacy profile values adapted to the current source profile. Enums retain original values. Numeric ranges are checked when exporting the CAF copy."
          : "Profile loaded into the draft. Native scalar ranges are checked when exporting the CAF copy.",
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
      const requestSha256 = await simulationRequestSha256(snapshot);
      if (!current()) return;
      const result = await apiBlobDocument(`/caf/${archive}/simulation`, {
        profile: snapshot,
      });
      if (
        result.headers.get("X-Studio-Source-Sha256") !== archive ||
        result.headers.get("X-Studio-Simulation-Version") !==
          String(snapshot.version) ||
        result.headers.get("X-Studio-Simulation-Request-Sha256") !==
          requestSha256 ||
        result.headers.get("X-Studio-Artifact-Sha256") !==
          (await sha256Blob(result.blob))
      )
        throw new Error(
          "Simulation CAF copy differs from its source, profile version, requested simulation values or artifact digest.",
        );
      if (!current()) return;
      saveBlob(result.blob, name);
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
          Existing float, Boolean and qualified numeric Enum simulation records
          support guarded edits. Ordinary program properties stay unchanged.
          Enum meanings and allowed states remain unverified; unknown records
          remain read-only. Validate exported CAFs in matching CCT/PCT before
          use.
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
                            inputMode={
                              row.native_type === "enum" ? "numeric" : undefined
                            }
                            maxLength={128}
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
          <p className="caf-simulation-validation">
            {summary.validation} Enum codes use the unsigned32 numeric
            representation; allowed states and code meanings remain unverified.
          </p>
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
