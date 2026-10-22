import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";
import "./network-number-plan.css";

type Assignment = {
  id: string;
  label: string;
  domain_key: string;
  physical_network_key: string | null;
  endpoint_key: string | null;
  port_key: string | null;
  network_number: number | null;
  medium: "unknown" | "bacnet-ip" | "mstp" | "other";
  role:
    | "network"
    | "router-port"
    | "engine-ip-port"
    | "engine-remote-field-integration"
    | "route-advertisement";
  policy: "generic" | "jci-r15-remote-field";
  assignment_state: "new" | "existing" | "unknown";
  notes: string;
};
type Plan = {
  format: "bms.bacnet-network-number-plan";
  version: 1;
  profile_sha256: string;
  name: string;
  declarations_complete: boolean;
  notes: string;
  assignments: Assignment[];
};
type Finding = {
  id: string;
  code: string;
  severity: string;
  message: string;
  assignment_ids: string[];
  domain_key?: string;
};
type Review = {
  status: string;
  plan_sha256: string;
  content_sha256: string;
  reviewed_at: string;
  scope: string;
  findings: Finding[];
  counts: { error: number; unknown: number; info: number };
};
type Catalog = {
  profile: { sha256: string; sources: Record<string, string>[] };
  template: Plan;
  scope: string;
};
const newRecord = (): Assignment => ({
  id: crypto.randomUUID(),
  label: "Network attachment",
  domain_key: "",
  physical_network_key: null,
  endpoint_key: null,
  port_key: null,
  network_number: null,
  medium: "unknown",
  role: "network",
  policy: "generic",
  assignment_state: "unknown",
  notes: "",
});
const keyPattern = /^[A-Za-z0-9_.:+-]{1,80}$/;
const optional = (text: string) => (text === "" ? null : text);

