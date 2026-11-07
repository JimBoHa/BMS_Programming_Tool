import {
  recordedBatchRecovery,
  recordedBatchValue,
} from "./nativeDefaultBatchRecoveryLedger";
type Data = Record<string, any>;
const text = (v: unknown) => (Object.is(v, -0) ? "-0" : String(v));
export function NativeDefaultBatchRecoveryLedgerView({
  row,
  onParent,
}: {
  row: Data;
  onParent: (id: string) => void;
}) {
  const data = recordedBatchRecovery(row);
  return (
    <section aria-label="Recorded previous batch recovery">
      <h3>
        {data
          ? "Recorded previous batch recovery"
          : "Batch recovery metadata unavailable"}
      </h3>
      {data ? (
        <>
          <dl>
            <dt>Original batch receipt</dt>
            <dd>{data.origin.parent_receipt_id}</dd>
            <dt>Recorded original verification</dt>
            <dd>
              {data.origin.verified_proof.kind} ·{" "}
              {data.origin.verified_proof.time}
            </dd>
          </dl>
          <div
            className="change-ledger-table"
            role="region"
            aria-label="Recorded batch recovery values viewport"
            tabIndex={0}
            onKeyDown={(event) => {
              if (
                event.target !== event.currentTarget ||
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                !["ArrowLeft", "ArrowRight"].includes(event.key)
              )
                return;
              event.preventDefault();
              event.currentTarget.scrollBy({
                left: event.key === "ArrowRight" ? 80 : -80,
              });
            }}
          >
            <table aria-label="Recorded batch recovery values">
              <thead>
                <tr>
                  <th>Default</th>
                  <th>Type</th>
                  <th>Original previous</th>
                  <th>Original result</th>
                  <th>Retained at review</th>
                  <th>Recovery proposal</th>
                </tr>
              </thead>
              <tbody>
                {data.origin.fields.map((f: Data) => (
                  <tr key={f.record_ref}>
                    <th scope="row">{f.record_ref}</th>
                    <td>{f.kind}</td>
                    {[f.previous, f.recorded_after, f.current, f.previous].map(
                      (v, i) => (
                        <td key={i}>{text(recordedBatchValue(f.kind, v))}</td>
                      ),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>{data.scope}</p>
          <button onClick={() => onParent(data.origin.parent_receipt_id)}>
            Find original batch receipt
          </button>
          <details>
            <summary>Recorded batch recovery references</summary>
            <pre>{JSON.stringify(data, null, 2)}</pre>
          </details>
        </>
      ) : (
        <p>
          Inspect original evidence. Recorded lineage grants no controller or
          recovery authority.
        </p>
      )}
    </section>
  );
}
