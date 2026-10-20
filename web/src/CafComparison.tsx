import { useEffect, useRef, useState } from "react";
import { Download, FileDiff, Upload } from "lucide-react";
import { api, saveBlob } from "./api";
import "./caf-comparison.css";

type Opened = {
  name: string;
  sha256: string;
  model: string;
  release_mode: string;
  objects: number;
};
type Side = {
  sha256: string;
  scalar: { type: string; text: string; text_truncated: boolean } | null;
  elements: number;
  attributes: Record<string, string>;
  attributes_truncated: boolean;
  leaf_text: string | null;
  leaf_text_truncated: boolean;
  mixed_text: string | null;
  tail_text: string | null;
  mixed_content: { element: string; kind: string; text: string }[];
};
type Evidence = {
  sha256: string;
  events: number;
  preview: { event: string; truncated: boolean }[];
  preview_truncated: boolean;
};
type Change = {
  index: number;
  category: string;
  change: string;
  ref: string | null;
  object: { name: string; class_name: string } | null;
  record_kind: string | null;
  property_id: string | null;
  property_name: string | null;
  numeric_lexeme_only?: boolean;
  before: Side | null;
  after: Side | null;
  before_evidence?: Evidence;
  after_evidence?: Evidence;
};
type Review = {
  before: Opened;
  after: Opened;
  byte_identical: boolean;
  xml_identical: boolean;
  native_records_equal: boolean;
  target_metadata_equal: boolean | null;
  counts: Record<string, number>;
  total: number;
  filtered_total: number;
  offset: number;
  limit: number;
  changes: Change[];
  scope: string;
  normalization: string;
  matching: string;
};
const CATEGORIES = [
  "application_value",
  "simulation_value",
  "wiring",
  "execution_order",
  "block_membership",
  "drawing",
  "controller_identity",
  "object_identity",
  "object_membership",
  "record_order",
  "native_metadata",
  "opaque_metadata",
];
const human = (text: string) => text.replaceAll("_", " ");

