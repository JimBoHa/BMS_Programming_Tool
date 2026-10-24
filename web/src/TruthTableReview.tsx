import { useEffect, useRef, useState } from "react";
import {
  Download,
  Plus,
  RefreshCw,
  TableProperties,
  Upload,
} from "lucide-react";
import { api, download } from "./api";
import "./truth-tables.css";

type State = {
  id: string;
  label: string;
  value: boolean | number | string | null;
};
type Domain = {
  id: string;
  label: string;
  kind: "boolean" | "enum";
  states: State[];
};
type Condition = { kind: "any" } | { kind: "state"; state_id: string };
type Row = {
  id: string;
  label: string;
  conditions: Record<string, Condition>;
  output_state_id: string;
};
type TableSource = {
  format: "bms.truth-table";
  version: 1;
  id: string;
  label: string;
  inputs: Domain[];
  output: Domain;
  rows: Row[];
  overlap_policy: "reject" | "first-match";
  fallback: { output_state_id: string; rationale: string } | null;
};
type Case = {
  index: number;
  inputs: Record<string, State>;
  matched_row_ids: string[];
  chosen_row_id: string | null;
  shadowed_row_ids: string[];
  output: State | null;
  disposition: string;
  fallback_rationale: string | null;
};
type Page = {
  cases: Case[];
  filter: string;
  offset: number;
  total: number;
  next_offset: number | null;
};
type Review = {
  id: string;
  table_sha256: string;
  content_sha256: string;
  source_profile: any;
  status: string;
  counts: Record<string, number>;
  warnings: string[];
  row_usage: {
    row_id: string;
    matches: number;
    chosen: number;
    shadowed: number;
  }[];
  row_diagnostics: { row_id: string; code: string }[];
  page: Page;
};
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const newId = (prefix: string) =>
  prefix + "-" + crypto.randomUUID().slice(0, 8);
const showValue = (value: State["value"]) =>
  typeof value === "boolean"
    ? value
      ? "True"
      : "False"
    : String(value ?? "not set");
function booleanDomain(id: string, label: string): Domain {
  return {
    id,
    label,
    kind: "boolean",
    states: [
      { id: "false", label: "False", value: false },
      { id: "true", label: "True", value: true },
    ],
  };
}
function identity(review: Review) {
  return {
    review_id: review.id,
    table_sha256: review.table_sha256,
    profile_sha256: review.source_profile.sha256,
  };
}
function StateChoice({
  domain,
  value,
  label,
  onChange,
}: {
  domain: Domain;
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {!domain.states.some((state) => state.id === value) && (
        <option value={value}>
          Missing state: {value || "choose a state"}
        </option>
      )}
      {domain.states.map((state) => (
        <option key={state.id} value={state.id}>
          {state.label} ({showValue(state.value)})
        </option>
      ))}
    </select>
  );
}
function DomainEditor({
  domain,
  output = false,
  onChange,
  onRemove,
}: {
  domain: Domain;
  output?: boolean;
  onChange: (domain: Domain) => void;
  onRemove?: () => void;
}) {
  const edit = (index: number, patch: Partial<State>) =>
    onChange({
      ...domain,
      states: domain.states.map((state, position) =>
        position === index ? { ...state, ...patch } : state,
      ),
    });
  return (
    <fieldset className="truth-domain" aria-label={`Domain ${domain.id}`}>
      <legend>
        {output ? "Output" : "Input"}: {domain.label}
      </legend>
      <label>
        {output ? "Output name" : "Input name"}
        <input
          aria-label={`Name ${domain.id}`}
          value={domain.label}
          maxLength={160}
          onChange={(event) =>
            onChange({ ...domain, label: event.target.value })
          }
        />
      </label>
      <label>
        Domain type
        <select
          aria-label={`Type ${domain.id}`}
          value={domain.kind}
          onChange={(event) =>
            onChange(
              event.target.value === "boolean"
                ? booleanDomain(domain.id, domain.label)
                : {
                    ...domain,
                    kind: "enum",
                    states: [
                      { id: "state0", label: "State 0", value: 0 },
                      { id: "state1", label: "State 1", value: 1 },
                    ],
                  },
            )
          }
        >
          <option value="boolean">Boolean: false and true</option>
          <option value="enum">Enum: explicit integer states</option>
        </select>
      </label>
      <p className="truth-small">
        Stable identifier: <code>{domain.id}</code>
      </p>
      {domain.states.map((state, index) => (
        <div className="truth-state" key={state.id}>
          <label>
            State label
            <input
              aria-label={`State label ${domain.id} ${state.id}`}
              value={state.label}
              maxLength={160}
              onChange={(event) => edit(index, { label: event.target.value })}
            />
          </label>
          {domain.kind === "enum" ? (
            <label>
              Integer value
              <input
                aria-label={`State value ${domain.id} ${state.id}`}
                inputMode="numeric"
                value={showValue(state.value)}
                onChange={(event) => {
                  const raw = event.target.value,
                    number = Number(raw);
                  edit(index, {
                    value:
                      raw.trim() !== "" && Number.isSafeInteger(number)
                        ? number
                        : raw,
                  });
                }}
              />
            </label>
          ) : (
            <span>{showValue(state.value)}</span>
          )}
          <code>{state.id}</code>
          {domain.kind === "enum" && (
            <button
              aria-label={`Remove state ${domain.id} ${state.id}`}
              onClick={() =>
                onChange({
                  ...domain,
                  states: domain.states.filter(
                    (_, position) => position !== index,
                  ),
                })
              }
            >
              Remove state
            </button>
          )}
        </div>
      ))}
      {domain.kind === "enum" && (
        <button
          disabled={domain.states.length >= 32}
          onClick={() => {
            const values = domain.states
              .filter((state) => typeof state.value === "number")
              .map((state) => state.value as number);
            const next = Math.max(-1, ...values) + 1;
            onChange({
              ...domain,
              states: [
                ...domain.states,
                {
                  id: newId("state"),
                  label: "New state",
                  value: next <= 2147483647 ? next : null,
                },
              ],
            });
          }}
        >
          Add Enum state
        </button>
      )}
      {onRemove && (
        <button aria-label={`Remove input ${domain.id}`} onClick={onRemove}>
          Remove input
        </button>
      )}
    </fieldset>
  );
}

