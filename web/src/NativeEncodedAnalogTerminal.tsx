import { sha256Digest, randomUUID } from "./browserCrypto";
import { useEffect, useRef, useState } from "react";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import { connectionSame as same } from "./nativeConnectionContract";
import {
  encodedAnalogTerminalEdit,
  encodedAnalogTerminalProfile,
  encodedAnalogTerminalReceipt,
  encodedAnalogTerminalReview,
  encodedAnalogTerminalSource,
  encodedAnalogTerminalVerified,
} from "./nativeEncodedAnalogTerminalContract";
import {
  NativeEncodedAnalogRecovery,
  type EncodedAnalogRecoveryDocument,
} from "./NativeEncodedAnalogRecovery";
import {
  encodedAnalogRecoveryReview,
  encodedAnalogRecoveryReceipt,
  sameEncodedAnalogRecoveryLineage,
  encodedAnalogRecoveryTransferProfile,
} from "./nativeEncodedAnalogRecoveryContract";
type Data = Record<string, any>;
type Draft = {
  object: string;
  destination: string;
  receipt: { data: Data; blob: Blob } | null;
  completed: boolean;
  recovery?: EncodedAnalogRecoveryDocument;
  ordinary?: { object: string; destination: string };
  recoveryParent?: string;
};
const drafts = new Map<string, Draft>(),
  blank = (): Draft => ({
    object: "",
    destination: "",
    receipt: null,
    completed: false,
    recovery: undefined,
    ordinary: undefined,
    recoveryParent: "",
  });
