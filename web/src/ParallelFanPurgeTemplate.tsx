import { useEffect, useRef, useState } from "react";
import { api, programJsonDocument, saveBlob, sourceJsonDocument } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import { sha256Blob } from "./activityContracts";
import {
  PURGE_BASE,
  PURGE_FIELDS,
  PURGE_DEFAULT_DRAFT,
  PURGE_LABELS,
  purgeCatalog,
  purgeDescriptors,
  purgePreview,
  readPurgeChoices,
  type PurgeChoices,
  type PurgeDraft,
  type PurgeField,
  type PurgeImport,
  type Data,
} from "./parallelFanPurgeContract";
import type { Program } from "./types";
import "./parallel-fan-purge.css";

type Review = {
  data: Data;
  key: string;
  sourceKey: string;
  choices: PurgeChoices;
  blob: Blob;
};
export function ParallelFanPurgeTemplate({
  program,
  sourceEpoch,
  authorityReady,
  disabled,
  onImport,
}: {
  program: Program;
  sourceEpoch: number;
  authorityReady: boolean;
  disabled: boolean;
  onImport: (
    request: PurgeImport,
    sourceKey: string,
    definition: string,
    expectedDefinition: Data,
    owned: () => boolean,
  ) => Promise<boolean>;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [draft, setDraft] = useState<PurgeDraft>(PURGE_DEFAULT_DRAFT),
    [scan, setScan] = useState("1"),
    [review, setReview] = useState<Review | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceEpoch + ":" + sourceStringify(program),
    key = JSON.stringify({
      draft,
      scan,
      sourceKey,
      authorityReady,
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
      const data = await purgeCatalog(await api(PURGE_BASE + "/catalog"));
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
  const previousSource = useRef(sourceKey);
  useEffect(() => {
    if (previousSource.current === sourceKey) return;
    previousSource.current = sourceKey;
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError("");
  }, [sourceKey]);
  const previousAuthority = useRef(authorityReady);
  useEffect(() => {
    const wasReady = previousAuthority.current;
    previousAuthority.current = authorityReady;
    if (!wasReady || authorityReady) return;
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError("");
  }, [authorityReady]);
  function edit(field: PurgeField, text: string) {
    epoch.current++;
    setDraft((previous) => ({ ...previous, [field]: text }));
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
      const choices = readPurgeChoices(draft, scan);
      if (choices.scan_seconds !== parent.scan_seconds)
        throw new Error(
          "Declared parallel purge scan must equal the current parent Program scan. Review the matching clock explicitly.",
        );
      const doc = await sourceJsonDocument(PURGE_BASE + "/preview", {
          program: parent,
          choices,
        }),
        data = purgePreview(doc.data, choices, parent, catalog);
      purgeDescriptors(JSON.parse(await doc.blob.text()), data);
      if (current(mine, owned))
        setReview({
          data,
          key: owned,
          sourceKey: source,
          choices,
          blob: doc.blob,
        });
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
          PURGE_BASE + "/export",
          { program: parent, choices: accepted.choices, format },
          true,
        ),
        digest = await sha256Blob(doc.blob),
        value = parseSourceDocument(await doc.blob.text());
      if (
        doc.blob.size > 8 * 1024 * 1024 ||
        doc.headers?.get("X-File-SHA256") !== digest
      )
        throw new Error(
          "Parallel fan purge original export failed its byte-digest check.",
        );
      if (format === "review") {
        if (
          !sourceEqual(
            purgePreview(value, accepted.choices, parent, catalog),
            accepted.data,
          )
        )
          throw new Error(
            "Parallel fan purge review changed after the exact preview.",
          );
      } else if (
        digest !== accepted.data.bundle_sha256 ||
        !sourceEqual(value, accepted.data.bundle)
      )
        throw new Error(
          "Parallel fan purge activity bundle differs from the reviewed definition.",
        );
      if (current(mine, owned))
        saveBlob(
          doc.blob,
          accepted.data.definition_id +
            (format === "review"
              ? ".parallel-fan-purge-review.json"
              : ".bms-activities.json"),
        );
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function adopt() {
    if (
      !review ||
      review.key !== key ||
      !review.data.can_import ||
      !catalog ||
      busy ||
      disabled
    )
      return;
    const accepted = review;
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
      className="macro-card parallel-purge-template"
      aria-label="Parallel fan purge template"
    >
      <h2>Parallel fan purge template</h2>
      <p>
        An editable thermal fan request with two shared memories: the previous
        request and elapsed time while raw heating remains below the fan-off
        threshold.
      </p>
      <div className="parallel-purge-fields">
        {PURGE_FIELDS.map((field) => (
          <label key={field}>
            {PURGE_LABELS[field]}
            <input
              aria-label={"Parallel purge " + PURGE_LABELS[field]}
              type="text"
              inputMode="decimal"
              value={draft[field]}
              disabled={busy || disabled}
              onChange={(e) => edit(field, e.target.value)}
            />
          </label>
        ))}
        <label>
          Declared scan seconds
          <input
            aria-label="Parallel purge Declared scan seconds"
            type="number"
            min="1"
            max="60"
            step="1"
            value={scan}
            disabled={busy || disabled}
            onChange={(e) => {
              epoch.current++;
              setScan(e.target.value);
              setReview(null);
              setBusy(false);
              setError("");
            }}
          />
        </label>
      </div>
      <p className="help-text">
        Standalone defaults do not replace the five required live instance
        connections. Commands are 0–100%; thresholds must satisfy 0 &lt; off
        &lt; on &lt; 100, with no invented epsilon. Live purge duration may be
        fractional from 0 to 86400 seconds.
      </p>
      <p className="help-text">
        Current parent: <b>{program.name}</b> · {program.scan_seconds}s scan.
        The declaration must match that whole 1–60 second scan. Elapsed memory
        counts this declared step per accepted scan; actual-dt overrides or
        later generic imports/edits can leave the recorded qualification.
      </p>
      <div className="button-row">
        <button
          disabled={busy || disabled || !catalog}
          onClick={() => void preview()}
        >
          Preview parallel fan purge
        </button>
        <button disabled={busy || disabled} onClick={() => void reload()}>
          Reload parallel fan purge criteria
        </button>
        {busy && (
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setReview(null);
              setError(
                "Pending parallel fan purge response discarded. No field operation was started.",
              );
            }}
          >
            Discard pending parallel fan purge response
          </button>
        )}
      </div>
      {busy && (
        <p role="status">Preparing local parallel fan purge evidence…</p>
      )}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Parallel fan purge preview">
          <h3>{shown.data.program.name}</h3>
          <p>
            {shown.data.program.nodes.length} editable blocks ·{" "}
            {shown.data.program.edges.length} wires · 5 required numeric inputs
            · 2 Boolean outputs · 2 shared Delays.
          </p>
          <table className="macro-table" aria-label="Parallel fan purge ports">
            <thead>
              <tr>
                <th>Role</th>
                <th>Port</th>
                <th>Type</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {[
                ...shown.data.inputs.map((port: Data) => ({
                  ...port,
                  role: "Required input",
                })),
                ...shown.data.outputs.map((port: Data) => ({
                  ...port,
                  role: "Named output",
                })),
              ].map((port) => (
                <tr key={port.role + port.id}>
                  <td>{port.role}</td>
                  <td>
                    {port.id} · {port.label}
                  </td>
                  <td>{port.value_type}</td>
                  <td>{port.unit || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <details>
            <summary>Ordinary control graph</summary>
            <table
              className="macro-table"
              aria-label="Parallel fan purge ordinary graph"
            >
              <thead>
                <tr>
                  <th>Block</th>
                  <th>Kind</th>
                  <th>Parameters</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.program.nodes.map((node: Data) => (
                  <tr key={node.id}>
                    <td>
                      {node.id} · {node.label}
                    </td>
                    <td>{node.kind}</td>
                    <td>
                      <code>{sourceStringify(node.params)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul>
              {shown.data.program.edges.map((edge: Data) => (
                <li key={edge.id}>
                  {edge.source} → {edge.target}.{edge.target_port}
                </li>
              ))}
            </ul>
          </details>
          <p className="help-text">
            Either command strictly above on requests the fan. Release requires
            both commands strictly below off and sufficient accumulated
            raw-heating-low time. Heating at or above off resets that time,
            including an in-band rise. Cooling affects start/release without
            pretending to reset the heating timer.
          </p>
          <p className="help-text">
            Elapsed memory caps at 86400 seconds, independently of the live
            duration. Increasing duration keeps trusted prior low time;
            decreasing it can release on the current successful scan. Low
            heating alone can accumulate time at startup without requesting a
            fan.
          </p>
          <p className="parallel-purge-retention">
            A good-quality invalid configuration holds the previous request,
            resets elapsed memory and commits false status. A bad-quality or
            failed scan instead rolls back the entire transaction, possibly
            retaining On, true status and earlier elapsed time. This is
            committed-scan accounting, not proof of continuous physical
            conditions.
          </p>
          <p className="help-text">
            The configuration flag describes the last committed configuration,
            not current sample quality or fan proof. Terminal portable output
            forces do not rewrite these generated memories. This request does
            not provide occupancy, fan proof, motor protection or physical
            switching.
          </p>
          <details>
            <summary>Source and limits</summary>
            <p>
              {shown.data.profile.source.title}{" "}
              {shown.data.profile.source.edition}, PDF pages 1167–1168. Strict
              comparison ties, bounded memory, invalid-configuration behavior
              and whole-transaction retention are authored substitutions; native
              last-reliable mechanics and Enum bindings remain unverified.
            </p>
            <p>
              Native IEC keeps its existing ±3e38 input limit and refuses
              nonzero samples that round to REAL zero. Finite-width rounding of
              thresholds or fractional duration can change comparisons; no
              cross-width trace or native equality equivalence is promised.
            </p>
            <ul>
              {shown.data.profile.gaps.map((gap: string) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </details>
          <p className="parallel-purge-digests">
            Definition <code>{shown.data.definition_id}</code>
            <br />
            Program SHA-256 <code>{shown.data.program_sha256}</code>
            <br />
            Parent SHA-256{" "}
            <code>{shown.data.parent_reference.program_sha256}</code>
          </p>
          {shown.data.diagnostics.map((diagnostic: Data, i: number) => (
            <p key={i}>
              {diagnostic.level}: {diagnostic.message}
            </p>
          ))}
          <div className="button-row">
            <button
              disabled={busy || disabled}
              onClick={() => void download("review")}
            >
              Export original parallel fan purge review JSON
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => void download("bundle")}
            >
              Export original parallel fan purge activity bundle
            </button>
            <button
              disabled={busy || disabled || !shown.data.can_import}
              onClick={() => void adopt()}
            >
              Import reviewed parallel fan purge definition
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => {
                if (mounted.current && shown.key === live.current)
                  saveBlob(
                    shown.blob,
                    shown.data.definition_id +
                      ".parallel-fan-purge-preview-response.json",
                  );
              }}
            >
              Download original parallel fan purge preview response
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => {
                epoch.current++;
                setReview(null);
              }}
            >
              Dismiss parallel fan purge review
            </button>
          </div>
          <p className="help-text">
            Import adds only the reviewed reusable definition. Add and wire an
            instance separately; no revision is saved. Source digests bind
            server-produced evidence, not manufacturer authentication, native
            JCI/G36/Title 24 acceptance or physical fan protection.
          </p>
        </section>
      )}
    </section>
  );
}
