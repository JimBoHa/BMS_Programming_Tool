import {
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  saveBlob,
  type JsonDocument,
} from "./api";
import { sha256Blob } from "./activityContracts";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeEnumTransfer } from "./NativeEnumTransfer";
import type { NativeDefaultRecoveryDocument } from "./nativeDefaultRecoveryContract";
import { controllerKey } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";
import { enumCode, rememberEnumText } from "./nativeEnumCopyWork";
import {
  checkEffectiveEnumReview,
  effectiveEnumSource,
  type EnumArchiveField,
} from "./nativeEnumEffective";

const base = "/bacnet/controller/native-application/enum-default-compiler";
const drafts = new Map<string, string>();
export function NativeEffectiveEnumCopy({
  source,
  field,
}: {
  source: NativeArchiveSource;
  field: EnumArchiveField;
}) {
  const [loaded, setLoaded] = useState<any>(null),
    [text, setText] = useState("");
  const [review, setReview] = useState<{
    document: JsonDocument;
    ticket: number;
  } | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const alive = useRef(true),
    generation = useRef(0),
    active = useRef(false);
  const transferContext = useContext(NativeBooleanTransferContext);
  const [recovery, setRecovery] =
    useState<NativeDefaultRecoveryDocument | null>(null);
  const recoveryPanel = useRef<HTMLElement>(null),
    pendingRecoveryFocus = useRef(false);
  const shownRecovery =
    recovery &&
    recovery.data.origin.current_capture_id === source.capture_id &&
    recovery.data.origin.current_snapshot_sha256 === source.snapshot_sha256 &&
    recovery.data.origin.record_ref === field.ref
      ? recovery
      : null;
  const activeRecovery = shownRecovery?.data.proposal ? shownRecovery : null;
  useLayoutEffect(() => {
    if (
      pendingRecoveryFocus.current &&
      shownRecovery &&
      (transferContext?.visible ?? true)
    ) {
      pendingRecoveryFocus.current = false;
      recoveryPanel.current?.focus({ preventScroll: true });
      recoveryPanel.current?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
      });
    }
  });
  const fieldBusy = transferContext?.fieldBusy ?? false;
  let nativeIp = false;
  try {
    nativeIp =
      JSON.parse(transferContext?.controller?.interfaceKey ?? "null")
        ?.transport !== "mstp";
  } catch {
    /* unavailable interface evidence */
  }
  const transferActive =
    !!loaded?.selected.saved_storage &&
    nativeIp &&
    !!transferContext?.controller?.interfaceOpen &&
    controllerKey(transferContext.controller) === controllerKey(source.target);
  const current = (ticket: number) =>
    alive.current && generation.current === ticket;
  const prepared =
    review?.ticket === generation.current ? review.document : null;
  const retire = () => {
    generation.current++;
    setReview(null);
  };
  useEffect(() => {
    alive.current = true;
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      alive.current = false;
      generation.current++;
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
    };
  }, []);
  useEffect(() => {
    if (fieldBusy) retire();
  }, [fieldBusy]);
  const key = loaded
    ? JSON.stringify([
        "effective-enum",
        source.capture_id,
        source.snapshot_sha256,
        source.sha256,
        loaded.effective_sha256,
        source.target,
        field.ref,
        field.class_id,
        loaded.selected.encoded_sha256,
        loaded.selected.effective_value,
        loaded.selected.saved_storage,
      ])
    : "";
  async function load() {
    if (active.current || fieldBusy) return;
    active.current = true;
    const ticket = ++generation.current;
    setBusy(true);
    setError("");
    setLoaded(null);
    setReview(null);
    try {
      const data = await api(base + "/source", {
        capture_id: source.capture_id,
        snapshot_sha256: source.snapshot_sha256,
      });
      const selected = effectiveEnumSource(data, source, field);
      const draftKey = JSON.stringify([
        "effective-enum",
        source.capture_id,
        source.snapshot_sha256,
        source.sha256,
        data.effective_sha256,
        source.target,
        field.ref,
        field.class_id,
        selected.encoded_sha256,
        selected.effective_value,
        selected.saved_storage,
      ]);
      if (current(ticket)) {
        setLoaded({ ...data, selected });
        setText(drafts.get(draftKey) ?? String(selected.effective_value));
        setRecovery(transferContext?.enumRecoveryDrafts.get(draftKey) ?? null);
      }
    } catch (failure) {
      if (current(ticket)) setError(String(failure));
    } finally {
      active.current = false;
      if (alive.current) setBusy(false);
    }
  }
  function request() {
    const value = activeRecovery
      ? activeRecovery.data.proposal.value
      : enumCode(text);
    if (value > loaded.selected.maximum_code)
      throw new Error(
        `Use a code from 0 through ${loaded.selected.maximum_code}; this snapshot records a fixed saved Enum slot.`,
      );
    return {
      capture_id: source.capture_id,
      snapshot_sha256: source.snapshot_sha256,
      source_sha256: source.sha256,
      record_ref: field.ref,
      encoded_sha256: loaded.selected.encoded_sha256,
      value,
    };
  }
  function receiveRecovery(document: NativeDefaultRecoveryDocument) {
    const cache = transferContext?.enumRecoveryDrafts;
    if (
      !loaded ||
      document.data.origin.current_capture_id !== source.capture_id ||
      document.data.origin.current_snapshot_sha256 !== source.snapshot_sha256 ||
      document.data.origin.record_ref !== field.ref
    )
      return;
    if (cache && !cache.has(key) && cache.size >= 128) {
      setError(
        "128 Enum recovery proposals are retained. Discard an older proposal before preparing another.",
      );
      return;
    }
    cache?.set(key, document);
    retire();
    setError("");
    pendingRecoveryFocus.current = true;
    setRecovery(document);
  }
  function discardRecovery() {
    transferContext?.enumRecoveryDrafts.delete(key);
    retire();
    setRecovery(null);
    setError("");
  }
  let transferProposal = null;
  if (loaded)
    try {
      transferProposal = request();
    } catch {
      /* Retain invalid raw text without field authority. */
    }
  async function preview() {
    if (active.current || fieldBusy || !loaded) return;
    active.current = true;
    const ticket = ++generation.current;
    setBusy(true);
    setError("");
    setReview(null);
    try {
      const expected = request(),
        document = await apiJsonDocument(base + "/preview", expected);
      checkEffectiveEnumReview(
        document.data,
        source,
        loaded.selected,
        loaded,
        expected,
      );
      if (current(ticket)) setReview({ document, ticket });
    } catch (failure) {
      if (current(ticket)) setError(String(failure));
    } finally {
      active.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function download() {
    if (active.current || fieldBusy || !prepared) return;
    active.current = true;
    const ticket = generation.current,
      expected = prepared.data;
    setBusy(true);
    setError("");
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...expected.request,
        review_sha256: expected.review_sha256,
      });
      if (
        result.headers.get("X-Studio-Artifact-Sha256") !==
          expected.output_sha256 ||
        result.headers.get("X-Studio-Review-Sha256") !==
          expected.review_sha256 ||
        result.headers.get("X-Studio-Snapshot-Sha256") !==
          source.snapshot_sha256 ||
        (await sha256Blob(result.blob)) !== expected.output_sha256
      )
        throw new Error(
          "Effective Enum download differs from its source, review or artifact digest. Review the current proposal again.",
        );
      if (current(ticket))
        saveBlob(result.blob, "native-effective-enum-default.moi");
    } catch (failure) {
      if (current(ticket)) {
        setReview(null);
        setError(String(failure));
      }
    } finally {
      active.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return (
    <section
      className="native-enum-copy"
      aria-label="Effective native Enum compiler"
    >
      <h4>Compile with retained saved settings</h4>
      <p>
        Use an identity-verified snapshot and recognized complete saved format.
        Code membership and state meanings remain unverified. This prepares a
        local native-file copy.
      </p>
      {!loaded && (
        <button
          className="primary"
          disabled={busy || fieldBusy}
          onClick={() => void load()}
        >
          Open saved Enum defaults
        </button>
      )}
      {busy && <p role="status">Preparing local effective Enum data…</p>}
      {error && <p role="alert">{error}</p>}
      {loaded && (
        <>
          <p>
            Original archive code:{" "}
            <strong>{loaded.selected.archive_value}</strong> · Saved merged
            code: <strong>{loaded.selected.effective_value}</strong>
          </p>
          <p>
            {loaded.selected.saved_storage
              ? `Captured Enum storage: ${loaded.selected.saved_storage.bytes} bytes; numeric maximum ${loaded.selected.maximum_code}.`
              : "No fixed saved Enum slot is recorded. Only the local unsigned32 code representation is checked."}{" "}
            This is a numeric storage bound; allowed states are unverified.
          </p>
          <label>
            Proposed effective Enum code
            <input
              aria-label="Proposed effective Enum code"
              inputMode="numeric"
              maxLength={128}
              value={
                activeRecovery
                  ? String(activeRecovery.data.proposal.value)
                  : text
              }
              disabled={fieldBusy || !!activeRecovery}
              onChange={(event) => {
                if (
                  !rememberEnumText(
                    drafts,
                    key,
                    event.target.value,
                    loaded.selected.effective_value,
                  )
                ) {
                  setError(
                    "Local effective Enum work is full (128 fields). Reopen an earlier field and discard its draft before editing another.",
                  );
                  return;
                }
                retire();
                setError("");
                setText(event.target.value);
              }}
            />
          </label>
          {shownRecovery && (
            <section
              className="native-compiler-source"
              aria-label="Prepared previous Enum default"
              ref={recoveryPanel}
              tabIndex={-1}
            >
              <h4>
                {shownRecovery.data.already_recorded
                  ? "Previous Enum code already recorded in this backup"
                  : "Previous effective Enum code prepared locally"}
              </h4>
              <p>
                Receipt{" "}
                <code>{shownRecovery.data.origin.parent_receipt_id}</code> ·{" "}
                {field.ref} · {shownRecovery.data.current_effective_value} to{" "}
                {shownRecovery.data.previous_effective_value}.
              </p>
              <p>
                {shownRecovery.data.already_recorded
                  ? "No transfer proposal was created. This retained backup does not establish current live state."
                  : "A new controller review and both transfer confirmations are required. Other current saved settings remain current."}{" "}
                Code meanings remain unverified. Your ordinary raw Enum draft
                remains retained separately.
              </p>
              <button
                onClick={() =>
                  saveBlob(
                    shownRecovery.blob,
                    "native-previous-enum-default-proposal.json",
                  )
                }
              >
                Export exact previous Enum proposal
              </button>
            </section>
          )}
          <div className="button-row">
            <button
              className={prepared || transferActive ? undefined : "primary"}
              disabled={busy || fieldBusy}
              onClick={() => void preview()}
            >
              Review effective Enum copy
            </button>
            <button
              disabled={
                busy || fieldBusy || (!shownRecovery && !drafts.has(key))
              }
              onClick={() => {
                if (shownRecovery) {
                  discardRecovery();
                  return;
                }
                retire();
                drafts.delete(key);
                setText(String(loaded.selected.effective_value));
                setError("");
              }}
            >
              {shownRecovery
                ? "Discard previous Enum proposal"
                : "Discard effective Enum draft"}
            </button>
          </div>
          {prepared && (
            <section aria-label="Reviewed effective Enum copy">
              <p>
                Saved merged code {prepared.data.edit.before_value} → copy code{" "}
                {prepared.data.edit.after_value}. Other merged settings and
                original backup files remain preserved.
              </p>
              <div className="button-row">
                <button
                  className={transferActive ? undefined : "primary"}
                  disabled={busy || fieldBusy}
                  onClick={() => void download()}
                >
                  Save effective Enum copy
                </button>
                <button
                  disabled={busy || fieldBusy}
                  onClick={() =>
                    saveBlob(prepared.blob, "native-effective-enum-review.json")
                  }
                >
                  Save effective Enum review JSON
                </button>
              </div>
            </section>
          )}
          <details>
            <summary>Effective Enum source and review evidence</summary>
            <pre>{JSON.stringify(prepared?.data ?? loaded, null, 2)}</pre>
          </details>
          <NativeEnumTransfer
            source={loaded}
            field={loaded.selected}
            proposal={transferProposal}
            recoveryDraft={activeRecovery}
            onRecoveryPrepared={receiveRecovery}
          />
        </>
      )}
    </section>
  );
}
