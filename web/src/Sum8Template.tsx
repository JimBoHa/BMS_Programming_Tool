import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob, sourceApi } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  SUM8_BASE,
  blobSha256,
  catalogResult,
  previewResult,
  type Data,
} from "./sum8TemplateContract";
import type { Program } from "./types";

export function Sum8Template({
  program,
  disabled,
  onImport,
}: {
  program: Program;
  disabled: boolean;
  onImport: (
    bundle: Data,
    sourceKey: string,
    definition: string,
    owned: () => boolean,
  ) => Promise<boolean>;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [unit, setUnit] = useState<string | null>(null),
    [review, setReview] = useState<{
      data: Data;
      key: string;
      sourceKey: string;
      unit: string;
    } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceStringify(program),
    key = JSON.stringify({ unit, sourceKey, profile: catalog?.profile_sha256 }),
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
      const result = await catalogResult(await api(SUM8_BASE + "/catalog"));
      if (mounted.current && epoch.current === mine) setCatalog(result);
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
  async function preview() {
    if (unit === null || !catalog || busy || disabled) return;
    const mine = ++epoch.current,
      owned = key,
      choice = unit,
      source = sourceKey;
    setBusy(true);
    setReview(null);
    setError("");
    try {
      const data = previewResult(
        await sourceApi(SUM8_BASE + "/preview", { unit: choice }),
        choice,
        catalog,
      );
      if (current(mine, owned))
        setReview({ data, key: owned, sourceKey: source, unit: choice });
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function download(format: "review" | "bundle") {
    if (!review || review.key !== key || !catalog || busy || disabled) return;
    const mine = ++epoch.current,
      owned = key,
      accepted = review;
    setBusy(true);
    setError("");
    try {
      const doc = await apiJsonDocument(
          SUM8_BASE + "/export",
          { unit: accepted.unit, format },
          true,
        ),
        digest = await blobSha256(doc.blob),
        value = parseSourceDocument(await doc.blob.text());
      if (
        doc.blob.size > 8 * 1024 * 1024 ||
        doc.headers?.get("X-File-SHA256") !== digest
      )
        throw new Error(
          "Sum template export failed its original byte-digest check.",
        );
      if (format === "review") {
        const checked = previewResult(value, accepted.unit, catalog);
        if (!sourceEqual(checked, accepted.data))
          throw new Error("Sum review changed after the exact preview.");
      } else if (
        digest !== accepted.data.bundle_sha256 ||
        !sourceEqual(value, accepted.data.bundle)
      )
        throw new Error(
          "Original sum bundle differs from the exact reviewed definition.",
        );
      if (current(mine, owned))
        saveBlob(
          doc.blob,
          accepted.data.definition_id +
            (format === "bundle" ? ".bms-macro.json" : ".sum8-review.json"),
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
      review.data.can_import !== true ||
      busy ||
      disabled
    )
      return;
    const accepted = review;
    if (
      !window.confirm(
        `Add “${accepted.data.program.name}” to the macro library of the current editor “${program.name}”? Conflicting definitions will not be replaced. This creates no instance and saves no project revision.`,
      )
    )
      return;
    const mine = ++epoch.current,
      owned = key;
    setBusy(true);
    setError("");
    try {
      const imported = await onImport(
        accepted.data.bundle,
        accepted.sourceKey,
        accepted.data.definition_id,
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
      className="macro-card sum8-template"
      aria-label="Eight-input sum template"
    >
      <h2>Eight-input sum template</h2>
      <p className="help-text">
        Eight required numeric inputs, seven ordinary Add blocks, one result.
        Wire unused contributions explicitly to zero. This authored fixed-order
        sum is not a physical chiller-capacity calculation or native JCI Add-8
        binding.
      </p>
      <label>
        Sum template units
        <select
          aria-label="Sum template units"
          disabled={busy || disabled || !catalog}
          value={unit ?? "__choose__"}
          onChange={(e) => {
            epoch.current++;
            setUnit(e.target.value === "__choose__" ? null : e.target.value);
            setReview(null);
            setBusy(false);
            setError("");
          }}
        >
          <option value="__choose__">Choose units explicitly…</option>
          {catalog?.units.map((u: any) => (
            <option key={u.value} value={u.value}>
              {u.label}
            </option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <button
          disabled={busy || disabled || !catalog || unit === null}
          onClick={() => void preview()}
        >
          Preview eight-input sum
        </button>
        <button disabled={busy || disabled} onClick={() => void reload()}>
          Reload sum template criteria
        </button>
        {busy && (
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setReview(null);
              setError(
                "Pending sum template response discarded. No field operation was started.",
              );
            }}
          >
            Discard pending sum template response
          </button>
        )}
      </div>
      {busy && <p role="status">Preparing local sum template evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Eight-input sum preview">
          <h3>{shown.data.program.name}</h3>
          <p>16 editable blocks · 15 wires · 8 required inputs · 1 output.</p>
          <p>
            Left fold: (((((((i1 + i2) + i3) + i4) + i5) + i6) + i7) + i8).
            Units are labels; no conversion is inferred.
          </p>
          <table className="macro-table" aria-label="Sum template ports">
            <thead>
              <tr>
                <th>Port</th>
                <th>Type / unit</th>
                <th>Required</th>
              </tr>
            </thead>
            <tbody>
              {shown.data.inputs.map((p: any) => (
                <tr key={p.id}>
                  <td>
                    {p.id} · {p.label}
                  </td>
                  <td>
                    {p.value_type} · {p.unit || "dimensionless"}
                  </td>
                  <td>yes</td>
                </tr>
              ))}
              <tr>
                <td>result · Sum</td>
                <td>number · {shown.unit || "dimensionless"}</td>
                <td>output</td>
              </tr>
            </tbody>
          </table>
          <p>
            Definition <code>{shown.data.definition_id}</code>
            <br />
            Program SHA-256 <code>{shown.data.program_sha256}</code>
            <br />
            Bundle SHA-256 <code>{shown.data.bundle_sha256}</code>
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
              Download original sum review
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => void download("bundle")}
            >
              Download original sum bundle
            </button>
            <button
              className="primary"
              disabled={busy || disabled || shown.data.can_import !== true}
              onClick={() => void importDefinition()}
            >
              Import reviewed sum definition
            </button>
          </div>
          <p className="help-text">
            Import adds only the definition to this editor. Use the existing Add
            instance action separately, then wire all eight ports. Identical
            definitions are idempotent; conflicting IDs refuse without
            overwriting. No project revision, field connection or power lease is
            created.
          </p>
          <details>
            <summary>Source criteria and limitations</summary>
            <a
              href={catalog?.profile.source.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {catalog?.profile.source.title} {catalog?.profile.source.edition}{" "}
              · PDF 677, Tables 276–277
            </a>
            <p>
              Profile <code>{catalog?.profile.profile}</code> · rules{" "}
              <code>{catalog?.profile_sha256}</code>
            </p>
            <p>
              Source SHA-256 <code>{catalog?.profile.source.sha256}</code>
            </p>
            <p>
              Bad quality/nonfinite arithmetic rolls back the whole scan and may
              retain nonzero output. Later definition edits retain historical
              provenance, not a claim of unchanged template generation. Hashes
              do not authenticate manufacturer origin; no
              native/physical/compliance acceptance is established.
            </p>
          </details>
        </section>
      )}
    </section>
  );
}
