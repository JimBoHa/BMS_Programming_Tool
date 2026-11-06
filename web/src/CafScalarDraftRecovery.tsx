import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";
import {
  rawScalarKey,
  scalarDraftStatus,
  scalarDraftToken,
  scalarProposals,
  savedScalarResult,
  restoredScalarResult,
  removedScalarResult,
  type ScalarProposal,
  type ScalarCheckpoint,
  type UnavailableCheckpoint,
  type RestoredScalarDraft,
} from "./cafScalarDraftContract";

type Data = Record<string, any>;
export function CafScalarDraftRecovery({
  id,
  visible,
  context,
  changes,
  mutation,
  onRestore,
}: {
  id: string;
  visible: boolean;
  context: string;
  changes: ScalarProposal[];
  mutation: number;
  onRestore: (
    restored: RestoredScalarDraft,
    expectedMutation: number,
  ) => boolean;
}) {
  const owner = JSON.stringify([context, rawScalarKey(changes), mutation]);
  const ownerNow = useRef(owner),
    contextNow = useRef(context),
    epoch = useRef(0),
    listEpoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  if (contextNow.current !== context) {
    contextNow.current = context;
    listEpoch.current++;
  }
  const [loaded, setLoaded] = useState<{
    context: string;
    checkpoint: ScalarCheckpoint | UnavailableCheckpoint | null;
    capacity: Data | null;
  } | null>(null);
  const [listState, setListState] = useState<{
    context: string;
    ticket: number;
    busy?: boolean;
    error?: string;
  } | null>(null);
  const [operation, setOperation] = useState<{
    owner: string;
    ticket: number;
    busy?: string;
    error?: string;
    replacement?: RestoredScalarDraft;
  } | null>(null);
  const [notice, setNotice] = useState<{
    context: string;
    text: string;
  } | null>(null);
  const shown =
    operation?.owner === owner && operation.ticket === epoch.current
      ? operation
      : null;
  const listing =
    listState?.context === context && listState.ticket === listEpoch.current
      ? listState
      : null;
  const status = loaded?.context === context ? loaded : null;
  const checkpoint = status?.checkpoint || null;
  const saved = checkpoint && !("state" in checkpoint) ? checkpoint : null;
  const unavailable = checkpoint && "state" in checkpoint ? checkpoint : null;
  const expected = scalarDraftToken(checkpoint);
  const locked =
    !visible || !!listing?.busy || !!shown?.busy || !!shown?.replacement;
  const base = `/caf/${id}/scalar-draft`;
  const current = (key: string, ticket: number) =>
    alive.current && key === ownerNow.current && ticket === epoch.current;
  const currentList = (key: string, ticket: number) =>
    alive.current && key === contextNow.current && ticket === listEpoch.current;
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
    setOperation(null);
    setNotice(null);
    setListState({ context: key, ticket, busy: true });
    try {
      const status = scalarDraftStatus(await api(base), id);
      if (currentList(key, ticket)) {
        setLoaded({ context, ...status });
        setListState(null);
      }
    } catch (error) {
      if (currentList(key, ticket))
        setListState({ context: key, ticket, error: String(error) });
    }
  }
  useEffect(() => {
    setLoaded(null);
    if (visible) void refresh();
  }, [context, visible]);
  function begin(busy: string) {
    const key = ownerNow.current,
      ticket = ++epoch.current;
    listEpoch.current++;
    setNotice(null);
    setOperation({ owner: key, ticket, busy });
    return { key, ticket };
  }
  async function save() {
    if (locked || !status || unavailable || !scalarProposals(changes)) return;
    const snapshot = changes.map((row) => ({ ...row })),
      token = expected;
    const { key, ticket } = begin("Saving unfinished scalar text…");
    try {
      const checkpoint = savedScalarResult(
        await api(base, { changes: snapshot, expected: token }),
        id,
        snapshot,
        token,
      );
      if (current(key, ticket)) {
        setLoaded({ context, checkpoint, capacity: null });
        setOperation(null);
        setNotice({
          context,
          text: `Saved scalar checkpoint revision ${checkpoint.revision}. Proposed values remain unvalidated.`,
        });
      }
    } catch (error) {
      if (current(key, ticket))
        setOperation({ owner: key, ticket, error: String(error) });
    }
  }
  function apply(restored: RestoredScalarDraft, key: string, ticket: number) {
    if (!current(key, ticket)) return;
    if (!onRestore(restored, mutation)) {
      setOperation({
        owner: key,
        ticket,
        error:
          "Current scalar edits changed. Restore the checkpoint again to review replacement.",
      });
      return;
    }
    setOperation(null);
    setNotice({
      context,
      text: "Restored saved text into local scalar edits. Review and export separately; no export success was restored.",
    });
  }
  async function restore() {
    if (locked || !saved || !expected) return;
    const { key, ticket } = begin(
      "Rechecking saved scalar fields in the original CAF…",
    );
    try {
      const restored = restoredScalarResult(
        await api(`${base}/restore`, { expected }),
        id,
        saved,
      );
      if (!current(key, ticket)) return;
      if (
        changes.length > 0 &&
        rawScalarKey(changes) !== rawScalarKey(restored.checkpoint.changes)
      )
        setOperation({ owner: key, ticket, replacement: restored });
      else apply(restored, key, ticket);
    } catch (error) {
      if (current(key, ticket))
        setOperation({ owner: key, ticket, error: String(error) });
    }
  }
  async function remove() {
    if (locked || !expected) return;
    const { key, ticket } = begin("Removing saved scalar checkpoint…");
    try {
      removedScalarResult(
        await api(base, { expected }, "DELETE"),
        id,
        expected,
      );
      if (current(key, ticket)) {
        setLoaded({ context, checkpoint: null, capacity: null });
        setOperation(null);
        setNotice({
          context,
          text: "Removed saved checkpoint. Current scalar edits and the original CAF are unchanged.",
        });
      }
    } catch (error) {
      if (current(key, ticket))
        setOperation({ owner: key, ticket, error: String(error) });
    }
  }
  return (
    <section aria-label="Saved scalar CAF draft">
      <h3>Recover unfinished scalar edits</h3>
      <p>
        Save a checkpoint of the scalar text shown here, including unfinished
        values. Reopen the same original CAF to restore it explicitly.
      </p>
      <p>
        Graph, hardware, instance and creation proposals are separate. This
        checkpoint restores no export success, controller connection or field
        review.
      </p>
      {changes.length > 0 && !scalarProposals(changes) && (
        <p role="alert">
          This draft exceeds checkpoint limits or contains unsupported proposal
          text. Checkpoints allow 1000 unique scalar proposals, references of
          1–512 characters, and original/proposed text of up to 8192 Unicode
          characters per field.
        </p>
      )}
      <div className="button-row">
        <button
          disabled={
            locked || !status || !!unavailable || !scalarProposals(changes)
          }
          onClick={() => void save()}
        >
          Save scalar draft checkpoint
        </button>
        <button disabled={locked} onClick={() => void refresh()}>
          Refresh saved scalar draft
        </button>
        <button disabled={locked || !saved} onClick={() => void restore()}>
          Restore saved scalar draft
        </button>
        <button disabled={locked || !expected} onClick={() => void remove()}>
          Remove saved scalar draft
        </button>
      </div>
      {listing?.busy && <p role="status">Reading saved scalar checkpoint…</p>}
      {shown?.busy && <p role="status">{shown.busy}</p>}
      {listing?.error && <p role="alert">{listing.error}</p>}
      {shown?.error && (
        <p role="alert">
          {shown.error} Refresh saved draft status before retrying a conflict.
        </p>
      )}
      {notice?.context === context && <p role="status">{notice.text}</p>}
      {status && !checkpoint && (
        <p>No saved scalar checkpoint for this original CAF.</p>
      )}
      {unavailable && <p role="alert">{unavailable.error}</p>}
      {saved && (
        <>
          <p>
            Saved revision {saved.revision} · {saved.changes.length} scalar
            proposals · updated {saved.updated_at}. Saving a CAF copy does not
            remove this checkpoint.
          </p>
          <details>
            <summary>Inspect saved raw proposals</summary>
            <div className="table-scroll">
              <table aria-label="Saved scalar proposal text">
                <thead>
                  <tr>
                    <th>Object</th>
                    <th>Property</th>
                    <th>Original text</th>
                    <th>Saved proposal text</th>
                  </tr>
                </thead>
                <tbody>
                  {saved.changes.map((row) => (
                    <tr key={JSON.stringify([row.ref, row.property])}>
                      <td>{row.ref}</td>
                      <td>{row.property}</td>
                      <td>
                        <code>{JSON.stringify(row.old)}</code>
                      </td>
                      <td>
                        <code>{JSON.stringify(row.value)}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              Quoted text preserves whitespace and unfinished input. It is not
              an exported or validated CAF.
            </p>
            <button
              disabled={!visible}
              onClick={() =>
                saveBlob(
                  new Blob([JSON.stringify(saved, null, 2)], {
                    type: "application/json",
                  }),
                  `caf-scalar-draft-${saved.id}-r${saved.revision}.json`,
                )
              }
            >
              Download saved scalar draft JSON
            </button>
            <details>
              <summary>Checkpoint source and integrity</summary>
              <pre>
                {JSON.stringify(
                  {
                    caf_sha256: saved.caf_sha256,
                    id: saved.id,
                    revision: saved.revision,
                    checkpoint_sha256: saved.checkpoint_sha256,
                    created_at: saved.created_at,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </details>
        </>
      )}
      {shown?.replacement && (
        <section aria-label="Replace current scalar edits">
          <h4>Current scalar text differs from the saved checkpoint</h4>
          <p>
            Restore replaces {changes.length} current scalar proposals with{" "}
            {shown.replacement.checkpoint.changes.length} saved proposals. Other
            edit families remain separate.
          </p>
          <div className="button-row">
            <button
              onClick={() =>
                apply(shown.replacement!, shown.owner, shown.ticket)
              }
            >
              Replace current scalar edits
            </button>
            <button
              onClick={() => {
                setOperation(null);
                setNotice({
                  context,
                  text: "Kept current scalar edits. Saved checkpoint is unchanged.",
                });
              }}
            >
              Keep current scalar edits
            </button>
          </div>
        </section>
      )}
      {status?.capacity && (
        <details>
          <summary>Saved draft storage</summary>
          <p>
            {status.capacity.count} of {status.capacity.limit} CAF checkpoints ·{" "}
            {status.capacity.bytes} of {status.capacity.byte_limit} bytes on
            this computer. Saving never evicts another checkpoint.
          </p>
        </details>
      )}
    </section>
  );
}