export function CafComparison() {
  const [before, setBefore] = useState<Opened | null>(null);
  const [after, setAfter] = useState<Opened | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  function invalidate() {
    generation.current++;
    setReview(null);
    setError("");
  }
  async function open(file: File | undefined, side: "before" | "after") {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    const current = ++generation.current;
    try {
      const form = new FormData();
      form.append("file", file);
      const next = await api("/caf", form);
      if (!mounted.current || current !== generation.current) return;
      const value = { ...next, name: file.name };
      if (side === "before") setBefore(value);
      else setAfter(value);
      setReview(null);
    } catch (e) {
      if (mounted.current && current === generation.current)
        setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function request(offset = 0, limit = 100) {
    if (!before || !after)
      throw new Error("Open both original and candidate CAFs.");
    return {
      before_sha: before.sha256,
      after_sha: after.sha256,
      category: category || null,
      query,
      offset,
      limit,
    };
  }
  async function compare(offset = 0) {
    if (busy || !before || !after) return;
    const current = generation.current;
    setBusy(true);
    setError("");
    try {
      const next = await api("/caf/compare", request(offset));
      if (mounted.current && current === generation.current) setReview(next);
    } catch (e) {
      if (mounted.current && current === generation.current)
        setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function exportReview() {
    if (!review || busy) return;
    if (review.filtered_total > 5000) {
      setError(
        "Apply a category or search filter before exporting more than 5000 changed records.",
      );
      return;
    }
    const current = generation.current;
    setBusy(true);
    setError("");
    try {
      const changes: Change[] = [];
      let first: Review | undefined;
      do {
        if (!mounted.current || current !== generation.current) return;
        const page: Review = await api(
          "/caf/compare",
          request(changes.length, 500),
        );
        if (
          page.filtered_total !== review.filtered_total ||
          page.before.sha256 !== review.before.sha256 ||
          page.after.sha256 !== review.after.sha256
        )
          throw new Error(
            "Comparison changed; create a new review before exporting.",
          );
        first ??= page;
        changes.push(...page.changes);
        if (!page.changes.length && changes.length < page.filtered_total)
          throw new Error("Comparison pagination did not advance.");
      } while (changes.length < review.filtered_total);
      if (!mounted.current || current !== generation.current) return;
      saveBlob(
        new Blob(
          [
            JSON.stringify(
              {
                ...first,
                filters: { category: category || null, query },
                offset: 0,
                limit: changes.length,
                changes,
              },
              null,
              2,
            ),
          ],
          { type: "application/json" },
        ),
        "caf-change-review.json",
      );
    } catch (e) {
      if (mounted.current && current === generation.current)
        setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function value(side: Side | null, evidence?: Evidence) {
    if (evidence)
      return (
        <>
          <strong>{evidence.events} XML evidence events</strong>
          <small>{evidence.preview.map((item) => item.event).join("\n")}</small>
          {(evidence.preview_truncated ||
            evidence.preview.some((item) => item.truncated)) && (
            <small>Preview clipped; hash covers all events.</small>
          )}
          <small className="mono" title={evidence.sha256}>
            {evidence.sha256.slice(0, 16)}…
          </small>
        </>
      );
    if (!side) return <span className="caf-compare-muted">Absent</span>;
    return (
      <>
        <strong>
          {side.scalar
            ? side.scalar.text || "(empty)"
            : side.leaf_text !== null
              ? side.leaf_text || "(empty)"
              : `${side.elements} XML elements`}
        </strong>
        <small>
          {side.scalar?.type || "structured record"}
          {side.scalar?.text_truncated || side.leaf_text_truncated
            ? " · text clipped at 2048 characters"
            : ""}
          {side.attributes_truncated ? " · attribute previews clipped" : ""}
        </small>
        <small className="mono" title={side.sha256}>
          {side.sha256.slice(0, 16)}…
        </small>
        {(side.mixed_text ||
          side.tail_text ||
          side.mixed_content.length > 0) && (
          <small>Mixed XML text changed; inspect evidence.</small>
        )}
      </>
    );
  }
  return (
    <div className="workspace-page caf-comparison">
      <div className="page-intro">
        <div>
          <span className="eyebrow">
            JOHNSON CONTROLS · OFFLINE CHANGE REVIEW
          </span>
          <h1>Compare CAF files</h1>
          <p>
            Review native records between an original and a candidate
            application. Both files remain unchanged.
          </p>
        </div>
        <FileDiff size={30} />
      </div>
      <div className="caf-compare-files">
        {(["before", "after"] as const).map((side) => {
          const item = side === "before" ? before : after;
          return (
            <section
              className="card"
              key={side}
              aria-label={side === "before" ? "Original CAF" : "Candidate CAF"}
            >
              <div className="card-header">
                <h3>{side === "before" ? "Original CAF" : "Candidate CAF"}</h3>
                <label className="caf-compare-upload">
                  <Upload size={14} />
                  Open {side === "before" ? "original" : "candidate"}
                  <input
                    aria-label={
                      side === "before"
                        ? "Original CAF file"
                        : "Candidate CAF file"
                    }
                    type="file"
                    accept=".caf"
                    disabled={busy}
                    onChange={(e) => {
                      open(e.target.files?.[0], side);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              <div className="caf-compare-file">
                {item ? (
                  <>
                    <h2>{item.name}</h2>
                    <p>
                      {item.model || "Unidentified controller"} · release mode{" "}
                      {item.release_mode || "unknown"} · {item.objects} objects
                    </p>
                    <small className="mono">SHA-256 {item.sha256}</small>
                  </>
                ) : (
                  <p>Choose a native CAF from this computer.</p>
                )}
              </div>
            </section>
          );
        })}
      </div>
      <p className="caf-compare-scope">
        This compares exact object references, record types and native property
        IDs. It does not compile, retarget, simulate or apply a controller
        program. Unknown metadata and saved simulation values stay visible.
      </p>
      <div className="caf-compare-controls">
        <label>
          Change category
          <select
            aria-label="CAF comparison category"
            value={category}
            disabled={busy}
            onChange={(e) => {
              invalidate();
              setCategory(e.target.value);
            }}
          >
            <option value="">All categories</option>
            {CATEGORIES.map((kind) => (
              <option value={kind} key={kind}>
                {human(kind)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Find object or property
          <input
            aria-label="CAF comparison search"
            value={query}
            disabled={busy}
            maxLength={200}
            placeholder="Name, reference, property ID…"
            onChange={(e) => {
              invalidate();
              setQuery(e.target.value);
            }}
          />
        </label>
        <button
          className="primary"
          disabled={busy || !before || !after}
          onClick={() => compare()}
        >
          <FileDiff size={15} />
          Compare CAF records
        </button>
        {busy && <span role="status">Reviewing native records…</span>}
      </div>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {review && (
        <section
          className="card caf-compare-report"
          aria-label="CAF comparison results"
        >
          <div className="card-header">
            <h3>{review.total} changed records</h3>
            <button disabled={busy} onClick={exportReview}>
              <Download size={15} />
              Download CAF change review
            </button>
          </div>
          <div className="caf-compare-summary">
            <p role="status">
              {review.byte_identical
                ? "Files are byte-for-byte identical."
                : review.native_records_equal
                  ? "Native records match; archive or XML formatting differs."
                  : "Native record changes found."}
            </p>
            {review.target_metadata_equal === false && (
              <p className="inline-error">
                Model or release-mode metadata differs. This review does not
                establish controller compatibility or convert between targets.
              </p>
            )}
            <p>
              {Object.entries(review.counts)
                .map(([kind, count]) => `${human(kind)}: ${count}`)
                .join(" · ") || "No changed records."}
            </p>
            <details>
              <summary>Comparison scope and evidence</summary>
              <p>{review.scope}</p>
              <p>{review.matching}</p>
              <p>{review.normalization}</p>
              <p>
                Large value and metadata previews are clipped. Record hashes
                cover complete content; inspect original CAFs for full values.
              </p>
            </details>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Record / change</th>
                  <th>Original</th>
                  <th>Candidate</th>
                </tr>
              </thead>
              <tbody>
                {review.changes.map((row) => (
                  <tr key={row.index}>
                    <td>
                      <b>{row.object?.name || row.ref || "Root metadata"}</b>
                      <small>
                        {human(row.category)} · {human(row.change)}
                      </small>
                      <small>
                        {row.record_kind} {row.property_id} {row.property_name}
                      </small>
                      {row.numeric_lexeme_only && (
                        <small>
                          Equivalent numeric text; representation differs.
                        </small>
                      )}
                      <details>
                        <summary>Native record identity and hashes</summary>
                        <pre>{JSON.stringify(row, null, 2)}</pre>
                      </details>
                    </td>
                    <td>{value(row.before, row.before_evidence)}</td>
                    <td>{value(row.after, row.after_evidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button
              disabled={busy || !review.offset}
              onClick={() => compare(Math.max(0, review.offset - review.limit))}
            >
              Previous comparison page
            </button>
            <span>
              {review.filtered_total ? review.offset + 1 : 0}–
              {Math.min(
                review.offset + review.changes.length,
                review.filtered_total,
              )}{" "}
              of {review.filtered_total} filtered records
            </span>
            <button
              disabled={
                busy ||
                review.offset + review.changes.length >= review.filtered_total
              }
              onClick={() => compare(review.offset + review.limit)}
            >
              Next comparison page
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
