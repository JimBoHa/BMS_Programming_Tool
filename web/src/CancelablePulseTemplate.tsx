import { useEffect, useRef, useState } from "react";
import { api, programJsonDocument, saveBlob, sourceJsonDocument } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  PULSE_BASE,
  blobSha256,
  pulseCatalog,
  pulsePreview,
  pulseDescriptors,
  readPulseChoices,
  type Data,
  type PulseChoices,
  type PulseImport,
} from "./cancelablePulseTemplateContract";
import type { Program } from "./types";

type Review = {
  data: Data;
  key: string;
  sourceKey: string;
  choices: PulseChoices;
};
export function CancelablePulseTemplate({
  program,
  disabled,
  onImport,
}: {
  program: Program;
  disabled: boolean;
  onImport: (
    request: PulseImport,
    sourceKey: string,
    definition: string,
    expectedDefinition: Data,
    owned: () => boolean,
  ) => Promise<boolean>;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [duration, setDuration] = useState("5"),
    [scan, setScan] = useState("1"),
    [review, setReview] = useState<Review | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceStringify(program),
    key = JSON.stringify({
      duration,
      scan,
      sourceKey,
      profile: catalog?.profile_sha256,
    }),
    live = useRef(key);
  live.current = key;
  const current = (mine: number, owned: string) =>
    mounted.current && epoch.current === mine && live.current === owned;
  async function reload() {
    const mine = ++epoch.current;
    setCatalog(null);
    setReview(null);
    setBusy(true);
    setError("");
    try {
      const data = await pulseCatalog(await api(PULSE_BASE + "/catalog"));
      if (mounted.current && epoch.current === mine) setCatalog(data);
    } catch (e) {
      if (mounted.current && epoch.current === mine) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  const priorSource = useRef(sourceKey);
  useEffect(() => {
    if (priorSource.current === sourceKey) return;
    priorSource.current = sourceKey;
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError("");
  }, [sourceKey]);
  function edit(which: "duration" | "scan", text: string) {
    epoch.current++;
    (which === "duration" ? setDuration : setScan)(text);
    setReview(null);
    setBusy(false);
    setError("");
  }
  async function preview() {
    if (!catalog || busy || disabled) return;
    const mine = ++epoch.current,
      owned = key,
      parent = program,
      source = sourceKey;
    setBusy(true);
    setReview(null);
    setError("");
    try {
      const choices = readPulseChoices(duration, scan);
      if (choices.scan_seconds !== parent.scan_seconds)
        throw new Error(
          "Pulse scan must equal the current parent Program scan. Change the declaration or the parent explicitly, then review again.",
        );
      const doc = await sourceJsonDocument(PULSE_BASE + "/preview", {
          program: parent,
          choices,
        }),
        data = pulsePreview(doc.data, choices, parent, catalog);
      pulseDescriptors(JSON.parse(await doc.blob.text()), data);
      if (current(mine, owned))
        setReview({ data, key: owned, sourceKey: source, choices });
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function download(format: "review" | "bundle") {
    if (!review || review.key !== key || !catalog || busy || disabled) return;
    const accepted = review,
      mine = ++epoch.current,
      owned = key,
      parent = program;
    setBusy(true);
    setError("");
    try {
      const doc = await programJsonDocument(
          PULSE_BASE + "/export",
          { program: parent, choices: accepted.choices, format },
          true,
        ),
        digest = await blobSha256(doc.blob),
        value = parseSourceDocument(await doc.blob.text());
      if (
        doc.blob.size > 8 * 1024 * 1024 ||
        doc.headers?.get("X-File-SHA256") !== digest
      )
        throw new Error("Pulse original export failed its byte-digest check.");
      if (format === "review") {
        const checked = pulsePreview(value, accepted.choices, parent, catalog);
        if (!sourceEqual(checked, accepted.data))
          throw new Error("Pulse review changed after the exact preview.");
      } else if (
        digest !== accepted.data.bundle_sha256 ||
        !sourceEqual(value, accepted.data.bundle)
      )
        throw new Error("Pulse bundle differs from the reviewed definition.");
      if (current(mine, owned))
        saveBlob(
          doc.blob,
          accepted.data.definition_id +
            (format === "bundle" ? ".bms-macro.json" : ".pulse-review.json"),
        );
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function importDefinition() {
    if (
      !review ||
      review.key !== key ||
      review.sourceKey !== sourceKey ||
      !catalog ||
      busy ||
      disabled ||
      review.data.can_import !== true
    )
      return;
    const accepted = review;
    if (
      !window.confirm(
        `Add “${accepted.data.program.name}” to the macro library of “${program.name}” at its current ${program.scan_seconds}s scan? Conflicts will not be replaced. This creates no instance and saves no revision.`,
      )
    )
      return;
    const mine = ++epoch.current,
      owned = key;
    setBusy(true);
    setError("");
    try {
      const imported = await onImport(
        {
          choices: accepted.choices,
          profile_sha256: catalog.profile_sha256,
          reviewed_parent_sha256: accepted.data.parent_reference.program_sha256,
        },
        accepted.sourceKey,
        accepted.data.definition_id,
        accepted.data.bundle.library.definitions[0],
        () => current(mine, owned),
      );
      if (current(mine, owned) && imported) setReview(null);
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  const shown = review?.key === key ? review : null;
  return (
    <section
      className="macro-card pulse-template"
      aria-label="Cancelable pulse template"
    >
      <h2>Cancelable pulse template</h2>
      <p className="help-text">
        One required Boolean request and one pulse. A committed false cancels
        immediately; held true after expiry does not retrigger.
      </p>
      <label>
        Pulse duration seconds
        <input
          aria-label="Pulse duration seconds"
          type="number"
          min="1"
          max="86400"
          step="1"
          value={duration}
          disabled={busy || disabled}
          onChange={(e) => edit("duration", e.target.value)}
        />
      </label>
      <label>
        Pulse scan seconds
        <input
          aria-label="Pulse scan seconds"
          type="number"
          min="1"
          max="60"
          step="1"
          value={scan}
          disabled={busy || disabled}
          onChange={(e) => edit("scan", e.target.value)}
        />
      </label>
      <p>
        Current parent: <b>{program.name}</b> · {program.scan_seconds}s scan.
        Duration must be a whole multiple of that declared scan.
      </p>
      <div className="button-row">
        <button
          disabled={busy || disabled || !catalog}
          onClick={() => void preview()}
        >
          Preview cancelable pulse
        </button>
        <button disabled={busy || disabled} onClick={() => void reload()}>
          Reload pulse template criteria
        </button>
        {busy && (
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setReview(null);
              setError(
                "Pending pulse response discarded. No field operation was started.",
              );
            }}
          >
            Discard pending pulse response
          </button>
        )}
      </div>
      {busy && <p role="status">Preparing local pulse evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Cancelable pulse preview">
          <h3>{shown.data.program.name}</h3>
          <p>
            6 editable blocks · 6 wires · 1 required Boolean input · 1 Boolean
            output.
          </p>
          <p>
            With continuous successful request scans, pulse is published true at{" "}
            {shown.choices.scan_seconds}s through{" "}
            {shown.choices.duration_seconds}s and false at{" "}
            {shown.choices.duration_seconds + shown.choices.scan_seconds}s. The
            true-to-false interval is {shown.choices.duration_seconds}s; this
            does not claim a physical edge at time zero.
          </p>
          <table className="macro-table" aria-label="Pulse ordinary graph">
            <thead>
              <tr>
                <th>Block</th>
                <th>Kind</th>
                <th>Parameters</th>
              </tr>
            </thead>
            <tbody>
              {shown.data.program.nodes.map((n: any) => (
                <tr key={n.id}>
                  <td>
                    {n.id} · {n.label}
                  </td>
                  <td>{n.kind}</td>
                  <td>
                    <code>{sourceStringify(n.params)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <details>
            <summary>Six connections</summary>
            <ul>
              {shown.data.program.edges.map((e: any) => (
                <li key={e.id}>
                  {e.source} → {e.target}.{e.target_port}
                </li>
              ))}
            </ul>
          </details>
          <p>
            Definition <code>{shown.data.definition_id}</code>
            <br />
            Program SHA-256 <code>{shown.data.program_sha256}</code>
            <br />
            Reviewed parent SHA-256{" "}
            <code>{shown.data.parent_reference.program_sha256}</code>
          </p>
          {shown.data.diagnostics.map((d: any, i: number) => (
            <p key={i}>
              {d.level}: {d.message}
            </p>
          ))}
          <div className="button-row">
            <button
              disabled={busy || disabled}
              onClick={() => void download("review")}
            >
              Download original pulse review
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => void download("bundle")}
            >
              Download original pulse bundle
            </button>
            <button
              className="primary"
              disabled={busy || disabled || shown.data.can_import !== true}
              onClick={() => void importDefinition()}
            >
              Import reviewed pulse definition
            </button>
          </div>
          <p className="help-text">
            Import adds only this definition. Add an instance separately and
            wire its required request. The scoped import rechecks the supplied
            parent clock/source; it is not a persisted review or server
            compare-and-swap. Generic imports, later parent clock changes and
            per-step time overrides can leave this historical qualification.
          </p>
          <details>
            <summary>Pulse source criteria and limits</summary>
            <a
              href={catalog?.profile.source.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {catalog?.profile.source.title} {catalog?.profile.source.edition}{" "}
              · PDF1698–1700
            </a>
            <p>
              Profile <code>{catalog?.profile.profile}</code> ·{" "}
              <code>{catalog?.profile_sha256}</code>
            </p>
            <p>
              Bad quality rolls back time/state/output and can retain a positive
              pulse. False with bad quality is not a cancellation. Fresh
              sessions reset state; no native Reset Action or retained restart
              is inferred. No field connection, power lease, native JCI or
              physical protection is established.
            </p>
          </details>
        </section>
      )}
    </section>
  );
}
