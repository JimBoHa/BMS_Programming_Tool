import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, apiKeepalive, saveBlob } from "./api";

type Target = { address: string; device: string; router: string; dnet: string };
const base = "/bacnet/device-instance";

export function DeviceInstancePanel({
  connected,
  interfaceIdentity,
  defaultAddress,
  defaultDevice,
  defaultRouter,
  defaultDnet,
  parentBusy,
  onBusy,
}: {
  connected: boolean;
  interfaceIdentity: string;
  defaultAddress: string;
  defaultDevice: string;
  defaultRouter: string;
  defaultDnet: number | null;
  parentBusy: boolean;
  onBusy: (value: boolean) => void;
}) {
  const [target, setTarget] = useState<Target>({
    address: "",
    device: "",
    router: "",
    dnet: "",
  });
  const [newInstance, setNewInstance] = useState("");
  const [allocated, setAllocated] = useState(false);
  const [plan, setPlan] = useState<any>(null);
  const [receipt, setReceipt] = useState<any>(null);
  const [receipts, setReceipts] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [hydratedDefaults, setHydratedDefaults] = useState<string | null>(null);
  const defaultsIdentity = JSON.stringify([
    connected,
    interfaceIdentity,
    defaultAddress,
    defaultDevice,
    defaultRouter,
    defaultDnet,
  ]);
  const targetReady = connected && hydratedDefaults === defaultsIdentity;
  const mounted = useRef(false);
  const operation = useRef<string | null>(null);
  const generation = useRef(0);
  const receiptEpoch = useRef(0);

  function cancel() {
    if (operation.current)
      void apiKeepalive(base + "/cancel", {
        operation_id: operation.current,
      }).catch(() => {});
  }
  async function refresh() {
    const result = await api(base + "/status");
    if (mounted.current) setReceipts(result.receipts);
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
    cancel();
    setPlan(null);
    setAllocated(false);
    setNewInstance("");
    setTarget({
      address: defaultAddress,
      device: defaultDevice,
      router: defaultRouter,
      dnet: defaultDnet == null ? "" : String(defaultDnet),
    });
    setHydratedDefaults(defaultsIdentity);
  }, [defaultsIdentity]);
  useEffect(() => {
    if (!plan) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [plan]);

  function edit(change: () => void) {
    generation.current++;
    setPlan(null);
    setAllocated(false);
    setError("");
    change();
  }
  function number(value: string, maximum: number) {
    if (!/^(0|[1-9][0-9]*)$/.test(value) || Number(value) > maximum)
      throw new Error(
        "Enter an integer in the displayed range, without signs or decimals.",
      );
    return Number(value);
  }
  async function run(kind: "preview" | "apply" | "readback") {
    if (operation.current || parentBusy || !connected) return;
    if (kind !== "readback" && !targetReady) return;
    const id = "instance-" + crypto.randomUUID();
    operation.current = id;
    const epoch = generation.current;
    setBusy(true);
    onBusy(true);
    setError("");
    // Retire history loads admitted before this operation. Readback remains
    // bound to its captured receipt even if another response arrives later.
    const operationReceiptEpoch = ++receiptEpoch.current;
    try {
      if (kind === "preview") {
        setPlan(null);
        setAllocated(false);
        const result = await api(base + "/preview", {
          operation_id: id,
          address: target.address,
          device: target.device,
          router: target.router || null,
          dnet: target.dnet ? number(target.dnet, 65534) : null,
          new_instance: number(newInstance, 4194302),
        });
        if (mounted.current && epoch === generation.current) setPlan(result);
      } else if (kind === "apply") {
        const reviewed = plan;
        setPlan(null);
        setAllocated(false);
        const result = await api(base + "/apply", {
          operation_id: id,
          token: reviewed.token,
          review_sha256: reviewed.review_sha256,
          allocation_confirmed: allocated,
        });
        if (mounted.current) {
          setReceipt({ attempt: result, readbacks: [] });
          if (epoch === generation.current && result.status === "verified") {
            generation.current++;
            setTarget((current) => ({
              ...current,
              device: `device,${result.new_instance}`,
            }));
            setNewInstance("");
          }
        }
      } else {
        const receiptId = receipt.attempt.id;
        const result = await api(base + "/readback", {
          operation_id: id,
          receipt_id: receiptId,
        });
        if (
          mounted.current &&
          operationReceiptEpoch === receiptEpoch.current &&
          result.receipt_id === receiptId
        )
          setReceipt((current: any) =>
            current?.attempt.id === receiptId
              ? { ...current, readbacks: [...current.readbacks, result] }
              : current,
          );
      }
      await refresh();
    } catch (failure) {
      if (mounted.current) {
        setError(String(failure));
        // HTTP failure may hide an already transmitted write. The durable list
        // is the recovery path; never offer an automatic resubmission.
        void refresh().catch(() => {});
      }
    } finally {
      operation.current = null;
      if (mounted.current) {
        setBusy(false);
        onBusy(false);
      }
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
  async function download() {
    try {
      const document = await apiJsonDocument(
        base + "/receipts/" + receipt.attempt.id,
      );
      saveBlob(document.blob, `device-instance-${receipt.attempt.id}.json`);
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    }
  }
  const locked = busy || parentBusy;
  const fresh = plan?.can_apply && now < Date.parse(plan.expires_at);
  const attempt = receipt?.attempt;
  const observed = receipt?.readbacks.at(-1)?.readback || attempt?.readback;
  const resolved =
    attempt?.readback?.status === "verified_new" ||
    receipt?.readbacks.some(
      (value: any) => value.readback.status === "verified_new",
    );
  return (
    <section
      id="controller-instance-commissioning"
      className="card"
      aria-label="Device instance commissioning"
    >
      <div className="card-header">
        <h2>Change controller instance</h2>
      </div>
      <div className="card-body">
        <p className="help-text">
          Writes the controller’s BACnet Device object identifier. The
          controller must support this property write; otherwise use its
          manufacturer’s commissioning tool. The client instance, network number
          and MAC stay the same.
        </p>
        <div className="form-grid">
          {(
            [
              ["address", "Controller address (IPv4 or DNET:MAC)"],
              ["device", "Current Device object (device,instance)"],
              ["router", "Instance-change router (routed targets only)"],
              ["dnet", "Instance-change network (1–65534)"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                disabled={!targetReady || locked}
                value={target[key]}
                onChange={(event) =>
                  edit(() =>
                    setTarget({ ...target, [key]: event.target.value }),
                  )
                }
              />
            </label>
          ))}
          <label>
            New controller instance (0–4194302)
            <input
              inputMode="numeric"
              disabled={!targetReady || locked}
              value={newInstance}
              onChange={(event) =>
                edit(() => setNewInstance(event.target.value))
              }
            />
          </label>
          <button
            disabled={!targetReady || locked || !newInstance || !target.device}
            onClick={() => void run("preview")}
          >
            Review instance change
          </button>
        </div>
        {plan && (
          <div aria-label="Reviewed instance change">
            <p>
              <strong>{plan.identity["object-name"]}</strong> ·{" "}
              {plan.identity["model-name"]} · firmware{" "}
              {plan.identity["firmware-revision"]}
            </p>
            <p>
              At {plan.target.address}
              {plan.target.router ? ` via ${plan.target.router}` : ""}:{" "}
              <strong>
                {plan.old_instance} → {plan.new_instance}
              </strong>
            </p>
            <p className="help-text">
              Collision query: {plan.collision_check.scope}.{" "}
              {plan.collision_check.limitation}
            </p>
            {plan.collision_check.devices.length > 0 && (
              <p role="alert">
                New instance is already responding. Choose another reserved
                number.
              </p>
            )}
            <p className="help-text">
              Review expires at {plan.expires_at}. Refresh discovery and update
              supervisor references after a verified change. No reset or
              application download is performed.
            </p>
            <label>
              <input
                type="checkbox"
                checked={allocated}
                disabled={!targetReady || locked}
                onChange={(event) => setAllocated(event.target.checked)}
              />
              I reserved this new number across the BACnet internetwork,
              including offline devices.
            </label>
            <button
              disabled={!targetReady || locked || !fresh || !allocated}
              onClick={() => void run("apply")}
            >
              Apply controller instance change
            </button>
            {!fresh && plan.can_apply && (
              <p role="status">
                Review expired. Review the instance change again.
              </p>
            )}
          </div>
        )}
        {busy && <button onClick={cancel}>Cancel instance operation</button>}
        {error && <p role="alert">{error}</p>}
        {attempt && (
          <div aria-label="Instance change receipt">
            <p>
              <strong>Result: {attempt.status}</strong> ·{" "}
              {attempt.target.address}
              {attempt.target.router
                ? ` via ${attempt.target.router}`
                : ""} · {attempt.old_instance} → {attempt.new_instance}
            </p>
            <p>
              Write acknowledgement:{" "}
              {attempt.protocol_accepted
                ? "accepted"
                : attempt.status === "rejected"
                  ? "rejected"
                  : "not confirmed"}
              . Readback: <strong>{observed?.status || "unknown"}</strong>.
            </p>
            {attempt.status === "rejected" && (
              <p>
                The controller rejected the standard property write. A read-only
                Object_Identifier requires the manufacturer’s commissioning
                tool.
              </p>
            )}
            {attempt.may_have_applied && !resolved && (
              <p role="alert">
                The change may have applied or may require time to become
                visible. Read back this station before any further
                commissioning; do not retry the write.
              </p>
            )}
            {attempt.errors?.length > 0 && (
              <pre>{attempt.errors.join("\n")}</pre>
            )}
            <button
              disabled={!connected || locked}
              onClick={() => void run("readback")}
            >
              Read back instance (no write)
            </button>
            <button disabled={locked} onClick={() => void download()}>
              Download instance receipt
            </button>
          </div>
        )}
        {receipts.length > 0 && (
          <label>
            Retained instance receipts
            <select
              aria-label="Retained instance receipts"
              disabled={locked}
              value=""
              onChange={(event) => void loadReceipt(event.target.value)}
            >
              <option value="" disabled>
                Choose an attempt
              </option>
              {receipts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.created_at} · {item.target.address} →{" "}
                  {item.new_instance} · {item.status}
                  {item.pending ? " (readback required)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </section>
  );
}
