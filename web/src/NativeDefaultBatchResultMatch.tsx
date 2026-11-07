import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, saveBlob } from "./api";
import { NativeDefaultBatchEvidenceDownload } from "./NativeDefaultBatchEvidenceDownload";
import {
  batchResultMatchBase,
  batchResultMatchParent,
  batchResultParentProblem,
  batchResultMatchEvidence,
  batchMatchValue,
} from "./nativeDefaultBatchResultMatchContract";
type Data = Record<string, any>;
type Document = { owner: string; epoch: number; data: Data; blob: Blob };
const text = (v: unknown) => (Object.is(v, -0) ? "-0" : String(v));
export function NativeDefaultBatchResultMatch({
  source,
  opened,
  receipt,
  visible,
  blocked,
  revision,
  parentCurrent,
}: {
  source: Data;
  opened: Data | null;
  receipt: Data;
  visible: boolean;
  blocked: boolean;
  revision: number;
  parentCurrent: () => boolean;
}) {
  const [document, setDocument] = useState<Document | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const receiptVersion = useRef({ data: receipt, revision: 0 });
  if (receiptVersion.current.data !== receipt)
    receiptVersion.current = {
      data: receipt,
      revision: receiptVersion.current.revision + 1,
    };
  const owner = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    opened?.capture_id,
    opened?.snapshot_sha256,
    receipt.intent?.id,
    receipt.intent?.evidence_sha256,
    receiptVersion.current.revision,
    visible,
    blocked,
    revision,
  ]);
  const actual = useRef({ owner, visible, blocked, parentCurrent }),
    epoch = useRef(0),
    alive = useRef(true),
    active = useRef<object | null>(null),
    documentNow = useRef(document);
  documentNow.current = document;
  if (actual.current.owner !== owner) {
    epoch.current++;
    active.current = null;
  }
  actual.current = { owner, visible, blocked, parentCurrent };
  const rendered = epoch.current;
  const current = (key: string, ticket: number) =>
    alive.current &&
    actual.current.owner === key &&
    epoch.current === ticket &&
    actual.current.visible &&
    !actual.current.blocked &&
    actual.current.parentCurrent() &&
    window.document.visibilityState !== "hidden";
  useEffect(() => {
    alive.current = true;
    const retire = () => {
      epoch.current++;
      active.current = null;
      setPending(false);
      setDocument(null);
      setError("");
    };
    window.addEventListener("pagehide", retire);
    window.document.addEventListener("visibilitychange", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      active.current = null;
      window.removeEventListener("pagehide", retire);
      window.document.removeEventListener("visibilitychange", retire);
    };
  }, []);
  useEffect(() => {
    setPending(false);
    setDocument(null);
    setError("");
  }, [owner]);
  const problem = batchResultParentProblem(receipt);
  const shown =
    document && current(document.owner, document.epoch) ? document : null;
  async function compare() {
    if (!opened || problem || active.current || !current(owner, rendered))
      return;
    const operation = {};
    active.current = operation;
    setPending(true);
    setDocument(null);
    setError("");
    try {
      if (!(await batchResultMatchParent(receipt)))
        throw Error(
          "The original batch receipt is unsupported or inconsistent.",
        );
      if (!current(owner, rendered)) return;
      const response = await apiJsonDocument(batchResultMatchBase, {
        receipt_id: receipt.intent.id,
        capture_id: opened.capture_id,
        snapshot_sha256: opened.snapshot_sha256,
      });
      if (!current(owner, rendered)) return;
      if (
        !(await batchResultMatchEvidence(
          response.data,
          source,
          opened,
          receipt,
        ))
      )
        throw Error(
          "The comparison does not match this retained source and recorded batch result.",
        );
      if (current(owner, rendered))
        setDocument({
          owner,
          epoch: rendered,
          data: response.data,
          blob: response.blob,
        });
    } catch (e) {
      if (current(owner, rendered)) setError(String(e));
    } finally {
      if (active.current === operation) {
        active.current = null;
        if (alive.current) setPending(false);
      }
    }
  }
  return (
    <section aria-label="Retained source result comparison">
      <h4>Compare retained source with batch result</h4>
      <p>
        Local comparison only. The retained backup and recorded verification do
        not establish current controller state.
      </p>
      {problem && <p>{problem}</p>}
      {!opened && <p>Open a retained current backup before comparing.</p>}
      <button
        disabled={!opened || !!problem || pending || blocked || !visible}
        onClick={() => void compare()}
      >
        {pending
          ? "Comparing retained source…"
          : "Compare retained source with recorded result"}
      </button>
      {error && <p role="alert">{error}</p>}
      {shown && (
        <>
          <p role="status">
            {shown.data.state === "application-and-values-match"
              ? "Retained application and effective values match the recorded batch result."
              : "The retained source differs from the recorded batch result. Inspect the separate comparisons below."}
          </p>
          <dl>
            {Object.entries({
              route_matches: "Captured route",
              identity_matches: "Captured identity",
              expanded_application_matches: "Expanded program",
              effective_application_matches: "Effective saved values",
              selected_values_match: "Selected defaults",
              original_saved_directory_matches: "Original saved directory",
            }).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{shown.data.comparisons[key] ? "Matches" : "Differs"}</dd>
              </div>
            ))}
          </dl>
          <div
            className="application-operation-table"
            role="region"
            aria-label="Recorded result comparison values viewport"
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
            <table aria-label="Recorded result comparison values">
              <thead>
                <tr>
                  <th>Default</th>
                  <th>Type</th>
                  <th>Recorded result</th>
                  <th>Retained effective value</th>
                  <th>Comparison</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.selected.map((row: Data) => (
                  <tr key={row.record_ref}>
                    <th scope="row">{row.record_ref}</th>
                    <td>{row.kind}</td>
                    <td>{text(batchMatchValue(row.kind, row.expected))}</td>
                    <td>
                      {row.current
                        ? `${row.current.kind !== row.kind ? row.current.kind + " · " : ""}${text(batchMatchValue(row.current.kind, row.current.value))}`
                        : "Unavailable"}
                    </td>
                    <td>{row.matches ? "Matches" : "Differs"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>{shown.data.scope}</p>
          <button
            onClick={() => {
              if (
                documentNow.current === shown &&
                current(shown.owner, shown.epoch)
              )
                saveBlob(shown.blob, "native-batch-result-comparison.json");
            }}
          >
            Save exact result comparison
          </button>
          <NativeDefaultBatchEvidenceDownload
            report={shown.data}
            current={() =>
              documentNow.current === shown && current(shown.owner, shown.epoch)
            }
          />
          <details>
            <summary>Recorded result comparison details</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
