import { useEffect, useRef, useState } from "react";
import { NativeRuntimeCalibration } from "./NativeRuntimeCalibration";
import { NativeRuntimeParametersNotice } from "./NativeRuntimeParametersNotice";
import { api, apiKeepalive, apiJsonDocument, saveBlob } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import {
  canRememberPointNameWork,
  emptyPointNameWork,
  hasPointNameWork,
  rememberPointNameWork,
  type PointNameWork,
} from "./nativePointNameWork";

const base = "/bacnet/controller/native-application";
const profile = "native-point-name-transfer/1";
const drafts = new Map<string, PointNameWork>();
const capacityMessage =
  "Local point name work is full (32 points). Open an earlier point and discard its local work before capturing another. Retained transfer receipts remain available.";
const sameEdit = (a: any, b: any) =>
  a &&
  b &&
  ["object_id", "record_ref", "encoded_sha256", "new_name"].every(
    (key) => a[key] === b[key],
  );

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
  const source = JSON.stringify([
    controllerKey(controller),
    controller.interfaceKey,
    object,
  ]);
  const [work, setWork] = useState<PointNameWork>(
    () => drafts.get(source) ?? emptyPointNameWork(),
  );
  const [review, setReview] = useState<any>(null),
    [status, setStatus] = useState<any>(null);
  const [busy, setBusy] = useState(false),
    [confirmed, setConfirmed] = useState(false),
    [transfer, setTransfer] = useState(false),
    [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const epoch = useRef(0),
    mounted = useRef(true),
    active = useRef<string | null>(null),
    reviewOperation = useRef<string | null>(null);
  const currentWork = useRef(work);
  currentWork.current = work;
  const currentOwner = (current: number) =>
    mounted.current && current === epoch.current;
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
    value.intent.operation_profile === profile &&
    /^[a-f0-9]{32}$/.test(value.intent.id) &&
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
    mounted.current = true;
    const current = epoch.current;
    void api(base + "/status")
      .then((value) => {
        if (currentOwner(current)) setStatus(value);
      })
      .catch((e) => {
        if (currentOwner(current)) setError(String(e));
      });
    const retire = () => {
      epoch.current++;
      cancelReview();
      if (active.current)
        void apiKeepalive(base + "/cancel", {
          operation_id: active.current,
        }).catch(() => {});
    };
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      mounted.current = false;
      epoch.current++;
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
      for (const id of new Set([active.current, reviewOperation.current]))
        if (id)
          void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
            () => {},
          );
      onBusy(false);
    };
  }, []);
  useEffect(() => {
    if (!rememberPointNameWork(drafts, source, work)) setError(capacityMessage);
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
      if (active.current)
        void apiKeepalive(base + "/cancel", {
          operation_id: active.current,
        }).catch(() => {});
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
        if (!canRememberPointNameWork(drafts, source))
          throw new Error(capacityMessage);
        cancelReview();
        const capture = await api(base + "/capture", {
          ...target,
          operation_id,
        });
        if (!currentOwner(current)) return;
        if (
          !capture.source_identity_matches ||
          !capture.instance_edit_supported ||
          !targetMatches(capture.target) ||
          capture.device !== controller.device
        )
          throw new Error(
            capture.compiler_error || "Capture does not match this controller.",
          );
        const pointSource = await api(base + "/point-name/source", {
          ...target,
          capture_id: capture.id,
          snapshot_sha256: capture.snapshot_evidence_sha256,
        });
        if (!currentOwner(current)) return;
        if (
          pointSource.profile !== profile ||
          pointSource.capture_id !== capture.id ||
          pointSource.snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
          !targetMatches(pointSource.target) ||
          pointSource.device !== controller.device
        )
          throw new Error(
            "Point-name source differs from the selected backup.",
          );
        const field = pointSource.points.find((p: any) => p.object_id === object);
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
        if (!currentOwner(current)) {
          void apiKeepalive(base + "/cancel", { operation_id }).catch(() => {});
          return;
        }
        reviewOperation.current = operation_id;
        const expectedEdit = {
          object_id: object,
          record_ref: work.field.record_ref,
          encoded_sha256: work.field.encoded_sha256,
          new_name: work.name,
        };
        if (
          result.profile !== "native-application-transfer/1" ||
          result.operation_profile !== profile ||
          result.operation_id !== operation_id ||
          result.change_kind !== "point-name" ||
          !targetMatches(result.target) ||
          result.identity?.device !== controller.device ||
          result.capture_id !== work.capture.id ||
          result.snapshot_sha256 !== work.capture.snapshot_evidence_sha256 ||
          !sameEdit(result.point_name_edit, expectedEdit) ||
          result.compilation?.selected_edit?.before !== work.field.name ||
          result.can_apply !== true ||
          !/^[A-Za-z0-9_-]{32}$/.test(result.token) ||
          !/^[a-f0-9]{64}$/.test(result.review_sha256) ||
          !Number.isFinite(Date.parse(result.expires_at)) ||
          Date.parse(result.expires_at) <= Date.now()
        ) {
          cancelReview();
          throw new Error("Point-name review differs from this draft.");
        }
        setReview(result);
        setNow(Date.now());
      } else {
        const plan = review;
        const original = work.receipt?.intent;
        if (kind === "apply") {
          if (!fresh || !confirmed || !transfer)
            throw new Error("Review and confirm this point name again.");
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
        if (!currentOwner(current)) return;
        const intent = result.intent;
        if (
          intent &&
          (!matchesReceipt(result) ||
            (kind === "apply"
              ? intent.operation_id !== operation_id ||
                intent.review_sha256 !== plan.review_sha256 ||
                intent.review_capture_id !== plan.capture_id ||
                !sameEdit(intent.point_name_edit, plan.point_name_edit)
              : intent.id !== original?.id ||
                intent.operation_id !== original.operation_id ||
                intent.review_sha256 !== original.review_sha256 ||
                intent.evidence_sha256 !== original.evidence_sha256 ||
                !sameEdit(intent.point_name_edit, original.point_name_edit)))
        )
          throw new Error(
            "The point name receipt does not match this operation. Keep the draft and open the original retained transfer for readback.",
          );
        if (
          !intent &&
          (kind !== "apply" ||
            result.pending !== false ||
            result.result?.status !== "not_sent")
        )
          throw new Error(
            "The point name receipt does not match this operation. Open the original retained transfer for readback.",
          );
        setWork((w) => ({ ...w, receipt: result }));
        const observed = result.latest_readback || result.result;
        if (
          intent &&
          observed?.status === "verified" &&
          result.pending === false
        ) {
          setWork((w) => ({
            ...w,
            // An older retained transfer must not clear a newer local proposal.
            ...(w.name === intent.point_name_edit.new_name &&
            w.capture?.id === intent.review_capture_id
              ? { name: "", capture: null, field: null }
              : {}),
            receipt: result,
          }));
          onVerified();
        }
      }
    } catch (e) {
      if (currentOwner(current)) setError(String(e));
    } finally {
      if (active.current === operation_id) active.current = null;
      if (mounted.current) {
        // Even a retired or mismatched Apply reply can leave a durable intent.
        // Refresh its discoverability without promoting that reply to success.
        const statusOwner = epoch.current;
        try {
          const result = await api(base + "/status");
          if (currentOwner(statusOwner)) setStatus(result);
        } catch (e) {
          if (currentOwner(current))
            setError((previous) => previous || String(e));
        }
        setBusy(false);
        onBusy(false);
      }
    }
  }
  async function saveReceipt() {
    const current = epoch.current,
      receipt = work.receipt?.intent;
    if (!receipt) return;
    try {
      const document = await apiJsonDocument(base + "/receipts/" + receipt.id);
      if (
        !currentOwner(current) ||
        currentWork.current.receipt?.intent !== receipt
      )
        return;
      if (
        !matchesReceipt(document.data) ||
        document.data.intent.id !== receipt.id ||
        document.data.intent.evidence_sha256 !== receipt.evidence_sha256
      )
        throw new Error(
          "The saved receipt differs from the selected transfer.",
        );
      saveBlob(document.blob, "point-name-receipt.json");
    } catch (e) {
      if (currentOwner(current)) setError(String(e));
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
        {hasPointNameWork(work) && (
          <button
            disabled={busy}
            onClick={() => {
              epoch.current++;
              cancelReview();
              drafts.delete(source);
              setWork(emptyPointNameWork());
              setError("");
            }}
          >
            Discard local point name work
          </button>
        )}
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
                  epoch.current++;
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
                <button disabled={busy} onClick={() => void saveReceipt()}>
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
                const receiptId = e.target.value;
                cancelReview();
                void api(base + "/receipts/" + receiptId)
                  .then((receipt) => {
                    if (!currentOwner(current)) return;
                    if (
                      !matchesReceipt(receipt) ||
                      receipt.intent.id !== receiptId
                    )
                      throw new Error(
                        "The retained receipt differs from the selected transfer.",
                      );
                    setWork((w) => ({ ...w, receipt }));
                  })
                  .catch((e) => {
                    if (currentOwner(current)) setError(String(e));
                  });
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
