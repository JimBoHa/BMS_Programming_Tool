import { useContext, useEffect, useRef, useState } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import { randomUUID } from "./browserCrypto";
import "./native-snapshot-restore.css";
import { sha256Blob } from "./activityContracts";
import { connectionSame } from "./nativeConnectionContract";
import { controllerKey, type ControllerContext } from "./workflow";
import {
  snapshotRestoreBase as base,
  snapshotRestoreProfile,
  snapshotRestoreSource,
  snapshotRestoreReview,
  snapshotRestoreReceipt,
  snapshotRestoreTarget,
  restoreID,
  type SnapshotRestoreArchive,
} from "./nativeSnapshotRestoreContract";
type Data = Record<string, any>;
type Doc = { data: Data; blob: Blob };
type Kind =
  | "source"
  | "export"
  | "preview"
  | "apply"
  | "readback"
  | "credentials";
type Operation = { id: string; kind: Kind; owner: string; epoch: number };
const common = "/bacnet/controller/native-application";
const label = (t: Data) =>
  `${t.device} · ${t.address}${t.router ? ` via ${t.router} / DNET ${t.dnet}` : ""}`;
const targetOf = (c: ControllerContext) => ({
  address: c.address,
  device: c.device,
  router: c.router || null,
  dnet: c.dnet ?? null,
});
function configuration(key?: string) {
  try {
    return JSON.parse(key || "null");
  } catch {
    return null;
  }
}

