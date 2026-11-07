import { useEffect, useRef, useState } from "react";
import { apiBlobDocument, saveBlob } from "./api";
import {
  batchEvidenceBase,
  batchEvidenceDocument,
  batchEvidenceHeader,
} from "./nativeDefaultBatchEvidenceContract";
type Data = Record<string, any>;
export function NativeDefaultBatchEvidenceDownload({
  report,
  current,
}: {
  report: Data;
  current: () => boolean;
}) {
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const alive = useRef(true),
    actual = useRef({ report, current }),
    active = useRef<object | null>(null);
  if (actual.current.report !== report) active.current = null;
  actual.current = { report, current };
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      active.current = null;
    };
  }, []);
  useEffect(() => {
    setPending(false);
    setError("");
  }, [report]);
  const owns = (source: Data) =>
    alive.current &&
    actual.current.report === source &&
    actual.current.current();
  async function save() {
    if (active.current || !owns(report)) return;
    const operation = {};
    active.current = operation;
    setPending(true);
    setError("");
    try {
      const reply = await apiBlobDocument(batchEvidenceBase, {
        receipt_id: report.receipt_id,
        capture_id: report.source.capture_id,
        snapshot_sha256: report.source.snapshot_sha256,
        comparison_sha256: report.evidence_sha256,
      });
      if (!owns(report)) return;
      if (
        !(await batchEvidenceDocument(
          reply.blob,
          reply.headers.get(batchEvidenceHeader),
          report,
        ))
      )
        throw Error(
          "The evidence bundle does not match this comparison and retained source.",
        );
      if (owns(report))
        saveBlob(reply.blob, `native-batch-evidence-${report.receipt_id}.zip`);
    } catch (e) {
      if (owns(report)) setError(String(e));
    } finally {
      if (active.current === operation) {
        active.current = null;
        if (alive.current) setPending(false);
      }
    }
  }
  return (
    <div aria-label="Retained comparison evidence export">
      <button disabled={pending || !current()} onClick={() => void save()}>
        {pending
          ? "Saving comparison evidence…"
          : "Save comparison evidence bundle"}
      </button>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
