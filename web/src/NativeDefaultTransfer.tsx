import { useEffect, useRef, useState } from "react";
import { NativeRuntimeCalibration } from "./NativeRuntimeCalibration";
import { NativeRuntimeParametersNotice } from "./NativeRuntimeParametersNotice";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import {
  previousRealDefaultMatches,
  realRecoveryProfile,
  type NativeDefaultRecoveryDocument,
} from "./nativeDefaultRecoveryContract";
import {
  booleanRecoveryProfile,
  previousBooleanDefaultMatches,
} from "./nativeBooleanRecoveryContract";
import {
  wireTransferReviewMatches,
  wireTransferReceiptMatches,
} from "./nativeWireTransferContract";
import {
  previousWireSourceMatches,
  wireRecoveryProfile,
  historicalWireRecoveryProfile,
} from "./nativeWireRecoveryContract";

type Data = Record<string, any>;
const base = "/bacnet/controller/native-application";
const floatBits = (value: number) => {
  const bytes = new DataView(new ArrayBuffer(4));
  bytes.setFloat32(0, value, false);
  return bytes.getUint32(0, false).toString(16).padStart(8, "0");
};
const targetOf = (controller: ControllerContext) => ({
  address: controller.address,
  device: controller.device,
  router: controller.router || null,
  dnet: controller.dnet ?? null,
});
const sameTarget = (a: Data, b: Data) =>
  ["address", "router", "dnet"].every(
    (key) => (a[key] ?? null) === (b[key] ?? null),
  );
const hasSerialInterface = (key?: string) => {
  try {
    return JSON.parse(key ?? "null")?.transport === "mstp";
  } catch {
    return false;
  }
};

