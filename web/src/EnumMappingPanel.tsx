import { useEffect, useRef, useState } from "react";
import { api, download } from "./api";

type State = { id: string; code: string; label: string; unknown: boolean };
type Domain = {
  namespace: string;
  id: string;
  datatype: string;
  number: string;
  complete: boolean;
  notes: string;
  states: State[];
};
type Row = { source: string; target: string };
type Draft = {
  source: Domain;
  target: Domain;
  rows: Row[];
  lossy: boolean;
  rationale: string;
  coverage: boolean;
  probes: string;
};
const domain = (side: string): Domain => ({
  namespace: "operator/" + side,
  id: side + "-domain",
  datatype: "declared-integer",
  number: "",
  complete: true,
  notes: "",
  states: [{ id: "state-1", code: "", label: "", unknown: true }],
});
const blank = (): Draft => ({
  source: domain("source"),
  target: domain("target"),
  rows: [],
  lossy: false,
  rationale: "",
  coverage: false,
  probes: "",
});
function integer(text: string, name: string) {
  if (!/^-?\d+$/.test(text.trim()))
    throw new Error(
      `${name} requires an integer code; no Boolean, decimal or label coercion.`,
    );
  const code = Number(text.trim());
  if (!Number.isSafeInteger(code) || code < -2147483648 || code > 4294967295)
    throw new Error(`${name} is outside the integer code profile.`);
  return code;
}
function document(draft: Draft) {
  const encode = (value: Domain, name: string) => ({
    namespace: value.namespace,
    id: value.id,
    datatype: value.datatype,
    number_of_states:
      value.datatype === "bacnet-multistate"
        ? integer(value.number, name + " state count")
        : null,
    declared_complete: value.complete,
    origin: "operator-declared",
    reference_notes: value.notes,
    states: value.states.map((row, i) => ({
      id: row.id,
      code: integer(row.code, `${name} state ${i + 1}`),
      label: row.unknown ? null : row.label,
    })),
  });
  return {
    schema_version: 1,
    source: encode(draft.source, "Source"),
    target: encode(draft.target, "Target"),
    mappings: draft.rows.map((row, i) => ({
      source_code: integer(row.source, `Mapping ${i + 1} source`),
      target_code: row.target.trim()
        ? integer(row.target, `Mapping ${i + 1} target`)
        : null,
    })),
    policy: {
      allow_many_to_one: draft.lossy,
      loss_rationale: draft.rationale,
      require_target_coverage: draft.coverage,
    },
    probes: draft.probes.trim()
      ? draft.probes
          .split(",")
          .map((value) =>
            value.trim() === "?" ? null : integer(value, "Probe"),
          )
      : [],
  };
}
function fromPlan(plan: any): Draft {
  const decode = (value: any): Domain => ({
    namespace: value.namespace,
    id: value.id,
    datatype: value.datatype,
    number:
      value.number_of_states == null ? "" : String(value.number_of_states),
    complete: value.declared_complete,
    notes: value.reference_notes,
    states: value.states.map((row: any) => ({
      id: row.id,
      code: String(row.code),
      label: row.label ?? "",
      unknown: row.label == null,
    })),
  });
  return {
    source: decode(plan.source),
    target: decode(plan.target),
    rows: plan.mappings.map((row: any) => ({
      source: String(row.source_code),
      target: row.target_code == null ? "" : String(row.target_code),
    })),
    lossy: plan.policy.allow_many_to_one,
    rationale: plan.policy.loss_rationale,
    coverage: plan.policy.require_target_coverage,
    probes: plan.probes
      .map((v: number | null) => (v == null ? "?" : String(v)))
      .join(", "),
  };
}
export function EnumMappingPanel() {
  const [draft, setDraft] = useState<Draft>(blank),
    [review, setReview] = useState<any>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [imported, setImported] = useState("");
  const alive = useRef(true),
    epoch = useRef(0),
    draftKey = JSON.stringify(draft),
    now = useRef(draftKey);
  now.current = draftKey;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    setReview(null);
    setError("");
  }, [draftKey]);
  const current = (ticket: number, key: string) =>
    alive.current && epoch.current === ticket && now.current === key;
  function change(update: Partial<Draft>) {
    epoch.current++;
    setDraft((old) => ({ ...old, ...update }));
    setReview(null);
    setImported("");
  }
  async function run() {
    const ticket = ++epoch.current,
      key = now.current;
    setBusy(true);
    setError("");
    setReview(null);
    try {
      const result = await api("/enum-mapping/review", document(draft));
      if (current(ticket, key)) setReview(result);
    } catch (failure) {
      if (current(ticket, key)) setError(String(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function exportFile(planOnly: boolean) {
    if (!review) return;
    const ticket = epoch.current,
      key = now.current;
    try {
      await download(
        planOnly ? "/enum-mapping/plan-export" : "/enum-mapping/export",
        { plan: document(draft), expected_review_sha256: review.review_sha256 },
        planOnly ? "enum-mapping-plan.json" : "enum-mapping-review.json",
        () => current(ticket, key),
      );
    } catch (failure) {
      if (current(ticket, key)) setError(String(failure));
    }
  }
  async function load(file: File | undefined) {
    if (!file) return;
    const ticket = ++epoch.current,
      key = now.current;
    setBusy(true);
    setError("");
    setReview(null);
    try {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Enum mapping plan exceeds 2 MiB.");
      const data = new FormData();
      data.append("file", file);
      const result = await api("/enum-mapping/import", data);
      if (current(ticket, key)) {
        epoch.current++;
        setDraft(fromPlan(result.source_plan));
        setImported(
          `Imported operator plan ${result.source_plan_sha256}. Review required; no native binding.`,
        );
      }
    } catch (failure) {
      if (current(ticket, key)) setError(String(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  function editDomain(side: "source" | "target", update: Partial<Domain>) {
    change({ [side]: { ...draft[side], ...update } });
  }
  function editState(
    side: "source" | "target",
    index: number,
    update: Partial<State>,
  ) {
    editDomain(side, {
      states: draft[side].states.map((row, i) =>
        i === index ? { ...row, ...update } : row,
      ),
    });
  }
  function example() {
    const source = domain("example-source"),
      target = domain("example-target");
    source.datatype = "bacnet-binarypv";
    source.states = [
      { id: "off", code: "0", label: "Off", unknown: false },
      { id: "on", code: "1", label: "On", unknown: false },
    ];
    target.datatype = "bacnet-multistate";
    target.number = "3";
    target.states = [
      { id: "stop", code: "1", label: "Stop", unknown: false },
      { id: "run", code: "2", label: "Run", unknown: false },
      { id: "hold", code: "3", label: "Hold", unknown: false },
    ];
    change({
      source,
      target,
      rows: [
        { source: "0", target: "1" },
        { source: "1", target: "2" },
      ],
      lossy: false,
      rationale: "",
      coverage: false,
      probes: "0, 1, 99, ?",
    });
  }
  return (
    <section className="card" aria-label="Operator enum mapping review">
      <h2>Enum mapping review</h2>
      <p>
        Declare two finite integer domains and each source-to-target code
        mapping. Review missing states, ambiguous rows, unreachable targets and
        information loss before using a mapping. This offline declaration does
        not bind a native point, JCI Enum Set or portable program, and does not
        convert or deploy a controller program.
      </p>
      <p>
        Native state labels above remain separate evidence. Matching labels do
        not establish equivalent meanings. The example is an operator
        declaration; its codes do not come from a CCT mapping table.
      </p>
      <div className="toolbar">
        <button disabled={busy} onClick={example}>
          Load operator mapping example
        </button>
        <button disabled={busy} onClick={() => change(blank())}>
          Clear enum declaration
        </button>
        <label>
          Import enum plan
          <input
            aria-label="Import enum plan"
            type="file"
            accept=".json,application/json"
            disabled={busy}
            onChange={(e) => {
              void load(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
      </div>
      {(["source", "target"] as const).map((side) => {
        const value = draft[side],
          title = side === "source" ? "Source" : "Target";
        return (
          <fieldset key={side} disabled={busy}>
            <legend>{title} operator domain</legend>
            <div className="form-grid">
              <label>
                {title} namespace
                <input
                  aria-label={`${title} enum namespace`}
                  value={value.namespace}
                  maxLength={100}
                  onChange={(e) =>
                    editDomain(side, { namespace: e.target.value })
                  }
                />
              </label>
              <label>
                {title} domain ID
                <input
                  aria-label={`${title} enum domain ID`}
                  value={value.id}
                  maxLength={100}
                  onChange={(e) => editDomain(side, { id: e.target.value })}
                />
              </label>
              <label>
                {title} datatype rule
                <select
                  aria-label={`${title} enum datatype`}
                  value={value.datatype}
                  onChange={(e) =>
                    editDomain(side, { datatype: e.target.value })
                  }
                >
                  <option value="declared-integer">
                    Declared integer codes
                  </option>
                  <option value="bacnet-binarypv">
                    BACnet BinaryPV numeric rule 0/1
                  </option>
                  <option value="bacnet-multistate">
                    BACnet multistate numeric rule 1..N
                  </option>
                </select>
              </label>
              {value.datatype === "bacnet-multistate" && (
                <label>
                  {title} declared number of states
                  <input
                    aria-label={`${title} enum number of states`}
                    inputMode="numeric"
                    value={value.number}
                    onChange={(e) =>
                      editDomain(side, { number: e.target.value })
                    }
                  />
                </label>
              )}
              <label>
                <input
                  type="checkbox"
                  checked={value.complete}
                  onChange={(e) =>
                    editDomain(side, { complete: e.target.checked })
                  }
                />
                {title} domain declared complete
              </label>
              <label>
                {title} reference notes
                <textarea
                  aria-label={`${title} enum reference notes`}
                  value={value.notes}
                  maxLength={1000}
                  onChange={(e) => editDomain(side, { notes: e.target.value })}
                />
              </label>
            </div>
            <table>
              <thead>
                <tr>
                  <th>State ID</th>
                  <th>Integer code</th>
                  <th>Label</th>
                  <th>Unknown label</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {value.states.map((row, i) => (
                  <tr key={i}>
                    <td>
                      <input
                        aria-label={`${title} state ${i + 1} ID`}
                        value={row.id}
                        maxLength={100}
                        onChange={(e) =>
                          editState(side, i, { id: e.target.value })
                        }
                      />
                    </td>
                    <td>
                      <input
                        aria-label={`${title} state ${i + 1} code`}
                        inputMode="numeric"
                        value={row.code}
                        onChange={(e) =>
                          editState(side, i, { code: e.target.value })
                        }
                      />
                    </td>
                    <td>
                      <input
                        aria-label={`${title} state ${i + 1} label`}
                        value={row.label}
                        maxLength={256}
                        disabled={busy || row.unknown}
                        onChange={(e) =>
                          editState(side, i, { label: e.target.value })
                        }
                      />
                    </td>
                    <td>
                      <input
                        aria-label={`${title} state ${i + 1} label unknown`}
                        type="checkbox"
                        checked={row.unknown}
                        onChange={(e) =>
                          editState(side, i, { unknown: e.target.checked })
                        }
                      />
                    </td>
                    <td>
                      <button
                        disabled={value.states.length <= 1}
                        onClick={() =>
                          editDomain(side, {
                            states: value.states.filter(
                              (_, index) => index !== i,
                            ),
                          })
                        }
                      >
                        Remove {title.toLowerCase()} state {i + 1}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              disabled={value.states.length >= 256}
              onClick={() =>
                editDomain(side, {
                  states: [
                    ...value.states,
                    {
                      id: `state-${value.states.length + 1}`,
                      code: "",
                      label: "",
                      unknown: true,
                    },
                  ],
                })
              }
            >
              Add {side} state
            </button>
          </fieldset>
        );
      })}
      <fieldset disabled={busy}>
        <legend>Explicit mapping rows</legend>
        <p>
          One row per source code. A blank target remains unmapped; labels never
          fill rows automatically.
        </p>
        <table>
          <thead>
            <tr>
              <th>Source integer code</th>
              <th>Target integer code (blank = unmapped)</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {draft.rows.map((row, i) => (
              <tr key={i}>
                <td>
                  <input
                    aria-label={`Mapping ${i + 1} source code`}
                    inputMode="numeric"
                    value={row.source}
                    onChange={(e) =>
                      change({
                        rows: draft.rows.map((r, index) =>
                          index === i ? { ...r, source: e.target.value } : r,
                        ),
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`Mapping ${i + 1} target code`}
                    inputMode="numeric"
                    value={row.target}
                    onChange={(e) =>
                      change({
                        rows: draft.rows.map((r, index) =>
                          index === i ? { ...r, target: e.target.value } : r,
                        ),
                      })
                    }
                  />
                </td>
                <td>
                  <button
                    onClick={() =>
                      change({
                        rows: draft.rows.filter((_, index) => index !== i),
                      })
                    }
                  >
                    Remove mapping {i + 1}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          disabled={draft.rows.length >= 256}
          onClick={() =>
            change({ rows: [...draft.rows, { source: "", target: "" }] })
          }
        >
          Add explicit mapping row
        </button>
        <div className="form-grid">
          <label>
            <input
              type="checkbox"
              checked={draft.lossy}
              onChange={(e) => change({ lossy: e.target.checked })}
            />
            Allow declared many-to-one information loss
          </label>
          <label>
            Loss rationale
            <textarea
              aria-label="Enum loss rationale"
              value={draft.rationale}
              maxLength={1000}
              onChange={(e) => change({ rationale: e.target.value })}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.coverage}
              onChange={(e) => change({ coverage: e.target.checked })}
            />
            Require every target state to be reachable
          </label>
          <label>
            Probe source codes (comma separated; ? = unknown)
            <input
              aria-label="Enum probe source codes"
              value={draft.probes}
              onChange={(e) => change({ probes: e.target.value })}
            />
          </label>
        </div>
      </fieldset>
      <div className="toolbar">
        <button disabled={busy} onClick={() => void run()}>
          Review enum mapping
        </button>
        <button
          disabled={busy || !review}
          onClick={() => void exportFile(false)}
        >
          Export exact enum review
        </button>
        <button
          disabled={busy || !review}
          onClick={() => void exportFile(true)}
        >
          Export reviewed enum plan
        </button>
      </div>
      {busy && <p role="status">Reviewing operator declarations…</p>}
      {error && <p role="alert">{error}</p>}
      {imported && <p>{imported}</p>}
      {review && (
        <div aria-label="Enum mapping review result">
          <p>
            <strong>{review.status}</strong> · Source total:{" "}
            {String(review.properties.source_function_complete)} · Lossless:{" "}
            {String(review.properties.lossless)} · Target coverage:{" "}
            {String(review.properties.target_coverage)}
          </p>
          <p>
            Semantic equivalence and native/portable binding: not established.
            Review SHA-256: {review.review_sha256}
          </p>
          <p>
            {review.finding_counts.error || 0} errors;{" "}
            {review.finding_counts.warning || 0} warnings;{" "}
            {review.omitted_findings} additional findings omitted from bounded
            detail.
          </p>
          <ul>
            {review.findings.map((finding: any, i: number) => (
              <li key={i}>
                {finding.severity} · {finding.code} · {JSON.stringify(finding)}
              </li>
            ))}
          </ul>
          <table>
            <thead>
              <tr>
                <th>Declared source ID / code / label</th>
                <th>Declared target ID / code / label</th>
              </tr>
            </thead>
            <tbody>
              {review.mapping_evidence.map((row: any) => (
                <tr key={row.source_code}>
                  <td>
                    {row.source_state_id} / {row.source_code} /{" "}
                    {row.source_label ?? "unknown"}
                  </td>
                  <td>
                    {row.target_state_id} / {row.target_code} /{" "}
                    {row.target_label ?? "unknown"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <details>
            <summary>Probe outcomes and complete review evidence</summary>
            <pre>{JSON.stringify(review, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}
