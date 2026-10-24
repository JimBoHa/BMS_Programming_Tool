import { useEffect, useRef, useState } from "react";
import { api, programJsonDocument, saveBlob, sourceJsonDocument } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import { sha256Blob } from "./activityContracts";
import {
  CO2_BASE,
  CO2_FIELDS,
  co2Catalog,
  co2Descriptors,
  co2Draft,
  co2Preview,
  co2Units,
  readCO2Choices,
  type CO2Choices,
  type CO2Draft,
  type CO2Field,
  type CO2Import,
  type Data,
  type FlowUnit,
} from "./co2MinimumFlowContract";
import type { Program } from "./types";
import "./co2-minimum-flow.css";

type Review = {
  data: Data;
  key: string;
  sourceKey: string;
  choices: CO2Choices;
  blob: Blob;
};
const defaults: CO2Draft = {
  co2_default: "800.0",
  co2_reset_a_default: "800.0",
  co2_reset_b_default: "1000.0",
  flow_low_default: "425.0",
  flow_high_default: "825.0",
};
const labels: Record<CO2Field, string> = {
  co2_default: "Measured CO2 default",
  co2_reset_a_default: "CO2 Reset A default",
  co2_reset_b_default: "CO2 Reset B default",
  flow_low_default: "Low minimum airflow default",
  flow_high_default: "High minimum airflow default",
};
export function CO2MinimumFlowTemplate({
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
    request: CO2Import,
    sourceKey: string,
    definition: string,
    expectedDefinition: Data,
    owned: () => boolean,
  ) => Promise<boolean>;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [draft, setDraft] = useState<CO2Draft>(defaults),
    [unit, setUnit] = useState<FlowUnit>("cfm"),
    [review, setReview] = useState<Review | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceEpoch + ":" + sourceStringify(program),
    key = JSON.stringify({
      draft,
      unit,
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
      const data = await co2Catalog(await api(CO2_BASE + "/catalog"));
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
  function edit(field: CO2Field, text: string) {
    epoch.current++;
    setDraft((previous) => ({ ...previous, [field]: text }));
    setReview(null);
    setBusy(false);
    setError("");
  }
  async function convert(target: FlowUnit) {
    if (!catalog || busy || disabled || target === unit) return;
    const mine = ++epoch.current,
      owned = key;
    setBusy(true);
    setReview(null);
    setError("");
    try {
      const choices = readCO2Choices(unit, draft),
        doc = await programJsonDocument(CO2_BASE + "/units", {
          choices,
          flow_unit: target,
          profile_sha256: catalog.profile_sha256,
        }),
        data = co2Units(
          parseSourceDocument(await doc.blob.text()),
          choices,
          target,
          catalog,
        );
      if (current(mine, owned)) {
        setDraft(co2Draft(data.choices));
        setUnit(target);
      }
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
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
      const choices = readCO2Choices(unit, draft),
        doc = await sourceJsonDocument(CO2_BASE + "/preview", {
          program: parent,
          choices,
        }),
        data = co2Preview(doc.data, choices, parent, catalog);
      co2Descriptors(JSON.parse(await doc.blob.text()), data);
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
          CO2_BASE + "/export",
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
          "CO2 airflow original export failed its byte-digest check.",
        );
      if (format === "review") {
        if (
          !sourceEqual(
            co2Preview(value, accepted.choices, parent, catalog),
            accepted.data,
          )
        )
          throw new Error(
            "CO2 airflow review changed after the exact preview.",
          );
      } else if (
        digest !== accepted.data.bundle_sha256 ||
        !sourceEqual(value, accepted.data.bundle)
      )
        throw new Error(
          "CO2 airflow activity bundle differs from the reviewed definition.",
        );
      if (current(mine, owned))
        saveBlob(
          doc.blob,
          accepted.data.definition_id +
            (format === "review"
              ? ".co2-flow-review.json"
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
      className="macro-card co2-flow-template"
      aria-label="CO2 minimum-airflow template"
    >
      <h2>CO₂ minimum-airflow template</h2>
      <p>
        One editable graph resets a minimum-airflow request from five live
        numeric inputs. Airflow uses cfm or L/s; connect it to an appropriate
        downstream airflow controller.
      </p>
      <div className="co2-flow-fields">
        <label>
          Airflow unit
          <select
            aria-label="CO2 airflow unit"
            value={unit}
            disabled={busy || disabled || !catalog}
            onChange={(e) => void convert(e.target.value as FlowUnit)}
          >
            <option value="cfm">cfm</option>
            <option value="L/s">L/s</option>
          </select>
        </label>
        {CO2_FIELDS.map((field) => (
          <label key={field}>
            {labels[field]} ({field.startsWith("flow_") ? unit : "ppm"})
            <input
              aria-label={
                labels[field].startsWith("CO2 ")
                  ? labels[field]
                  : "CO2 " + labels[field]
              }
              type="text"
              inputMode="decimal"
              value={draft[field]}
              disabled={busy || disabled}
              onChange={(e) => edit(field, e.target.value)}
            />
          </label>
        ))}
      </div>
      <p className="help-text">
        These are standalone-definition defaults. Every instance still requires
        all five live connections. Reset B must exceed A inside 0–1000000 ppm.
        Airflow endpoints must be nonnegative, ordered and within 1000000 L/s
        equivalent; equal airflow endpoints are allowed.
      </p>
      <p className="help-text">
        Current parent: <b>{program.name}</b> · {program.scan_seconds}s scan.
        The graph has no timer or independent clock; the parent scan applies.
        Changing units converts only the two airflow defaults and retires the
        review.
      </p>
      <div className="button-row">
        <button
          disabled={busy || disabled || !catalog}
          onClick={() => void preview()}
        >
          Preview CO2 minimum airflow
        </button>
        <button disabled={busy || disabled} onClick={() => void reload()}>
          Reload CO2 airflow criteria
        </button>
        {busy && (
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setReview(null);
              setError(
                "Pending CO2 airflow response discarded. No field operation was started.",
              );
            }}
          >
            Discard pending CO2 airflow response
          </button>
        )}
      </div>
      {busy && <p role="status">Preparing local CO₂ airflow evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="CO2 minimum-airflow preview">
          <h3>{shown.data.program.name}</h3>
          <p>
            38 editable blocks · 57 wires · 5 required numeric inputs · 2 named
            mixed-type outputs · 1 shared Delay.
          </p>
          <table className="macro-table" aria-label="CO2 minimum-airflow ports">
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
              aria-label="CO2 minimum-airflow ordinary graph"
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
          <p className="co2-flow-retention">
            A good-quality invalid endpoint configuration holds the previous
            selected airflow and commits false configuration-valid status; the
            first such scan selects zero. Repair resumes immediately. This zero
            fallback is not a ventilation guarantee.
          </p>
          <p className="help-text">
            Bad quality or another scan fault rolls back the whole transaction,
            retaining previous flow and status, which may remain positive and
            true. “Last committed reset configuration valid” does not report
            current sample quality, occupancy, module reliability or measured
            ventilation. Before the first successful scan, existing empty/zero
            startup applies.
          </p>
          <p className="help-text">
            Terminal output forcing in the portable simulator does not rewrite
            this graph’s retained unforced flow. No native or physical forcing
            support is implied.
          </p>
          <details>
            <summary>Source and limits</summary>
            <p>
              {shown.data.profile.source.title}{" "}
              {shown.data.profile.source.edition}, PDF pages 736–737. The cited
              output is airflow, despite the source’s position-related module
              name. The bounded linear curve, invalid-configuration hold,
              diagnostic and transaction policy are authored substitutions.
            </p>
            <p>
              Measured CO₂ may be any finite portable sample. The unchanged
              Native IEC input profile refuses values outside ±3e38 and nonzero
              values that round to REAL zero. Endpoint rounding can merge a
              native band and commit false/held flow where portable arithmetic
              remains valid. No cross-width or exact unit round-trip equivalence
              is promised.
            </p>
            <ul>
              {shown.data.profile.gaps.map((gap: string) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </details>
          <p className="co2-flow-digests">
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
              Export original CO2 airflow review JSON
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => void download("bundle")}
            >
              Export original CO2 airflow activity bundle
            </button>
            <button
              disabled={busy || disabled || !shown.data.can_import}
              onClick={() => void adopt()}
            >
              Import reviewed CO2 airflow definition
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => {
                if (mounted.current && shown.key === live.current)
                  saveBlob(
                    shown.blob,
                    shown.data.definition_id +
                      ".co2-flow-preview-response.json",
                  );
              }}
            >
              Download original CO2 airflow preview response
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => {
                epoch.current++;
                setReview(null);
              }}
            >
              Dismiss CO2 airflow review
            </button>
          </div>
          <p className="help-text">
            Import adds only the reviewed reusable definition. Add and wire an
            instance separately. Server-produced digests bind the reviewed
            source; they are not manufacturer authentication, native
            JCI/G36/Title 24 acceptance or physical ventilation proof.
          </p>
        </section>
      )}
    </section>
  );
}
