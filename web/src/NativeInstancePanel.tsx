import { useEffect, useRef, useState } from "react";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import type { DeviceInstanceProps } from "./DeviceInstancePanel";

const base = "/bacnet/controller/native-application";

export function NativeInstancePanel(props: DeviceInstanceProps) {
  const [capture, setCapture] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [receipt, setReceipt] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [number, setNumber] = useState("");
  const [allocated, setAllocated] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [backup, setBackup] = useState("");
  const [restore, setRestore] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const mounted = useRef(false),
    generation = useRef(0),
    receiptEpoch = useRef(0);
  const operation = useRef<string | null>(null),
    review = useRef<string | null>(null);
  const selection = JSON.stringify([
    props.connected,
    props.interfaceIdentity,
    props.defaultAddress,
    props.defaultDevice,
    props.defaultRouter,
    props.defaultDnet,
  ]);
  const [hydrated, setHydrated] = useState("");
  const ready =
    props.connected &&
    hydrated === selection &&
    !!props.defaultAddress &&
    !!props.defaultDevice;
  const locked = busy || props.parentBusy;

  function cancel() {
    for (const id of new Set([operation.current, review.current]))
      if (id)
        void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
          () => {},
        );
    review.current = null;
  }
  async function refresh() {
    const result = await api(base + "/status");
    if (mounted.current) setStatus(result);
  }
  useEffect(() => {
    mounted.current = true;
    void refresh().catch((failure) => {
      if (mounted.current) setError(String(failure));
    });
    return () => {
      mounted.current = false;
      generation.current++;
      receiptEpoch.current++;
      cancel();
    };
  }, []);
  useEffect(() => {
    generation.current++;
    receiptEpoch.current++;
    cancel();
    setCapture(null);
    setPlan(null);
    setNumber("");
    setAllocated(false);
    setConfirmed(false);
    setError("");
    setHydrated(selection);
  }, [selection]);
  useEffect(() => {
    if (!plan && !busy) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      if (operation.current) void refresh().catch(() => {});
    }, 1000);
    return () => window.clearInterval(timer);
  }, [plan, busy]);
  function editNumber(value: string) {
    cancel();
    generation.current++;
    setPlan(null);
    setAllocated(false);
    setConfirmed(false);
    setNumber(value);
  }

  async function run(
    kind: "capture" | "preview" | "apply" | "readback" | "credentials",
  ) {
    if (
      operation.current ||
      props.parentBusy ||
      (kind !== "credentials" && !props.connected)
    )
      return;
    if (["capture", "preview", "apply"].includes(kind) && !ready) return;
    const id = "native-" + crypto.randomUUID(),
      epoch = generation.current,
      receiptGeneration = ++receiptEpoch.current;
    operation.current = id;
    setBusy(true);
    props.onBusy(true);
    setError("");
    const target = {
      address: props.defaultAddress,
      device: props.defaultDevice,
      router: props.defaultRouter || null,
      dnet: props.defaultDnet,
    };
    try {
      if (kind === "credentials") {
        await api(base + "/credentials", { backup, restore });
        setBackup("");
        setRestore("");
        setPlan(null);
      } else if (kind === "capture") {
        setPlan(null);
        setCapture(null);
        setAllocated(false);
        setConfirmed(false);
        const result = await api(base + "/capture", {
          ...target,
          operation_id: id,
        });
        if (mounted.current && epoch === generation.current) setCapture(result);
      } else if (kind === "preview") {
        if (!/^(0|[1-9][0-9]*)$/.test(number) || Number(number) > 4194302)
          throw new Error("Enter a Device instance from 0 through 4194302.");
        setPlan(null);
        setAllocated(false);
        setConfirmed(false);
        review.current = id;
        const result = await api(base + "/preview", {
          ...target,
          operation_id: id,
          capture_id: capture.id,
          new_instance: Number(number),
        });
        if (mounted.current && epoch === generation.current) {
          setPlan(result);
          setNow(Date.now());
        } else
          void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
            () => {},
          );
      } else {
        let result;
        if (kind === "apply") {
          const p = plan;
          setPlan(null);
          setAllocated(false);
          setConfirmed(false);
          review.current = null;
          result = await api(base + "/apply", {
            operation_id: id,
            token: p.token,
            review_sha256: p.review_sha256,
            allocation_confirmed: allocated,
            application_transfer_confirmed: confirmed,
          });
        } else
          result = await api(base + "/readback", {
            operation_id: id,
            receipt_id: receipt.intent.id,
          });
        if (mounted.current && receiptGeneration === receiptEpoch.current) {
          setReceipt(result);
          const observed =
            result.events?.filter((e: any) => e.stage === "readback").at(-1)
              ?.detail || result.result;
          if (epoch === generation.current && observed?.status === "verified") {
            setCapture(null);
            setNumber("");
            props.onVerified?.({ ...result.intent, ...observed });
          }
        }
      }
      await refresh();
    } catch (failure) {
      if (mounted.current) {
        setError(String(failure));
        void refresh().catch(() => {});
      }
    } finally {
      operation.current = null;
      if (mounted.current) setBusy(false);
      props.onBusy(false);
    }
  }
  async function loadReceipt(id: string) {
    const epoch = ++receiptEpoch.current;
    try {
      const result = await api(base + "/receipts/" + id);
      if (mounted.current && epoch === receiptEpoch.current) setReceipt(result);
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    }
  }
  async function download(kind: "backup" | "receipt") {
    try {
      const id = kind === "backup" ? capture.id : receipt.intent.id;
      const result =
        kind === "backup"
          ? await apiBlobDocument(base + "/backups/" + id)
          : await apiJsonDocument(base + "/receipts/" + id);
      saveBlob(
        result.blob,
        `native-${kind}-${id}.${kind === "backup" ? "zip" : "json"}`,
      );
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    }
  }
  const fresh = plan?.can_apply && now < Date.parse(plan.expires_at);
  const observed =
    receipt?.latest_readback ||
    receipt?.events?.filter((e: any) => e.stage === "readback").at(-1)
      ?.detail ||
    receipt?.result;
  return (
    <section
      id="controller-instance-commissioning"
      className="card"
      aria-label="Native application instance commissioning"
    >
      <div className="card-header">
        <h2>Edit connected application instance</h2>
      </div>
      <div className="card-body">
        <p>
          The app reads the controller’s application and saved parameters, edits
          its Device identity, transfers the reviewed application, then reads it
          back at the same physical station.
        </p>
        <p className="help-text">
          {props.defaultAddress}
          {props.defaultRouter ? ` via ${props.defaultRouter}` : ""} ·{" "}
          {props.defaultDevice}. Support is determined from the actual protocol
          and application format.
        </p>
        <details>
          <summary>
            Transfer credentials{" "}
            {status?.credentials_configured
              ? "— configured on this machine"
              : "— required"}
          </summary>
          <p className="help-text">
            Controller family credentials are stored privately on this machine.
          </p>
          <div className="form-grid">
            <label>
              Backup credential
              <input
                type="password"
                autoComplete="off"
                disabled={locked}
                value={backup}
                onChange={(e) => setBackup(e.target.value)}
              />
            </label>
            <label>
              Application transfer credential
              <input
                type="password"
                autoComplete="off"
                disabled={locked}
                value={restore}
                onChange={(e) => setRestore(e.target.value)}
              />
            </label>
            <button
              disabled={locked || !backup || !restore}
              onClick={() => void run("credentials")}
            >
              Save private transfer credentials
            </button>
          </div>
        </details>
        <div className="button-row" style={{ marginTop: 16 }}>
          <button
            className={!capture ? "primary" : ""}
            disabled={!ready || locked || !status?.credentials_configured}
            onClick={() => void run("capture")}
          >
            Read application backup
          </button>
          {capture && (
            <button disabled={locked} onClick={() => void download("backup")}>
              Save original backup
            </button>
          )}
        </div>
        {capture && (
          <div aria-label="Captured native application">
            <p>
              <strong>{capture.identity["object-name"]}</strong> ·{" "}
              {capture.identity["model-name"]} · captured {capture.captured_at}
            </p>
            <p>
              {capture.application.record_count ?? "Unrecognized"} application
              records. Original application and both parameter files retained.
            </p>
            {capture.instance_edit_supported === false ? (
              <p role="alert">
                This format cannot yet be compiled: {capture.compiler_error}
              </p>
            ) : (
              <div className="form-grid">
                <label>
                  New application Device instance (0–4194302)
                  <input
                    inputMode="numeric"
                    disabled={!ready || locked}
                    value={number}
                    onChange={(e) => editNumber(e.target.value)}
                  />
                </label>
                <button
                  className={!plan ? "primary" : ""}
                  disabled={!ready || locked || !number}
                  onClick={() => void run("preview")}
                >
                  Review application instance change
                </button>
              </div>
            )}
          </div>
        )}
        {plan && (
          <div aria-label="Reviewed native application transfer">
            <p>
              <strong>
                {plan.identity["object-name"]}: {plan.old_instance} →{" "}
                {plan.new_instance}
              </strong>{" "}
              at {plan.target.address}
              {plan.target.router ? ` via ${plan.target.router}` : ""}
            </p>
            <p>{plan.parameter_policy}</p>
            <p className="help-text">
              Collision check: {plan.collision_check.scope}.{" "}
              {plan.collision_check.limitation}
            </p>
            {!!plan.collision_check.devices.length && (
              <p role="alert">
                The proposed instance is already responding. Select another
                reserved number.
              </p>
            )}
            <details>
              <summary>Application change details</summary>
              <p>
                Two typed identity fields change. Other application records are
                preserved, with saved parameters merged from a fresh backup.
              </p>
              <pre>
                {JSON.stringify(plan.compilation.identity_edit.edits, null, 2)}
              </pre>
            </details>
            <p className="help-text">Review expires at {plan.expires_at}.</p>
            <label>
              <input
                type="checkbox"
                disabled={!ready || locked || !fresh}
                checked={allocated}
                onChange={(e) => setAllocated(e.target.checked)}
              />{" "}
              I reserved this instance across the BACnet internetwork, including
              offline devices.
            </label>
            <label>
              <input
                type="checkbox"
                disabled={!ready || locked || !fresh}
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />{" "}
              I reviewed this application transfer and its possible brief
              interruption of controller operation.
            </label>
            <button
              className="primary"
              disabled={!ready || locked || !fresh || !allocated || !confirmed}
              onClick={() => void run("apply")}
            >
              Apply application instance change
            </button>
            {!fresh && plan.can_apply && (
              <p role="status">
                Review expired. Review the application instance change again.
              </p>
            )}
          </div>
        )}
        {busy && (
          <p role="status">
            {status?.active?.phase || "Working with selected controller…"}{" "}
            <button onClick={cancel}>Cancel native operation</button>
          </p>
        )}
        {error && <p role="alert">{error}</p>}
        {receipt && (
          <div aria-label="Native application transfer receipt">
            <p>
              <strong>Result: {observed?.status || "unknown"}</strong>
              {receipt.intent &&
                ` · ${receipt.intent.target.address} · ${receipt.intent.old_instance} → ${receipt.intent.new_instance}`}
            </p>
            <p>
              Device readback: {observed?.readback?.status || "not read"}.
              Application readback:{" "}
              {observed?.native_sha256 &&
              observed.native_sha256 === observed.expected_native_sha256
                ? "matches transferred application"
                : "not verified"}
              .
            </p>
            {receipt.pending && (
              <p role="alert">
                This transfer is unresolved. Read back its receipt before
                another change. Do not resend it.
              </p>
            )}
            {!!observed?.errors?.length && (
              <pre>{observed.errors.join("\n")}</pre>
            )}
            {observed?.error && <p role="alert">{observed.error}</p>}
            {receipt.intent && (
              <div className="button-row">
                <button
                  disabled={!props.connected || locked}
                  onClick={() => void run("readback")}
                >
                  Read back application and instance
                </button>
                <button
                  disabled={locked}
                  onClick={() => void download("receipt")}
                >
                  Save transfer receipt
                </button>
              </div>
            )}
          </div>
        )}
        {!!status?.receipts?.length && (
          <label>
            Retained native transfer receipts
            <select
              aria-label="Retained native transfer receipts"
              value=""
              disabled={locked}
              onChange={(e) => void loadReceipt(e.target.value)}
            >
              <option value="" disabled>
                Choose a transfer
              </option>
              {status.receipts.map((r: any) => (
                <option key={r.id} value={r.id}>
                  {r.created_at} · {r.target.address} → {r.new_instance} ·{" "}
                  {r.pending ? "readback required" : r.status}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </section>
  );
}
