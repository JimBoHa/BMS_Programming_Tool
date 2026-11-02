import { useContext, useEffect, useRef, useState } from "react";
import {
  apiBlobDocument,
  apiJsonDocument,
  saveBlob,
  type JsonDocument,
} from "./api";
import { sha256Blob } from "./activityContracts";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import type { NativeArchiveSource } from "./NativeRecords";
import { enumCode, rememberEnumText } from "./nativeEnumCopyWork";
import "./native-enum-copy.css";

const base = "/bacnet/controller/native-application/inspection/enum-default";
const drafts = new Map<string, string>();
const capacity =
  "Local Enum work is full (128 fields). Reopen an earlier field and discard its local Enum draft before editing another.";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);

export function NativeEnumDefaultCopy({
  source,
  field,
}: {
  source: NativeArchiveSource;
  field: {
    ref: string;
    class_id: number;
    encoded_sha256: string;
    value: number;
  };
}) {
  const key = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    source.sha256,
    source.target,
    field.ref,
    field.class_id,
    field.encoded_sha256,
    field.value,
  ]);
  const [text, setText] = useState(
    () => drafts.get(key) ?? String(field.value),
  );
  const [review, setReview] = useState<{
    document: JsonDocument;
    generation: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0),
    alive = useRef(true),
    active = useRef(false);
  const fieldBusy =
    useContext(NativeBooleanTransferContext)?.fieldBusy ?? false;
  const owned = (ticket: number) =>
    alive.current && generation.current === ticket;
  const current =
    review?.generation === generation.current ? review.document : null;
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
  const request = () => ({
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: source.sha256,
    record_ref: field.ref,
    encoded_sha256: field.encoded_sha256,
    value: enumCode(text),
  });
  function check(result: any, expected: ReturnType<typeof request>) {
    const edit = result?.edit;
    if (
      result?.profile !== "native-backup-enum-default-copy/1" ||
      result.source_immutable !== true ||
      result.controller_queries !== false ||
      result.controller_write !== false ||
      result.field_transfer_enabled !== false ||
      result.enum_semantics_verified !== false ||
      !hash(result.output_sha256) ||
      !hash(result.review_sha256) ||
      !result.request ||
      Object.keys(result.request).length !== Object.keys(expected).length ||
      !Object.entries(expected).every(([k, v]) => result.request[k] === v) ||
      result.target?.address !== source.target.address ||
      result.target?.device !== source.target.device ||
      (result.target?.router ?? null) !== (source.target.router ?? null) ||
      (result.target?.dnet ?? null) !== (source.target.dnet ?? null) ||
      edit?.profile !== "tagged-moi-enum-default-copy/1" ||
      edit.source_sha256 !== source.sha256 ||
      edit.record_ref !== field.ref ||
      edit.class_id !== field.class_id ||
      edit.property !== 3113 ||
      edit.datatype !== "Enumerated" ||
      edit.encoded_sha256 !== field.encoded_sha256 ||
      edit.before_value !== field.value ||
      edit.after_value !== expected.value ||
      edit.changed !== (field.value !== expected.value) ||
      edit.controller_write !== false ||
      edit.saved_settings_merged !== false ||
      edit.enum_semantics_verified !== false ||
      edit.unrelated_native_bytes_preserved !== true ||
      !hash(edit.plan_sha256) ||
      edit.output_sha256 !== result.output_sha256
    )
      throw new Error(
        "Enum copy evidence differs from this exact captured field. Inspect the original source again.",
      );
  }
  async function preview() {
    if (active.current || fieldBusy) return;
    active.current = true;
    const ticket = ++generation.current;
    setBusy(true);
    setReview(null);
    setError("");
    try {
      const expected = request(),
        document = await apiJsonDocument(base + "/preview", expected);
      check(document.data, expected);
      if (owned(ticket)) setReview({ document, generation: ticket });
    } catch (failure) {
      if (owned(ticket)) setError(String(failure));
    } finally {
      active.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function download() {
    if (active.current || fieldBusy || !current) return;
    active.current = true;
    const ticket = generation.current,
      expected = current.data;
    setBusy(true);
    setError("");
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...expected.request,
        review_sha256: expected.review_sha256,
      });
      if (
        result.headers?.get("X-Studio-Artifact-Sha256") !==
          expected.output_sha256 ||
        result.headers?.get("X-Studio-Review-Sha256") !==
          expected.review_sha256 ||
        result.headers?.get("X-Studio-Snapshot-Sha256") !==
          source.snapshot_sha256 ||
        (await sha256Blob(result.blob)) !== expected.output_sha256
      )
        throw new Error(
          "Enum copy download differs from its original source or review. Review the field again.",
        );
      if (owned(ticket)) saveBlob(result.blob, "native-enum-default-copy.moi");
    } catch (failure) {
      if (owned(ticket)) {
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
      aria-label="Native Enum default archive copy"
    >
      <h4>Local Enum default copy</h4>
      <p>
        Original stored code: <strong>{field.value}</strong> · {field.ref}
      </p>
      <p>
        Export a local native-file copy. Verify the code against this block’s
        Enum definitions; membership and state meanings are unverified. Saved
        settings are not merged.
      </p>
      <label>
        Proposed Enum code
        <input
          inputMode="numeric"
          aria-label="Proposed Enum code"
          maxLength={128}
          value={text}
          disabled={fieldBusy}
          onChange={(event) => {
            const value = event.target.value;
            if (!rememberEnumText(drafts, key, value, field.value)) {
              setError(capacity);
              return;
            }
            retire();
            setError("");
            setText(value);
          }}
        />
      </label>
      <div className="button-row">
        <button
          className={current ? undefined : "primary"}
          disabled={busy || fieldBusy}
          onClick={() => void preview()}
        >
          Review Enum copy
        </button>
        <button
          disabled={busy || fieldBusy || !drafts.has(key)}
          onClick={() => {
            retire();
            drafts.delete(key);
            setText(String(field.value));
            setError("");
          }}
        >
          Discard local Enum draft
        </button>
      </div>
      {busy && <p role="status">Preparing local Enum copy…</p>}
      {error && <p role="alert">{error}</p>}
      {current && (
        <section aria-label="Reviewed Enum archive copy">
          <p>
            Stored code {current.data.edit.before_value} → copy code{" "}
            {current.data.edit.after_value}. Other native record bytes remain
            preserved.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy || fieldBusy}
              onClick={() => void download()}
            >
              Save Enum file copy
            </button>
            <button
              disabled={busy || fieldBusy}
              onClick={() =>
                saveBlob(current.blob, "native-enum-copy-review.json")
              }
            >
              Save Enum copy review
            </button>
          </div>
          <details>
            <summary>Enum copy evidence</summary>
            <pre>{JSON.stringify(current.data, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
