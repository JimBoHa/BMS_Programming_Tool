import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, saveBlob } from "./api";
import { NativeDefaultBatchTransfer } from "./NativeDefaultBatchTransfer";
import type { ControllerContext } from "./workflow";
import { preparedBatchRecoveryEvidence } from "./nativeDefaultBatchRecoveryTransferContract";
import { batchRecoveryBase } from "./nativeDefaultBatchRecoveryContract";
type Data = Record<string, any>;
export function NativeDefaultBatchRecovery({
  source,
  opened,
  receipt,
  visible,
  blocked,
  revision,
  parentCurrent,
  controller,
  onOwnedBusy,
  onCaptured,
  onFieldFocus,
}: {
  source: Data;
  opened: Data | null;
  receipt: Data;
  visible: boolean;
  blocked: boolean;
  revision: number;
  parentCurrent: () => boolean;
  controller?: ControllerContext | null;
  onOwnedBusy: (value: boolean) => void;
  onCaptured: (id: string) => void;
  onFieldFocus: (value: boolean) => void;
}) {
  const [document, setDocument] = useState<{
    owner: string;
    epoch: number;
    data: Data;
    blob: Blob;
  } | null>(null);
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const [fieldBusy, setFieldBusy] = useState(false),
    fieldBusyNow = useRef(false);
  const [fieldOpen, setFieldOpen] = useState(false),
    fieldOpenNow = useRef(false),
    fieldGeneration = useRef(0);
  const [, redrawField] = useState(0);
  const fieldTicket = fieldGeneration.current;
  const receiptVersion = useRef({ data: receipt, revision: 0 });
  if (receiptVersion.current.data !== receipt) {
    receiptVersion.current = {
      data: receipt,
      revision: receiptVersion.current.revision + 1,
    };
  }
  const owner = JSON.stringify([
    opened?.capture_id,
    opened?.snapshot_sha256,
    receipt.intent?.id,
    receipt.intent?.evidence_sha256,
    receiptVersion.current.revision,
    revision,
    visible,
    blocked,
  ]);
  const actual = useRef({ owner, visible, blocked, parentCurrent }),
    epoch = useRef(0),
    alive = useRef(true);
  if (actual.current.owner !== owner) epoch.current++;
  actual.current = { owner, visible, blocked, parentCurrent };
  const rendered = epoch.current;
  const possible =
    (receipt.result
      ? receipt.result.may_have_applied
      : receipt.intent?.may_have_applied) === true;
  const verified =
    receipt.result?.status === "verified" ||
    (Array.isArray(receipt.events) &&
      receipt.events.some(
        (event: Data) =>
          event?.stage === "readback" && event.detail?.status === "verified",
      ));
  const parentProblem =
    receipt.pending !== false
      ? "Resolve the original batch outcome before preparing previous values."
      : !receipt.intent || !possible
        ? "This receipt records no possible batch restore. There are no transferred defaults to recover."
        : !verified
          ? "This receipt has no retained verified batch outcome. Read back the original transfer before preparing previous values."
          : null;
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
      setDocument(null);
      setPending(false);
      setError("");
    };
    window.addEventListener("pagehide", retire);
    window.document.addEventListener("visibilitychange", retire);
    return () => {
      alive.current = false;
      onFieldFocus(false);
      epoch.current++;
      window.removeEventListener("pagehide", retire);
      window.document.removeEventListener("visibilitychange", retire);
    };
  }, []);
  useEffect(() => {
    setPending(false);
    setDocument(null);
    setError("");
  }, [owner]);
  async function prepare() {
    if (
      !opened ||
      fieldBusyNow.current ||
      parentProblem !== null ||
      receipt.pending !== false ||
      pending ||
      !current(owner, rendered)
    )
      return;
    const ticket = ++epoch.current,
      key = owner;
    setPending(true);
    setDocument(null);
    setError("");
    try {
      const response = await apiJsonDocument(batchRecoveryBase, {
        receipt_id: receipt.intent.id,
        capture_id: opened.capture_id,
        snapshot_sha256: opened.snapshot_sha256,
      });
      if (!current(key, ticket)) return;
      if (
        !(await preparedBatchRecoveryEvidence(
          response.data as Data,
          opened,
          receipt,
        ))
      )
        throw new Error(
          "The previous-batch report differs from this retained source or verified receipt.",
        );
      if (current(key, ticket))
        setDocument({
          owner: key,
          epoch: ticket,
          data: response.data as Data,
          blob: response.blob,
        });
    } catch (problem) {
      if (current(key, ticket)) setError(String(problem));
    } finally {
      if (
        alive.current &&
        actual.current.owner === key &&
        epoch.current === ticket
      )
        setPending(false);
    }
  }
  const shown =
    document && current(document.owner, document.epoch) ? document : null;
  const value = (kind: string, v: Data) => {
    if (kind !== "real") return String(v.value);
    const view = new DataView(new ArrayBuffer(4));
    view.setUint32(0, Number.parseInt(v.bits, 16), false);
    const number = view.getFloat32(0, false);
    return Object.is(number, -0) ? "-0" : String(number);
  };
  return (
    <section aria-label="Previous typed batch defaults">
      <h4>Previous effective batch values</h4>
      <p>
        Prepare from this receipt and the opened retained backup. The
        application and saved directory must match the recorded outcome. Other
        current saved values stay current. This local check queries no
        controller and prepares no controller review.
      </p>
      {!opened && (
        <p>
          Inspect the retained typed defaults first. Read a current native
          backup separately when needed.
        </p>
      )}
      <button
        disabled={
          !opened ||
          parentProblem !== null ||
          pending ||
          blocked ||
          !visible ||
          fieldBusy
        }
        onClick={() => void prepare()}
      >
        Prepare previous batch defaults
      </button>
      {parentProblem && <p role="status">{parentProblem}</p>}
      {pending && <p role="status">Checking retained previous batch values…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <>
          <p role="status">
            {shown.data.already_recorded
              ? "Every previous value is already present in this retained source. No recovery proposal was created."
              : "Previous values have a source-bound local compilation. Open the recovery transfer task for a separate fresh controller review."}
          </p>
          <div
            className="application-operation-table"
            role="region"
            aria-label="Previous batch values table viewport"
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
            <table aria-label="Previous typed batch values">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Type</th>
                  <th>Previous effective value</th>
                  <th>Recorded result</th>
                  <th>Retained current value</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.origin.fields.map((f: Data) => (
                  <tr key={f.record_ref}>
                    <th scope="row">{f.record_ref}</th>
                    <td>{f.kind}</td>
                    <td>{value(f.kind, f.previous)}</td>
                    <td>{value(f.kind, f.recorded_after)}</td>
                    <td>{value(f.kind, f.current)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            onClick={() => {
              if (current(shown.owner, shown.epoch))
                saveBlob(shown.blob, "native-previous-batch-proposal.json");
            }}
          >
            Save exact previous batch proposal
          </button>
          <details>
            <summary>Previous batch proposal evidence</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
        </>
      )}
      <details open={fieldOpen} aria-label="Previous batch field workflow">
        <summary
          onClick={(event) => {
            event.preventDefault();
            if (fieldBusyNow.current || blocked) return;
            fieldGeneration.current++;
            fieldOpenNow.current = !fieldOpenNow.current;
            onFieldFocus(fieldOpenNow.current);
            setFieldOpen(fieldOpenNow.current);
            redrawField((value) => value + 1);
          }}
        >
          Transfer previous batch values to controller
        </summary>
        <NativeDefaultBatchTransfer
          source={source}
          opened={opened}
          proposal={shown?.data.proposal ?? null}
          controller={controller}
          visible={visible && fieldOpen}
          otherBusy={blocked || pending}
          revision={fieldTicket}
          parentCurrent={() =>
            current(owner, rendered) &&
            fieldOpenNow.current &&
            fieldGeneration.current === fieldTicket
          }
          onCaptured={onCaptured}
          recoveryMode
          onOwnedBusy={(value) => {
            fieldBusyNow.current = value;
            if (alive.current) setFieldBusy(value);
            onOwnedBusy(value);
          }}
          recoveryContext={
            shown?.data.proposal
              ? {
                  report: shown.data,
                  parent: receipt,
                  generation: shown.epoch,
                  current: () => current(shown.owner, shown.epoch),
                }
              : null
          }
        />
      </details>
    </section>
  );
}
