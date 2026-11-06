import { recordedBinaryTerminalRecoveryRow } from "./nativeBinaryTerminalRecoveryLedger";

type Data = Record<string, any>;
export function BinaryTerminalRecoverySummary({ row }: { row: Data }) {
  if (row.native_binary_terminal_recovery === undefined) return null;
  const value = recordedBinaryTerminalRecoveryRow(row);
  return (
    <span>
      {value
        ? `Previous binary terminal recovery · parent ${value.origin.parent_receipt_id}`
        : "Binary recovery metadata unavailable"}
    </span>
  );
}
export function NativeBinaryTerminalRecoveryLedgerView({
  row,
  onParent,
}: {
  row: Data;
  onParent: (id: string) => void;
}) {
  const value = recordedBinaryTerminalRecoveryRow(row),
    o = value?.origin;
  return (
    <section aria-label="Recorded binary recovery lineage">
      <h4>
        {value
          ? "Recorded previous binary terminal transfer"
          : "Binary recovery metadata unavailable"}
      </h4>
      {value ? (
        <>
          <dl>
            <dt>Parent receipt</dt>
            <dd>{o.parent_receipt_id}</dd>
            <dt>Recorded input</dt>
            <dd>
              {o.object_id} · {o.record_ref}
            </dd>
            <dt>Recorded inverse</dt>
            <dd>
              UI IN{o.current_slot} to UI IN{o.proposal_slot}
            </dd>
            <dt>Historical parent verification</dt>
            <dd>
              {o.verified_proof.kind === "result"
                ? "Original result"
                : "Later readback event"}{" "}
              · {o.verified_proof.time}
            </dd>
          </dl>
          <p>{value.scope}</p>
          <button onClick={() => onParent(o.parent_receipt_id)}>
            Search recorded binary recovery parent receipt
          </button>
          <details>
            <summary>Recorded binary recovery references</summary>
            <pre>
              {JSON.stringify(
                { origin: o, origin_sha256: value.origin_sha256 },
                null,
                2,
              )}
            </pre>
          </details>
        </>
      ) : (
        <p>
          Inspect original evidence. Recorded parent/source availability and new
          transfer authority are not established here.
        </p>
      )}
    </section>
  );
}
