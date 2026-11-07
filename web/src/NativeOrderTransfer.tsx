import { randomUUID } from "./browserCrypto";
import { useContext, useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, apiKeepalive, saveBlob } from "./api";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeOrderResultMatch } from "./NativeOrderResultMatch";
import { orderMatchParent } from "./nativeOrderResultMatchContract";
import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey, type ControllerContext } from "./workflow";
import { connectionSame } from "./nativeConnectionContract";
import {
  orderTransferBase,
  orderTransferProfile,
  orderTransferProposal,
  orderTransferReceipt,
  orderTransferReview,
  orderTransferTarget,
} from "./nativeOrderTransferContract";

type Data = Record<string, any>;
type Document = { data: Data; blob: Blob };
type Kind = "credentials" | "capture" | "preview" | "apply" | "readback";
type Operation = { id: string; kind: Kind; owner: string; epoch: number };
const base = "/bacnet/controller/native-application";
const targetOf = (c: ControllerContext) => ({
  address: c.address,
  device: c.device,
  router: c.router || null,
  dnet: c.dnet ?? null,
});
const targetLabel = (c: Data) =>
  `${c.device} · ${c.address}${c.router ? ` via ${c.router} / DNET ${c.dnet}` : ""}`;
function interfaceConfiguration(value?: string) {
  try {
    return JSON.parse(value || "null");
  } catch {
    return null;
  }
}

