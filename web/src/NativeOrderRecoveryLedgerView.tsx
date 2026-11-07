import { saveBlob } from "./api";
import { recordedOrderRecovery } from "./nativeOrderRecoveryLedger";
type Data = Record<string, any>;
export function OrderRecoverySummary({ row }: { row: Data }) {
  if (row.native_order_recovery === undefined) return null;
  const data = recordedOrderRecovery(row);
  return (
    <span>
      {data
        ? `Previous execution-order recovery · parent ${data.origin.parent_receipt_id}`
        : "Execution-order recovery metadata unavailable"}
    </span>
  );
}
export function NativeOrderRecoveryLedgerView({
  row,
  onParent,
}: {
  row: Data;
  onParent: (id: string) => void;
}) {
  const data = recordedOrderRecovery(row);
  return (
    <section aria-label="Recorded previous execution-order recovery">
      <h4>
        {data
          ? "Recorded previous execution-order recovery"
          : "Execution-order recovery metadata unavailable"}
      </h4>
      {data ? (
        <>
          <dl>
            <dt>Original receipt</dt>
            <dd>{data.origin.parent_receipt_id}</dd>
            <dt>Recorded original proof</dt>
            <dd>
              {data.origin.verified_proof.kind} ·{" "}
              {data.origin.verified_proof.time}
            </dd>
            <dt>Reviewed native source</dt>
            <dd>{data.review_capture_id}</dd>
            <dt>Recorded diagram</dt>
            <dd>{data.diagram_ref}</dd>
          </dl>
          <div className="change-ledger-table">
            <table aria-label="Recorded previous-order members">
              <thead>
                <tr>
                  <th>Position</th>
                  <th>Before member index</th>
                  <th>After member index</th>
                  <th>Unsigned bytes</th>
                </tr>
              </thead>
              <tbody>
                {data.before.map((value: number, index: number) => (
                  <tr key={index}>
                    <td>{index + 1}</td>
                    <td>{value}</td>
                    <td>{data.after[index]}</td>
                    <td>{data.payload_widths[index]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>{data.scope}</p>
          <button onClick={() => onParent(data.origin.parent_receipt_id)}>
            Find original execution-order receipt
          </button>
          <button
            onClick={() =>
              saveBlob(
                new Blob([JSON.stringify(data, null, 2)], {
                  type: "application/json",
                }),
                "recorded-previous-execution-order-lineage.json",
              )
            }
          >
            Save recorded execution-order lineage
          </button>
        </>
      ) : (
        <p>
          Inspect the original receipt evidence. This row grants no field
          authority.
        </p>
      )}
    </section>
  );
}