const base = "/bacnet/controller/native-application";
export function NativeEncodedAnalogTerminal({
  parent,
  controller,
  connected,
  fieldBusy,
  credentialsConfigured,
  onBusy,
  onVerified,
  onOpenChange,
}: {
  parent: Data | null;
  controller: ControllerContext | null;
  connected: boolean;
  fieldBusy: boolean;
  credentialsConfigured: boolean;
  onBusy: (value: boolean, field: boolean) => void;
  onVerified: () => void;
  onOpenChange: (value: boolean) => void;
}) {
  const key = JSON.stringify([
    controller ? controllerKey(controller) : "offline",
    controller?.interfaceKey,
    parent?.capture_id,
    parent?.snapshot_sha256,
  ]);
  const context = JSON.stringify([key, connected, fieldBusy]);
  const scope = useRef(context),
    epoch = useRef(0),
    alive = useRef(true),
    pendingRef = useRef<number | null>(null),
    active = useRef<string | null>(null),
    planOperation = useRef<string | null>(null);
  const attempted = useRef<string | null>(null);
  const callbacks = useRef({ onBusy, onVerified, onOpenChange });
  callbacks.current = { onBusy, onVerified, onOpenChange };
  if (scope.current !== context) {
    scope.current = context;
    epoch.current++;
  }
  const [opened, setOpened] = useState(false),
    [work, setWork] = useState<{ key: string; draft: Draft }>(() => ({
      key,
      draft: drafts.get(key) ?? blank(),
    }));
  const draft = work.key === key ? work.draft : (drafts.get(key) ?? blank());
  const [loaded, setLoaded] = useState<{ context: string; data: Data } | null>(
      null,
    ),
    [review, setReview] = useState<{
      context: string;
      ticket: number;
      field: boolean;
      data: Data;
      blob: Blob;
    } | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [confirm, setConfirm] = useState([false, false, false]),
    [now, setNow] = useState(Date.now()),
    [records, setRecords] = useState<Data[]>([]);
  const source = loaded?.context === context ? loaded.data : null;
  const proposal = source
    ? encodedAnalogTerminalEdit(source, draft.object, draft.destination)
    : null;
  const current = (owner: string, ticket: number) =>
    alive.current && scope.current === owner && epoch.current === ticket;
  const shown =
    opened &&
    !fieldBusy &&
    review?.context === context &&
    review.ticket === epoch.current
      ? review
      : null;
  const fieldAllowed =
    !!controller &&
    connected &&
    !!source &&
    controllerKey(controller) ===
      controllerKey({ ...source.target, device: source.identity.device });
  const fresh =
    shown?.field && Date.parse(shown.data.expires_at) > now && fieldAllowed;
  function remember(next: Draft) {
    if (!drafts.has(key) && drafts.size >= 32) {
      setError(
        "Analog input work is full (32 sources). Save or discard an earlier draft first.",
      );
      return false;
    }
    if (
      !next.object &&
      !next.destination &&
      !next.receipt &&
      !next.completed &&
      !next.recovery &&
      !next.ordinary &&
      !next.recoveryParent
    )
      drafts.delete(key);
    else drafts.set(key, next);
    setWork({ key, draft: next });
    return true;
  }
  function retire() {
    epoch.current++;
    setReview(null);
    setConfirm([false, false, false]);
    if (planOperation.current)
      void apiKeepalive(base + "/cancel", {
        operation_id: planOperation.current,
      }).catch(() => {});
    planOperation.current = null;
  }
  function update(change: Partial<Draft>) {
    retire();
    setError("");
    remember({
      ...draft,
      ...change,
      ...(Object.hasOwn(change, "object") ||
      Object.hasOwn(change, "destination")
        ? { recovery: undefined }
        : {}),
    });
  }
  useEffect(() => {
    alive.current = true;
    const leave = () => {
      retire();
      setOpened(false);
      callbacks.current.onOpenChange(false);
      if (active.current)
        void apiKeepalive(base + "/cancel", {
          operation_id: active.current,
        }).catch(() => {});
    };
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", leave);
    return () => {
      alive.current = false;
      leave();
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", leave);
      callbacks.current.onBusy(false, true);
    };
  }, []);
  useEffect(() => {
    retire();
    setLoaded(null);
    attempted.current = null;
    setWork({ key, draft: drafts.get(key) ?? blank() });
    setError("");
  }, [context]);
  useEffect(() => {
    if (!shown?.field) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [shown?.data]);
  useEffect(() => {
    if (
      opened &&
      parent &&
      !fieldBusy &&
      !busy &&
      attempted.current !== context
    )
      void run("source");
  }, [opened, context, busy]);
  async function run(kind: string, id?: string) {
    if (pendingRef.current !== null || fieldBusy) return;
    if (!parent) return;
    if (["field", "apply", "readback"].includes(kind) && !fieldAllowed) {
      setError("Open the exact captured controller and interface first.");
      return;
    }
    if (["local", "field"].includes(kind) && !proposal) return;
    if (kind === "apply" && (!fresh || !confirm.every(Boolean))) return;
    const previous = shown;
    if (kind !== "apply" && kind !== "save") retire();
    const owner = context,
      ticket = ++epoch.current,
      operation_id = randomUUID();
    pendingRef.current = ticket;
    setBusy(true);
    const fieldOperation = ["field", "apply", "readback"].includes(kind);
    callbacks.current.onBusy(true, fieldOperation);
    setError("");
    const args = {
      capture_id: parent.capture_id,
      snapshot_sha256: parent.snapshot_sha256,
    };
    try {
      if (kind === "source") {
        attempted.current = context;
        const [value, status] = await Promise.all([
          api(base + "/input/encoded-terminal/source", args),
          api(base + "/status"),
        ]);
        if (!current(owner, ticket)) return;
        if (!encodedAnalogTerminalSource(value, parent))
          throw Error(
            "Analog input source differs from this retained capture.",
          );
        setLoaded({ context: owner, data: value });
        setRecords(
          (status.receipts ?? []).filter(
            (r: Data) =>
              r.operation_profile === encodedAnalogTerminalProfile &&
              r.input_edit?.action === "encoded-terminal" &&
              same(r.target, value.target) &&
              same(r.identity, value.identity),
          ),
        );
      } else if (kind === "local" || kind === "field") {
        setReview(null);
        setConfirm([false, false, false]);
        if (planOperation.current)
          void apiKeepalive(base + "/cancel", {
            operation_id: planOperation.current,
          }).catch(() => {});
        const field = kind === "field";
        if (field) {
          active.current = operation_id;
          planOperation.current = operation_id;
        }
        const request = {
          ...args,
          edit: proposal,
          ...(field
            ? {
                address: controller!.address,
                device: controller!.device,
                router: controller!.router || null,
                dnet: controller!.dnet ?? null,
                operation_id,
                ...(draft.recovery
                  ? {
                      encoded_analog_recovery_parent_receipt:
                        draft.recovery.data.origin.parent_receipt_id,
                      encoded_analog_recovery_origin_sha256:
                        draft.recovery.data.origin_sha256,
                    }
                  : {}),
              }
            : {}),
        };
        const document = await apiJsonDocument(
          base +
            (field
              ? draft.recovery
                ? "/input/encoded-terminal/recovery/preview"
                : "/input/preview"
              : "/input/copy/preview"),
          request,
        );
        if (
          !(await encodedAnalogTerminalReview(
            document,
            source!,
            proposal!,
            field,
          )) ||
          (field &&
            (document.data.operation_id !== operation_id ||
              !encodedAnalogRecoveryReview(
                document.data,
                draft.recovery?.data ?? null,
              )))
        )
          throw Error(
            "Analog terminal proof differs from this exact captured configuration and move.",
          );
        if (current(owner, ticket))
          setReview({ context: owner, ticket, field, ...document });
        else if (field)
          void apiKeepalive(base + "/cancel", { operation_id }).catch(() => {});
      } else if (kind === "save") {
        if (
          !previous ||
          previous.field ||
          !proposal ||
          !same(previous.data.edit, proposal)
        )
          return;
        const document = await apiBlobDocument(base + "/input/copy/export", {
          ...args,
          edit: proposal,
          expected_review_sha256: previous.data.review_sha256,
        });
        const digest = [
          ...new Uint8Array(
            await sha256Digest(await document.blob.arrayBuffer()),
          ),
        ]
          .map((n) => n.toString(16).padStart(2, "0"))
          .join("");
        if (digest !== previous.data.output_sha256)
          throw Error("Analog terminal copy differs from its reviewed bytes.");
        if (current(owner, ticket))
          saveBlob(document.blob, "native-analog-terminal-copy.moi");
      } else {
        if (kind === "apply") {
          planOperation.current = null;
          setReview(null);
          setConfirm([false, false, false]);
        }
        if (kind !== "receipt") active.current = operation_id;
        const prior = draft.receipt?.data.intent;
        const document = await apiJsonDocument(
          kind === "receipt"
            ? base + "/receipts/" + id
            : base + (kind === "apply" ? "/input/apply" : "/readback"),
          kind === "receipt"
            ? undefined
            : kind === "apply"
              ? {
                  operation_id,
                  token: previous!.data.token,
                  review_sha256: previous!.data.review_sha256,
                  physical_wiring_confirmed: confirm[0],
                  input_change_confirmed: confirm[1],
                  application_transfer_confirmed: confirm[2],
                }
              : { operation_id, receipt_id: prior.id },
        );
        if (!current(owner, ticket)) return;
        const r = document.data;
        if (
          !r.intent &&
          kind === "apply" &&
          r.pending === false &&
          r.result?.status === "not_sent"
        ) {
          setError(
            r.result.error ||
              "Analog terminal transfer was not sent. Review again.",
          );
          return;
        }
        if (
          !encodedAnalogTerminalReceipt(r, source!) ||
          !(await encodedAnalogRecoveryReceipt(r.intent)) ||
          (kind === "apply" &&
            (r.intent.operation_id !== operation_id ||
              r.intent.review_sha256 !== previous!.data.review_sha256 ||
              r.intent.review_capture_id !== parent.capture_id ||
              !sameEncodedAnalogRecoveryLineage(r.intent, previous!.data) ||
              !same(r.intent.input_edit, previous!.data.input_edit) ||
              !same(
                r.intent.compilation.stored_configuration,
                previous!.data.compilation.stored_configuration,
              ))) ||
          (kind === "readback" &&
            (r.intent.id !== prior.id ||
              r.intent.evidence_sha256 !== prior.evidence_sha256 ||
              !sameEncodedAnalogRecoveryLineage(r.intent, prior)))
        )
          throw Error(
            "Analog transfer receipt differs from this exact operation. Retain original evidence for readback.",
          );
        if (!current(owner, ticket)) return;
        const verified = encodedAnalogTerminalVerified(r);
        remember({
          ...draft,
          receipt: document,
          completed: draft.completed || verified,
          ...(verified &&
          kind !== "receipt" &&
          draft.recovery &&
          draft.ordinary &&
          r.intent.encoded_analog_recovery_origin_sha256 ===
            draft.recovery.data.origin_sha256
            ? { ...draft.ordinary, recovery: undefined, ordinary: undefined }
            : {}),
        });
        if (verified && kind !== "receipt") callbacks.current.onVerified();
      }
    } catch (failure) {
      if (kind === "field")
        void apiKeepalive(base + "/cancel", { operation_id }).catch(() => {});
      if (current(owner, ticket)) setError(String(failure));
    } finally {
      if (active.current === operation_id) active.current = null;
      if (pendingRef.current === ticket) {
        pendingRef.current = null;
        if (alive.current) {
          setBusy(false);
          callbacks.current.onBusy(false, fieldOperation);
        }
      }
    }
  }
  const receipt = draft.receipt?.data,
    observed = receipt?.latest_readback || receipt?.result;
  return (
    <details
      aria-label="Analog input terminal movement"
      open={opened}
      onToggle={(e) => {
        const next = e.currentTarget.open;
        if (next === opened) return;
        attempted.current = null;
        retire();
        setOpened(next);
        callbacks.current.onOpenChange(next);
      }}
    >
      <summary
        aria-disabled={fieldBusy}
        onClick={(e) => {
          if (fieldBusy) e.preventDefault();
        }}
      >
        Move a configured analog input
      </summary>
      {!parent && (
        <p>Select or capture a retained native input source above.</p>
      )}
      {error && (
        <>
          <p role="alert" className="inline-error">
            {error}
          </p>
          <button
            disabled={busy || fieldBusy || !parent}
            onClick={() => void run("source")}
          >
            Analyze analog source again
          </button>
        </>
      )}
      {busy && <p role="status">Working on this analog input operation…</p>}
      {source && (
        <>
          <p>
            <strong>Captured analog source:</strong>{" "}
            {source.identity["object-name"]} ·{" "}
            {source.identity.device ?? `device,${source.controller.instance}`} ·{" "}
            {source.target.router || source.target.address} / network{" "}
            {source.target.dnet ?? "local"} / station {source.target.address}.
          </p>
          <p>
            Stored electrical configuration and scaling stay unchanged. Unstored
            output endpoints remain absent. Confirm physical wiring before
            applying.
          </p>
          <NativeEncodedAnalogRecovery
            source={source}
            receipts={records}
            fieldBusy={busy || fieldBusy}
            draftKey={JSON.stringify([
              key,
              draft.object,
              draft.destination,
              epoch.current,
            ])}
            selected={draft.recoveryParent ?? ""}
            canStage={!draft.completed && !draft.receipt?.data.pending}
            onSelected={(value) => {
              retire();
              setError("");
              remember({
                ...draft,
                ...(draft.ordinary ?? {}),
                recovery: undefined,
                ordinary: undefined,
                recoveryParent: value,
              });
            }}
            onUse={(document) => {
              const r = document.data,
                e = r.proposal?.edit;
              if (
                r.source.capture_id !== parent?.capture_id ||
                r.source.snapshot_sha256 !== parent?.snapshot_sha256 ||
                !e ||
                r.already_recorded ||
                !same(
                  e,
                  encodedAnalogTerminalEdit(
                    source,
                    `analog-input,${e.object_instance}`,
                    String(e.slot),
                  ),
                )
              )
                return;
              retire();
              setError("");
              remember({
                ...draft,
                ordinary: draft.ordinary ?? {
                  object: draft.object,
                  destination: draft.destination,
                },
                object: `analog-input,${e.object_instance}`,
                destination: String(e.slot),
                recovery: document,
              });
            }}
          />
          {draft.ordinary && (
            <section aria-label="Staged previous analog terminal">
              <p>
                {draft.recovery
                  ? `Previous-terminal proposal: ${draft.recovery.data.origin.object_id}, UI IN${draft.recovery.data.origin.current_slot} to UI IN${draft.recovery.data.origin.previous_slot}. Parent ${draft.recovery.data.origin.parent_receipt_id}. Fresh controller review is required.`
                  : "The saved ordinary analog draft is retained. This edited proposal needs its own review."}
              </p>
              <button
                disabled={busy || fieldBusy}
                onClick={() => {
                  retire();
                  remember({
                    ...draft,
                    ...draft.ordinary!,
                    ordinary: undefined,
                    recovery: undefined,
                  });
                }}
              >
                Restore ordinary analog draft
              </button>
              {draft.recovery && (
                <button
                  disabled={busy || fieldBusy}
                  onClick={() =>
                    saveBlob(
                      draft.recovery!.blob,
                      "staged-previous-analog-terminal.json",
                    )
                  }
                >
                  Save staged analog recovery evidence
                </button>
              )}
            </section>
          )}
          <fieldset disabled={busy || fieldBusy}>
            <legend>Move one existing analog input</legend>
            <label>
              Configured analog input
              <select
                aria-label="Configured analog input"
                value={draft.object}
                onChange={(e) => update({ object: e.target.value })}
              >
                <option value="">Select a recorded input</option>
                {source.inputs.map((r: Data) => (
                  <option
                    key={r.object_id}
                    value={r.object_id}
                    disabled={r.configuration_error !== null}
                  >
                    {r.name} · {r.object_id} · UI IN{r.slot}
                    {r.configuration_error
                      ? " · unsupported configuration"
                      : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Destination universal terminal
              <select
                aria-label="Analog terminal destination"
                value={draft.destination}
                onChange={(e) => update({ destination: e.target.value })}
              >
                <option value="">Select a free terminal</option>
                {source.available_slots.map((n: number) => (
                  <option key={n} value={n}>
                    UI IN{n}
                  </option>
                ))}
              </select>
            </label>
          </fieldset>
          {draft.object &&
            source.inputs.find((r: Data) => r.object_id === draft.object)
              ?.configuration_error === null && (
              <table aria-label="Preserved analog configuration">
                <caption>Recorded configuration stays unchanged</caption>
                <thead>
                  <tr>
                    <th>Stored field</th>
                    <th>Captured value</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(
                    source.inputs.find(
                      (r: Data) => r.object_id === draft.object,
                    ).stored_configuration,
                  ).map(([name, value]) => (
                    <tr key={name}>
                      <th>
                        {
                          (
                            {
                              setup: "Setup code",
                              field_units: "Field unit code",
                              input_low: "Input low",
                              input_high: "Input high",
                              output_low: "Output low",
                              output_high: "Output high",
                              units: "Unit code",
                              minimum: "Minimum",
                              maximum: "Maximum",
                            } as Record<string, string>
                          )[name]
                        }
                      </th>
                      <td>
                        {value === null
                          ? "Not stored"
                          : Object.is(value, -0)
                            ? "-0"
                            : String(value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          {!source.inputs.length && (
            <p>No existing local universal analog input was recorded.</p>
          )}
          {!source.available_slots.length && (
            <p>No free local universal terminal was recorded.</p>
          )}
          {draft.completed && (
            <p>
              Capture native inputs again before another controller change. The
              retained copy remains historical.
            </p>
          )}
          <div className="button-row">
            <button
              className={!fieldAllowed && !shown ? "primary" : ""}
              disabled={busy || fieldBusy || !proposal}
              onClick={() => void run("local")}
            >
              Review local analog terminal copy
            </button>
            {fieldAllowed && (
              <button
                className={!shown ? "primary" : ""}
                disabled={
                  busy ||
                  fieldBusy ||
                  !proposal ||
                  draft.completed ||
                  !!receipt?.pending ||
                  !credentialsConfigured
                }
                onClick={() => void run("field")}
              >
                Review analog controller change
              </button>
            )}
          </div>
          {shown && (
            <section aria-label="Analog terminal review">
              <h4>{shown.field ? "Controller" : "Local copy"} review</h4>
              {shown.data.encoded_analog_recovery_profile ===
                encodedAnalogRecoveryTransferProfile && (
                <p>
                  Fresh previous-terminal review, bound to parent{" "}
                  {shown.data.encoded_analog_recovery_parent_receipt}.
                </p>
              )}
              <p>
                {shown.data.compilation.object_id}: UI IN
                {shown.data.compilation.terminal_compilation.old_slot} to UI IN
                {shown.data.compilation.terminal_compilation.destination_slot}.
                Stored electrical configuration, scaling, graph and other
                settings preserved.
              </p>
              {!shown.field ? (
                <button
                  className="primary"
                  disabled={busy || fieldBusy}
                  onClick={() => void run("save")}
                >
                  Save native analog terminal copy
                </button>
              ) : (
                <>
                  {[
                    "I confirm physical wiring, common and jumpers match this destination.",
                    "I confirm this analog terminal move with unchanged electrical configuration and scaling.",
                    "I confirm the application transfer and possible control restart.",
                  ].map((text, i) => (
                    <label key={text}>
                      <input
                        type="checkbox"
                        checked={confirm[i]}
                        onChange={(e) =>
                          setConfirm((v) =>
                            v.map((x, j) => (j === i ? e.target.checked : x)),
                          )
                        }
                      />{" "}
                      {text}
                    </label>
                  ))}
                  <button
                    className="primary"
                    disabled={
                      busy || fieldBusy || !fresh || !confirm.every(Boolean)
                    }
                    onClick={() => void run("apply")}
                  >
                    Apply analog terminal change to controller
                  </button>
                  {!fresh && (
                    <p>Review expired or its target changed. Review again.</p>
                  )}
                </>
              )}
              <button
                disabled={busy || fieldBusy}
                onClick={() =>
                  saveBlob(shown.blob, "analog-terminal-review.json")
                }
              >
                Save analog terminal review
              </button>
              <details>
                <summary>Exact analog terminal proof</summary>
                <pre>{JSON.stringify(shown.data.compilation, null, 2)}</pre>
              </details>
            </section>
          )}
          {receipt && (
            <section aria-label="Analog terminal transfer result">
              <h4>
                Analog terminal transfer:{" "}
                {receipt.pending
                  ? "outcome uncertain"
                  : encodedAnalogTerminalVerified(receipt)
                    ? "verified"
                    : observed?.status === "verified"
                      ? "verification incomplete"
                      : observed?.status || "unknown"}
              </h4>
              <p>
                Receipt {receipt.intent.id}. {observed?.error}
              </p>
              {receipt.intent.encoded_analog_recovery_profile ===
                encodedAnalogRecoveryTransferProfile && (
                <p>
                  Recorded previous-terminal transfer · parent{" "}
                  {receipt.intent.encoded_analog_recovery_parent_receipt}.
                </p>
              )}
              <button
                disabled={busy || fieldBusy || !fieldAllowed}
                onClick={() => void run("readback")}
              >
                Read back analog transfer
              </button>
              <button
                disabled={busy || fieldBusy}
                onClick={() =>
                  saveBlob(draft.receipt!.blob, "analog-terminal-receipt.json")
                }
              >
                Save original analog transfer evidence
              </button>
            </section>
          )}
          <details>
            <summary>Retained analog transfers</summary>
            {records.map((r) => (
              <p key={r.id}>
                {r.status} · {r.created_at}{" "}
                <button
                  disabled={busy || fieldBusy}
                  onClick={() => void run("receipt", r.id)}
                >
                  Open analog receipt {r.id.slice(0, 8)}
                </button>
              </p>
            ))}
          </details>
          <button disabled={busy || fieldBusy} onClick={() => update(blank())}>
            Discard local analog draft
          </button>
        </>
      )}
    </details>
  );
}