export function NativeOrderTransfer({
  source,
  proposal,
  opened,
  controller,
  visible,
  otherBusy,
  onOwnedBusy,
  parentGeneration,
  parentCurrent,
  onPreviousOrder,
}: {
  source: NativeArchiveSource;
  proposal: Data | null;
  opened: Data | null;
  controller?: ControllerContext | null;
  visible: boolean;
  otherBusy: boolean;
  onOwnedBusy: (value: boolean, kind: Kind) => void;
  parentGeneration: string;
  parentCurrent: () => boolean;
  onPreviousOrder: (request: Data) => boolean;
}) {
  const context = useContext(NativeBooleanTransferContext);
  const busyOwner = useRef("execution-order-" + randomUUID());
  const [busy, setBusy] = useState(false),
    [status, setStatus] = useState<Data | null>(null);
  const [backup, setBackup] = useState(""),
    [restore, setRestore] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [interruption, setInterruption] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [plan, setPlan] = useState<
    (Document & { owner: string; epoch: number }) | null
  >(null);
  const [receipt, setReceipt] = useState<Document | null>(null),
    [chosenReceipt, setChosenReceipt] = useState("");
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [uncertainty, setUncertainty] = useState<{
    target: Data;
    operationId: string;
    receiptId?: string;
    text: string;
  } | null>(null);
  const owner = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    proposal,
    opened?.effective_sha256,
    visible,
    otherBusy,
    parentGeneration,
    context?.workspaceGeneration,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
      controller.ownedCommands,
    ],
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true);
  const active = useRef<Operation | null>(null),
    reviewId = useRef<string | null>(null);
  const statusTicket = useRef(0),
    receiptTicket = useRef(0),
    receiptNow = useRef(receipt);
  receiptNow.current = receipt;
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const current = (key: string, ticket: number) =>
    alive.current &&
    ownerNow.current === key &&
    epoch.current === ticket &&
    parentCurrent() &&
    (context?.workspaceCurrent?.() ?? true) &&
    document.visibilityState !== "hidden";
  const renderedEpoch = epoch.current;
  const shown = plan && current(plan.owner, plan.epoch) ? plan : null;
  const fresh = !!shown && now < Date.parse(shown.data.expires_at);
  const configuration = interfaceConfiguration(controller?.interfaceKey);
  const connected =
    !!controller?.interfaceOpen &&
    controller.ownedCommands === 0 &&
    !!configuration?.local_address &&
    !configuration.transport &&
    !configuration.bbmd_address;
  const sourceMatches =
    !!controller && orderTransferTarget(source.target, controller);
  const available =
    status?.execution_order_transfer_profile === orderTransferProfile;
  const engineeringPending =
    Array.isArray(status?.receipts) &&
    status.receipts.some((row: Data) => row.pending === true);
  const locked = busy || otherBusy;
  const canReview =
    parentCurrent() &&
    (context?.workspaceCurrent?.() ?? true) &&
    document.visibilityState !== "hidden" &&
    visible &&
    connected &&
    available &&
    status?.credentials_configured === true &&
    sourceMatches &&
    !!opened &&
    !!proposal &&
    orderTransferProposal(proposal) &&
    !engineeringPending &&
    !locked;
  const observed = receipt?.data.latest_readback || receipt?.data.result;
  const intent = receipt?.data.intent;
  const receiptTarget = intent
    ? { ...intent.target, device: intent.identity.device }
    : null;
  const receiptMatches =
    !!controller &&
    !!intent &&
    orderTransferTarget(receiptTarget, controller) &&
    connectionSame(intent.connector_config, configuration);
  const completed =
    observed?.status === "verified" ||
    observed?.status === "recovered_original";

  function cancelOwned() {
    const ids = new Set([
      reviewId.current,
      active.current?.kind !== "credentials" ? active.current?.id : null,
    ]);
    for (const id of ids)
      if (id)
        void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
          () => {},
        );
    reviewId.current = null;
  }
  function cancelReview() {
    if (reviewId.current)
      void apiKeepalive(base + "/cancel", {
        operation_id: reviewId.current,
      }).catch(() => {});
    reviewId.current = null;
    setPlan(null);
    setConfirmed(false);
    setInterruption(false);
  }
  function release(operation: Operation) {
    if (active.current !== operation) return;
    active.current = null;
    if (alive.current) setBusy(false);
    onOwnedBusy(false, operation.kind);
    context?.onBusy(busyOwner.current, false);
  }
  function retire() {
    epoch.current++;
    setPlan(null);
    setConfirmed(false);
    setInterruption(false);
    cancelOwned();
  }
  async function refresh() {
    const request = ++statusTicket.current,
      key = ownerNow.current,
      generation = epoch.current;
    const data = await api(base + "/status");
    if (request === statusTicket.current && current(key, generation))
      setStatus(data);
  }
  useEffect(() => {
    alive.current = true;
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      statusTicket.current++;
      receiptTicket.current++;
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
      cancelOwned();
      if (active.current) release(active.current);
    };
  }, []);
  useEffect(() => {
    cancelOwned();
    setPlan(null);
    setConfirmed(false);
    setInterruption(false);
    setBackup("");
    setRestore("");
    setError("");
    setStatus(null);
    if (
      !active.current ||
      !["apply", "readback"].includes(active.current.kind)
    ) {
      receiptTicket.current++;
      setReceiptLoading(false);
    }
    const key = ownerNow.current,
      generation = epoch.current;
    if (visible)
      void refresh().catch((failure) => {
        if (current(key, generation)) setError(String(failure));
      });
  }, [owner]);
  useEffect(() => {
    if (!shown) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [shown]);

  function retain(document: Document) {
    setReceipt(document);
    const i = document.data.intent,
      observation = document.data.latest_readback || document.data.result;
    if (
      i &&
      document.data.pending === false &&
      ["verified", "recovered_original", "not_sent"].includes(
        observation?.status,
      )
    ) {
      setUncertainty((old) =>
        old &&
        (old.receiptId
          ? old.receiptId === i.id
          : old.operationId === i.operation_id)
          ? null
          : old,
      );
    }
  }
  async function run(kind: Kind) {
    if (
      !visible ||
      active.current ||
      otherBusy ||
      !current(owner, renderedEpoch)
    )
      return;
    if (kind !== "credentials" && (!connected || !controller || !available))
      return;
    if ((kind === "preview" || kind === "apply") && !canReview) return;
    if (
      kind === "apply" &&
      (!shown ||
        !fresh ||
        !confirmed ||
        !interruption ||
        !current(shown.owner, shown.epoch))
    )
      return;
    if (kind === "readback" && (!receiptMatches || !receipt?.data.pending))
      return;
    const selectedPlan = shown,
      selectedReceipt = receipt;
    const operation: Operation = {
      id: "execution-order-" + randomUUID(),
      kind,
      owner: ownerNow.current,
      epoch: epoch.current,
    };
    const originalTarget = controller ? targetOf(controller) : source.target;
    active.current = operation;
    setBusy(true);
    onOwnedBusy(true, kind);
    context?.onBusy(busyOwner.current, true);
    setError("");
    const recordTicket =
      kind === "apply" || kind === "readback" ? ++receiptTicket.current : null;
    try {
      if (kind === "credentials") {
        cancelReview();
        await api(base + "/credentials", { backup, restore });
        if (current(operation.owner, operation.epoch)) {
          setBackup("");
          setRestore("");
        }
      } else if (kind === "capture") {
        cancelReview();
        const data = await api(base + "/capture", {
          ...targetOf(controller!),
          operation_id: operation.id,
        });
        if (
          !/^[a-f0-9]{32}$/.test(data.id || "") ||
          data.source_identity_matches !== true ||
          !orderTransferTarget(
            { ...data.target, device: data.device },
            controller!,
          )
        ) {
          throw new Error(
            "The captured application does not match this selected controller. Retain its evidence and capture again.",
          );
        }
        if (current(operation.owner, operation.epoch))
          context?.onCaptured(data.id);
      } else if (kind === "preview") {
        cancelReview();
        reviewId.current = operation.id;
        const document = await apiJsonDocument(orderTransferBase + "/preview", {
          ...targetOf(controller!),
          ...proposal!,
          operation_id: operation.id,
        });
        if (
          !(await orderTransferReview(
            document.data,
            source,
            proposal!,
            opened!,
            controller!,
          ))
        ) {
          throw new Error(
            "The execution-order review does not match this controller, source and proposed permutation.",
          );
        }
        if (current(operation.owner, operation.epoch)) {
          setPlan({
            ...document,
            owner: operation.owner,
            epoch: operation.epoch,
          });
          setNow(Date.now());
        } else
          void apiKeepalive(base + "/cancel", {
            operation_id: operation.id,
          }).catch(() => {});
      } else {
        if (kind === "apply") {
          setPlan(null);
          reviewId.current = null;
          setConfirmed(false);
          setInterruption(false);
        }
        const document = await apiJsonDocument(
          kind === "apply" ? orderTransferBase + "/apply" : base + "/readback",
          kind === "apply"
            ? {
                operation_id: operation.id,
                token: selectedPlan!.data.token,
                review_sha256: selectedPlan!.data.review_sha256,
                order_change_confirmed: confirmed,
                application_transfer_confirmed: interruption,
              }
            : {
                operation_id: operation.id,
                receipt_id: selectedReceipt!.data.intent.id,
              },
        );
        if (
          (kind === "apply" &&
            document.data.intent &&
            document.data.intent.operation_id !== operation.id) ||
          !(await orderTransferReceipt(
            document.data,
            kind === "apply"
              ? selectedPlan!.data
              : selectedReceipt!.data.intent,
          ))
        ) {
          throw new Error(
            "The returned execution-order receipt has inconsistent target, compilation or preservation evidence.",
          );
        }
        if (alive.current && recordTicket === receiptTicket.current)
          retain(document);
      }
    } catch (failure) {
      if (kind === "preview") {
        void apiKeepalive(base + "/cancel", {
          operation_id: operation.id,
        }).catch(() => {});
        if (reviewId.current === operation.id) reviewId.current = null;
      }
      if (alive.current && (kind === "apply" || kind === "readback")) {
        setUncertainty({
          target: originalTarget,
          operationId: operation.id,
          ...(kind === "readback"
            ? { receiptId: selectedReceipt!.data.intent.id }
            : {}),
          text:
            String(failure) +
            " Outcome is unconfirmed. Load retained receipts before another transfer.",
        });
      }
      if (current(operation.owner, operation.epoch)) setError(String(failure));
    } finally {
      release(operation);
      if (alive.current && visible) void refresh().catch(() => {});
    }
  }
  async function loadReceipt() {
    if (!visible || !/^[a-f0-9]{32}$/.test(chosenReceipt)) return;
    const request = ++receiptTicket.current,
      key = ownerNow.current,
      generation = epoch.current;
    setReceiptLoading(true);
    setError("");
    try {
      const document = await apiJsonDocument(
        base + "/receipts/" + chosenReceipt,
      );
      if (
        (!(await orderTransferReceipt(document.data)) && !(await orderMatchParent(document.data))) ||
        document.data.intent?.id !== chosenReceipt
      ) {
        throw new Error(
          "This receipt does not contain a supported execution-order operation. Inspect its original evidence in History.",
        );
      }
      if (request === receiptTicket.current && current(key, generation))
        retain(document);
    } catch (failure) {
      if (request === receiptTicket.current && current(key, generation))
        setError(String(failure));
    } finally {
      if (alive.current && request === receiptTicket.current)
        setReceiptLoading(false);
    }
  }
  const records: Data[] = Array.isArray(status?.receipts)
    ? status!.receipts.filter(
        (row: Data) =>
          row.change_kind === "execution-order" &&
          row.operation_profile === orderTransferProfile,
      )
    : [];
  return (
    <section
      className="native-compiler-source native-default-transfer"
      aria-label="Native execution-order controller transfer"
    >
      <h3>Controller transfer</h3>
      <p>
        {controller
          ? `Selected controller: ${controller.name} · ${targetLabel(controller)}.`
          : "Open and verify a controller before reviewing a connected transfer. Local file work remains available."}
      </p>
      <p>
        Reorder existing members while preserving recorded wire timing. Capture
        and readback enter and end backup mode. Apply restores the native
        application and can interrupt control.
      </p>
      {!sourceMatches && (
        <p>
          This retained source belongs to another controller. Capture the
          selected controller before transfer review.
        </p>
      )}
      {!connected && controller && (
        <p>
          Execution-order transfer requires an open plain BACnet/IPv4 interface
          and no owned override. The selected controller remains visible above.
        </p>
      )}
      {status && !available && (
        <p>
          The installed server does not advertise the execution-order transfer
          profile. Keep the local copy and its evidence.
        </p>
      )}
      {engineeringPending && (
        <p>
          Resolve the retained native transfer before starting another
          engineering operation. Load its original receipt and select its
          controller and interface for readback.
        </p>
      )}
      <details>
        <summary>Native transfer credentials</summary>
        <p>
          {status?.credentials_configured
            ? "Native credentials configured on this machine."
            : "Configure native family credentials before capture or review."}
        </p>
        <label>
          Execution-order backup credential
          <input
            type="password"
            autoComplete="off"
            value={backup}
            disabled={locked || !visible}
            onChange={(e) => setBackup(e.target.value)}
          />
        </label>
        <label>
          Execution-order restore credential
          <input
            type="password"
            autoComplete="off"
            value={restore}
            disabled={locked || !visible}
            onChange={(e) => setRestore(e.target.value)}
          />
        </label>
        <button
          disabled={locked || !visible || !backup || !restore}
          onClick={() => void run("credentials")}
        >
          Save execution-order transfer credentials
        </button>
      </details>
      <div className="button-row">
        <button
          disabled={
            locked ||
            !visible ||
            !connected ||
            !available ||
            engineeringPending ||
            !status?.credentials_configured
          }
          onClick={() => void run("capture")}
        >
          Capture selected controller application
        </button>
        <button
          disabled={!visible}
          onClick={() =>
            void refresh().catch((failure) => setError(String(failure)))
          }
        >
          Refresh execution-order transfer status
        </button>
        {busy && (
          <button onClick={retire}>Cancel execution-order operation</button>
        )}
      </div>
      {busy && (
        <p role="status">
          {active.current?.kind === "apply"
            ? "Applying reviewed execution order"
            : active.current?.kind === "readback"
              ? "Reading back the original transfer"
              : "Preparing execution-order operation"}
          {status?.active &&
          active.current &&
          status.active.operation_id === active.current.id
            ? ` · ${status.active.phase}`
            : ""}
          …
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {uncertainty && (
        <p role="alert">
          Unconfirmed operation for {targetLabel(uncertainty.target)}.{" "}
          {uncertainty.text}
        </p>
      )}
      {shown && (
        <section aria-label="Reviewed controller execution order">
          <p>
            Review: {proposal!.diagram_ref}. Proposed member order:{" "}
            {proposal!.proposed_order.map((v: number) => v + 1).join(" → ")}.
            Device identity stays unchanged.
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={locked || !visible || !fresh}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I confirm this execution order and the retained wire timing
            relationships.
          </label>
          <label>
            <input
              type="checkbox"
              checked={interruption}
              disabled={locked || !visible || !fresh}
              onChange={(e) => setInterruption(e.target.checked)}
            />
            I confirm the application transfer and possible control
            interruption.
          </label>
          {!fresh && <p>Review expired. Review this execution order again.</p>}
          <button
            disabled={locked || !visible}
            onClick={() => {
              if (shown && current(shown.owner, shown.epoch))
                saveBlob(shown.blob, "native-execution-order-review.json");
            }}
          >
            Save execution-order transfer review
          </button>
          <details>
            <summary>Execution-order transfer review details</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
        </section>
      )}
      {receipt && (
        <section aria-label="Execution-order transfer result">
          <NativeOrderResultMatch
            source={source}
            opened={opened}
            receipt={receipt.data}
            visible={visible}
            blocked={locked}
            revision={owner}
            onPreviousOrder={onPreviousOrder}
            parentCurrent={() => current(owner, renderedEpoch)}
          />
          {receiptTarget && (
            <p>Original transfer target: {targetLabel(receiptTarget)}.</p>
          )}
          <p role="status">
            {observed?.status === "verified"
              ? "Execution order verified in the complete native readback."
              : observed?.status === "recovered_original"
                ? "Original application recovered. The proposed execution order is not verified."
                : observed?.status === "not_sent"
                  ? "Restore not sent. Backup-state commands may have occurred."
                  : "Execution-order outcome uncertain. Retain the original receipt and read back before another transfer."}
          </p>
          {intent && !receiptMatches && (
            <p>
              This receipt belongs to its original controller and interface.
              Readback is unavailable for the current selection.
            </p>
          )}
          {observed?.error && <p>{String(observed.error)}</p>}
          {Array.isArray(observed?.errors) &&
            observed.errors.map((text: string, index: number) => (
              <p key={index}>{text}</p>
            ))}
          <button
            disabled={!visible}
            onClick={() => {
              const selected = receiptNow.current;
              if (visible && selected === receipt)
                saveBlob(receipt.blob, "native-execution-order-receipt.json");
            }}
          >
            Save execution-order transfer receipt
          </button>
          <details>
            <summary>Execution-order transfer receipt details</summary>
            <pre>{JSON.stringify(receipt.data, null, 2)}</pre>
          </details>
        </section>
      )}
      <div className="button-row">
        {receipt?.data.pending && receiptMatches ? (
          <button
            className={visible ? "primary" : undefined}
            disabled={locked || !visible || !connected || !receiptMatches}
            onClick={() => void run("readback")}
          >
            Read back execution order
          </button>
        ) : completed &&
          connectionSame(intent?.order_edit, proposal) &&
          /^[a-f0-9]{32}$/.test(observed?.verification_capture_id || "") ? (
          <button
            className={visible ? "primary" : undefined}
            disabled={locked || !visible}
            onClick={() =>
              context?.onCaptured(observed.verification_capture_id)
            }
          >
            Open verified application snapshot
          </button>
        ) : fresh ? (
          <button
            className={visible ? "primary" : undefined}
            disabled={!canReview || !confirmed || !interruption}
            onClick={() => void run("apply")}
          >
            Apply execution order to controller
          </button>
        ) : (
          <button
            className={visible ? "primary" : undefined}
            disabled={!canReview}
            onClick={() => void run("preview")}
          >
            Review execution-order transfer
          </button>
        )}
        {shown && (
          <button disabled={locked || !visible} onClick={retire}>
            Discard execution-order transfer review
          </button>
        )}
      </div>
      <details>
        <summary>Retained execution-order receipts</summary>
        <label>
          Execution-order receipt
          <select
            aria-label="Execution-order receipt"
            value={chosenReceipt}
            disabled={locked || !visible || receiptLoading}
            onChange={(e) => setChosenReceipt(e.target.value)}
          >
            <option value="">Choose a retained transfer</option>
            {records.map((row) => (
              <option key={row.id} value={row.id}>
                {row.created_at} · device,{row.old_instance} ·{" "}
                {row.target.address}
                {row.target.router
                  ? ` via ${row.target.router} / ${row.target.dnet}`
                  : ""}{" "}
                · {row.status}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={locked || !visible || receiptLoading || !chosenReceipt}
          onClick={() => void loadReceipt()}
        >
          Load execution-order receipt
        </button>
        <p>
          Loaded receipts are recorded evidence. Loading prepares no review,
          restore or readback. Changes and History retain the original records.
        </p>
      </details>
    </section>
  );
}
