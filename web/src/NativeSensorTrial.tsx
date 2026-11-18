import { useEffect, useRef, useState } from "react";
import { randomUUID, sha256Digest } from "./browserCrypto";
import { api, apiBlobDocument, apiKeepalive, saveBlob } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import "./native-sensor-trial.css";

const base = "/bacnet/controller/native-application";
const endpoint = base + "/sensor-trial";
const profile = "native-netsensor-compatibility-trial/1";
type Work = {
  source: any;
  sensor: string;
  addresses: string;
  instance: string;
  units: number;
  receipt: any;
  observation: any;
};
const drafts = new Map<string, Work>();
const blank = (): Work => ({
  source: null,
  sensor: "",
  addresses: "199,200,201,202,203,204,205,206",
  instance: "",
  units: 64,
  receipt: null,
  observation: null,
});
const same = (a: any, b: any): boolean => {
  const canonical = (v: any): string =>
    JSON.stringify(v, (_key, x) =>
      x && typeof x === "object" && !Array.isArray(x)
        ? Object.fromEntries(
            Object.keys(x)
              .sort()
              .map((k) => [k, x[k]]),
          )
        : x,
    );
  return canonical(a) === canonical(b);
};

export function NativeSensorTrial({
  controller,
  connected,
  onBusy,
  onClose,
}: {
  controller: ControllerContext | null;
  connected: boolean;
  onBusy: (value: boolean) => void;
  onClose: () => void;
}) {
  const owner = controller
    ? controllerKey(controller) + controller.interfaceKey
    : "offline-sensor-trial";
  const [work, setWork] = useState<Work>(() => drafts.get(owner) || blank());
  const [sources, setSources] = useState<any[]>([]),
    [receipts, setReceipts] = useState<any[]>([]);
  const [chosen, setChosen] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [review, setReview] = useState<any>(null),
    [copyReview, setCopyReview] = useState<any>(null);
  const [confirmed, setConfirmed] = useState(false),
    [transfer, setTransfer] = useState(false);
  const epoch = useRef(0),
    mounted = useRef(true),
    operation = useRef<string | null>(null),
    plan = useRef<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const target = {
    address: controller?.address,
    device: controller?.device,
    router: controller?.router || null,
    dnet: controller?.dnet ?? null,
  };
  const matches = (value: any) =>
    !!controller &&
    value?.address === target.address &&
    (value?.router || null) === target.router &&
    (value?.dnet ?? null) === target.dnet;
  const sourceMatches =
    matches(work.source?.target) &&
    work.source?.identity?.device === target.device;
  const current = (value: number) => mounted.current && epoch.current === value;
  const latest = work.receipt?.latest_readback || work.receipt?.result;
  const sourceRetired =
    !!work.receipt?.intent &&
    sourceMatches &&
    Date.parse(work.source?.captured_at) <
      Date.parse(work.receipt.intent.created_at);
  const originalReceipt =
    work.receipt?.intent?.sensor_action === "install"
      ? work.receipt?.intent?.id
      : work.receipt?.intent?.trial_receipt;
  const restored = (work.receipt?.intent?.sensor_action === "restore" && latest?.status === "verified") ||
    work.receipt?.events?.some((e: any) => e.stage === "sensor-trial-restored");
  function retire() {
    if (plan.current)
      void apiKeepalive(endpoint + "/cancel", {
        operation_id: plan.current,
      }).catch(() => {});
    plan.current = null;
    setReview(null);
    setConfirmed(false);
    setTransfer(false);
  }
  function update(change: Partial<Work>) {
    epoch.current++;
    retire();
    setCopyReview(null);
    setError("");
    setWork((value) => ({ ...value, ...change }));
  }
  async function refresh(value: number) {
    const [s, r] = await Promise.all([
      api(base + "/input/sources"),
      api(endpoint + "/status"),
    ]);
    if (current(value)) {
      setSources(s.sources);
      setReceipts(r.receipts);
    }
  }
  useEffect(() => {
    mounted.current = true;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    const leave = () => {
      epoch.current++;
      retire();
      if (operation.current)
        void apiKeepalive(endpoint + "/cancel", {
          operation_id: operation.current,
        }).catch(() => {});
    };
    const visibility = () => {
      if (document.hidden) leave();
    };
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      mounted.current = false;
      leave();
      window.clearInterval(timer);
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", visibility);
      onBusy(false);
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    retire();
    setCopyReview(null);
    setChosen("");
    setWork(drafts.get(owner) || blank());
    setBusy(false);
    onBusy(false);
    void refresh(epoch.current).catch((e) => setError(String(e)));
  }, [owner, connected]);
  useEffect(() => {
    if (work.source || work.receipt) {
      if (drafts.has(owner) || drafts.size < 32) drafts.set(owner, work);
      else
        setError(
          "Sensor drafts are full. Close and discard an earlier draft before loading another source.",
        );
    }
  }, [work, owner]);
  function edit() {
    const sensor = work.source?.sensors.find(
      (s: any) => s.sensor_ref === work.sensor,
    );
    const addresses = work.addresses.split(",").map((v) => v.trim());
    if (
      !sensor ||
      !addresses.length ||
      addresses.some((v) => !/^\d+$/.test(v)) ||
      !/^\d+$/.test(work.instance)
    )
      throw new Error(
        "Choose a captured NS8000 definition, numeric addresses and a first trial identifier.",
      );
    return {
      sensor_ref: sensor.sensor_ref,
      sensor_sha256: sensor.sensor_sha256,
      addresses: addresses.map(Number),
      first_instance: Number(work.instance),
      units: work.units,
    };
  }
  async function load(capture: any, value: number) {
    if (!drafts.has(owner) && drafts.size >= 32)
      throw new Error(
        "Sensor drafts are full. Discard an earlier local draft first.",
      );
    const request = {
      capture_id: capture.capture_id || capture.id,
      snapshot_sha256:
        capture.snapshot_sha256 || capture.snapshot_evidence_sha256,
    };
    const source = await api(endpoint + "/source", request);
    if (!current(value)) return;
    if (
      source.profile !== profile ||
      source.capture_id !== request.capture_id ||
      source.snapshot_sha256 !== request.snapshot_sha256
    )
      throw new Error(
        "The sensor source differs from the selected native capture.",
      );
    setWork((w) => ({
      ...w,
      source,
      sensor: source.sensors[0]?.sensor_ref || "",
      observation: null,
    }));
    if (
      connected &&
      matches(source.target) &&
      source.identity.device === target.device
    ) {
      const support = await api(endpoint + "/support", {
        ...target,
        ...request,
        operation_id: "sensor-support-" + randomUUID(),
      });
      if (current(value)) {
        if (
          support.profile !== profile ||
          support.capture_id !== request.capture_id ||
          !matches(support.target)
        )
          throw new Error(
            "The identifier response belongs to another controller or source.",
          );
        setWork((w) => ({
          ...w,
          instance: String(support.next_available_instance),
        }));
      }
    }
  }
  async function run(action: string, retained?: any) {
    if (busy) return;
    const value = ++epoch.current;
    const op = "sensor-" + action + "-" + randomUUID();
    if (action !== "apply") retire();
    if (!["copy-review", "copy-export"].includes(action)) setCopyReview(null);
    setBusy(true);
    onBusy(true);
    setError("");
    operation.current = op;
    try {
      if (action === "capture") {
        const capture = await api(base + "/capture", {
          ...target,
          operation_id: op,
        });
        if (current(value)) await load(capture, value);
      } else if (action === "load") {
        const capture = sources.find((s) => s.capture_id === chosen);
        if (!capture) throw new Error("Choose a retained native capture.");
        await load(capture, value);
      } else if (action === "copy-review" || action === "copy-export") {
        const request = {
          capture_id: work.source.capture_id,
          snapshot_sha256: work.source.snapshot_sha256,
          edit: edit(),
        };
        if (action === "copy-review") {
          const result = await api(endpoint + "/copy-review", request);
          if (current(value)) {
            if (
              result.profile !== profile ||
              result.capture_id !== request.capture_id ||
              !same(result.edit, request.edit) ||
              result.can_apply !== false
            )
              throw new Error(
                "The local copy review differs from this source or edit.",
              );
            setCopyReview(result);
          }
        } else {
          const document = await apiBlobDocument(endpoint + "/copy-export", {
            ...request,
            expected_review_sha256: copyReview.review_sha256,
          });
          if (!current(value)) return;
          const digest = Array.from(
            new Uint8Array(
              await sha256Digest(await document.blob.arrayBuffer()),
            ),
            (v) => v.toString(16).padStart(2, "0"),
          ).join("");
          if (digest !== copyReview.output_sha256)
            throw new Error(
              "The downloaded copy differs from the reviewed application bytes.",
            );
          if (current(value))
            saveBlob(document.blob, "netsensor-trial-copy.moz");
        }
      } else if (action === "review" || action === "restore") {
        let source = work.source;
        if (action === "restore") {
          const capture = await api(base + "/capture", {
            ...target,
            operation_id: op + "-capture",
          });
          if (!current(value)) return;
          source = await api(endpoint + "/source", {
            capture_id: capture.id,
            snapshot_sha256: capture.snapshot_evidence_sha256,
          });
        }
        const request = {
          ...target,
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
          operation_id: op,
          action: action === "restore" ? "restore" : "install",
          trial_receipt: action === "restore" ? originalReceipt : null,
          edit: action === "restore" ? null : edit(),
        };
        const result = await api(endpoint + "/preview", request);
        if (current(value)) {
          if (result.profile !== profile || !same(result.request, request))
            throw new Error(
              "The sensor review differs from the selected controller, source or proposal.",
            );
          plan.current = op;
          setReview({ ...result, received: Date.now() });
        } else
          void apiKeepalive(endpoint + "/cancel", { operation_id: op }).catch(
            () => {},
          );
      } else if (action === "apply") {
        const selected = review;
        if (
          !selected ||
          now >= selected.received + selected.expires_seconds * 1000
        )
          throw new Error("The sensor review expired.");
        plan.current = null;
        setReview(null);
        setConfirmed(false);
        setTransfer(false);
        const result = await api(endpoint + "/apply", {
          operation_id: op,
          token: selected.token,
          review_sha256: selected.review_sha256,
          sensor_trial_confirmed: confirmed,
          application_transfer_confirmed: transfer,
        });
        if (
          result.intent &&
          (result.intent.operation_profile !== profile ||
            result.intent.operation_id !== op ||
            !matches(result.intent.target) ||
            !same(result.intent.identity, selected.identity) ||
            result.intent.review_sha256 !== selected.review_sha256 ||
            result.intent.sensor_action !== selected.request.action)
        )
          throw new Error(
            "The returned sensor receipt differs from this exact reviewed transfer.",
          );
        if (
          !result.intent &&
          !(result.pending === false && result.result?.status === "not_sent")
        )
          throw new Error(
            "No attributable sensor transfer receipt was returned. Reopen retained evidence before another write.",
          );
        if (current(value))
          setWork((w) => ({ ...w, receipt: result, observation: null }));
      } else if (action === "receipt") {
        if (
          !retained ||
          !matches(retained.intent?.target) ||
          retained.intent?.identity?.device !== target.device
        )
          throw new Error(
            "Select this controller before reopening its retained sensor receipt.",
          );
        setWork((w) => ({ ...w, receipt: retained, observation: null }));
      } else {
        const result = await api(
          endpoint + (action === "observe" ? "/observe" : "/readback"),
          {
            ...target,
            operation_id: op,
            receipt_id: work.receipt.intent.id,
          },
        );
        if (current(value)) {
          if (action === "observe") {
            if (
              result.profile !== profile ||
              result.receipt_id !== work.receipt.intent.id ||
              !matches(result.target) ||
              !same(result.identity, work.receipt.intent.identity)
            )
              throw new Error(
                "The sensor observation differs from the selected trial.",
              );
            setWork((w) => ({ ...w, observation: result }));
          } else {
            if (
              result.intent?.id !== work.receipt.intent.id ||
              result.intent?.evidence_sha256 !==
                work.receipt.intent.evidence_sha256
            )
              throw new Error(
                "The readback belongs to another sensor transfer.",
              );
            setWork((w) => ({ ...w, receipt: result, observation: null }));
          }
        }
      }
      if (current(value)) await refresh(value);
    } catch (failure) {
      if (current(value)) {
        setError(String(failure));
        await refresh(value).catch(() => {});
      }
    } finally {
      if (operation.current === op) operation.current = null;
      if (current(value)) {
        setBusy(false);
        onBusy(false);
      }
    }
  }
  const validReview =
    review && now < review.received + review.expires_seconds * 1000;
  const receiptMatches =
    matches(work.receipt?.intent?.target) &&
    work.receipt?.intent?.identity?.device === target.device;
  return (
    <section
      aria-label="Sensor definition compatibility"
      className="native-inputs native-sensor-trial"
    >
      <div className="button-row">
        <button disabled={busy} onClick={onClose}>
          Back to input configuration
        </button>
        <h3>Sensor definition compatibility</h3>
      </div>
      <p>
        Test the legacy NetSensor definition with unconnected temperature
        readers. The existing NS8000 definition is temporarily disabled.
        Existing control inputs and NAE point references stay unchanged. Apply
        and Restore transfer the application and can interrupt control.
      </p>
      <p>
        {controller
          ? `${controller.name} · ${controller.address} · ${controller.device}`
          : "Offline native capture inspection"}{" "}
        · {connected ? "Interface open" : "Interface closed"}
      </p>
      <div className="button-row">
        <button
          className={connected && !review && (!work.source || sourceRetired) ? "primary" : ""}
          disabled={busy || !connected || !controller}
          onClick={() => void run("capture")}
        >
          Capture sensor configuration
        </button>
        <label>
          Retained sensor capture
          <select
            aria-label="Retained sensor capture"
            disabled={busy}
            value={chosen}
            onChange={(event) => {
              retire();
              setChosen(event.target.value);
            }}
          >
            <option value="">Choose a retained capture</option>
            {sources.map((s) => (
              <option key={s.capture_id} value={s.capture_id}>
                {s.identity?.["object-name"]} · {s.captured_at}
              </option>
            ))}
          </select>
        </label>
        <button disabled={busy || !chosen} onClick={() => void run("load")}>
          Open sensor capture
        </button>
      </div>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <p role="status">
        {busy
          ? "Working on the selected sensor task…"
          : review
            ? "Review the exact trial before Apply."
            : "Local copies and live controller transfers are separate actions."}
      </p>
      {work.source && (
        <>
          {sourceRetired && (
            <p>
              This source predates the retained transfer. Capture sensor
              configuration again before another controller trial.
            </p>
          )}
          <p>
            Captured source: {work.source.identity["object-name"]} ·{" "}
            {work.source.capture_id}.{" "}
            {sourceMatches
              ? "Matches selected controller."
              : "Local inspection; this source does not match the selected controller."}
          </p>
          {!work.source.sensors.length && (
            <p>
              No enabled NS8000 definition is eligible in this capture. An
              installed trial is restored through its retained receipt below.
            </p>
          )}
          {!!work.source.sensors.length && (
            <>
              <label>
                NS8000 definition
                <select
                  aria-label="NS8000 definition"
                  disabled={busy}
                  value={work.sensor}
                  onChange={(e) => update({ sensor: e.target.value })}
                >
                  {work.source.sensors.map((s: any) => (
                    <option key={s.sensor_ref} value={s.sensor_ref}>
                      {s.name} · SA {s.address}
                    </option>
                  ))}
                </select>
              </label>
              <div className="form-grid">
                <label>
                  Trial SA addresses
                  <input
                    aria-label="Trial SA addresses"
                    disabled={busy}
                    value={work.addresses}
                    onChange={(e) => update({ addresses: e.target.value })}
                  />
                </label>
                <label>
                  First trial identifier
                  <input
                    aria-label="First trial identifier"
                    disabled={busy}
                    inputMode="numeric"
                    value={work.instance}
                    onChange={(e) => update({ instance: e.target.value })}
                  />
                </label>
                <label>
                  Trial temperature units
                  <select
                    aria-label="Trial temperature units"
                    disabled={busy}
                    value={work.units}
                    onChange={(e) => update({ units: Number(e.target.value) })}
                  >
                    <option value={64}>°F</option>
                    <option value={62}>°C</option>
                  </select>
                </label>
              </div>
              <div className="button-row">
                <button disabled={busy} onClick={() => void run("copy-review")}>
                  Review local trial copy
                </button>
                {copyReview && (
                  <button
                    disabled={busy}
                    onClick={() => void run("copy-export")}
                  >
                    Save trial application copy
                  </button>
                )}
                <button
                  className={!review && !sourceRetired ? "primary" : ""}
                  disabled={
                    busy || !connected || !sourceMatches || sourceRetired
                  }
                  onClick={() => void run("review")}
                >
                  Review controller sensor trial
                </button>
              </div>
              {copyReview && (
                <p>
                  Local copy reviewed:{" "}
                  {copyReview.compilation.added_native_records} new unconnected
                  records. Saving this copy sends no controller request.
                </p>
              )}
            </>
          )}
        </>
      )}
      {review && (
        <section aria-label="Sensor trial review">
          <h4>
            {review.request.action === "restore"
              ? "Restore original sensor definition"
              : "Install temporary NetSensor readers"}
          </h4>
          <p>
            {review.identity["object-name"]} · {review.request.address} ·{" "}
            {review.identity.device}
          </p>
          <p>
            {review.request.action === "restore"
              ? "Remove the owned trial readers and restore the original NS8000 enable state."
              : `Disable ${review.compilation.original_sensor.name}; add temperature readers at SA ${review.compilation.trial_points.map((p: any) => p.address).join(", ")}.`}
          </p>
          <p>
            {validReview
              ? "One-use review is current."
              : "Review expired; review the change again."}
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I reviewed the exact controller, addresses and reversible sensor
            trial.
          </label>
          <label>
            <input
              type="checkbox"
              checked={transfer}
              onChange={(e) => setTransfer(e.target.checked)}
            />
            I authorize the application transfer and temporary control
            interruption.
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={
                busy || !connected || !validReview || !confirmed || !transfer
              }
              onClick={() => void run("apply")}
            >
              Apply reviewed sensor change
            </button>
            <button disabled={busy} onClick={retire}>
              Cancel sensor review
            </button>
          </div>
        </section>
      )}
      {work.receipt && (
        <section aria-label="Sensor trial result">
          <h4>
            {busy ? "Earlier application transfer" : "Application transfer"}:{" "}
            {latest?.status || "unknown"}
          </h4>
          <p>{latest?.errors?.join(" ")}</p>
          <p>
            Receipt {work.receipt.intent?.id || "not sent"}. Sensor
            communication requires separate live reads.
          </p>
          <div className="button-row">
            <button
              disabled={
                busy || !connected || !receiptMatches || !work.receipt.intent
              }
              onClick={() => void run("readback")}
            >
              Read back sensor transfer
            </button>
              {work.receipt.intent?.sensor_action === "install" && !restored && (
              <button
                disabled={
                  busy || !connected || !receiptMatches || work.receipt.pending
                }
                onClick={() => void run("observe")}
              >
                Read trial sensor values
              </button>
            )}
              {originalReceipt && !restored && (
              <button
                disabled={
                  busy || !connected || !receiptMatches || work.receipt.pending
                }
                onClick={() => void run("restore")}
              >
                Review restoring original definition
              </button>
            )}
          </div>
          {work.observation && (
            <div
              className="table-scroll"
              role="region"
              aria-label="Trial sensor readings"
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    <th>SA address</th>
                    <th>Temperature</th>
                    <th>Quality</th>
                    <th>Device offline</th>
                  </tr>
                </thead>
                <tbody>
                  {work.observation.readings.map((r: any) => (
                    <tr key={r.address}>
                      <td>{r.address}</td>
                      <td>
                        {r.status === "live"
                          ? `${r.temperature} ${r.units === 64 ? "°F" : "°C"}`
                          : "Unavailable"}
                      </td>
                      <td>
                        {r.status}
                        {r.reliability != null
                          ? ` · reliability ${r.reliability}`
                          : ""}
                        {r.errors?.join(" ")}
                      </td>
                      <td>{String(r.offline ?? "unconfirmed")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <details>
            <summary>Sensor transfer and preservation evidence</summary>
            <pre>{JSON.stringify(work.receipt, null, 2)}</pre>
          </details>
        </section>
      )}
      <details>
        <summary>Retained sensor trials and recovery</summary>
        {receipts.map((r) => (
          <p key={r.intent.id}>
            {r.intent.identity["object-name"]} · {r.intent.sensor_action} ·{" "}
            {r.latest_readback?.status || r.result?.status || "unknown"} ·{" "}
            {r.intent.created_at}{" "}
            <button
              disabled={
                busy ||
                !connected ||
                !matches(r.intent.target) ||
                r.intent.identity.device !== target.device
              }
              onClick={() => void run("receipt", r)}
            >
              Open sensor receipt {r.intent.id.slice(0, 8)}
            </button>
          </p>
        ))}
      </details>
      <button
        disabled={busy}
        onClick={() => {
          epoch.current++;
          retire();
          setCopyReview(null);
          drafts.delete(owner);
          setWork(blank());
        }}
      >
        Discard local sensor draft
      </button>
    </section>
  );
}
