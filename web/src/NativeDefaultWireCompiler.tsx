import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { rememberWireDraft } from "./nativeWireDrafts";
import {
  defaultWireBase as base,
  defaultWireSource,
  defaultWireSelection,
  defaultWireReview,
} from "./nativeDefaultWireContract";

type Data = Record<string, any>;
type Owned = { owner: string; ticket: number };
export function NativeDefaultWireCompiler({
  source,
  field,
  valueText,
  context,
  generation,
  visible,
  blocked,
  parentCurrent,
  drafts,
}: {
  source: Data;
  field: Data;
  valueText: string;
  context: string;
  generation: number;
  visible: boolean;
  blocked: boolean;
  parentCurrent: () => boolean;
  drafts: Map<string, string>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState<{ key: string; data: Data } | null>(
    null,
  );
  const [connection, setConnection] = useState<{
    key: string;
    data: Data;
  } | null>(null);
  const [, redraw] = useState(0);
  const [review, setReview] = useState<
    (Owned & { data: Data; blob: Blob }) | null
  >(null);
  const [pending, setPending] = useState<Owned | null>(null);
  const [error, setError] = useState<(Owned & { text: string }) | null>(null);
  const [saved, setSaved] = useState<Owned | null>(null);
  const sourceKey = JSON.stringify([source.capture_id, source.snapshot_sha256]);
  const opened = loaded?.key === sourceKey ? loaded.data : null;
  const diagramRef =
    drafts.get(sourceKey + "/diagram") ??
    opened?.diagrams.find((d: Data) => d.available)?.ref ??
    "";
  const diagram = opened?.diagrams.find((d: Data) => d.ref === diagramRef);
  const diagramKey = sourceKey + "/" + diagramRef;
  const wireIndex = Number(drafts.get(diagramKey + "/wire") ?? "0");
  const selectionKey = diagramKey + "/" + wireIndex;
  const selected = connection?.key === selectionKey ? connection.data : null;
  const selection = selected?.selection,
    wire = selection?.selected_wire;
  const sourceRef =
    drafts.get(selectionKey + "/source") ?? wire?.source_ref ?? "";
  const candidate = selection?.candidates.find(
    (c: Data) => c.ref === sourceRef,
  );
  const wires = connection?.key.startsWith(diagramKey + "/")
    ? connection.data.selection.wires
    : [];
  const owner = JSON.stringify([
    context,
    generation,
    visible,
    blocked,
    expanded,
    sourceKey,
    field.ref,
    field.encoded_sha256,
    valueText,
    opened?.effective_sha256,
    selectionKey,
    selection?.property_sha256,
    sourceRef,
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const current = (ticket: number, key: string) =>
    alive.current &&
    visible &&
    !blocked &&
    expanded &&
    parentCurrent() &&
    epoch.current === ticket &&
    ownerNow.current === key;
  const owns = (value: Owned | null) =>
    !!value &&
    value.owner === owner &&
    value.ticket === epoch.current &&
    parentCurrent();
  const shown = owns(review) ? review : null;
  const busy = blocked || owns(pending);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  function retire() {
    epoch.current++;
    setReview(null);
    setError(null);
    setSaved(null);
  }
  function remember(key: string, value: string) {
    if (!rememberWireDraft(drafts, key, value)) {
      setError({
        owner,
        ticket: epoch.current,
        text: "All 256 combined connection draft slots are retained. Discard an older combined connection draft before adding another; no draft was removed.",
      });
      return false;
    }
    retire();
    redraw((v) => v + 1);
    return true;
  }
  async function operate(
    action: (ticket: number, key: string) => Promise<void>,
  ) {
    if (!visible || blocked || !expanded || !parentCurrent() || owns(pending))
      return;
    const ticket = ++epoch.current,
      key = ownerNow.current;
    setReview(null);
    setError(null);
    setSaved(null);
    setPending({ owner: key, ticket });
    try {
      await action(ticket, key);
    } catch (failure) {
      if (current(ticket, key))
        setError({ owner: key, ticket, text: String(failure) });
    } finally {
      if (current(ticket, key)) setPending(null);
    }
  }
  const sourceRequest = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
  };
  const selectionRequest =
    opened && diagram
      ? {
          ...sourceRequest,
          source_sha256: opened.source_sha256,
          effective_sha256: opened.effective_sha256,
          diagram_ref: diagram.ref,
          record_sha256: diagram.archive_record_sha256,
          wire_index: wireIndex,
        }
      : null;
  const body =
    selectionRequest && wire && candidate
      ? {
          ...selectionRequest,
          effective_record_sha256: selection.record_sha256,
          property_sha256: selection.property_sha256,
          old: wire.old,
          source_ref: sourceRef,
          record_ref: field.ref,
          encoded_sha256: field.encoded_sha256,
          value_text: valueText,
        }
      : null;
  async function open() {
    await operate(async (ticket, key) => {
      const data = await api(base + "/source", sourceRequest);
      if (!defaultWireSource(data, source))
        throw new Error(
          "Combined compiler source differs from this retained backup and saved values.",
        );
      if (current(ticket, key)) {
        setLoaded({ key: sourceKey, data });
        setConnection(null);
      }
    });
  }
  async function inspect() {
    if (!selectionRequest) return;
    await operate(async (ticket, key) => {
      const data = await api(base + "/selection", selectionRequest);
      if (!defaultWireSelection(data, source, opened!, selectionRequest))
        throw new Error(
          "Combined connection selection differs from this retained diagram.",
        );
      if (current(ticket, key)) setConnection({ key: selectionKey, data });
    });
  }
  async function compile() {
    if (!body) return;
    await operate(async (ticket, key) => {
      const result = await apiJsonDocument(base + "/preview", body);
      if (
        !defaultWireReview(result.data, source, opened!, selected!, body, field)
      )
        throw new Error(
          "Combined native review differs from these sources and two proposed edits.",
        );
      if (current(ticket, key)) setReview({ owner: key, ticket, ...result });
    });
  }
  async function save() {
    if (!shown || !body || busy || !visible || !parentCurrent()) return;
    const ticket = epoch.current,
      key = ownerNow.current;
    setPending({ owner: key, ticket });
    setError(null);
    setSaved(null);
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...body,
        review_sha256: shown.data.review_sha256,
      });
      if (
        result.headers.get("X-Studio-Artifact-Sha256") !==
          shown.data.output_sha256 ||
        result.headers.get("X-Studio-Review-Sha256") !==
          shown.data.review_sha256 ||
        result.headers.get("X-Studio-Snapshot-Sha256") !==
          source.snapshot_sha256 ||
        (await sha256Blob(result.blob)) !== shown.data.output_sha256
      )
        throw new Error(
          "Combined native output bytes differ from the reviewed file.",
        );
      if (current(ticket, key)) {
        saveBlob(result.blob, "native-default-wire.moi");
        setSaved({ owner: key, ticket });
      }
    } catch (failure) {
      if (current(ticket, key))
        setError({ owner: key, ticket, text: String(failure) });
    } finally {
      if (current(ticket, key)) setPending(null);
    }
  }
  return (
    <details
      className="native-compiler-source"
      aria-label="Combined native default and connection"
      open={expanded}
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          retire();
          setExpanded((v) => !v);
        }}
      >
        Combine this default with a connection change
      </summary>
      {expanded && (
        <>
          <p>
            Use the proposed Real default above and one existing connection in
            this retained backup. Review and save a local native copy.
          </p>
          <p>
            {source.device} at {source.target.address}
            {source.target.router
              ? ` via ${source.target.router} / DNET ${source.target.dnet}`
              : ""}{" "}
            · captured {source.captured_at}. Values come from this saved
            snapshot.
          </p>
          <button type="button" disabled={busy} onClick={() => void open()}>
            Open combined compiler
          </button>
          {opened && (
            <>
              <p>
                {opened.parameter_merge.matched_parameters} saved application
                parameters merged. The selected default and connection use the
                same saved application.
              </p>
              {!opened.diagrams.some((d: Data) => d.available) && (
                <p role="status">
                  No existing connection is available in the actual retained
                  diagrams.
                </p>
              )}
              <label>
                Combined native diagram
                <select
                  aria-label="Combined native diagram"
                  value={diagramRef}
                  disabled={blocked}
                  onChange={(e) => {
                    remember(sourceKey + "/diagram", e.target.value);
                  }}
                >
                  <option value="">Select an actual retained diagram</option>
                  {opened.diagrams.map((d: Data) => (
                    <option key={d.ref} value={d.ref}>
                      {d.name} · {d.ref} · {d.wire_count} connections
                    </option>
                  ))}
                </select>
              </label>
              {diagram?.error && <p role="status">{diagram.error}</p>}
              {wires.length > 0 && (
                <label>
                  Combined native connection
                  <select
                    aria-label="Combined native connection"
                    value={wireIndex}
                    disabled={blocked}
                    onChange={(e) => {
                      remember(diagramKey + "/wire", e.target.value);
                    }}
                  >
                    {wires.map((w: Data) => (
                      <option key={w.index} value={w.index}>
                        {w.index}: {w.source_ref}:{w.source_port} to{" "}
                        {w.target_ref}:{w.target_port}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                type="button"
                disabled={busy || !diagram?.available}
                onClick={() => void inspect()}
              >
                Inspect combined connection
              </button>
              {wire && (
                <>
                  <label>
                    Combined replacement source
                    <select
                      aria-label="Combined replacement source"
                      value={sourceRef}
                      disabled={blocked}
                      onChange={(e) => {
                        remember(selectionKey + "/source", e.target.value);
                      }}
                    >
                      {selection.candidates.map((c: Data) => (
                        <option key={c.ref} value={c.ref}>
                          {c.name} · {c.ref}
                          {c.current_source ? " · current source" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div
                    className="table-scroll"
                    tabIndex={0}
                    role="region"
                    aria-label="Combined native proposal table"
                  >
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">Field</th>
                          <th scope="col">Saved source</th>
                          <th scope="col">Proposed</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <th scope="row">Real default · {field.ref}</th>
                          <td>
                            <code>{field.effective_bits}</code>
                          </td>
                          <td>
                            <code>{JSON.stringify(valueText)}</code>
                          </td>
                        </tr>
                        <tr>
                          <th scope="row">
                            Connection {wire.index} · source pin{" "}
                            {wire.source_port}
                          </th>
                          <td>{wire.source_ref}</td>
                          <td>{sourceRef}</td>
                        </tr>
                        <tr>
                          <th scope="row">Destination</th>
                          <td colSpan={2}>
                            {wire.target_ref} · pin {wire.target_port} ·
                            unchanged
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div className="button-row">
                    <button
                      type="button"
                      disabled={busy || !body || !valueText}
                      onClick={() => void compile()}
                    >
                      Review combined native compilation
                    </button>
                    <button
                      type="button"
                      disabled={blocked}
                      onClick={() => {
                        retire();
                        drafts.delete(selectionKey + "/source");
                        redraw((v) => v + 1);
                      }}
                    >
                      Discard combined connection draft
                    </button>
                  </div>
                </>
              )}
            </>
          )}
          {owns(error) && <p role="alert">{error!.text}</p>}
          {shown && (
            <section aria-label="Reviewed combined native compilation">
              <h2>Reviewed combined native compilation</h2>
              <p>
                Real default:{" "}
                <code>
                  {shown.data.compilation.selected_default.before_bits}
                </code>{" "}
                to{" "}
                <code>
                  {shown.data.compilation.selected_default.after_bits}
                </code>
                {shown.data.compilation.selected_default
                  .decimal_precision_changed
                  ? " · proposed decimal is rounded"
                  : ""}
                .
              </p>
              <p>
                Connection:{" "}
                {shown.data.compilation.selected_wire.old_source_ref} to{" "}
                {shown.data.compilation.selected_wire.source_ref}. Both edit
                orders produce identical bytes; all other merged bytes remain
                unchanged.
              </p>
              <p>
                Saving this file does not transfer it. Native runtime,
                resource/package validation and CCT or physical acceptance
                require separate qualification.
              </p>
              <div className="button-row">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void save()}
                >
                  Save compiled default and connection
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    if (current(shown.ticket, shown.owner))
                      saveBlob(shown.blob, "native-default-wire-review.json");
                  }}
                >
                  Export exact combined review
                </button>
              </div>
              <details>
                <summary>
                  Sources, independent edits and both composition orders
                </summary>
                <pre>{JSON.stringify(shown.data, null, 2)}</pre>
              </details>
            </section>
          )}
          {owns(saved) && (
            <p role="status">Saved reviewed combined native copy.</p>
          )}
        </>
      )}
    </details>
  );
}
