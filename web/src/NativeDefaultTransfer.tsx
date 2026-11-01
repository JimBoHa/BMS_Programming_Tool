import { useEffect, useRef, useState } from "react";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import { controllerKey, type ControllerContext } from "./workflow";

type Data = Record<string, any>;
const base = "/bacnet/controller/native-application";
const operationProfile = "native-effective-default-transfer/1";
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

export function NativeDefaultTransfer({
  controller,
  source,
  proposal,
  field,
  visible,
  parentBusy = false,
  onBusy,
  onCaptured,
}: {
  controller?: ControllerContext | null;
  source: Data | null;
  proposal: Data | null;
  field: Data | undefined;
  visible: boolean;
  parentBusy?: boolean;
  onBusy: (busy: boolean) => void;
  onCaptured: (id: string) => void;
}) {
  const [status, setStatus] = useState<Data | null>(null);
  const [plan, setPlan] = useState<{
    data: Data;
    blob: Blob;
    owner: string;
    epoch: number;
  } | null>(null);
  const [receipt, setReceipt] = useState<{ data: Data; blob: Blob } | null>(
    null,
  );
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
    visible,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
      controller.ownedCommands,
    ],
    source?.snapshot_sha256,
    proposal,
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
  const connected =
    !!controller?.interfaceOpen && controller.ownedCommands === 0;
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
      (!sourceMatches || !proposal || !field)
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
        const result = await apiJsonDocument(
          base + "/signal-default/transfer/preview",
          {
            ...targetOf(controller!),
            ...proposal,
            operation_id: id,
          },
        );
        const data = result.data,
          edit = data.compilation?.selected_edit;
        if (
          data.operation_profile !== operationProfile ||
          data.change_kind !== "signal-default" ||
          data.can_apply !== true ||
          data.snapshot_sha256 !== source!.snapshot_sha256 ||
          !sameTarget(data.target || {}, controller!) ||
          data.identity?.device !== controller!.device ||
          data.capture_id !== source!.capture_id ||
          !["record_ref", "encoded_sha256", "value_text"].every(
            (name) => data.default_edit?.[name] === proposal![name],
          ) ||
          edit?.before_bits !== field!.effective_bits ||
          edit?.record_ref !== field!.ref ||
          edit?.encoded_sha256 !== field!.encoded_sha256 ||
          !Number.isFinite(edit?.stored_value) ||
          edit?.after_bits !== floatBits(Number(proposal!.value_text)) ||
          edit?.after_bits !== floatBits(edit.stored_value) ||
          !/^[a-f0-9]{8}$/.test(edit?.after_bits || "") ||
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
          base +
            (kind === "apply" ? "/signal-default/transfer/apply" : "/readback"),
          kind === "apply"
            ? {
                operation_id: id,
                token: selectedPlan!.data.token,
                review_sha256: selectedPlan!.data.review_sha256,
                default_change_confirmed: confirmed,
                application_transfer_confirmed: interruption,
              }
            : { operation_id: id, receipt_id: receipt!.data.intent.id },
        );
        const intent = result.data.intent;
        if (
          intent &&
          (intent.change_kind !== "signal-default" ||
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
        result.data.intent?.change_kind !== "signal-default" ||
        result.data.intent?.operation_profile !== operationProfile
      )
        throw new Error("This is not a native default transfer receipt.");
      if (alive.current && ticket === receiptTicket.current) setReceipt(result);
    } catch (failure) {
      if (alive.current && ticket === receiptTicket.current)
        setError(String(failure));
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
    status?.receipts?.filter(
      (row: Data) => row.change_kind === "signal-default",
    ) ?? [];
  return (
    <section
      className="native-compiler-source native-default-transfer"
      aria-label="Native default controller transfer"
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
          defaults. Local compilation remains available.
        </p>
      )}
      <p>
        Capture and readback enter and end backup mode. Apply transfers one
        native application and can interrupt controller operation. Device
        identity stays unchanged.
      </p>
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
          disabled={localLocked || !connected || !proposal}
          onClick={() => void run("preview")}
        >
          Review controller default transfer
        </button>
      )}
      {shown && (
        <section
          className="native-compiler-source"
          aria-label="Reviewed controller default transfer"
        >
          <h3>Review controller default transfer</h3>
          <p>
            {shown.data.default_edit.record_ref} ·{" "}
            {shown.data.compilation.selected_edit.before_bits} →{" "}
            {shown.data.compilation.selected_edit.after_bits} · stored value{" "}
            {Object.is(shown.data.compilation.selected_edit.stored_value, -0)
              ? "-0"
              : String(shown.data.compilation.selected_edit.stored_value)}
            .
          </p>
          <p>{shown.data.parameter_policy}</p>
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
            I confirm the selected controller, native default and proposed
            value.
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
              Apply native default to controller
            </button>
            <button
              onClick={() =>
                saveBlob(shown.blob, "native-default-transfer-review.json")
              }
            >
              Export exact transfer review
            </button>
          </div>
        </section>
      )}
      {busy && (
        <div role="status">
          Native operation in progress.{" "}
          <button onClick={cancel}>Stop native operation</button>
        </div>
      )}
      {!!receipts.length && (
        <details open={!!receipts.some((row: Data) => row.pending)}>
          <summary>
            Retained native default transfers ({receipts.length})
          </summary>
          <table aria-label="Native default transfer receipts">
            <thead>
              <tr>
                <th>Controller station</th>
                <th>Default</th>
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
                  <td>{row.default_edit?.record_ref}</td>
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
        <section aria-label="Native default transfer outcome">
          <h3>
            {observed?.status === "verified"
              ? "Verified native default transfer"
              : observed?.status === "not_sent"
                ? "Native default transfer not sent"
                : "Native default transfer outcome uncertain"}
          </h3>
          {receipt.data.intent && (
            <p>
              Receipt station: {receipt.data.intent.identity.device} ·{" "}
              {receipt.data.intent.target.address}
              {receipt.data.intent.target.router
                ? ` via ${receipt.data.intent.target.router} / DNET ${receipt.data.intent.target.dnet}`
                : ""}{" "}
              · {receipt.data.intent.default_edit.record_ref}.
            </p>
          )}
          <p>{observed?.error || observed?.errors?.join(" ")}</p>
          {observed?.status === "verified" ? (
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
                saveBlob(receipt.blob, "native-default-transfer-receipt.json")
              }
            >
              Export exact transfer receipt
            </button>
            {receipt.data.intent && (
              <button
                disabled={localLocked || !connected || !receiptMatches}
                onClick={() => void run("readback")}
              >
                Read back native default transfer
              </button>
            )}
          </div>
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