export function TruthTableReview() {
  const [catalog, setCatalog] = useState<any>(null),
    [draft, setDraft] = useState<TableSource | null>(null);
  const [review, setReview] = useState<Review | null>(null),
    [page, setPage] = useState<Page | null>(null);
  const [selection, setSelection] = useState<Record<string, string>>({}),
    [evaluation, setEvaluation] = useState<any>(null);
  const [importedFile, setImportedFile] = useState<{
    name: string;
    sha256: string;
  } | null>(null);
  const [filter, setFilter] = useState("all"),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false),
    [pageBusy, setPageBusy] = useState(false),
    [evalBusy, setEvalBusy] = useState(false),
    [exportBusy, setExportBusy] = useState(false);
  const mounted = useRef(false),
    epoch = useRef(0),
    reviewRequest = useRef(0),
    pageRequest = useRef(0),
    evalRequest = useRef(0),
    exportRequest = useRef(0);
  const source = useRef<TableSource | null>(null),
    currentReview = useRef<Review | null>(null);
  function invalidate() {
    epoch.current++;
    reviewRequest.current++;
    pageRequest.current++;
    evalRequest.current++;
    exportRequest.current++;
    currentReview.current = null;
    setReview(null);
    setPage(null);
    setEvaluation(null);
    setFilter("all");
    setReviewBusy(false);
    setPageBusy(false);
    setEvalBusy(false);
    setExportBusy(false);
    setError("");
    setMessage("");
  }
  function change(next: TableSource) {
    invalidate();
    source.current = next;
    setDraft(next);
    setImportedFile(null);
    setSelection(
      Object.fromEntries(
        next.inputs.map((input) => [input.id, input.states[0]?.id ?? ""]),
      ),
    );
  }
  useEffect(() => {
    mounted.current = true;
    const generation = epoch.current;
    api("/truth-tables/profile")
      .then((value) => {
        if (!mounted.current) return;
        setCatalog(value);
        if (generation === epoch.current && source.current === null)
          change(clone(value.template));
      })
      .catch((error) => {
        if (mounted.current) setError(String(error));
      });
    return () => {
      mounted.current = false;
      epoch.current++;
      reviewRequest.current++;
      pageRequest.current++;
      evalRequest.current++;
      exportRequest.current++;
      currentReview.current = null;
    };
  }, []);
  function owns(generation: number, id: string) {
    return (
      mounted.current &&
      epoch.current === generation &&
      currentReview.current?.id === id
    );
  }
  async function calculate() {
    if (!source.current || reviewBusy || !catalog) return;
    const snapshot = clone(source.current);
    invalidate();
    const generation = epoch.current,
      request = ++reviewRequest.current;
    setReviewBusy(true);
    try {
      const value = await api("/truth-tables/review", {
        table: snapshot,
        profile_sha256: catalog.profile.sha256,
      });
      if (
        mounted.current &&
        generation === epoch.current &&
        request === reviewRequest.current
      ) {
        currentReview.current = value;
        setReview(value);
        setPage(value.page);
      }
    } catch (error) {
      if (
        mounted.current &&
        generation === epoch.current &&
        request === reviewRequest.current
      )
        setError(String(error));
    } finally {
      if (
        mounted.current &&
        generation === epoch.current &&
        request === reviewRequest.current
      )
        setReviewBusy(false);
    }
  }
  async function loadPage(nextFilter: string, offset: number) {
    const active = currentReview.current;
    if (!active) return;
    const generation = epoch.current,
      request = ++pageRequest.current;
    setFilter(nextFilter);
    setPage(null);
    setPageBusy(true);
    setError("");
    try {
      const value = await api("/truth-tables/cases", {
        ...identity(active),
        filter: nextFilter,
        offset,
        limit: 64,
      });
      if (owns(generation, active.id) && request === pageRequest.current)
        setPage(value);
    } catch (error) {
      if (owns(generation, active.id) && request === pageRequest.current)
        setError(String(error));
    } finally {
      if (owns(generation, active.id) && request === pageRequest.current)
        setPageBusy(false);
    }
  }
  async function evaluate() {
    const active = currentReview.current,
      table = source.current;
    if (!active || !table || evalBusy) return;
    const generation = epoch.current,
      request = ++evalRequest.current;
    const values = Object.fromEntries(
      table.inputs.map((input) => [
        input.id,
        input.states.find((state) => state.id === selection[input.id])?.value,
      ]),
    );
    setEvalBusy(true);
    setEvaluation(null);
    setError("");
    try {
      const value = await api("/truth-tables/evaluate", {
        ...identity(active),
        values,
      });
      if (owns(generation, active.id) && request === evalRequest.current)
        setEvaluation(value);
    } catch (error) {
      if (owns(generation, active.id) && request === evalRequest.current)
        setError(String(error));
    } finally {
      if (owns(generation, active.id) && request === evalRequest.current)
        setEvalBusy(false);
    }
  }
  async function exportFile(kind: "table" | "review") {
    const active = currentReview.current;
    if (!active || exportBusy || !source.current) return;
    const generation = epoch.current,
      request = ++exportRequest.current;
    setExportBusy(true);
    setError("");
    try {
      await download(
        `/truth-tables/export/${kind}`,
        identity(active),
        source.current.id +
          (kind === "table" ? ".bms-truth-table.json" : "-review.json"),
        () => owns(generation, active.id) && request === exportRequest.current,
      );
    } catch (error) {
      if (owns(generation, active.id) && request === exportRequest.current)
        setError(String(error));
    } finally {
      if (owns(generation, active.id) && request === exportRequest.current)
        setExportBusy(false);
    }
  }
  async function importFile(file: File) {
    invalidate();
    const generation = epoch.current;
    if (file.size > 1024 * 1024) {
      setError("Portable truth-table files are limited to 1 MiB.");
      return;
    }
    try {
      const body = new FormData();
      body.append("file", file);
      const value = await api("/truth-tables/import", body);
      if (mounted.current && generation === epoch.current) {
        change(value.table);
        setImportedFile({ name: file.name, sha256: value.source_file_sha256 });
        setMessage(
          "Imported verified source. Review coverage before evaluating or exporting.",
        );
      }
    } catch (error) {
      if (mounted.current && generation === epoch.current)
        setError(String(error));
    }
  }
  function patchRow(index: number, patch: Partial<Row>) {
    if (draft)
      change({
        ...draft,
        rows: draft.rows.map((row, position) =>
          index === position ? { ...row, ...patch } : row,
        ),
      });
  }
  const rowName = (id: string) =>
    draft?.rows.find((row) => row.id === id)?.label + " [" + id + "]";
  const caseResult = (item: Case) =>
    item.output
      ? `${item.output.label} (${showValue(item.output.value)})`
      : "Output cannot be determined";
  return (
    <div className="truth-page">
      <header className="truth-heading">
        <div>
          <h1>Truth tables</h1>
          <p>
            Review every declared input combination, reveal missing cases and
            make row priority explicit.
          </p>
        </div>
        <TableProperties size={30} />
      </header>
      <p>
        Offline Boolean and integer Enum review. Results do not execute JCI
        logic, retain a prior output, encode a CAF or deploy a controller
        program.
      </p>
      <div className="truth-actions">
        <button
          onClick={() =>
            change({
              format: "bms.truth-table",
              version: 1,
              id: newId("table"),
              label: "Untitled truth table",
              inputs: [booleanDomain(newId("input"), "Input 1")],
              output: booleanDomain("result", "Result"),
              rows: [],
              overlap_policy: "reject",
              fallback: null,
            })
          }
        >
          <Plus size={15} />
          New table
        </button>
        <button
          disabled={!catalog}
          onClick={() => change(clone(catalog.template))}
        >
          <RefreshCw size={15} />
          Reset example
        </button>
        <label className="truth-upload">
          <Upload size={15} />
          Import table
          <input
            aria-label="Import truth table"
            type="file"
            accept=".json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void importFile(file);
            }}
          />
        </label>
      </div>
      {importedFile && (
        <p
          className="truth-small"
          aria-label="Imported truth-table file identity"
        >
          Imported {importedFile.name} · exact file SHA-256{" "}
          <code>{importedFile.sha256}</code>
        </p>
      )}
      {draft && (
        <>
          <section className="truth-card" aria-label="Truth-table source">
            <h2>Table source</h2>
            <label>
              Table name
              <input
                aria-label="Truth-table name"
                value={draft.label}
                maxLength={160}
                onChange={(event) =>
                  change({ ...draft, label: event.target.value })
                }
              />
            </label>
            <p className="truth-small">
              Stable table identifier: <code>{draft.id}</code>. Identifiers stay
              with copied/imported sources; labels can change.
            </p>
            <div className="truth-domains">
              {draft.inputs.map((input, index) => (
                <DomainEditor
                  key={input.id}
                  domain={input}
                  onChange={(domain) =>
                    change({
                      ...draft,
                      inputs: draft.inputs.map((current, position) =>
                        position === index ? domain : current,
                      ),
                    })
                  }
                  onRemove={() =>
                    change({
                      ...draft,
                      inputs: draft.inputs.filter(
                        (_, position) => position !== index,
                      ),
                      rows: draft.rows.map((row) => ({
                        ...row,
                        conditions: Object.fromEntries(
                          Object.entries(row.conditions).filter(
                            ([key]) => key !== input.id,
                          ),
                        ),
                      })),
                    })
                  }
                />
              ))}
            </div>
            <button
              disabled={draft.inputs.length >= 12}
              onClick={() => {
                const input = booleanDomain(
                  newId("input"),
                  `Input ${draft.inputs.length + 1}`,
                );
                change({
                  ...draft,
                  inputs: [...draft.inputs, input],
                  rows: draft.rows.map((row) => ({
                    ...row,
                    conditions: {
                      ...row.conditions,
                      [input.id]: { kind: "any" },
                    },
                  })),
                });
              }}
            >
              Add input
            </button>
            <DomainEditor
              domain={draft.output}
              output
              onChange={(output) => change({ ...draft, output })}
            />
          </section>
          <section className="truth-card" aria-label="Truth-table rules">
            <h2>Rules and explicit policy</h2>
            <label>
              Overlapping rows
              <select
                aria-label="Overlap policy"
                value={draft.overlap_policy}
                onChange={(event) =>
                  change({
                    ...draft,
                    overlap_policy: event.target
                      .value as TableSource["overlap_policy"],
                  })
                }
              >
                <option value="reject">Reject every overlap (default)</option>
                <option value="first-match">
                  Use first matching row (explicit priority)
                </option>
              </select>
            </label>
            <p>
              Any declared state is a wildcard within this finite domain. Every
              overlap remains visible, including rows with the same result.
            </p>
            <div className="truth-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Row name</th>
                    {draft.inputs.map((input) => (
                      <th key={input.id}>{input.label}</th>
                    ))}
                    <th>{draft.output.label}</th>
                    <th>Order and actions</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.rows.map((row, index) => (
                    <tr key={row.id}>
                      <td>
                        <input
                          aria-label={`Row name ${row.id}`}
                          value={row.label}
                          maxLength={160}
                          onChange={(event) =>
                            patchRow(index, { label: event.target.value })
                          }
                        />
                        <code>{row.id}</code>
                      </td>
                      {draft.inputs.map((input) => {
                        const condition = row.conditions[input.id];
                        return (
                          <td key={input.id}>
                            <select
                              aria-label={`Condition ${row.id} ${input.id}`}
                              value={
                                condition?.kind === "any"
                                  ? "@any"
                                  : (condition?.state_id ?? "")
                              }
                              onChange={(event) =>
                                patchRow(index, {
                                  conditions: {
                                    ...row.conditions,
                                    [input.id]:
                                      event.target.value === "@any"
                                        ? { kind: "any" }
                                        : {
                                            kind: "state",
                                            state_id: event.target.value,
                                          },
                                  },
                                })
                              }
                            >
                              <option value="@any">Any declared state *</option>
                              {condition?.kind === "state" &&
                                !input.states.some(
                                  (state) => state.id === condition.state_id,
                                ) && (
                                  <option value={condition.state_id}>
                                    Missing state: {condition.state_id}
                                  </option>
                                )}
                              {input.states.map((state) => (
                                <option key={state.id} value={state.id}>
                                  {state.label} ({showValue(state.value)})
                                </option>
                              ))}
                            </select>
                          </td>
                        );
                      })}
                      <td>
                        <StateChoice
                          domain={draft.output}
                          value={row.output_state_id}
                          label={`Result ${row.id}`}
                          onChange={(output_state_id) =>
                            patchRow(index, { output_state_id })
                          }
                        />
                      </td>
                      <td>
                        <div className="truth-row-actions">
                          <span>Row {index + 1}</span>
                          <button
                            aria-label={`Move row ${row.id} up`}
                            disabled={index === 0}
                            onClick={() => {
                              const rows = [...draft.rows];
                              [rows[index - 1], rows[index]] = [
                                rows[index],
                                rows[index - 1],
                              ];
                              change({ ...draft, rows });
                            }}
                          >
                            Up
                          </button>
                          <button
                            aria-label={`Move row ${row.id} down`}
                            disabled={index + 1 === draft.rows.length}
                            onClick={() => {
                              const rows = [...draft.rows];
                              [rows[index + 1], rows[index]] = [
                                rows[index],
                                rows[index + 1],
                              ];
                              change({ ...draft, rows });
                            }}
                          >
                            Down
                          </button>
                          <button
                            aria-label={`Copy row ${row.id}`}
                            disabled={draft.rows.length >= 128}
                            onClick={() =>
                              change({
                                ...draft,
                                rows: [
                                  ...draft.rows,
                                  {
                                    ...clone(row),
                                    id: newId("row"),
                                    label: row.label + " copy",
                                  },
                                ],
                              })
                            }
                          >
                            Copy
                          </button>
                          <button
                            aria-label={`Delete row ${row.id}`}
                            onClick={() =>
                              change({
                                ...draft,
                                rows: draft.rows.filter(
                                  (_, position) => position !== index,
                                ),
                              })
                            }
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              disabled={draft.rows.length >= 128}
              onClick={() =>
                change({
                  ...draft,
                  rows: [
                    ...draft.rows,
                    {
                      id: newId("row"),
                      label: "New rule",
                      conditions: Object.fromEntries(
                        draft.inputs.map((input) => [
                          input.id,
                          { kind: "any" } as Condition,
                        ]),
                      ),
                      output_state_id: draft.output.states[0]?.id ?? "",
                    },
                  ],
                })
              }
            >
              Add rule
            </button>
            <label className="truth-check">
              <input
                aria-label="Enable constant fallback"
                type="checkbox"
                checked={draft.fallback !== null}
                onChange={(event) =>
                  change({
                    ...draft,
                    fallback: event.target.checked
                      ? {
                          output_state_id: draft.output.states[0]?.id ?? "",
                          rationale: "",
                        }
                      : null,
                  })
                }
              />
              Use a declared constant fallback for unlisted combinations
            </label>
            {draft.fallback && (
              <div className="truth-fallback">
                <StateChoice
                  domain={draft.output}
                  value={draft.fallback.output_state_id}
                  label="Fallback output state"
                  onChange={(output_state_id) =>
                    change({
                      ...draft,
                      fallback: { ...draft.fallback!, output_state_id },
                    })
                  }
                />
                <label>
                  Fallback rationale
                  <input
                    aria-label="Fallback rationale"
                    value={draft.fallback.rationale}
                    maxLength={512}
                    onChange={(event) =>
                      change({
                        ...draft,
                        fallback: {
                          ...draft.fallback!,
                          rationale: event.target.value,
                        },
                      })
                    }
                  />
                </label>
              </div>
            )}
            <p>
              Up to 12 inputs, 32 states per domain, 128 rows and 4,096
              combinations. A fallback resolves unlisted cases only.
            </p>
            <button
              className="primary"
              disabled={reviewBusy || !catalog}
              onClick={() => void calculate()}
            >
              Review all combinations
            </button>
          </section>
          {review && (
            <section className="truth-card" aria-label="Truth-table review">
              <h2>Coverage: {review.status}</h2>
              <p>
                {review.counts.cases} combinations · {review.counts.uncovered}{" "}
                unresolved holes · {review.counts.overlapping_cases} overlapping
                cases · {review.counts.fallback} fallback cases
              </p>
              <p>
                {review.counts.unlisted_cases} combinations have no matching
                source row. Priority and fallback never hide that evidence.
              </p>
              {review.warnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
              <div className="truth-actions">
                <button
                  disabled={exportBusy}
                  onClick={() => void exportFile("table")}
                >
                  <Download size={15} />
                  Export table
                </button>
                <button
                  disabled={exportBusy}
                  onClick={() => void exportFile("review")}
                >
                  <Download size={15} />
                  Export full review
                </button>
              </div>
              <p className="truth-small">
                Canonical table SHA-256 <code>{review.table_sha256}</code>
                <br />
                Review SHA-256 <code>{review.content_sha256}</code>
                <br />
                Profile SHA-256 <code>{review.source_profile.sha256}</code>
              </p>
              <label>
                Coverage filter
                <select
                  aria-label="Coverage filter"
                  value={filter}
                  onChange={(event) => void loadPage(event.target.value, 0)}
                >
                  <option value="all">All combinations</option>
                  <option value="uncovered">Unresolved holes</option>
                  <option value="unlisted">All unlisted combinations</option>
                  <option value="overlap">All overlaps</option>
                  <option value="fallback">Fallback cases</option>
                  <option value="resolved">Resolved outputs</option>
                </select>
              </label>
              {page && (
                <>
                  <p>
                    {page.total ? page.offset + 1 : 0}–
                    {page.offset + page.cases.length} of {page.total} filtered
                    combinations
                  </p>
                  <div className="truth-scroll">
                    <table aria-label="Coverage combinations">
                      <thead>
                        <tr>
                          <th>Case</th>
                          <th>Input states</th>
                          <th>Result</th>
                          <th>Matching rows and priority evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {page.cases.map((item) => (
                          <tr key={item.index}>
                            <td>{item.index + 1}</td>
                            <td>
                              {Object.entries(item.inputs).map(
                                ([id, state]) => (
                                  <div key={id}>
                                    {
                                      draft.inputs.find(
                                        (input) => input.id === id,
                                      )?.label
                                    }
                                    : {state.label} ({showValue(state.value)})
                                  </div>
                                ),
                              )}
                            </td>
                            <td>
                              {caseResult(item)}
                              <p>{item.disposition}</p>
                              {item.fallback_rationale && (
                                <p>{item.fallback_rationale}</p>
                              )}
                            </td>
                            <td>
                              {item.matched_row_ids.length ? (
                                <details>
                                  <summary>
                                    {item.matched_row_ids.length} matching
                                    row(s);{" "}
                                    {item.chosen_row_id
                                      ? `chosen ${rowName(item.chosen_row_id)}`
                                      : "no row selected"}
                                  </summary>
                                  <p>
                                    Matches:{" "}
                                    {item.matched_row_ids
                                      .map(rowName)
                                      .join(", ")}
                                  </p>
                                  <p>
                                    Shadowed:{" "}
                                    {item.shadowed_row_ids.length
                                      ? item.shadowed_row_ids
                                          .map(rowName)
                                          .join(", ")
                                      : "none"}
                                  </p>
                                </details>
                              ) : (
                                "No matching row"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="truth-actions">
                    <button
                      disabled={pageBusy || page.offset === 0}
                      onClick={() =>
                        void loadPage(filter, Math.max(0, page.offset - 64))
                      }
                    >
                      Previous cases
                    </button>
                    <button
                      disabled={pageBusy || page.next_offset === null}
                      onClick={() => void loadPage(filter, page.next_offset!)}
                    >
                      Next cases
                    </button>
                  </div>
                </>
              )}
              <details>
                <summary>Row usage and unreachable-row diagnostics</summary>
                <table aria-label="Truth-table row usage">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Matches</th>
                      <th>Chosen</th>
                      <th>Shadowed</th>
                      <th>Diagnostic</th>
                    </tr>
                  </thead>
                  <tbody>
                    {review.row_usage.map((row) => (
                      <tr key={row.row_id}>
                        <td>{rowName(row.row_id)}</td>
                        <td>{row.matches}</td>
                        <td>{row.chosen}</td>
                        <td>{row.shadowed}</td>
                        <td>
                          {review.row_diagnostics.find(
                            (item) => item.row_id === row.row_id,
                          )?.code ?? "chosen in at least one case"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </section>
          )}
          {review && (
            <section
              className="truth-card"
              aria-label="Selected truth-table combination"
            >
              <h2>Evaluate a selected combination</h2>
              <div className="truth-actions">
                {draft.inputs.map((input) => (
                  <label key={input.id}>
                    {input.label}
                    <StateChoice
                      domain={input}
                      value={selection[input.id] ?? ""}
                      label={`Selected ${input.id}`}
                      onChange={(value) => {
                        evalRequest.current++;
                        setEvalBusy(false);
                        setEvaluation(null);
                        setSelection({ ...selection, [input.id]: value });
                      }}
                    />
                  </label>
                ))}
                <button disabled={evalBusy} onClick={() => void evaluate()}>
                  Evaluate selected combination
                </button>
              </div>
              {evaluation && (
                <div role="status" aria-label="Selected combination result">
                  <strong>{caseResult(evaluation.case)}</strong>
                  <p>
                    {evaluation.case.disposition}; matched rows:{" "}
                    {evaluation.case.matched_row_ids.length
                      ? evaluation.case.matched_row_ids.map(rowName).join(", ")
                      : "none"}
                    .
                  </p>
                  {evaluation.case.shadowed_row_ids.length > 0 && (
                    <p>
                      Shadowed rows:{" "}
                      {evaluation.case.shadowed_row_ids.map(rowName).join(", ")}
                    </p>
                  )}
                  {evaluation.case.fallback_rationale && (
                    <p>{evaluation.case.fallback_rationale}</p>
                  )}
                  <p>
                    Selection SHA-256 <code>{evaluation.selection_sha256}</code>
                  </p>
                </div>
              )}
            </section>
          )}
        </>
      )}
      <p>
        Draft stays in this view. Export a reviewed table before leaving; import
        it to review again. No automatic save or field traffic.
      </p>
      {catalog && (
        <details className="truth-card">
          <summary>Reviewed source and portable policy</summary>
          <p>{catalog.scope}</p>
          <p>{catalog.profile.sources[0].documented_behavior}</p>
          <p>
            Portable default: reject overlaps. Explicit first-match uses source
            row order and retains every shadowed identity. Unlisted cases never
            imply a remembered output.
          </p>
          <a
            href={catalog.profile.sources[0].configuration_url}
            target="_blank"
            rel="noreferrer"
          >
            CCT18 reviewed manual
          </a>
          <p>
            PDF pages 167–168 and 1690–1691 · SHA-256{" "}
            <code>{catalog.profile.sources[0].sha256}</code>
          </p>
        </details>
      )}
      {(reviewBusy || pageBusy || evalBusy || exportBusy) && (
        <p role="status">Processing the explicit offline request…</p>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
