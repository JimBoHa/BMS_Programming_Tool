import { useContext, useEffect, useRef, useState } from "react";
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
      }
    } catch (failure) {
      if (current(ticket)) setError(String(failure));
    } finally {
      active.current = false;
      if (alive.current) setBusy(false);
    }
  }
  function request() {
    const value = enumCode(text);
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
              value={text}
              disabled={fieldBusy}
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
          <div className="button-row">
            <button
              className={prepared || transferActive ? undefined : "primary"}
              disabled={busy || fieldBusy}
              onClick={() => void preview()}
            >
              Review effective Enum copy
            </button>
            <button
              disabled={busy || fieldBusy || !drafts.has(key)}
              onClick={() => {
                retire();
                drafts.delete(key);
                setText(String(loaded.selected.effective_value));
                setError("");
              }}
            >
              Discard effective Enum draft
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
          />
        </>
      )}
    </section>
  );
}
