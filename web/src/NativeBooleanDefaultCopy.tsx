import { useEffect, useRef, useState } from "react";
import { apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { controllerKey } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";

export type BooleanCopyDrafts = Map<string, boolean>;
type Data = Record<string, any>;
const base = "/bacnet/controller/native-application/inspection/boolean-default";
export function NativeBooleanDefaultCopy({
  source,
  field,
  drafts,
}: {
  source: NativeArchiveSource;
  field: {
    ref: string;
    class_id: number;
    encoded_sha256: string;
    value: boolean;
  };
  drafts: BooleanCopyDrafts;
}) {
  const owner = JSON.stringify([source, field]);
  const draftKey = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    field.ref,
    field.encoded_sha256,
  ]);
  const [value, setValue] = useState(drafts.get(draftKey) ?? field.value);
  const [review, setReview] = useState<{
    data: Data;
    blob: Blob;
    ticket: number;
  } | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const epoch = useRef(0),
    ownerNow = useRef(owner),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const shown = review && current(owner, review.ticket) ? review : null;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  function change(next: boolean) {
    if (next !== field.value && !drafts.has(draftKey) && drafts.size >= 256) {
      setError(
        "256 Boolean copy drafts are retained. Discard an older draft before editing another field.",
      );
      return;
    }
    if (next === field.value) drafts.delete(draftKey);
    else drafts.set(draftKey, next);
    epoch.current++;
    setReview(null);
    setValue(next);
    setError("");
    setBusy(false);
  }
  const body = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: source.sha256,
    record_ref: field.ref,
    encoded_sha256: field.encoded_sha256,
    value,
  };
  async function prepare() {
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setReview(null);
    setError("");
    setBusy(true);
    try {
      const result = await apiJsonDocument(base + "/preview", body),
        data = result.data,
        edit = data.edit;
      if (
        data.profile !== "native-backup-boolean-default-copy/1" ||
        !Object.entries(body).every(
          ([name, input]) => data.request?.[name] === input,
        ) ||
        typeof data.target?.address !== "string" ||
        typeof data.target?.device !== "string" ||
        controllerKey(data.target) !== controllerKey(source.target) ||
        !/^[a-f0-9]{64}$/.test(data.review_sha256 || "") ||
        !/^[a-f0-9]{64}$/.test(data.output_sha256 || "") ||
        data.source_immutable !== true ||
        data.controller_queries !== false ||
        data.controller_write !== false ||
        data.field_transfer_enabled !== false ||
        edit?.profile !== "tagged-moi-boolean-default-copy/1" ||
        edit.record_ref !== field.ref ||
        edit.class_id !== field.class_id ||
        edit.property !== 3113 ||
        edit.datatype !== "Boolean" ||
        edit.encoded_sha256 !== field.encoded_sha256 ||
        edit.source_sha256 !== source.sha256 ||
        edit.before_value !== field.value ||
        edit.after_value !== value ||
        edit.before_tag !== (field.value ? "11" : "10") ||
        edit.after_tag !== (value ? "11" : "10") ||
        edit.output_sha256 !== data.output_sha256 ||
        edit.controller_write !== false ||
        edit.saved_settings_merged !== false ||
        edit.changed !== (value !== field.value)
      )
        throw new Error(
          "Boolean archive-copy review differs from the selected source or proposal.",
        );
      if (current(key, ticket)) setReview({ data, blob: result.blob, ticket });
    } catch (error) {
      if (current(key, ticket)) setError(String(error));
    } finally {
      if (current(key, ticket)) setBusy(false);
    }
  }
  async function save() {
    if (!shown) return;
    const key = ownerNow.current,
      ticket = epoch.current,
      accepted = shown.data;
    setError("");
    setBusy(true);
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...body,
        review_sha256: accepted.review_sha256,
      });
      if (
        result.headers.get("X-Studio-Review-Sha256") !==
          accepted.review_sha256 ||
        result.headers.get("X-Studio-Snapshot-Sha256") !==
          source.snapshot_sha256 ||
        result.headers.get("X-Studio-Artifact-Sha256") !==
          accepted.output_sha256 ||
        (await sha256Blob(result.blob)) !== accepted.output_sha256
      )
        throw new Error(
          "Boolean archive copy failed its reviewed source or byte-digest check.",
        );
      if (current(key, ticket))
        saveBlob(result.blob, "native-boolean-default-copy.moi");
    } catch (error) {
      if (current(key, ticket)) setError(String(error));
    } finally {
      if (current(key, ticket)) setBusy(false);
    }
  }
  return (
    <details
      className="native-boolean-copy"
      aria-label="Native Boolean archive copy"
    >
      <summary>Save a Boolean default archive copy</summary>
      <p>
        Existing Boolean Default Value (3113) · {field.ref}. This edits a
        separate original archive copy. Saved settings are not merged and may
        override this default on a controller. No controller change is prepared.
      </p>
      <label>
        <input
          type="checkbox"
          aria-label="Proposed Boolean archive default"
          checked={value}
          onChange={(event) => change(event.target.checked)}
        />
        Proposed default: {String(value)}
      </label>
      <div className="button-row">
        <button
          className={shown ? undefined : "primary"}
          disabled={busy}
          onClick={() => void prepare()}
        >
          Review Boolean archive copy
        </button>
        <button disabled={busy} onClick={() => change(field.value)}>
          Discard Boolean copy draft
        </button>
      </div>
      {busy && <p role="status">Preparing local Boolean archive copy…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Reviewed Boolean archive copy">
          <p>
            Original archive default {String(shown.data.edit.before_value)} ·
            proposed {String(shown.data.edit.after_value)}.{" "}
            {shown.data.edit.changed
              ? "One native tag byte changes."
              : "No value change; original archive bytes are preserved."}
          </p>
          <p>
            Retained source {source.capture_id.slice(0, 8)} ·{" "}
            {source.target.device} at {source.target.address}. Saving does not
            transfer this file.
          </p>
          <button
            className="primary"
            disabled={busy}
            onClick={() => void save()}
          >
            Save Boolean archive copy
          </button>
          <button
            onClick={() =>
              saveBlob(shown.blob, "native-boolean-copy-review.json")
            }
          >
            Save Boolean copy review JSON
          </button>
        </section>
      )}
    </details>
  );
}
