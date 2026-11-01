import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { controllerKey } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";

export type BooleanCopyDrafts = Map<string, boolean>;
type Data = Record<string, any>;
export function BooleanCopyEditor({
  source,
  field,
  drafts,
  effective,
  renderTransfer,
}: {
  source: NativeArchiveSource;
  field: {
    ref: string;
    class_id: number;
    encoded_sha256: string;
    value: boolean;
  };
  drafts: BooleanCopyDrafts;
  effective?: { source_sha256: string; archive_value: boolean };
  renderTransfer?: (proposal: Data) => ReactNode;
}) {
  const transferContext = useContext(NativeBooleanTransferContext);
  const fieldBusy = transferContext?.fieldBusy ?? false;
  const transferActive =
    !!renderTransfer &&
    !!transferContext?.controller?.interfaceOpen &&
    controllerKey(transferContext.controller) === controllerKey(source.target);
  const base = effective
    ? "/bacnet/controller/native-application/boolean-default-compiler"
    : "/bacnet/controller/native-application/inspection/boolean-default";
  const profile = effective
    ? "native-effective-boolean-default-compiler/1"
    : "native-backup-boolean-default-copy/1";
  const label = effective ? "Boolean compilation" : "Boolean archive copy";
  const owner = JSON.stringify([source, field, effective]);
  const draftKey = JSON.stringify([
    effective ? "effective" : "archive",
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
        data.profile !== profile ||
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
        edit.source_sha256 !== (effective?.source_sha256 ?? source.sha256) ||
        edit.before_value !== field.value ||
        edit.after_value !== value ||
        edit.before_tag !== (field.value ? "11" : "10") ||
        edit.after_tag !== (value ? "11" : "10") ||
        edit.output_sha256 !== data.output_sha256 ||
        edit.controller_write !== false ||
        edit.saved_settings_merged !== false ||
        edit.changed !== (value !== field.value) ||
        (effective &&
          (data.saved_settings_merged !== true ||
            data.current_identity_verified !== false ||
            data.source_sha256 !== source.sha256 ||
            data.effective_sha256 !== effective.source_sha256 ||
            data.archive_value !== effective.archive_value ||
            data.compilation?.profile !== profile ||
            data.compilation.saved_settings_merged !== true ||
            data.compilation.other_merged_bytes_preserved !== true ||
            JSON.stringify(data.compilation.selected_edit) !==
              JSON.stringify(edit) ||
            data.compilation.controller_write !== false ||
            data.compilation.field_transfer_enabled !== false ||
            data.compilation.compiled_sha256 !== data.output_sha256 ||
            data.compilation.files?.["3"]?.sha256 !== source.sha256))
      )
        throw new Error(
          effective
            ? "Effective Boolean review differs from the selected source or proposal."
            : "Boolean archive-copy review differs from the selected source or proposal.",
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
        saveBlob(
          result.blob,
          effective
            ? "native-effective-boolean-default.moi"
            : "native-boolean-default-copy.moi",
        );
    } catch (error) {
      if (current(key, ticket)) setError(String(error));
    } finally {
      if (current(key, ticket)) setBusy(false);
    }
  }
  return (
    <details
      className="native-boolean-copy"
      aria-label={
        effective
          ? "Effective Boolean default compilation"
          : "Native Boolean archive copy"
      }
      open={effective ? true : undefined}
    >
      <summary>
        {effective
          ? "Compile a Boolean default with saved settings"
          : "Save a Boolean default archive copy"}
      </summary>
      <p>
        Existing Boolean Default Value (3113) · {field.ref}.{" "}
        {effective
          ? `Original archive default ${String(effective.archive_value)} · retained effective default ${String(field.value)}. Other retained saved application values are merged before this edit. This is not a fresh controller setting or a field transfer.`
          : "This edits a separate original archive copy. Saved settings are not merged and may override this default on a controller. No controller change is prepared."}
      </p>
      <label>
        <input
          type="checkbox"
          disabled={fieldBusy}
          aria-label={
            effective
              ? "Proposed effective Boolean default"
              : "Proposed Boolean archive default"
          }
          checked={value}
          onChange={(event) => change(event.target.checked)}
        />
        Proposed default: {String(value)}
      </label>
      <div className="button-row">
        <button
          className={shown || transferActive ? undefined : "primary"}
          disabled={busy || fieldBusy}
          onClick={() => void prepare()}
        >
          {effective
            ? "Review effective Boolean compilation"
            : "Review Boolean archive copy"}
        </button>
        <button
          disabled={busy || fieldBusy}
          onClick={() => change(field.value)}
        >
          {effective
            ? "Discard effective Boolean draft"
            : "Discard Boolean copy draft"}
        </button>
      </div>
      {busy && <p role="status">Preparing local {label}…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section
          aria-label={
            effective
              ? "Reviewed effective Boolean compilation"
              : "Reviewed Boolean archive copy"
          }
        >
          <p>
            {effective
              ? "Retained effective default"
              : "Original archive default"}{" "}
            {String(shown.data.edit.before_value)} · proposed{" "}
            {String(shown.data.edit.after_value)}.{" "}
            {shown.data.edit.changed
              ? "One native tag byte changes."
              : effective
                ? "Selected value unchanged; other retained saved settings remain merged."
                : "No value change; original archive bytes are preserved."}
          </p>
          <p>
            Retained source {source.capture_id.slice(0, 8)} ·{" "}
            {source.target.device} at {source.target.address}. Saving does not
            transfer this file.
          </p>
          <button
            className={transferActive ? undefined : "primary"}
            disabled={busy || fieldBusy}
            onClick={() => void save()}
          >
            {effective
              ? "Save compiled Boolean default"
              : "Save Boolean archive copy"}
          </button>
          <button
            onClick={() =>
              saveBlob(
                shown.blob,
                effective
                  ? "native-effective-boolean-review.json"
                  : "native-boolean-copy-review.json",
              )
            }
          >
            Save Boolean copy review JSON
          </button>
        </section>
      )}
      {renderTransfer?.(body)}
    </details>
  );
}