export function NetworkNumberPlanPanel() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [draft, setDraft] = useState<Plan | null>(null);
  const [record, setRecord] = useState<Assignment>(newRecord);
  const [editing, setEditing] = useState<string | null>(null);
  const [pendingRecord, setPendingRecord] = useState(false);
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [savedSignature, setSavedSignature] = useState("");
  const root = useRef<HTMLDetailsElement>(null),
    importer = useRef<HTMLInputElement>(null);
  const mounted = useRef(false),
    generation = useRef(0),
    requestId = useRef(0);
  const dirty =
    !!draft && (JSON.stringify(draft) !== savedSignature || pendingRecord);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestId.current++;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function invalidate() {
    generation.current++;
    setReview(null);
    setError("");
    setMessage("");
  }
  function current(request: number, epoch: number) {
    return (
      mounted.current &&
      !!root.current?.open &&
      requestId.current === request &&
      generation.current === epoch
    );
  }
  async function initialize() {
    if (catalog) return;
    const request = ++requestId.current,
      epoch = generation.current;
    setBusy(true);
    setError("");
    try {
      const value: Catalog = await api("/network-number-plan/catalog");
      if (!current(request, epoch)) return;
      setCatalog(value);
      setDraft(value.template);
      setSavedSignature(JSON.stringify(value.template));
    } catch (e) {
      if (current(request, epoch))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && requestId.current === request) setBusy(false);
    }
  }
  function changePlan(changes: Partial<Plan>) {
    if (!draft) return;
    invalidate();
    setDraft({ ...draft, ...changes });
  }
  function changeRecord(changes: Partial<Assignment>) {
    invalidate();
    setRecord({ ...record, ...changes });
    setPendingRecord(true);
  }
  function clearRecord() {
    setRecord(newRecord());
    setEditing(null);
    setPendingRecord(false);
  }
  function applyRecord() {
    if (!draft) return;
    if (
      !keyPattern.test(record.domain_key) ||
      [record.physical_network_key, record.endpoint_key, record.port_key].some(
        (value) => value !== null && !keyPattern.test(value),
      )
    ) {
      setError(
        "Identity keys require 1–80 ASCII letters, digits, underscore, dot, colon, plus or hyphen. A domain key is required; leave unknown optional keys blank.",
      );
      return;
    }
    if (
      !record.label.trim() ||
      record.label.length > 160 ||
      record.label !== record.label.trim()
    ) {
      setError(
        "Attachment label requires 1–160 characters with no surrounding whitespace.",
      );
      return;
    }
    if (
      record.network_number !== null &&
      (!Number.isInteger(record.network_number) ||
        record.network_number < 0 ||
        record.network_number > 65535)
    ) {
      setError(
        "Enter an integer 0–65535, or leave the number unknown. Review diagnoses 0 and 65535 as nonassignable physical-network numbers.",
      );
      return;
    }
    if (!editing && draft.assignments.length >= 512) {
      setError("Plan is limited to 512 attachment records.");
      return;
    }
    const rows = editing
      ? draft.assignments.map((row) => (row.id === editing ? record : row))
      : [...draft.assignments, record];
    changePlan({ assignments: rows });
    clearRecord();
    setMessage(
      "Attachment applied to local plan. Review again to check the updated declarations.",
    );
  }
  function editRecord(row: Assignment) {
    if (pendingRecord && !window.confirm("Discard unapplied attachment edits?"))
      return;
    setRecord(structuredClone(row));
    setEditing(row.id);
    setPendingRecord(false);
  }
  function reset() {
    if (
      !catalog ||
      (dirty &&
        !window.confirm(
          "Discard this network plan's unsaved or unapplied changes?",
        ))
    )
      return;
    invalidate();
    requestId.current++;
    setBusy(false);
    setDraft(structuredClone(catalog.template));
    setSavedSignature(JSON.stringify(catalog.template));
    clearRecord();
  }
  async function operate(kind: "review" | "plan" | "report") {
    if (!draft || pendingRecord) return;
    const snapshot = structuredClone(draft),
      epoch = generation.current,
      request = ++requestId.current;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api(
        kind === "plan"
          ? "/network-number-plan/validate"
          : "/network-number-plan/review",
        { plan: snapshot },
      );
      if (!current(request, epoch)) return;
      if (kind !== "plan") setReview(result);
      if (kind !== "review") {
        saveBlob(
          new Blob(
            [
              JSON.stringify(kind === "plan" ? result.plan : result, null, 2) +
                "\n",
            ],
            { type: "application/json" },
          ),
          kind === "plan"
            ? "bacnet-network-number-plan.json"
            : "bacnet-network-number-review.json",
        );
        if (kind === "plan") setSavedSignature(JSON.stringify(snapshot));
        setMessage(
          "Source-checked local JSON download requested. No field operation occurred.",
        );
      } else
        setMessage(
          "Reviewed only the submitted declarations; omitted or incorrectly identified networks remain unverified.",
        );
    } catch (e) {
      if (current(request, epoch))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && requestId.current === request) setBusy(false);
    }
  }
  async function importPlan(file?: File) {
    if (
      !file ||
      !catalog ||
      (dirty &&
        !window.confirm(
          "Replace the local draft and unapplied attachment edits with this plan?",
        ))
    )
      return;
    invalidate();
    const epoch = generation.current,
      request = ++requestId.current;
    setBusy(true);
    try {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Network plan exceeds 2 MiB.");
      const result = await api("/network-number-plan/validate", {
        plan: JSON.parse(await file.text()),
      });
      if (!current(request, epoch)) return;
      setDraft(result.plan);
      setSavedSignature(JSON.stringify(result.plan));
      clearRecord();
      setMessage(
        "Imported source-checked plan. Run a fresh review; imported files do not carry an active review.",
      );
    } catch (e) {
      if (current(request, epoch))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && requestId.current === request) setBusy(false);
    }
  }
  return (
    <details
      className="network-number-plan card"
      ref={root}
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        invalidate();
        if (event.currentTarget.open && !catalog) void initialize();
      }}
    >
      <summary>Network-number engineering plan</summary>
      <section aria-label="BACnet network-number planning">
        <h2>BACnet network-number review</h2>
        <p>
          Offline operator declarations only. Declare an internetwork/domain key
          and a physical-network key; the same network through multiple routers
          is valid. Unrelated internetworks may reuse numbers. Keys are exact
          and case-sensitive.
        </p>
        <p>
          A physical-network key identifies one numbered BACnet network, which
          may span IP subnets or bridged physical segments. Addresses, subnet
          membership and advertised routes do not establish that identity.
        </p>
        {!catalog || !draft ? (
          <button disabled={busy} onClick={() => void initialize()}>
            {busy ? "Loading source profile…" : "Load planning source profile"}
          </button>
        ) : (
          <>
            <div className="network-plan-actions">
              <button onClick={reset}>New empty network plan</button>
              <button onClick={() => importer.current?.click()}>
                Import network plan JSON
              </button>
              <button
                disabled={busy || pendingRecord}
                onClick={() => void operate("plan")}
              >
                Export network plan JSON
              </button>
              <button
                disabled={busy || pendingRecord}
                onClick={() => void operate("review")}
              >
                Review network numbers
              </button>
              <button
                disabled={busy || pendingRecord || !review}
                onClick={() => void operate("report")}
              >
                Export network review JSON
              </button>
            </div>
            <input
              ref={importer}
              type="file"
              accept=".json,application/json"
              hidden
              aria-label="Network plan JSON"
              onChange={(event) => {
                void importPlan(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <div className="network-plan-grid">
              <label>
                Network plan name
                <input
                  value={draft.name}
                  maxLength={160}
                  onChange={(event) => changePlan({ name: event.target.value })}
                />
              </label>
              <label className="network-plan-check">
                <input
                  type="checkbox"
                  checked={draft.declarations_complete}
                  onChange={(event) =>
                    changePlan({ declarations_complete: event.target.checked })
                  }
                />
                I have included the intended inventory in these declarations
              </label>
            </div>
            <label>
              Network plan notes
              <textarea
                maxLength={4000}
                value={draft.notes}
                onChange={(event) => changePlan({ notes: event.target.value })}
              />
            </label>
            <p>
              This checkbox records your inventory assertion. It does not verify
              completeness or establish that any number is globally available.
              For the R15 site-wide comparison, include the site's remote buses,
              local trunks and BACnet/IP networks in the same declared domain.
            </p>
            <fieldset>
              <legend>
                {editing ? "Edit network attachment" : "Add network attachment"}
              </legend>
              <p>
                Use the same domain + physical-network key for an engine
                integration and its corresponding router side. Distinct actual
                networks need different physical-network keys. Leave uncertain
                physical relationships unknown.
              </p>
              <div className="network-plan-grid">
                <label>
                  Attachment label
                  <input
                    value={record.label}
                    maxLength={160}
                    onChange={(event) =>
                      changeRecord({ label: event.target.value })
                    }
                  />
                </label>
                <label>
                  Internetwork/domain key
                  <input
                    value={record.domain_key}
                    maxLength={80}
                    onChange={(event) =>
                      changeRecord({ domain_key: event.target.value })
                    }
                  />
                </label>
                <label>
                  Physical-network key (blank = unknown)
                  <input
                    value={record.physical_network_key ?? ""}
                    maxLength={80}
                    onChange={(event) =>
                      changeRecord({
                        physical_network_key: optional(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Network number (blank = unknown)
                  <input
                    type="number"
                    min={0}
                    max={65535}
                    step={1}
                    value={record.network_number ?? ""}
                    onChange={(event) =>
                      changeRecord({
                        network_number:
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Endpoint identity key (optional)
                  <input
                    value={record.endpoint_key ?? ""}
                    maxLength={80}
                    onChange={(event) =>
                      changeRecord({
                        endpoint_key: optional(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Endpoint port key (optional)
                  <input
                    value={record.port_key ?? ""}
                    maxLength={80}
                    onChange={(event) =>
                      changeRecord({ port_key: optional(event.target.value) })
                    }
                  />
                </label>
                <label>
                  Declared network medium
                  <select
                    value={record.medium}
                    onChange={(event) =>
                      changeRecord({
                        medium: event.target.value as Assignment["medium"],
                      })
                    }
                  >
                    <option value="unknown">Unknown</option>
                    <option value="bacnet-ip">BACnet/IP</option>
                    <option value="mstp">MS/TP</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label>
                  Attachment role
                  <select
                    value={record.role}
                    onChange={(event) =>
                      changeRecord({
                        role: event.target.value as Assignment["role"],
                      })
                    }
                  >
                    <option value="network">Network declaration</option>
                    <option value="router-port">Router port</option>
                    <option value="engine-ip-port">Engine IP port</option>
                    <option value="engine-remote-field-integration">
                      Engine remote field integration
                    </option>
                    <option value="route-advertisement">
                      Route advertisement only
                    </option>
                  </select>
                </label>
                <label>
                  Engineering policy
                  <select
                    value={record.policy}
                    onChange={(event) =>
                      changeRecord({
                        policy: event.target.value as Assignment["policy"],
                      })
                    }
                  >
                    <option value="generic">Generic BACnet numbering</option>
                    <option value="jci-r15-remote-field">
                      JCI Release 15 Remote Field Bus
                    </option>
                  </select>
                </label>
                <label>
                  Assignment context
                  <select
                    value={record.assignment_state}
                    onChange={(event) =>
                      changeRecord({
                        assignment_state: event.target
                          .value as Assignment["assignment_state"],
                      })
                    }
                  >
                    <option value="unknown">Unknown</option>
                    <option value="existing">Existing</option>
                    <option value="new">New assignment</option>
                  </select>
                </label>
              </div>
              <label>
                Attachment evidence notes
                <textarea
                  maxLength={2000}
                  value={record.notes}
                  onChange={(event) =>
                    changeRecord({ notes: event.target.value })
                  }
                />
              </label>
              <p>
                Endpoint/port keys describe an operator-identified configuration
                endpoint. They do not open or resolve an address. Engine
                integrations may use their integration/trunk key. The JCI policy
                is limited to the reviewed R15 Remote Field Bus profile; it is
                not inferred from a brand, IP or controller model.
              </p>
              <div className="network-plan-actions">
                <button onClick={applyRecord}>
                  {editing
                    ? "Apply attachment edits"
                    : "Add attachment to plan"}
                </button>
                <button
                  onClick={() => {
                    invalidate();
                    clearRecord();
                  }}
                >
                  Clear attachment editor
                </button>
              </div>
            </fieldset>
            {pendingRecord && (
              <p role="note">
                Attachment editor has unapplied changes. Apply or clear them
                before reviewing or exporting the plan.
              </p>
            )}
            <h3>Declared attachments ({draft.assignments.length}/512)</h3>
            {!draft.assignments.length ? (
              <p>No attachments declared.</p>
            ) : (
              <div className="network-plan-table">
                <table>
                  <thead>
                    <tr>
                      <th>Attachment</th>
                      <th>Domain / physical network</th>
                      <th>Number</th>
                      <th>Endpoint / port</th>
                      <th>Medium / role</th>
                      <th>Policy / context</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {draft.assignments.map((row) => (
                      <tr key={row.id}>
                        <td>
                          {row.label}
                          <small>{row.id}</small>
                        </td>
                        <td>
                          {row.domain_key}
                          <small>
                            {row.physical_network_key ??
                              "Unknown physical network"}
                          </small>
                        </td>
                        <td>{row.network_number ?? "Unknown"}</td>
                        <td>
                          {row.endpoint_key ?? "Unspecified"}
                          <small>{row.port_key ?? "Unspecified"}</small>
                        </td>
                        <td>
                          {row.medium}
                          <small>{row.role}</small>
                        </td>
                        <td>
                          {row.policy}
                          <small>{row.assignment_state}</small>
                        </td>
                        <td>
                          <button
                            onClick={() => editRecord(row)}
                            aria-label={`Edit attachment ${row.label}`}
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => {
                              changePlan({
                                assignments: draft.assignments.filter(
                                  (other) => other.id !== row.id,
                                ),
                              });
                              if (editing === row.id) clearRecord();
                            }}
                            aria-label={`Remove attachment ${row.label}`}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {review && (
              <section aria-label="Network-number review results">
                <h3>Review status: {review.status}</h3>
                <p>
                  {review.counts.error} conflicts · {review.counts.unknown}{" "}
                  unknowns · {review.counts.info} notes
                </p>
                <p>{review.scope}</p>
                <p>Reviewed {review.reviewed_at}</p>
                <p>
                  Plan SHA-256 <code>{review.plan_sha256}</code>
                  <br />
                  Review SHA-256 <code>{review.content_sha256}</code>
                </p>
                {!review.findings.length ? (
                  <p>
                    No conflicts found in these submitted declarations. This
                    does not establish a complete or physically verified
                    inventory.
                  </p>
                ) : (
                  <ul className="network-plan-findings">
                    {review.findings.map((finding) => (
                      <li key={finding.id}>
                        <strong>
                          {finding.severity}: {finding.code}
                        </strong>
                        <p>{finding.message}</p>
                        {finding.domain_key && (
                          <p>Domain: {finding.domain_key}</p>
                        )}
                        <p>
                          Records:{" "}
                          {finding.assignment_ids.length
                            ? finding.assignment_ids
                                .map(
                                  (id) =>
                                    draft.assignments.find(
                                      (row) => row.id === id,
                                    )?.label ?? id,
                                )
                                .join(", ")
                            : "Whole plan"}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
            <details>
              <summary>Reviewed source profile</summary>
              <p>
                Source hashes identify reviewed documents and rule versions;
                they do not authenticate operator declarations or installed
                devices.
              </p>
              <code>{catalog.profile.sha256}</code>
              <ul>
                {catalog.profile.sources.map((source) => (
                  <li key={source.id}>
                    <a href={source.url} target="_blank" rel="noreferrer">
                      {source.document}
                    </a>
                    <p>
                      {source.section} · {source.artifact}
                    </p>
                    <code>{source.sha256}</code>
                    <p>{source.scope}</p>
                  </li>
                ))}
              </ul>
            </details>
            <p>
              Draft stays in this Connect view. Export plan JSON before leaving;
              reopen it through Import. Plan/review exports revalidate exact
              source-profile hashes. No automatic source migration, field scans,
              renumbering or device writes occur.
            </p>
          </>
        )}
        {busy && <p role="status">Validating local declarations…</p>}
        {message && <p role="status">{message}</p>}
        {error && <p role="alert">{error}</p>}
      </section>
    </details>
  );
}
