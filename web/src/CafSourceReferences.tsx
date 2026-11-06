import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob } from "./api";
import type { ComparisonSource } from "./cafNativeCorrelationSources";
import {
  referenceClassifications,
  referenceFlags,
  referenceList,
  referenceReport,
  referenceRequest,
  referenceSave,
} from "./cafSourceReferenceContract";

type Data = Record<string, any>;
const station = (v: Data) =>
  v.router
    ? `${v.router} / network ${v.dnet} / station ${v.address} · ${v.device}`
    : `${v.address} · ${v.device}`;

/** A local reference never selects a controller, a comparison source or a review. */
export function CafSourceReferences({
  id,
  visible,
  context,
  selected,
  hasLocalProposals,
}: {
  id: string;
  visible: boolean;
  context: string;
  selected?: ComparisonSource;
  hasLocalProposals: boolean;
}) {
  const owner = JSON.stringify([
    context,
    id,
    visible,
    selected?.kind,
    selected?.id,
    selected?.signature,
    selected?.target,
  ]);
  const ownerNow = useRef(owner),
    contextNow = useRef(context),
    listEpoch = useRef(0),
    epoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  if (contextNow.current !== context) {
    contextNow.current = context;
    listEpoch.current++;
  }
  const [listState, setListState] = useState<{
    context: string;
    ticket: number;
    busy?: boolean;
    error?: string;
  } | null>(null);
  const [listing, setListing] = useState<{
    context: string;
    rows: Data[];
    capacity: Data;
  } | null>(null);
  const [state, setState] = useState<{
    owner: string;
    ticket: number;
    busy?: string;
    error?: string;
    notice?: string;
    report?: { row: Data; data: Data; blob: Blob };
  } | null>(null);
  const current = (key: string, ticket: number) =>
    alive.current && key === ownerNow.current && ticket === epoch.current;
  const shown =
    state?.owner === owner && state.ticket === epoch.current ? state : null;
  const rows = listing?.context === context ? listing.rows : [];
  const currentList =
    listState?.context === context && listState.ticket === listEpoch.current
      ? listState
      : null;
  const listCurrent = (key: string, ticket: number) =>
    alive.current && key === contextNow.current && ticket === listEpoch.current;
  const base = `/caf/${id}/source-references`;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
      listEpoch.current++;
    };
  }, []);

  async function refresh() {
    if (!visible) return;
    const key = contextNow.current,
      ticket = ++listEpoch.current;
    epoch.current++;
    setState(null);
    setListState({ context: key, ticket, busy: true });
    try {
      const result = await api(base),
        references = referenceList(result, id);
      if (listCurrent(key, ticket)) {
        setListing({ context, rows: references, capacity: result.capacity });
        setListState(null);
      }
    } catch (error) {
      if (listCurrent(key, ticket))
        setListState({ context: key, ticket, error: String(error) });
    }
  }
  useEffect(() => {
    setListing(null);
    if (visible) void refresh();
  }, [context, id, visible]);

  async function save() {
    if (!selected || !visible) return;
    const key = ownerNow.current,
      ticket = ++epoch.current;
    listEpoch.current++;
    setState({
      owner: key,
      ticket,
      busy: "Saving original CAF/source reference…",
    });
    try {
      const result = await api(base, referenceRequest(selected, id));
      referenceSave(result, selected, id);
      const updated = await api(base),
        references = referenceList(updated, id);
      if (current(key, ticket)) {
        setListing({ context, rows: references, capacity: updated.capacity });
        setState({
          owner: key,
          ticket,
          notice: result.created
            ? "Saved reference to the original CAF and selected recorded source."
            : "This exact CAF/source reference was already saved.",
        });
      }
    } catch (error) {
      if (current(key, ticket))
        setState({ owner: key, ticket, error: String(error) });
    }
  }
  async function open(row: Data) {
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setState({ owner: key, ticket, busy: "Reading original saved report…" });
    try {
      const result = await referenceReport(
        await apiJsonDocument(`${base}/${row.id}/report`, undefined, true),
        row,
        id,
      );
      if (current(key, ticket))
        setState({ owner: key, ticket, report: { row, ...result } });
    } catch (error) {
      if (current(key, ticket))
        setState({ owner: key, ticket, error: String(error) });
    }
  }
  async function remove(row: Data) {
    const key = ownerNow.current,
      ticket = ++epoch.current;
    listEpoch.current++;
    setState({ owner: key, ticket, busy: "Removing local reference…" });
    try {
      const result = await api(`${base}/${row.id}`, undefined, "DELETE");
      if (
        !referenceFlags(result) ||
        result.profile !== "caf-source-reference-remove/1" ||
        result.id !== row.id ||
        result.removed !== true
      )
        throw new Error(
          "Reference removal did not return the expected local result. Refresh saved references.",
        );
      const updated = await api(base),
        references = referenceList(updated, id);
      if (current(key, ticket)) {
        setListing({ context, rows: references, capacity: updated.capacity });
        setState({
          owner: key,
          ticket,
          notice:
            "Removed local reference. Original CAF and retained source are unchanged.",
        });
      }
    } catch (error) {
      if (current(key, ticket))
        setState({ owner: key, ticket, error: String(error) });
    }
  }
  return (
    <section aria-label="Saved CAF/source references">
      <h4>Saved CAF/source references</h4>
      <p>
        Keep a user-selected recorded reference with this original CAF.
        Reopening identical CAF bytes restores its references.
      </p>
      <p>
        Save recomputes the unfiltered identity summary and first 128 record
        details. Search text and the current comparison page are excluded.
      </p>
      {hasLocalProposals && (
        <p>
          Unsaved CAF proposals remain separate and are excluded from saved
          references.
        </p>
      )}
      <div className="button-row">
        <button
          disabled={!visible || !selected || !!shown?.busy}
          onClick={() => void save()}
        >
          Save selected source reference
        </button>
        <button
          disabled={!visible || !!shown?.busy || !!currentList?.busy}
          onClick={() => void refresh()}
        >
          Refresh saved references
        </button>
      </div>
      <p>
        References do not verify matching logic, compiler compatibility or the
        current controller application. Retained source availability is not
        revalidated.
      </p>
      {shown?.busy && <p role="status">{shown.busy}</p>}
      {currentList?.busy && <p role="status">Reading saved references…</p>}
      {currentList?.error && <p role="alert">{currentList.error}</p>}
      {shown?.notice && <p role="status">{shown.notice}</p>}
      {shown?.error && <p role="alert">{shown.error}</p>}
      {listing?.context === context && !rows.length && (
        <p>No saved references for this original CAF.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table aria-label="Saved CAF/source reference list">
            <thead>
              <tr>
                <th>Recorded source</th>
                <th>Recorded station</th>
                <th>Identity observation</th>
                <th>Saved</th>
                <th>Local actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.state === "saved" ? (
                      <>
                        {row.source_kind === "backup"
                          ? "Native backup"
                          : "Captured BACnet File"}
                        <br />
                        <span className="mono">{row.source.capture_id}</span>
                        {row.source.file_object && (
                          <>
                            <br />
                            {row.source.file_object}
                          </>
                        )}
                      </>
                    ) : (
                      "Saved reference unavailable"
                    )}
                  </td>
                  <td>
                    {row.state === "saved"
                      ? station(row.source.target)
                      : "Unavailable"}
                  </td>
                  <td>
                    {row.state === "saved"
                      ? referenceClassifications[row.classification]
                      : row.error}
                  </td>
                  <td>
                    {row.state === "saved" ? row.created_at : "Unavailable"}
                  </td>
                  <td>
                    <div className="button-row">
                      {row.state === "saved" && (
                        <button
                          disabled={!visible || !!shown?.busy}
                          onClick={() => void open(row)}
                        >
                          Open saved report
                        </button>
                      )}
                      <button
                        disabled={!visible || !!shown?.busy}
                        onClick={() => void remove(row)}
                      >
                        Remove reference
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {listing?.context === context && (
        <details>
          <summary>Local reference storage</summary>
          <p>
            {listing.capacity.count} of {listing.capacity.limit} references on
            this computer · {listing.capacity.bytes} of{" "}
            {listing.capacity.byte_limit} bytes. Remove references to free
            space; existing work is never evicted.
          </p>
        </details>
      )}
      {shown?.report && (
        <section aria-label="Original saved CAF/source report">
          <h4>{referenceClassifications[shown.report.row.classification]}</h4>
          <p>
            User-selected historical reference ·{" "}
            {shown.report.row.source_kind === "backup"
              ? "Native backup"
              : "Captured BACnet File"}{" "}
            · {station(shown.report.row.source.target)}.
          </p>
          <p>
            Source captured {shown.report.row.source.captured_at}. Reference
            saved {shown.report.row.created_at}.
          </p>
          <p>
            Full comparison coverage: {shown.report.row.coverage.caf_objects}{" "}
            CAF objects · {shown.report.row.coverage.native_engineering_records}{" "}
            native engineering records ·{" "}
            {shown.report.row.coverage.native_metadata_records} native metadata
            records excluded · {shown.report.row.coverage.union_references}{" "}
            union references.
          </p>
          <p>
            Retained record detail page: {shown.report.data.records.length} of{" "}
            {shown.report.data.total_matches} references, unfiltered, offset 0,
            limit 128.{" "}
            {shown.report.data.next_offset !== null
              ? "Additional record details are not retained in this report."
              : "All record identity details fit on this page."}
          </p>
          <div className="table-scroll">
            <table aria-label="Saved record identity counts">
              <thead>
                <tr>
                  <th>Observation</th>
                  <th>Full comparison count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(
                  shown.report.row.coverage.record_status_counts,
                ).map(([name, count]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{String(count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            onClick={() =>
              saveBlob(
                shown.report!.blob,
                `caf-source-reference-${shown.report!.row.id}.json`,
              )
            }
          >
            Download original saved report
          </button>
          <details>
            <summary>Recorded comparison details and source evidence</summary>
            <p>{shown.report.row.scope}</p>
            <ul>
              {shown.report.row.coverage.not_compared.map((value: string) => (
                <li key={value}>{value}</li>
              ))}
            </ul>
            <pre>
              {JSON.stringify(
                {
                  reference: shown.report.row,
                  device_checks: shown.report.data.device_checks,
                  records: shown.report.data.records,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      )}
    </section>
  );
}