export function NativeDefaultTransfer({
  controller,
  source,
  proposal,
  field,
  visible,
  parentBusy = false,
  onBusy,
  onCaptured,
  booleanDefault = false,
  wireSource = false,
  otherOperationBusy = false,
  recoveryDraft = null,
  onRecoveryPrepared,
  wireSelection,
}: {
  controller?: ControllerContext | null;
  source: Data | null;
  proposal: Data | null;
  field: Data | undefined;
  visible: boolean;
  parentBusy?: boolean;
  onBusy: (busy: boolean) => void;
  onCaptured: (id: string) => void;
  booleanDefault?: boolean;
  wireSource?: boolean;
  otherOperationBusy?: boolean;
  recoveryDraft?: NativeDefaultRecoveryDocument | null;
  onRecoveryPrepared?: (document: NativeDefaultRecoveryDocument) => void;
  wireSelection?: { diagram_ref: string; wire_index: number; class_id: number };
}) {
  const operationProfile = wireSource
    ? "native-effective-wire-source-transfer/1"
    : booleanDefault
      ? "native-effective-boolean-default-transfer/1"
      : "native-effective-default-transfer/1";
  const changeKind = wireSource
    ? "wire-source"
    : booleanDefault
      ? "boolean-default"
      : "signal-default";
  const transferPath = wireSource
    ? "/wire-source/transfer"
    : booleanDefault
      ? "/boolean-default/transfer"
      : "/signal-default/transfer";
  const [status, setStatus] = useState<Data | null>(null);
  const adapterAvailable = wireSource
    ? status?.wire_source_transfer_profile === operationProfile
    : !booleanDefault ||
      status?.boolean_default_transfer_profile === operationProfile;
  const [plan, setPlan] = useState<{
    data: Data;
    blob: Blob;
    owner: string;
    epoch: number;
  } | null>(null);
  const [receipt, setReceipt] = useState<{ data: Data; blob: Blob } | null>(
    null,
  );
  const receiptNow = useRef(receipt);
  receiptNow.current = receipt;
  const [backup, setBackup] = useState(""),
    [restore, setRestore] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [interruption, setInterruption] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const alive = useRef(true),
    epoch = useRef(0),
    statusTicket = useRef(0),
    receiptTicket = useRef(0);
  const operation = useRef<string | null>(null),
    reviewId = useRef<string | null>(null);
  const owner = JSON.stringify([
    wireSource,
    booleanDefault,
    otherOperationBusy,
    visible,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
      controller.ownedCommands,
    ],
    source?.snapshot_sha256,
    proposal,
    recoveryDraft?.data.origin_sha256,
    wireSelection,
  ]);
  const ownerNow = useRef(owner);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const shown =
    plan?.owner === owner && plan.epoch === epoch.current ? plan : null;
  const serialInterface = hasSerialInterface(controller?.interfaceKey);
  const connected =
    !!controller?.interfaceOpen &&
    controller.ownedCommands === 0 &&
    !serialInterface;
  const sourceMatches =
    !!controller &&
    !!source &&
    source.device === controller.device &&
    sameTarget(source.target, controller);
  const localLocked = busy || parentBusy;
  function cancel() {
    for (const id of new Set([operation.current, reviewId.current]))
      if (id)
        void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
          () => {},
        );
    reviewId.current = null;
  }
  async function refresh() {
    const ticket = ++statusTicket.current;
    const data = await api(base + "/status");
    if (alive.current && ticket === statusTicket.current) setStatus(data);
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
      receiptTicket.current++;
      statusTicket.current++;
      cancel();
      if (operation.current) onBusy(false);
    };
  }, []);
  useEffect(() => {
    cancel();
    setConfirmed(false);
    setInterruption(false);
    setPlan(null);
    setError("");
    setBackup("");
    setRestore("");
    if (visible)
      void refresh().catch((failure) => {
        if (alive.current) setError(String(failure));
      });
  }, [owner]);
  useEffect(() => {
    if (!shown) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [shown]);
  async function run(
    kind: "credentials" | "capture" | "preview" | "apply" | "readback",
  ) {
    if (operation.current || parentBusy) return;
    if (kind !== "credentials" && (!controller || !connected)) return;
    if (
      (kind === "preview" || kind === "apply") &&
      (!sourceMatches || !proposal || !field || !adapterAvailable)
    )
      return;
    const selectedPlan = shown;
    if (
      kind === "apply" &&
      (!selectedPlan ||
        !confirmed ||
        !interruption ||
        Date.now() >= Date.parse(selectedPlan.data.expires_at))
    )
      return;
    if (
      kind === "readback" &&
      (!receipt?.data.intent ||
        !controller ||
        !sameTarget(receipt.data.intent.target, controller) ||
        receipt.data.intent.identity.device !== controller.device)
    )
      return;
    const id = "native-default-" + crypto.randomUUID(),
      key = ownerNow.current,
      ticket = epoch.current;
    operation.current = id;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      if (kind === "credentials") {
        setPlan(null);
        reviewId.current = null;
        await api(base + "/credentials", { backup, restore });
        if (current(key, ticket)) {
          setBackup("");
          setRestore("");
        }
      } else if (kind === "capture") {
        setPlan(null);
        const data = await api(base + "/capture", {
          ...targetOf(controller!),
          operation_id: id,
        });
        if (
          !/^[a-f0-9]{32}$/.test(data.id || "") ||
          !data.source_identity_matches ||
          !sameTarget(data.target, controller!) ||
          data.device !== controller!.device
        )
          throw new Error(
            "Native backup does not match the selected controller. Retain its evidence and capture again.",
          );
        if (current(key, ticket)) onCaptured(data.id);
      } else if (kind === "preview") {
        setPlan(null);
        setConfirmed(false);
        setInterruption(false);
        reviewId.current = id;
        const result = await apiJsonDocument(base + transferPath + "/preview", {
          ...targetOf(controller!),
          ...proposal,
          ...(recoveryDraft?.data.proposal
            ? {
                recovery_parent_receipt:
                  recoveryDraft.data.origin.parent_receipt_id,
                recovery_origin_sha256: recoveryDraft.data.origin_sha256,
              }
            : {}),
          operation_id: id,
        });
        const data = result.data,
          edit = data.compilation?.selected_edit;
        if (
          data.operation_profile !== operationProfile ||
          data.change_kind !== changeKind ||
          data.can_apply !== true ||
          data.snapshot_sha256 !== source!.snapshot_sha256 ||
          !sameTarget(data.target || {}, controller!) ||
          data.identity?.device !== controller!.device ||
          data.capture_id !== source!.capture_id ||
          (recoveryDraft?.data.proposal
            ? data.recovery_origin_sha256 !==
                recoveryDraft.data.origin_sha256 ||
              JSON.stringify(data.recovery_origin) !==
                JSON.stringify(recoveryDraft.data.origin)
            : data.recovery_origin !== undefined ||
              data.recovery_origin_sha256 !== undefined) ||
          (wireSource
            ? !wireTransferReviewMatches(data, source!, proposal!, field!)
            : ![
                "record_ref",
                "encoded_sha256",
                booleanDefault ? "value" : "value_text",
              ].every(
                (name) => data.default_edit?.[name] === proposal![name],
              ) ||
              edit?.record_ref !== field!.ref ||
              edit?.encoded_sha256 !== field!.encoded_sha256 ||
              (booleanDefault
                ? data.application_sha256 !== proposal!.source_sha256 ||
                  data.compilation?.profile !==
                    "native-effective-boolean-default-compiler/1" ||
                  data.compilation.other_merged_bytes_preserved !== true ||
                  data.compilation.saved_settings_merged !== true ||
                  edit?.datatype !== "Boolean" ||
                  edit?.property !== 3113 ||
                  edit?.class_id !== field!.class_id ||
                  typeof edit?.before_value !== "boolean" ||
                  typeof edit?.after_value !== "boolean" ||
                  edit.before_value !== field!.effective_value ||
                  edit.after_value !== proposal!.value ||
                  edit.before_tag !== (field!.effective_value ? "11" : "10") ||
                  edit.after_tag !== (proposal!.value ? "11" : "10")
                : edit?.before_bits !== field!.effective_bits ||
                  !Number.isFinite(edit?.stored_value) ||
                  edit?.after_bits !==
                    floatBits(Number(proposal!.value_text)) ||
                  edit?.after_bits !== floatBits(edit.stored_value) ||
                  !/^[a-f0-9]{8}$/.test(edit?.after_bits || ""))) ||
          !/^[A-Za-z0-9_-]{32}$/.test(data.token || "") ||
          !/^[a-f0-9]{64}$/.test(data.review_sha256 || "") ||
          !Number.isFinite(Date.parse(data.expires_at))
        )
          throw new Error(
            "Native transfer review does not match this controller, snapshot and proposal.",
          );
        if (current(key, ticket)) {
          setPlan({ data, blob: result.blob, owner: key, epoch: ticket });
          setNow(Date.now());
        } else
          void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
            () => {},
          );
      } else {
        const receiptEpoch = ++receiptTicket.current;
        if (kind === "apply") {
          setPlan(null);
          reviewId.current = null;
          setConfirmed(false);
          setInterruption(false);
        }
        const result = await apiJsonDocument(
          base + (kind === "apply" ? transferPath + "/apply" : "/readback"),
          kind === "apply"
            ? {
                operation_id: id,
                token: selectedPlan!.data.token,
                review_sha256: selectedPlan!.data.review_sha256,
                ...(wireSource
                  ? { wire_change_confirmed: confirmed }
                  : { default_change_confirmed: confirmed }),
                application_transfer_confirmed: interruption,
              }
            : { operation_id: id, receipt_id: receipt!.data.intent.id },
        );
        const intent = result.data.intent;
        if (
          wireSource &&
          !wireTransferReceiptMatches(
            result.data,
            kind === "apply" ? selectedPlan?.data : receipt?.data.intent,
          )
        )
          throw new Error(
            "Native wire receipt does not match its reviewed edit and preservation evidence. Load retained receipts before another transfer.",
          );
        if (
          intent &&
          (intent.change_kind !== changeKind ||
            intent.operation_profile !== operationProfile ||
            !sameTarget(intent.target, controller!) ||
            intent.identity.device !== controller!.device)
        )
          throw new Error(
            "The returned receipt belongs to a different native operation. Load retained receipts before any further transfer.",
          );
        if (alive.current && receiptTicket.current === receiptEpoch)
          setReceipt(result);
      }
    } catch (failure) {
      if (kind === "preview") {
        void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
          () => {},
        );
        if (reviewId.current === id) reviewId.current = null;
      }
      if (current(key, ticket))
        setError(
          String(failure) +
            (kind === "apply" || kind === "readback"
              ? " Consult retained transfer receipts before another attempt."
              : ""),
        );
    } finally {
      operation.current = null;
      if (alive.current) {
        setBusy(false);
        void refresh().catch(() => {});
      }
      onBusy(false);
    }
  }
  async function loadReceipt(id: string) {
    const ticket = ++receiptTicket.current;
    setError("");
    try {
      const result = await apiJsonDocument(base + "/receipts/" + id);
      if (
        result.data.intent?.id !== id ||
        result.data.intent?.change_kind !== changeKind ||
        result.data.intent?.operation_profile !== operationProfile ||
        (wireSource && !wireTransferReceiptMatches(result.data))
      )
        throw new Error(
          wireSource
            ? "This is not a native wire transfer receipt."
            : "This is not a native default transfer receipt.",
        );
      if (alive.current && ticket === receiptTicket.current) setReceipt(result);
    } catch (failure) {
      if (alive.current && ticket === receiptTicket.current)
        setError(String(failure));
    }
  }
  async function preparePreviousDefault() {
    if (
      localLocked ||
      operation.current ||
      !source ||
      !receipt ||
      !onRecoveryPrepared
    )
      return;
    if (
      booleanDefault &&
      receipt.data.intent?.default_edit?.record_ref !== field?.ref
    )
      return;
    if (
      wireSource &&
      (receipt.data.intent?.wire_edit?.diagram_ref !==
        wireSelection?.diagram_ref ||
        receipt.data.intent?.wire_edit?.wire_index !==
          wireSelection?.wire_index)
    )
      return;
    const selectedReceipt = receipt,
      key = ownerNow.current,
      ticket = ++epoch.current,
      receiptEpoch = receiptTicket.current;
    cancel();
    setPlan(null);
    setError("");
    setBusy(true);
    try {
      const document = await apiJsonDocument(
        base +
          (wireSource
            ? "/wire-source/recovery/prepare"
            : booleanDefault
              ? "/boolean-default/recovery/prepare"
              : "/signal-default/recovery/prepare"),
        {
          receipt_id: receipt.data.intent.id,
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
        },
      );
      if (
        (wireSource &&
          document.data.profile === historicalWireRecoveryProfile &&
          status?.historical_wire_pin_recovery_profile !==
            historicalWireRecoveryProfile) ||
        !(wireSource
          ? previousWireSourceMatches(
              document.data,
              source,
              receipt.data,
              wireSelection!,
            )
          : booleanDefault
            ? previousBooleanDefaultMatches(
                document.data,
                source,
                receipt.data,
                field!,
              )
            : previousRealDefaultMatches(document.data, source, receipt.data))
      )
        throw new Error(
          "The previous-value proposal does not match this receipt and retained source.",
        );
      if (
        current(key, ticket) &&
        receiptTicket.current === receiptEpoch &&
        receiptNow.current === selectedReceipt
      )
        onRecoveryPrepared(document);
    } catch (failure) {
      if (
        current(key, ticket) &&
        receiptTicket.current === receiptEpoch &&
        receiptNow.current === selectedReceipt
      )
        setError(String(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function saveBackup() {
    if (!source) return;
    const ticket = epoch.current,
      key = ownerNow.current,
      id = source.capture_id;
    try {
      const result = await apiBlobDocument(base + "/backups/" + id);
      if (
        result.headers.get("Content-Disposition") !==
        `attachment; filename="native-backup-${id}.zip"`
      )
        throw new Error("Native backup download does not match this source.");
      if (current(key, ticket))
        saveBlob(result.blob, `native-backup-${id}.zip`);
    } catch (failure) {
      if (current(key, ticket)) setError(String(failure));
    }
  }
  const observed = receipt?.data.latest_readback || receipt?.data.result;
  const receiptMatches =
    !!controller &&
    !!receipt?.data.intent &&
    sameTarget(receipt.data.intent.target, controller) &&
    receipt.data.intent.identity.device === controller.device;
  const fresh =
    shown?.data.can_apply && now < Date.parse(shown.data.expires_at);
  const receipts =
    status?.receipts?.filter((row: Data) => row.change_kind === changeKind) ??
    [];
  return (
    <section
      className="native-compiler-source native-default-transfer"
      aria-label={
        wireSource
          ? "Native wire source controller transfer"
          : booleanDefault
            ? "Native Boolean default controller transfer"
            : "Native default controller transfer"
      }
    >
      <h2>Controller transfer</h2>
      {controller ? (
        <p>
          Selected controller: {controller.name} · {controller.device} ·{" "}
          {controller.address}
          {controller.router
            ? ` via ${controller.router} / DNET ${controller.dnet}`
            : ""}
          .
        </p>
      ) : (
        <p>
          Open and verify a controller to capture or transfer its native
          {wireSource ? "wire source" : "defaults"}. Local compilation remains
          available.
        </p>
      )}
      <p>
        Capture and readback enter and end backup mode. Apply transfers one
        native application and can interrupt controller operation. Device
        identity stays unchanged.
      </p>
      {serialInterface && (
        <p>
          Native backup and application transfer require a BACnet/IPv4
          interface. Local compilation and saved receipts remain available.
        </p>
      )}
      {!adapterAvailable && (
        <p>
          The installed native {wireSource ? "wire source" : "Boolean"} transfer
          profile is unavailable. Retain this local compilation; no transfer
          review is prepared.
        </p>
      )}
      <details>
        <summary>Native backup and restore credentials</summary>
        <p>
          {status?.credentials_configured
            ? "Native credentials configured on this machine."
            : "Configure the controller family credentials before capture."}
        </p>
        <label>
          Native backup credential
          <input
            type="password"
            autoComplete="off"
            value={backup}
            disabled={localLocked}
            onChange={(event) => setBackup(event.target.value)}
          />
        </label>
        <label>
          Native restore credential
          <input
            type="password"
            autoComplete="off"
            value={restore}
            disabled={localLocked}
            onChange={(event) => setRestore(event.target.value)}
          />
        </label>
        <button
          disabled={localLocked || !backup || !restore}
          onClick={() => void run("credentials")}
        >
          Save native transfer credentials
        </button>
      </details>
      <div className="button-row">
        <button
          disabled={
            localLocked || !connected || !status?.credentials_configured
          }
          onClick={() => void run("capture")}
        >
          Read current native backup
        </button>
        {source && (
          <button disabled={localLocked} onClick={() => void saveBackup()}>
            Save original native backup
          </button>
        )}
        <button
          disabled={localLocked}
          onClick={() =>
            void refresh().catch((failure) => setError(String(failure)))
          }
        >
          Refresh transfer receipts
        </button>
      </div>
      {source && !sourceMatches && (
        <p>
          This retained backup belongs to another station. Capture the selected
          controller before reviewing a transfer.
        </p>
      )}
      {sourceMatches && field && (
        <button
          className={shown ? "" : "primary"}
          disabled={localLocked || !connected || !proposal || !adapterAvailable}
          onClick={() => void run("preview")}
        >
          {wireSource
            ? "Review controller wire transfer"
            : "Review controller default transfer"}
        </button>
      )}
      {shown && (
        <section
          className="native-compiler-source"
          aria-label={
            wireSource
              ? "Reviewed controller wire transfer"
              : "Reviewed controller default transfer"
          }
        >
          <h3>
            {wireSource
              ? "Review controller wire transfer"
              : "Review controller default transfer"}
          </h3>
          {shown.data.recovery_origin && (
            <p>
              New transfer to the previous{" "}
              {wireSource ? "wire source" : "effective value"} from receipt{" "}
              <code>{shown.data.recovery_origin.parent_receipt_id}</code>. This
              review does not replay the earlier operation.
            </p>
          )}
          {wireSource ? (
            <p>
              {shown.data.wire_edit.diagram_ref} · connection{" "}
              {shown.data.wire_edit.wire_index + 1} ·{" "}
              {shown.data.compilation.wire_edit.old_source_ref} →{" "}
              {shown.data.wire_edit.source_ref}. Destination and ports remain
              unchanged.
            </p>
          ) : (
            <p>
              {shown.data.default_edit.record_ref} ·{" "}
              {booleanDefault
                ? String(shown.data.compilation.selected_edit.before_value)
                : shown.data.compilation.selected_edit.before_bits}{" "}
              →{" "}
              {booleanDefault
                ? String(shown.data.compilation.selected_edit.after_value)
                : shown.data.compilation.selected_edit.after_bits}{" "}
              · stored value{" "}
              {booleanDefault
                ? String(shown.data.compilation.selected_edit.after_value)
                : Object.is(
                      shown.data.compilation.selected_edit.stored_value,
                      -0,
                    )
                  ? "-0"
                  : String(shown.data.compilation.selected_edit.stored_value)}
              .
            </p>
          )}
          <p>{shown.data.parameter_policy}</p>
          <NativeRuntimeParametersNotice
            parameters={shown.data.compilation.parameter_merge}
          />
          <p>
            Review expires {shown.data.expires_at}.
            {!fresh && " Review expired; review the current source again."}
          </p>
          <label className="native-transfer-check">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={localLocked}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            {wireSource
              ? "I confirm the selected controller, native connection and proposed wire source."
              : "I confirm the selected controller, native default and proposed value."}
          </label>
          <label className="native-transfer-check">
            <input
              type="checkbox"
              checked={interruption}
              disabled={localLocked}
              onChange={(event) => setInterruption(event.target.checked)}
            />
            I confirm the application transfer and controller interruption.
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={
                localLocked ||
                !fresh ||
                !confirmed ||
                !interruption ||
                !connected ||
                !sourceMatches
              }
              onClick={() => void run("apply")}
            >
              {wireSource
                ? "Apply native wire to controller"
                : "Apply native default to controller"}
            </button>
            <button
              onClick={() =>
                saveBlob(
                  shown.blob,
                  wireSource
                    ? "native-wire-transfer-review.json"
                    : "native-default-transfer-review.json",
                )
              }
            >
              Export exact transfer review
            </button>
          </div>
        </section>
      )}
      {busy && (
        <div role="status">
          {operation.current ? (
            <>
              Native operation in progress.{" "}
              <button onClick={cancel}>Stop native operation</button>
            </>
          ) : (
            "Preparing the previous value from retained local evidence."
          )}
        </div>
      )}
      {!!receipts.length && (
        <details open={!!receipts.some((row: Data) => row.pending)}>
          <summary>
            Retained native {wireSource ? "wire" : "default"} transfers (
            {receipts.length})
          </summary>
          <table
            aria-label={
              wireSource
                ? "Native wire transfer receipts"
                : "Native default transfer receipts"
            }
          >
            <thead>
              <tr>
                <th>Controller station</th>
                <th>{wireSource ? "Connection" : "Default"}</th>
                <th>Outcome</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map((row: Data) => (
                <tr key={row.id}>
                  <td>
                    {row.target.address}
                    {row.target.router
                      ? ` via ${row.target.router} / DNET ${row.target.dnet}`
                      : ""}
                  </td>
                  <td>
                    {wireSource
                      ? `${row.wire_edit?.diagram_ref} · connection ${(row.wire_edit?.wire_index ?? -1) + 1}`
                      : row.default_edit?.record_ref}
                  </td>
                  <td>
                    {row.status}
                    {row.pending ? " · unresolved" : ""}
                  </td>
                  <td>
                    <button
                      disabled={localLocked}
                      onClick={() => void loadReceipt(row.id)}
                    >
                      Open receipt {row.id.slice(0, 8)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {receipt && (
        <section
          aria-label={
            wireSource
              ? "Native wire transfer outcome"
              : "Native default transfer outcome"
          }
        >
          <h3>
            {observed?.status === "recovered_original"
              ? "Original application recovered"
              : observed?.status === "verified"
                ? wireSource
                  ? "Verified native wire transfer"
                  : "Verified native default transfer"
                : observed?.status === "not_sent"
                  ? wireSource
                    ? "Native wire transfer not sent"
                    : "Native default transfer not sent"
                  : wireSource
                    ? "Native wire transfer outcome uncertain"
                    : "Native default transfer outcome uncertain"}
          </h3>
          {receipt.data.intent && (
            <p>
              Receipt station: {receipt.data.intent.identity.device} ·{" "}
              {receipt.data.intent.target.address}
              {receipt.data.intent.target.router
                ? ` via ${receipt.data.intent.target.router} / DNET ${receipt.data.intent.target.dnet}`
                : ""}{" "}
              ·{" "}
              {wireSource
                ? receipt.data.intent.wire_edit.diagram_ref
                : receipt.data.intent.default_edit.record_ref}
              .
            </p>
          )}
          <p>{observed?.error || observed?.errors?.join(" ")}</p>
          <NativeRuntimeCalibration
            report={observed?.runtime_calibration}
            preservation={observed?.preservation}
          />
          {receipt.data.intent?.recovery_origin && (
            <p>
              New previous-value transfer from receipt{" "}
              <code>
                {receipt.data.intent.recovery_origin.parent_receipt_id}
              </code>
              . Original attempt and verification history remain retained.
            </p>
          )}
          {observed?.status === "recovered_original" ? (
            <p>
              Original identity, application and saved settings recovered. The
              proposed change was not verified. Readback did not send an
              application.
            </p>
          ) : observed?.status === "verified" ? (
            <p>
              Native application bytes and effective saved settings verified.
              Physical control performance remains unverified.
            </p>
          ) : (
            <p>
              Retain this evidence. Read back an unresolved transfer before any
              further write; no automatic retry or rollback occurs.
            </p>
          )}
          <div className="button-row">
            <button
              onClick={() =>
                saveBlob(
                  receipt.blob,
                  wireSource
                    ? "native-wire-transfer-receipt.json"
                    : "native-default-transfer-receipt.json",
                )
              }
            >
              Export exact transfer receipt
            </button>
            {receipt.data.intent && (
              <button
                disabled={localLocked || !connected || !receiptMatches}
                onClick={() => void run("readback")}
              >
                {wireSource
                  ? "Read back native wire transfer"
                  : "Read back native default transfer"}
              </button>
            )}
            {onRecoveryPrepared && (
              <button
                disabled={
                  localLocked ||
                  !source ||
                  (wireSource
                    ? status?.wire_source_recovery_profile !==
                        wireRecoveryProfile ||
                      receipt.data.intent?.wire_edit?.diagram_ref !==
                        wireSelection?.diagram_ref ||
                      receipt.data.intent?.wire_edit?.wire_index !==
                        wireSelection?.wire_index
                    : booleanDefault
                      ? status?.boolean_default_recovery_profile !==
                          booleanRecoveryProfile ||
                        receipt.data.intent?.default_edit?.record_ref !==
                          field?.ref
                      : status?.real_default_recovery_profile !==
                        realRecoveryProfile)
                }
                onClick={() => void preparePreviousDefault()}
              >
                {wireSource
                  ? "Prepare previous wire source"
                  : booleanDefault
                    ? "Prepare previous Boolean default"
                    : "Prepare previous Real default"}
              </button>
            )}
          </div>
          {onRecoveryPrepared && (
            <p className="muted">
              Preparation uses this receipt and the selected retained backup
              locally. Read a current backup first when connected. A new review
              and confirmed transfer are required; this action sends no
              controller request.
              {wireSource && (
                <>
                  {" "}
                  Open its recorded diagram and connection first.{" "}
                  {status?.historical_wire_pin_recovery_profile ===
                  historicalWireRecoveryProfile
                    ? "A missing current output pin requires verified original pin evidence and matching current configuration."
                    : "The previous source must still have an observed compatible output pin."}
                </>
              )}
              {booleanDefault &&
                receipt.data.intent?.default_edit?.record_ref !==
                  field?.ref && (
                  <>
                    {" "}
                    Open its recorded Boolean field{" "}
                    <code>
                      {receipt.data.intent?.default_edit?.record_ref}
                    </code>{" "}
                    before preparing.
                  </>
                )}
            </p>
          )}
          <details>
            <summary>Transfer and preservation evidence</summary>
            <pre>{JSON.stringify(receipt.data, null, 2)}</pre>
          </details>
        </section>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
