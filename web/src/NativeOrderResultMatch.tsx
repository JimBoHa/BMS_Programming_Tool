import { useEffect, useRef, useState } from "react";
import { NativeOrderRecoveryProposal } from "./NativeOrderRecoveryProposal";
import "./change-ledger.css";
import { apiJsonDocument, saveBlob } from "./api";
import type { NativeArchiveSource } from "./NativeRecords";
import {
  orderMatchParent,
  orderMatchParentProblem,
  orderResultMatchBase,
  orderResultMatchEvidence,
} from "./nativeOrderResultMatchContract";
type Data = Record<string, any>;
type Document = { owner: string; epoch: number; data: Data; blob: Blob };
export function NativeOrderResultMatch({
  source,
  opened,
  receipt,
  visible,
  blocked,
  revision,
  parentCurrent,
  onPreviousOrder,
  onControllerProposal,
  controllerProposalAvailable,
}: {
  source: NativeArchiveSource;
  opened: Data | null;
  receipt: Data;
  visible: boolean;
  blocked: boolean;
  revision: string;
  parentCurrent: () => boolean;
  onPreviousOrder: (request: Data) => boolean;
  onControllerProposal?: (proposal: Data) => boolean;
  controllerProposalAvailable?: boolean;
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
  const problem = orderMatchParentProblem(receipt);
  const diagramMatches =
    !!opened &&
    opened.selection?.diagram_ref === receipt.intent?.order_edit?.diagram_ref;
  async function compare() {
    const key = actual.current.owner,
      ticket = epoch.current;
    if (
      !opened ||
      !diagramMatches ||
      problem ||
      active.current ||
      !current(key, ticket)
    )
      return;
    const operation = {};
    active.current = operation;
    setPending(true);
    setError("");
    setDocument(null);
    try {
      if (!(await orderMatchParent(receipt)))
        throw Error(
          "The original receipt lacks a supported verified execution-order proof.",
        );
      if (!current(key, ticket)) return;
      const reply = await apiJsonDocument(orderResultMatchBase, {
        receipt_id: receipt.intent.id,
        capture_id: source.capture_id,
        snapshot_sha256: source.snapshot_sha256,
      });
      if (!current(key, ticket)) return;
      if (
        !(await orderResultMatchEvidence(reply.data, source, opened, receipt))
      )
        throw Error(
          "The comparison does not match this retained source, diagram and original order result.",
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
  return (
    <details
      aria-label="Retained execution-order result comparison"
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
        Compare retained execution-order result
      </summary>
      <p>
        Compare this historical retained source with the reconstructed original
        order result. This reads local evidence and sends no controller request.
      </p>
      {problem && <p>{problem}</p>}
      {!diagramMatches && (
        <p>
          Inspect the receipt's original native diagram (
          {receipt.intent?.order_edit?.diagram_ref || "not recorded"}) in the
          retained source before comparing.
        </p>
      )}
      <button
        disabled={
          !visible || blocked || pending || !!problem || !diagramMatches
        }
        onClick={() => void compare()}
      >
        Compare retained source with recorded execution order
      </button>
      {pending && (
        <>
          <p role="status">Comparing retained execution-order evidence…</p>
          <button onClick={retire}>Cancel order result comparison</button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Retained execution-order comparison result">
          <p role="status">
            {shown.data.state === "application-and-order-match"
              ? "Retained application and execution order match the recorded result."
              : "Retained source differs from the recorded execution-order result."}
          </p>
          <p>
            Historical proof: {shown.data.verified_proof.kind} ·{" "}
            {shown.data.verified_proof.time}. Current controller state is
            unverified.
          </p>
          <p>
            Recorded route: {shown.data.recorded_target.address}
            {shown.data.recorded_target.router
              ? ` via ${shown.data.recorded_target.router} / DNET ${shown.data.recorded_target.dnet}`
              : ""}
            . Retained source: {source.target.address}
            {source.target.router
              ? ` via ${source.target.router} / DNET ${source.target.dnet}`
              : ""}{" "}
            · {shown.data.source.captured_at}.
          </p>
          <div className="change-ledger-table">
            <table aria-label="Recorded and retained execution order">
              <thead>
                <tr>
                  <th>Position</th>
                  <th>Recorded result</th>
                  <th>Retained effective order</th>
                </tr>
              </thead>
              <tbody>
                {Array.from(
                  {
                    length: Math.max(
                      shown.data.expected_selection.original_order.length,
                      shown.data.source.selection.original_order.length,
                    ),
                  },
                  (_, position) => {
                    const expected = shown.data.expected_selection,
                      current = shown.data.source.selection;
                    const before =
                        expected.members[expected.original_order[position]],
                      after = current.members[current.original_order[position]];
                    return (
                      <tr key={position}>
                        <td>{position + 1}</td>
                        <td>
                          {before
                            ? `${before.index}: ${before.name || before.ref}`
                            : "Not recorded"}
                        </td>
                        <td>
                          {after
                            ? `${after.index}: ${after.name || after.ref}`
                            : "Not recorded"}
                        </td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          </div>
          <div className="change-ledger-table">
            <table aria-label="Retained order comparison checks">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Comparison</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(shown.data.comparisons).map(
                  ([key, matches]) => (
                    <tr key={key}>
                      <td>{key.replaceAll("_", " ")}</td>
                      <td>{matches ? "Matches" : "Different"}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
          <button
            onClick={() => {
              if (current(shown.owner, shown.epoch))
                saveBlob(
                  shown.blob,
                  "native-execution-order-result-comparison.json",
                );
            }}
          >
            Save exact execution-order comparison
          </button>
          <NativeOrderRecoveryProposal
            source={source}
            opened={opened}
            receipt={receipt}
            comparison={shown.data}
            visible={visible}
            blocked={blocked || pending}
            revision={owner}
            parentCurrent={() => current(shown.owner, shown.epoch)}
            onPreviousOrder={onPreviousOrder}
            onControllerProposal={onControllerProposal}
            controllerProposalAvailable={controllerProposalAvailable}
          />
          <p>
            Original archive encoding and saved-directory layout are separate
            from expanded/effective application equivalence. This evidence
            creates no recovery proposal, review or transfer authority.
          </p>
        </section>
      )}
    </details>
  );
}