export function NativeSnapshotRestore({
  source,
  controller,
  visible,
}: {
  source: SnapshotRestoreArchive | null;
  controller?: ControllerContext | null;
  visible: boolean;
}) {
  const context = useContext(NativeBooleanTransferContext);
  const [expanded, setExpanded] = useState(false),
    [inspected, setInspected] = useState<(Doc & { owner: string }) | null>(
      null,
    );
  const [plan, setPlan] = useState<
    (Doc & { owner: string; epoch: number }) | null
  >(null);
  const [receipt, setReceipt] = useState<Doc | null>(null),
    [status, setStatus] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState(""),
    [uncertainty, setUncertainty] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [interruption, setInterruption] = useState(false),
    [now, setNow] = useState(Date.now());
  const [backup, setBackup] = useState(""),
    [restore, setRestore] = useState(""),
    [receiptChoice, setReceiptChoice] = useState("");
  const [loadingReceipt, setLoadingReceipt] = useState(false);
  const details = useRef<HTMLDetailsElement>(null),
    alive = useRef(true),
    epoch = useRef(0),
    active = useRef<Operation | null>(null);
  const reviewID = useRef<string | null>(null),
    busyOwner = useRef("retained-restore-" + randomUUID());
  const statusTicket = useRef(0),
    receiptTicket = useRef(0),
    receiptChanging = useRef(false),
    receiptNow = useRef(receipt);
  receiptNow.current = receipt;
  const owner = JSON.stringify([
    source && [
      source.capture_id,
      source.snapshot_sha256,
      source.sha256,
      source.target,
    ],
    visible,
    context?.workspaceGeneration,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
      controller.ownedCommands,
    ],
  ]);
  const ownerNow = useRef(owner);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const generation = epoch.current;
  const current = (key: string, version: number) =>
    alive.current &&
    ownerNow.current === key &&
    epoch.current === version &&
    visible &&
    details.current?.open === true &&
    (context?.workspaceCurrent?.() ?? true) &&
    document.visibilityState !== "hidden";
  const opened = inspected?.owner === owner ? inspected : null;
  const shown = plan && current(plan.owner, plan.epoch) ? plan : null;
  const fresh = !!shown && now < Date.parse(shown.data.expires_at);
  const config = configuration(controller?.interfaceKey);
  const connected =
    !!controller?.interfaceOpen &&
    controller.ownedCommands === 0 &&
    !!config?.local_address &&
    !config.transport &&
    !config.bbmd_address;
  const available =
    status?.retained_application_restore_profile === snapshotRestoreProfile;
  const pending =
    Array.isArray(status?.receipts) &&
    status.receipts.some((r: Data) => r.pending === true);
  const otherBusy = !!context?.fieldBusy && active.current === null;
  const locked = busy || otherBusy || loadingReceipt;
  const canReview =
    !!source &&
    !!opened &&
    !!controller &&
    connected &&
    available &&
    status?.credentials_configured === true &&
    snapshotRestoreTarget(source.target, controller) &&
    !pending &&
    !locked &&
    visible;
  const intent = receipt?.data.intent,
    observed = receipt?.data.latest_readback || receipt?.data.result;
  const receiptMatches =
    !!intent &&
    !!controller &&
    connected &&
    snapshotRestoreTarget(
      { ...intent.target, device: intent.identity.device },
      controller,
    ) &&
    connectionSame(intent.connector_config, config);
  function cancelOwned() {
    for (const id of new Set([
      reviewID.current,
      active.current &&
      ["preview", "apply", "readback"].includes(active.current.kind)
        ? active.current.id
        : null,
    ]))
      if (id)
        void apiKeepalive(common + "/cancel", { operation_id: id }).catch(
          () => {},
        );
    reviewID.current = null;
  }
  function retire() {
    epoch.current++;
    setPlan(null);
    setConfirmed(false);
    setInterruption(false);
    cancelOwned();
  }
  function release(operation: Operation) {
    if (active.current !== operation) return;
    active.current = null;
    if (alive.current) setBusy(false);
    context?.onBusy(busyOwner.current, false);
  }
  async function refresh() {
    const ticket = ++statusTicket.current,
      key = ownerNow.current,
      version = epoch.current;
    const data = await api(common + "/status");
    if (ticket === statusTicket.current && current(key, version))
      setStatus(data);
  }
  useEffect(() => {
    alive.current = true;
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      receiptTicket.current++;
      statusTicket.current++;
      cancelOwned();
      if (active.current) release(active.current);
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
    };
  }, []);
  useEffect(() => {
    cancelOwned();
    setPlan(null);
    setConfirmed(false);
    setInterruption(false);
  }, [owner]);
  useEffect(() => {
    if (!shown) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [shown]);
  function retain(doc: Doc) {
    receiptNow.current = doc;
    setReceipt(doc);
    if (doc.data.pending === false) setUncertainty("");
  }

  async function loadReceipt() {
    if (
      active.current ||
      receiptChanging.current ||
      !restoreID(receiptChoice) ||
      !current(owner, generation)
    )
      return;
    retire();
    receiptChanging.current = true;
    setLoadingReceipt(true);
    setFailure("");
    const ticket = ++receiptTicket.current,
      key = ownerNow.current,
      version = epoch.current,
      id = receiptChoice;
    try {
      const doc = await apiJsonDocument(common + "/receipts/" + id);
      if (
        doc.data.intent?.id !== id ||
        !(await snapshotRestoreReceipt(doc.data))
      )
        throw new Error(
          "The recorded application restore receipt is incomplete or inconsistent.",
        );
      if (ticket === receiptTicket.current && current(key, version))
        retain(doc);
    } catch (error) {
      if (ticket === receiptTicket.current && current(key, version))
        setFailure(String(error));
    } finally {
      if (alive.current && ticket === receiptTicket.current) {
        receiptChanging.current = false;
        setLoadingReceipt(false);
      }
    }
  }

  async function run(kind: Kind) {
    if (
      active.current ||
      locked ||
      !current(owner, generation) ||
      receiptChanging.current
    )
      return;
    if (["source", "export", "preview"].includes(kind) && !source) return;
    if (kind === "export" && !opened) return;
    if (kind === "preview" && !canReview) return;
    if (
      kind === "apply" &&
      (!shown ||
        !fresh ||
        !confirmed ||
        !interruption ||
        !controller ||
        !connected ||
        !available ||
        pending ||
        !current(shown.owner, shown.epoch))
    )
      return;
    if (kind === "readback" && (!receiptMatches || !receipt?.data.pending))
      return;
    if (kind === "credentials" && (!backup || !restore)) return;
    const selected = source,
      local = opened,
      review = shown,
      record = receipt;
    if (["source", "preview", "credentials"].includes(kind)) retire();
    const operation: Operation = {
      id: "retained-restore-" + randomUUID(),
      kind,
      owner: ownerNow.current,
      epoch: epoch.current,
    };
    active.current = operation;
    setBusy(true);
    context?.onBusy(busyOwner.current, true);
    setFailure("");
    const ticket = ["apply", "readback"].includes(kind)
      ? ++receiptTicket.current
      : null;
    try {
      if (kind === "credentials") {
        await api(common + "/credentials", { backup, restore });
        if (current(operation.owner, operation.epoch)) {
          setBackup("");
          setRestore("");
        }
      } else if (kind === "source") {
        const doc = await apiJsonDocument(base + "/source", {
          restore_capture_id: selected!.capture_id,
          restore_snapshot_sha256: selected!.snapshot_sha256,
        });
        if (!(await snapshotRestoreSource(doc.data, selected!)))
          throw new Error(
            "The reconstructed image does not match this retained source.",
          );
        if (current(operation.owner, operation.epoch))
          setInspected({ ...doc, owner: operation.owner });
      } else if (kind === "export") {
        const artifact = await apiBlobDocument(base + "/export", {
          restore_capture_id: selected!.capture_id,
          restore_snapshot_sha256: selected!.snapshot_sha256,
          source_evidence_sha256: local!.data.evidence_sha256,
        });
        if (
          artifact.headers.get("X-BMS-Restore-Source") !==
            selected!.capture_id ||
          artifact.headers.get("X-BMS-Restore-Snapshot") !==
            selected!.snapshot_sha256 ||
          artifact.headers.get("X-BMS-Restore-Review") !==
            local!.data.evidence_sha256 ||
          artifact.headers.get("X-BMS-Artifact-SHA256") !==
            local!.data.compilation.compiled_sha256 ||
          (await sha256Blob(artifact.blob)) !==
            local!.data.compilation.compiled_sha256
        )
          throw new Error(
            "The saved application copy does not match its exact image review.",
          );
        if (current(operation.owner, operation.epoch))
          saveBlob(
            artifact.blob,
            "retained-saved-application." +
              (local!.data.compilation.encoding === "gzip-moi-v2"
                ? "moz"
                : "moi"),
          );
      } else if (kind === "preview") {
        reviewID.current = operation.id;
        const doc = await apiJsonDocument(base + "/preview", {
          ...targetOf(controller!),
          restore_capture_id: selected!.capture_id,
          restore_snapshot_sha256: selected!.snapshot_sha256,
          operation_id: operation.id,
        });
        if (
          !(await snapshotRestoreReview(
            doc.data,
            selected!,
            local!.data,
            controller!,
          ))
        )
          throw new Error(
            "The restore review does not match the selected image, controller or current backup.",
          );
        if (current(operation.owner, operation.epoch)) {
          setPlan({ ...doc, owner: operation.owner, epoch: operation.epoch });
          setNow(Date.now());
        } else
          void apiKeepalive(common + "/cancel", {
            operation_id: operation.id,
          }).catch(() => {});
      } else {
        if (kind === "apply") {
          reviewID.current = null;
          setPlan(null);
          setConfirmed(false);
          setInterruption(false);
        }
        const doc = await apiJsonDocument(
          kind === "apply" ? base + "/apply" : common + "/readback",
          kind === "apply"
            ? {
                operation_id: operation.id,
                token: review!.data.token,
                review_sha256: review!.data.review_sha256,
                historical_application_confirmed: true,
                application_transfer_confirmed: true,
              }
            : {
                operation_id: operation.id,
                receipt_id: record!.data.intent.id,
              },
        );
        if (
          (kind === "apply" &&
            doc.data.intent &&
            doc.data.intent.operation_id !== operation.id) ||
          !(await snapshotRestoreReceipt(
            doc.data,
            kind === "apply" ? review!.data : record!.data.intent,
          ))
        )
          throw new Error(
            "The restore receipt does not bind the original operation and retained image. Inspect History before another change.",
          );
        if (alive.current && ticket === receiptTicket.current) retain(doc);
      }
    } catch (error) {
      if (alive.current) {
        if (current(operation.owner, operation.epoch))
          setFailure(String(error));
        if (kind === "apply" || kind === "readback")
          setUncertainty(
            `Unconfirmed ${kind === "apply" ? "restore" : "readback"} for ${controller ? label(controller) : "the original controller"}. Keep operation ${operation.id}; inspect its receipt in History. No restore was replayed.`,
          );
      }
      if (kind === "preview")
        void apiKeepalive(common + "/cancel", {
          operation_id: operation.id,
        }).catch(() => {});
    } finally {
      release(operation);
      if (current(operation.owner, operation.epoch))
        void refresh().catch((error) => setFailure(String(error)));
    }
  }

  const entries: Data[] = Array.isArray(status?.receipts)
    ? status.receipts.filter(
        (r: Data) =>
          r.change_kind === "application-restore" &&
          r.operation_profile === snapshotRestoreProfile,
      )
    : [];
  return (
    <details
      ref={details}
      className="native-compiler-source native-default-transfer native-snapshot-restore"
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        const open = event.currentTarget.open;
        setExpanded(open);
        if (open) void refresh().catch((error) => setFailure(String(error)));
        else retire();
      }}
    >
      <summary onClick={retire}>Restore a retained application</summary>
      <section aria-label="Retained native application restore">
        <h3>Retained application restore</h3>
        <p>
          {source
            ? `Selected historical source: ${source.capture_id} · ${label(source.target)}.`
            : "Select and inspect a retained native backup to reconstruct its saved application."}
        </p>
        <p>
          {controller
            ? `Selected controller: ${controller.name} · ${label(controller)}.`
            : "Local reconstruction and saving remain available without a controller."}
        </p>
        <p>
          Restore replaces the application and its historical saved application
          values. Review captures current configuration; Apply keeps a separate
          fresh backup and can interrupt control. Unsaved runtime and
          whole-controller state are not restored.
        </p>
        {!expanded ? null : (
          <>
            <button
              key={`inspect-${owner}`}
              className={!opened ? "primary" : undefined}
              disabled={!source || locked || !visible}
              onClick={() => void run("source")}
            >
              Inspect retained restore image
            </button>
            {opened && (
              <>
                <p role="status">
                  Reconstructed historical image:{" "}
                  {opened.data.compilation.native_record_count} native records ·{" "}
                  {opened.data.compilation.saved_application_parameters} saved
                  application fields · {opened.data.compilation.compiled_bytes}{" "}
                  archive bytes.
                </p>
                <div className="button-row">
                  <button
                    disabled={locked || !visible}
                    onClick={() => void run("export")}
                  >
                    Save saved-application copy
                  </button>
                  <button
                    disabled={!visible}
                    onClick={() => {
                      if (current(owner, generation) && opened)
                        saveBlob(
                          opened.blob,
                          "retained-application-image-review.json",
                        );
                    }}
                  >
                    Save exact retained-image review
                  </button>
                </div>
              </>
            )}
            {!connected && (
              <p>
                Controller restore requires an open plain BACnet/IPv4 interface
                with no owned commands. Local image work remains available.
              </p>
            )}
            {source &&
              controller &&
              !snapshotRestoreTarget(source.target, controller) && (
                <p>
                  This historical source belongs to another route or Device.
                  Select its matching controller for a fresh restore review.
                </p>
              )}
            {status && !available && (
              <p>
                The installed server does not advertise retained application
                restoration. Keep the local image and original evidence.
              </p>
            )}
            {pending && (
              <p>
                Resolve the retained native operation before starting another
                engineering change. Load its original receipt for explicit
                readback.
              </p>
            )}
            <details>
              <summary>Native family credentials</summary>
              <p>
                {status?.credentials_configured
                  ? "Native credentials configured on this computer."
                  : "Configure native family credentials before controller review."}
              </p>
              <label>
                Retained-application backup credential
                <input
                  type="password"
                  autoComplete="off"
                  value={backup}
                  disabled={locked || !visible}
                  onChange={(e) => setBackup(e.target.value)}
                />
              </label>
              <label>
                Retained-application restore credential
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
                Save retained-application credentials
              </button>
            </details>
            {failure && <p role="alert">{failure}</p>}
            {uncertainty && <p role="alert">{uncertainty}</p>}
            {busy && (
              <p role="status">
                {active.current?.kind === "apply"
                  ? "Applying retained application"
                  : active.current?.kind === "readback"
                    ? "Reading back the recorded restore"
                    : "Preparing retained application operation"}
                …
              </p>
            )}
            {busy && (
              <button onClick={retire}>
                Cancel retained-application operation
              </button>
            )}
            {shown && (
              <section aria-label="Reviewed retained application restore">
                <p>
                  Historical source:{" "}
                  {shown.data.restore_source.request.restore_capture_id}.
                  Current review backup: {shown.data.capture_id}. The pre-write
                  backup will be a separate new record.
                </p>
                <div
                  className="application-operation-table"
                  tabIndex={0}
                  aria-label="Retained restore comparison table"
                >
                  <table aria-label="Retained restore record changes">
                    <thead>
                      <tr>
                        <th>Current records</th>
                        <th>Restored records</th>
                        <th>Added</th>
                        <th>Removed</th>
                        <th>Changed existing</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {[
                          "before_records",
                          "restored_records",
                          "added_records",
                          "removed_records",
                          "changed_existing_records",
                        ].map((k) => (
                          <td key={k}>
                            {shown.data.compilation.difference[k]}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
                <label className="restore-confirmation">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    disabled={locked || !fresh || !visible}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  I confirm this historical application and its saved values are
                  correct for the selected controller and connected I/O.
                </label>
                <label className="restore-confirmation">
                  <input
                    type="checkbox"
                    checked={interruption}
                    disabled={locked || !fresh || !visible}
                    onChange={(e) => setInterruption(e.target.checked)}
                  />
                  I confirm the application restore can interrupt controller
                  operation.
                </label>
                {!fresh && (
                  <p role="status">
                    This restore review expired. Read current configuration and
                    review again.
                  </p>
                )}
                <button
                  disabled={!visible}
                  onClick={() => {
                    if (shown && current(shown.owner, shown.epoch))
                      saveBlob(
                        shown.blob,
                        "retained-application-controller-review.json",
                      );
                  }}
                >
                  Save exact controller restore review
                </button>
              </section>
            )}
            {shown ? (
              <button
                key={`apply-${shown.data.review_sha256}-${generation}`}
                className="primary"
                disabled={
                  locked ||
                  !fresh ||
                  !confirmed ||
                  !interruption ||
                  !connected ||
                  !visible ||
                  pending
                }
                onClick={() => void run("apply")}
              >
                Apply retained application to controller
              </button>
            ) : (
              <button
                key={`review-${generation}`}
                className={opened ? "primary" : undefined}
                disabled={!canReview}
                onClick={() => void run("preview")}
              >
                Review retained application restore
              </button>
            )}
            {receipt && (
              <section aria-label="Recorded retained application restore">
                <h4>Recorded restore result</h4>
                {intent ? (
                  <>
                    <p>Recorded transfer receipt: {intent.id}.</p>
                    <p>
                      Original target:{" "}
                      {label({
                        ...intent.target,
                        device: intent.identity.device,
                      })}
                      . Restored source:{" "}
                      {intent.restore_source.request.restore_capture_id}.
                      Pre-write backup: {intent.backup_id}.
                    </p>
                    <p role="status">
                      {observed?.status === "verified"
                        ? "Retained application and saved values verified"
                        : observed?.status === "recovered_original"
                          ? "Original pre-write application recovered; retained restore not verified"
                          : observed?.status === "not_sent"
                            ? "Restore not sent"
                            : "Restore outcome requires attention"}
                      .
                    </p>
                  </>
                ) : (
                  <p>
                    Restore not sent; no durable transfer intent was created.
                  </p>
                )}
                <p>
                  {receipt.data.pending
                    ? "Pending original operation. Use explicit readback; no restore will be replayed."
                    : "Recorded result; a fresh controller review is required for any new change."}
                </p>
                {observed?.errors?.map((text: string, index: number) => (
                  <p key={index}>{text}</p>
                ))}
                {observed?.error && <p>{observed.error}</p>}
                <button
                  disabled={!visible}
                  onClick={() => {
                    if (
                      receiptNow.current === receipt &&
                      current(owner, generation)
                    )
                      saveBlob(
                        receipt.blob,
                        "retained-application-restore-receipt.json",
                      );
                  }}
                >
                  Save exact retained-restore receipt
                </button>
                {intent && receipt.data.pending && (
                  <button
                    key={`readback-${intent.id}-${generation}`}
                    className="primary"
                    disabled={locked || !receiptMatches || !visible}
                    onClick={() => void run("readback")}
                  >
                    Read back original retained-application restore
                  </button>
                )}
                {intent && !receiptMatches && (
                  <p>
                    Select this receipt's original controller and interface to
                    read back. Loading a receipt never changes the selected
                    controller.
                  </p>
                )}
              </section>
            )}
            <label>
              Recorded application restores
              <select
                value={receiptChoice}
                disabled={locked || !visible}
                onChange={(e) => {
                  if (
                    active.current ||
                    receiptChanging.current ||
                    !current(owner, generation)
                  )
                    return;
                  retire();
                  receiptTicket.current++;
                  setReceiptChoice(e.target.value);
                }}
              >
                <option value="">Select recorded restore</option>
                {entries.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.id} · {row.target.address} ·{" "}
                    {row.pending ? "pending" : "recorded"}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={locked || !restoreID(receiptChoice) || !visible}
              onClick={() => void loadReceipt()}
            >
              Load recorded application restore
            </button>
            <button
              disabled={!visible}
              onClick={() =>
                void refresh().catch((error) => setFailure(String(error)))
              }
            >
              Refresh retained-restore status
            </button>
          </>
        )}
      </section>
    </details>
  );
}
