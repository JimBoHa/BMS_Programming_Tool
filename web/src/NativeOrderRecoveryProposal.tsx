import { useEffect, useRef, useState } from "react";
import "./change-ledger.css";
import { apiJsonDocument, saveBlob } from "./api";
import type { NativeArchiveSource } from "./NativeRecords";
import {
  orderRecoveryProposalBase,
  orderRecoveryProposalEvidence,
} from "./nativeOrderRecoveryProposalContract";
type Data = Record<string, any>;
type Document = { owner: string; epoch: number; data: Data; blob: Blob };
export function NativeOrderRecoveryProposal({
  source,
  opened,
  receipt,
  comparison,
  visible,
  blocked,
  revision,
  parentCurrent,
  onPreviousOrder,
}: {
  source: NativeArchiveSource;
  opened: Data | null;
  receipt: Data;
  comparison: Data;
  visible: boolean;
  blocked: boolean;
  revision: string;
  parentCurrent: () => boolean;
  onPreviousOrder: (request: Data) => boolean;
}) {
  const [document, setDocument] = useState<Document | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const version = useRef({ data: receipt, value: 0 });
  if (version.current.data !== receipt)
    version.current = { data: receipt, value: version.current.value + 1 };
  const owner = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    opened?.source_report_sha256,
    receipt.intent?.id,
    receipt.intent?.evidence_sha256,
    version.current.value,
    visible,
    blocked,
    revision,
    comparison.evidence_sha256,
  ]);
  const actual = useRef({ owner, visible, blocked, parentCurrent }),
    epoch = useRef(0),
    alive = useRef(true),
    present = useRef(true),
    surface = useRef(false),
    active = useRef<object | null>(null);
  if (actual.current.owner !== owner) {
    epoch.current++;
    active.current = null;
  }
  actual.current = { owner, visible, blocked, parentCurrent };
  function retire() {
    epoch.current++;
    active.current = null;
    setDocument(null);
    setPending(false);
    setError("");
  }
  const current = (key: string, ticket: number) =>
    alive.current &&
    present.current &&
    surface.current &&
    actual.current.owner === key &&
    epoch.current === ticket &&
    actual.current.visible &&
    !actual.current.blocked &&
    actual.current.parentCurrent() &&
    window.document.visibilityState !== "hidden";
  useEffect(() => {
    alive.current = true;
    const hide = () => {
      present.current = false;
      retire();
    };
    const show = () => {
      present.current = true;
      retire();
    };
    const visibility = () => {
      present.current = window.document.visibilityState !== "hidden";
      retire();
    };
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    window.document.addEventListener("visibilitychange", visibility);
    return () => {
      alive.current = false;
      epoch.current++;
      active.current = null;
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
      window.document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  useEffect(() => {
    setDocument(null);
    setPending(false);
    setError("");
  }, [owner]);
  const shown =
    document && current(document.owner, document.epoch) ? document : null;
  async function prepare() {
    const key = actual.current.owner,
      ticket = epoch.current;
    if (!opened || active.current || !current(key, ticket)) return;
    const operation = {};
    active.current = operation;
    setPending(true);
    setError("");
    setDocument(null);
    try {
      const reply = await apiJsonDocument(orderRecoveryProposalBase, {
        receipt_id: receipt.intent.id,
        capture_id: source.capture_id,
        snapshot_sha256: source.snapshot_sha256,
      });
      if (!current(key, ticket)) return;
      if (
        !(await orderRecoveryProposalEvidence(
          reply.data,
          source,
          opened,
          receipt,
          comparison,
        ))
      )
        throw Error(
          "The previous-order proposal does not match this exact retained source and verified original result.",
        );
      if (current(key, ticket))
        setDocument({
          owner: key,
          epoch: ticket,
          data: reply.data,
          blob: reply.blob,
        });
    } catch (e) {
      if (current(key, ticket)) setError(String(e));
    } finally {
      if (active.current === operation) {
        active.current = null;
        if (alive.current) setPending(false);
      }
    }
  }
  async function replaceLocal() {
    if (
      !shown ||
      !opened ||
      active.current ||
      !current(shown.owner, shown.epoch)
    )
      return;
    const selected = shown,
      operation = {};
    active.current = operation;
    setPending(true);
    setError("");
    try {
      if (
        !(await orderRecoveryProposalEvidence(
          selected.data,
          source,
          opened,
          receipt,
          comparison,
        ))
      )
        throw Error(
          "The previous-order proposal no longer matches this retained source and proof.",
        );
      if (
        current(selected.owner, selected.epoch) &&
        onPreviousOrder(selected.data.proposal)
      )
        retire();
    } catch (e) {
      if (current(selected.owner, selected.epoch)) setError(String(e));
    } finally {
      if (active.current === operation) {
        active.current = null;
        if (alive.current) setPending(false);
      }
    }
  }
  return (
    <details
      aria-label="Previous execution-order proposal"
      onToggle={(event) => {
        const open = event.currentTarget.open;
        if (surface.current !== open) {
          surface.current = open;
          retire();
        }
      }}
    >
      <summary
        onClick={(event) => {
          surface.current =
            !event.currentTarget.parentElement!.hasAttribute("open");
          retire();
        }}
      >
        Prepare previous execution order
      </summary>
      <p>
        Prepare a local proposal using the original recorded order. The retained
        after application, effective order and static saved directory must match
        the verified original result.
      </p>
      <p>
        This compiles a local review and sends no controller request. Changing
        an operating controller still requires a separately confirmed fresh
        review, application transfer and full readback. This proposal records no
        controller recovery lineage.
      </p>
      <button
        disabled={
          !visible ||
          blocked ||
          pending ||
          comparison.state !== "application-and-order-match" ||
          comparison.comparisons.original_saved_directory_matches !== true
        }
        onClick={() => void prepare()}
      >
        Prepare previous order proposal
      </button>
      {pending && (
        <>
          <p role="status">Compiling local previous-order proposal…</p>
          <button onClick={retire}>Cancel previous order proposal</button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Prepared previous execution order">
          <p role="status">
            Previous order compiled locally. Current controller state remains
            unverified.
          </p>
          <p>
            Original receipt: {shown.data.origin.parent_receipt_id} · proof{" "}
            {shown.data.origin.verified_proof.kind} from{" "}
            {shown.data.origin.verified_proof.time}.
          </p>
          <div className="change-ledger-table">
            <table aria-label="Previous execution-order proposal members">
              <thead>
                <tr>
                  <th>Position</th>
                  <th>Retained order</th>
                  <th>Proposed previous order</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.proposal.proposed_order.map(
                  (index: number, position: number) => {
                    const selection = shown.data.comparison.source.selection,
                      current =
                        selection.members[selection.original_order[position]],
                      previous = selection.members[index];
                    return (
                      <tr key={position}>
                        <td>{position + 1}</td>
                        <td>
                          {current.index}: {current.name || current.ref}
                        </td>
                        <td>
                          {previous.index}: {previous.name || previous.ref}
                        </td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          </div>
          <label>
            Previous order indices
            <input
              aria-label="Previous order indices"
              readOnly
              value={shown.data.proposal.proposed_order.join(", ")}
            />
          </label>
          <p>
            Replace the local draft explicitly, then use the existing order
            editor for a separate review. An unfinished different proposal
            requires confirmation. Saving this evidence never applies it.
          </p>
          <p>
            Other merged application bytes, existing members, wire phase and
            Unsigned widths were preserved by the local compiler. Complete
            native authoring, package resources, CCT/firmware and physical
            acceptance remain separate.
          </p>
          <details>
            <summary>Local compilation and origin evidence</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
          <button
            className="primary"
            disabled={pending || blocked || !visible}
            onClick={() => void replaceLocal()}
          >
            Replace local order proposal with previous order
          </button>
          <button
            onClick={() => {
              if (current(shown.owner, shown.epoch))
                saveBlob(
                  shown.blob,
                  "native-previous-execution-order-proposal.json",
                );
            }}
          >
            Save exact previous-order proposal
          </button>
        </section>
      )}
    </details>
  );
}
