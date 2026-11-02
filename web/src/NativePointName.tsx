import { useEffect, useRef, useState } from "react";
import { NativeRuntimeCalibration } from "./NativeRuntimeCalibration";
import { NativeRuntimeParametersNotice } from "./NativeRuntimeParametersNotice";
import { api, apiKeepalive, apiJsonDocument, saveBlob } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";

const base = "/bacnet/controller/native-application";
type Work = { name: string; capture: any; field: any; receipt: any };
const drafts = new Map<string, Work>();

export function NativePointName({
  controller,
  object,
  connected,
  onBusy,
  onVerified,
}: {
  controller: ControllerContext;
  object: string;
  connected: boolean;
  onBusy: (busy: boolean) => void;
  onVerified: () => void;
}) {
  const source = controllerKey(controller) + controller.interfaceKey + object;
  const [work, setWork] = useState<Work>(
    () =>
      drafts.get(source) ?? {
        name: "",
        capture: null,
        field: null,
        receipt: null,
      },
  );
  const [review, setReview] = useState<any>(null),
    [status, setStatus] = useState<any>(null);
  const [busy, setBusy] = useState(false),
    [confirmed, setConfirmed] = useState(false),
    [transfer, setTransfer] = useState(false),
    [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const epoch = useRef(0),
    active = useRef<string | null>(null),
    reviewOperation = useRef<string | null>(null);
  const target = {
    address: controller.address,
    device: controller.device,
    router: controller.router || null,
    dnet: controller.dnet ?? null,
  };
  const targetMatches = (value: any) =>
    value?.address === target.address &&
    (value.router || null) === target.router &&
    (value.dnet ?? null) === target.dnet;
  const matchesReceipt = (value: any) =>
    value?.intent?.change_kind === "point-name" &&
    targetMatches(value.intent.target) &&
    value.intent.identity?.device === controller.device &&
    value.intent.point_name_edit?.object_id === object;
  function cancelReview() {
    if (reviewOperation.current)
      void apiKeepalive(base + "/cancel", {
        operation_id: reviewOperation.current,
      }).catch(() => {});
    reviewOperation.current = null;
    setReview(null);
    setConfirmed(false);
    setTransfer(false);
  }
  useEffect(() => {
    void api(base + "/status")
      .then(setStatus)
      .catch((e) => setError(String(e)));
    return () => {
      epoch.current++;
      for (const id of new Set([active.current, reviewOperation.current]))
        if (id)
          void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
            () => {},
          );
      onBusy(false);
    };
  }, []);
  useEffect(() => {
    drafts.delete(source);
    drafts.set(source, work);
    while (drafts.size > 32) drafts.delete(drafts.keys().next().value!);
  }, [source, work]);
  useEffect(() => {
    if (!review) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [review]);
  useEffect(() => {
    if (!connected) {
      epoch.current++;
      cancelReview();
    }
  }, [connected]);
  async function run(kind: "capture" | "review" | "apply" | "readback") {
    if (!connected || busy) return;
    const current = ++epoch.current,
      operation_id = crypto.randomUUID();
    active.current = operation_id;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      if (kind === "capture") {
        cancelReview();
        const capture = await api(base + "/capture", {
          ...target,
          operation_id,
        });
        if (current !== epoch.current) return;
        if (
          !capture.source_identity_matches ||
          !capture.instance_edit_supported ||
          !targetMatches(capture.target) ||
          capture.device !== controller.device
        )
          throw new Error(
            capture.compiler_error || "Capture does not match this controller.",
          );
        const source = await api(base + "/point-name/source", {
          ...target,
          capture_id: capture.id,
          snapshot_sha256: capture.snapshot_evidence_sha256,
        });
        if (current !== epoch.current) return;
        if (
          source.profile !== "native-point-name-transfer/1" ||
          source.capture_id !== capture.id ||
          source.snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
          !targetMatches(source.target) ||
          source.device !== controller.device
        )
          throw new Error(
            "Point-name source differs from the selected backup.",
          );
        const field = source.points.find((p: any) => p.object_id === object);
        if (!field)
          throw new Error(
            "This application has no supported native name for the selected point.",
          );
        setWork((w) => ({ ...w, capture, field }));
      } else if (kind === "review") {
        cancelReview();
        const result = await api(base + "/point-name/preview", {
          ...target,
          operation_id,
          capture_id: work.capture.id,
          snapshot_sha256: work.capture.snapshot_evidence_sha256,
          object_id: object,
          record_ref: work.field.record_ref,
          encoded_sha256: work.field.encoded_sha256,
          new_name: work.name,
        });
        if (current !== epoch.current) {
          void apiKeepalive(base + "/cancel", { operation_id }).catch(() => {});
          return;
        }
        if (
          result.change_kind !== "point-name" ||
          !targetMatches(result.target) ||
          result.identity?.device !== controller.device ||
          result.point_name_edit?.object_id !== object ||
          result.point_name_edit?.new_name !== work.name
        )
          throw new Error("Point-name review differs from this draft.");
        reviewOperation.current = operation_id;
        setReview(result);
        setNow(Date.now());
      } else {
        const plan = review;
        if (kind === "apply") {
          reviewOperation.current = null;
          setReview(null);
          setConfirmed(false);
          setTransfer(false);
        }
        const result = await api(
          base + (kind === "apply" ? "/point-name/apply" : "/readback"),
          kind === "apply"
            ? {
                operation_id,
                token: plan.token,
                review_sha256: plan.review_sha256,
                point_name_confirmed: confirmed,
                application_transfer_confirmed: transfer,
              }
            : { operation_id, receipt_id: work.receipt.intent.id },
        );
        if (current !== epoch.current) return;
        if (result.intent && !matchesReceipt(result))
          throw new Error(
            "Retain this receipt: it belongs to another point or controller.",
          );
        setWork((w) => ({ ...w, receipt: result }));
        const observed = result.latest_readback || result.result;
        if (observed?.status === "verified" && !result.pending) {
          setWork((w) => ({
            ...w,
            name: "",
            capture: null,
            field: null,
            receipt: result,
          }));
          onVerified();
        }
      }
      const result = await api(base + "/status");
      if (current === epoch.current) setStatus(result);
    } catch (e) {
      if (current === epoch.current) setError(String(e));
    } finally {
      active.current = null;
      setBusy(false);
      onBusy(false);
    }
  }
  const observed = work.receipt?.latest_readback || work.receipt?.result;
  const fresh = review?.can_apply && now < Date.parse(review.expires_at);
  const retained =
    status?.receipts?.filter(
      (r: any) =>
        r.change_kind === "point-name" &&
        r.point_object_id === object &&
        targetMatches(r.target),
    ) ?? [];
  return (
    <details>
      <summary>Edit point name</summary>
      <section aria-label="Native point name configuration">
        <p>
          Rename {object} in this controller’s application. The point keeps its
          identifier, wiring and logic references. Supervisor labels are
          separate. Applying briefly interrupts control.
        </p>
        {!status?.credentials_configured && (
          <p>
            Configure private transfer credentials in Overview → Identity
            settings.
          </p>
        )}
        <button
          disabled={!connected || busy || !status?.credentials_configured}
          onClick={() => void run("capture")}
        >
          Read point name backup
        </button>
        {work.field && (
          <>
            <p>
              Captured name: <strong>{work.field.name}</strong> ·{" "}
              {work.field.object_id}
            </p>
            <label>
              New point name
              <input
                value={work.name}
                maxLength={128}
                disabled={busy}
                onChange={(e) => {
                  cancelReview();
                  setWork((w) => ({ ...w, name: e.target.value }));
                }}
              />
            </label>
            <button
              className="primary"
              disabled={
                !connected ||
                busy ||
                !work.name ||
                work.name === work.field.name
              }
              onClick={() => void run("review")}
            >
              Review point name change
            </button>
          </>
        )}
        {review && (
          <section aria-label="Reviewed point name change">
            <p>
              <strong>
                {review.compilation.selected_edit.before} →{" "}
                {review.point_name_edit.new_name}
              </strong>{" "}
              · {object}
            </p>
            <p>{review.parameter_policy}</p>
            <NativeRuntimeParametersNotice
              parameters={review.compilation.parameter_merge}
            />
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                disabled={!fresh || busy}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              I confirm this point name change.
            </label>
            <label>
              <input
                type="checkbox"
                checked={transfer}
                disabled={!fresh || busy}
                onChange={(e) => setTransfer(e.target.checked)}
              />
              I reviewed the application transfer and brief interruption.
            </label>
            <button
              className="primary"
              disabled={!connected || busy || !fresh || !confirmed || !transfer}
              onClick={() => void run("apply")}
            >
              Apply point name
            </button>
            {!fresh && (
              <p role="status">Review expired. Review this point name again.</p>
            )}
          </section>
        )}
        {busy && <p role="status">Working with the selected controller…</p>}
        {error && <p role="alert">{error}</p>}
        {work.receipt && (
          <section aria-label="Point name transfer receipt">
            <NativeRuntimeCalibration report={observed?.runtime_calibration} />
            <p>
              Result: <strong>{observed?.status || "unknown"}</strong>.
              Published name: {observed?.published_point_name || "not verified"}
              .
            </p>
            {work.receipt.pending && (
              <p role="alert">
                Outcome uncertain. Read back this receipt before another change.
              </p>
            )}
            {(observed?.error || observed?.errors?.length > 0) && (
              <p role="alert">{observed.error || observed.errors.join(" ")}</p>
            )}
            {work.receipt.intent && (
              <>
                <button
                  disabled={!connected || busy}
                  onClick={() => void run("readback")}
                >
                  Read back point name
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void apiJsonDocument(
                      base + "/receipts/" + work.receipt.intent.id,
                    )
                      .then((d) => saveBlob(d.blob, "point-name-receipt.json"))
                      .catch((e) => setError(String(e)))
                  }
                >
                  Save point name receipt
                </button>
              </>
            )}
          </section>
        )}
        {retained.length > 0 && (
          <label>
            Retained point name transfer
            <select
              aria-label="Retained point name transfer"
              disabled={busy}
              value=""
              onChange={(e) => {
                const current = ++epoch.current;
                cancelReview();
                void api(base + "/receipts/" + e.target.value)
                  .then((receipt) => {
                    if (current === epoch.current && matchesReceipt(receipt))
                      setWork((w) => ({ ...w, receipt }));
                  })
                  .catch((e) => setError(String(e)));
              }}
            >
              <option value="" disabled>
                Choose a transfer receipt
              </option>
              {retained.map((r: any) => (
                <option key={r.id} value={r.id}>
                  {r.created_at} · {r.status}
                </option>
              ))}
            </select>
          </label>
        )}
      </section>
    </details>
  );
}
