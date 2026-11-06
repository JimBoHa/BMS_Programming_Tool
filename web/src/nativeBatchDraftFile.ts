import { parseSourceJSON, sourceEqual } from "./programSource";
import { defaultBatchSource } from "./nativeDefaultBatchContract";

type Data = Record<string, any>;
export const nativeBatchDraftProfile =
  "native-default-batch-unfinished-draft/1";
export const nativeBatchDraftBytes = 64 * 1024;
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const rawText = (v: unknown) =>
  typeof v === "string" &&
  v.length <= 128 &&
  !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(
    v,
  );

function binding(source: Data, opened: Data) {
  if (!defaultBatchSource(opened, source))
    throw new Error(
      "Open the actual retained native source and its typed batch first.",
    );
  return structuredClone({
    capture_id: opened.capture_id,
    snapshot_sha256: opened.snapshot_sha256,
    captured_at: opened.captured_at,
    target: opened.target,
    identity: opened.identity,
    source_sha256: opened.source_sha256,
    effective_sha256: opened.effective_sha256,
    effective_native_sha256: opened.parameter_merge.native_output_sha256,
    files: opened.files,
  });
}

function fieldBinding(opened: Data, ref: string) {
  const row = opened.fields.find((r: Data) => r.field.ref === ref);
  if (!row)
    throw new Error("A draft field is absent from this actual native source.");
  const f = row.field;
  return {
    kind: row.kind,
    record_ref: f.ref,
    class_id: f.class_id,
    property: f.property,
    encoded_sha256: f.encoded_sha256,
    ...(row.kind === "real"
      ? { effective_bits: f.effective_bits }
      : { effective_value: f.effective_value }),
    ...(row.kind === "enum" ? { maximum_code: f.maximum_code } : {}),
  };
}

function checkedDocument(value: Data, source: Data, opened: Data) {
  if (
    !exact(value, [
      "profile",
      "field_authority",
      "controller_queries",
      "native_review_created",
      "current_identity_verified",
      "source",
      "buffers",
    ]) ||
    value.profile !== nativeBatchDraftProfile ||
    value.field_authority !== false ||
    value.controller_queries !== false ||
    value.native_review_created !== false ||
    value.current_identity_verified !== false ||
    !sourceEqual(value.source, binding(source, opened)) ||
    !Array.isArray(value.buffers) ||
    !value.buffers.length ||
    value.buffers.length > 16
  )
    throw new Error(
      "Unfinished batch draft has unknown authority, a different source or invalid selection count. Existing work was kept.",
    );
  const recovered: Record<string, string> = Object.create(null);
  for (const row of value.buffers) {
    const ref = row?.field?.record_ref;
    if (
      !exact(row, ["field", "value_text"]) ||
      typeof ref !== "string" ||
      Object.hasOwn(recovered, ref) ||
      !rawText(row.value_text) ||
      !sourceEqual(row.field, fieldBinding(opened, ref)) ||
      (row.field.kind === "boolean" &&
        !["true", "false"].includes(row.value_text))
    )
      throw new Error(
        "Unfinished batch fields must match actual types and encodings, with distinct selections and bounded raw text. Existing work was kept.",
      );
    recovered[ref] = row.value_text;
  }
  return recovered;
}

export function nativeBatchDraftDocument(
  source: Data,
  opened: Data,
  entries: Record<string, string>,
) {
  const document = {
    profile: nativeBatchDraftProfile,
    field_authority: false,
    controller_queries: false,
    native_review_created: false,
    current_identity_verified: false,
    source: binding(source, opened),
    buffers: Object.entries(entries).map(([ref, value_text]) => ({
      field: fieldBinding(opened, ref),
      value_text,
    })),
  };
  checkedDocument(document, source, opened);
  const blob = new Blob([JSON.stringify(document, null, 2)], {
    type: "application/json",
  });
  if (blob.size > nativeBatchDraftBytes)
    throw new Error(
      "Unfinished batch draft exceeds 64 KiB; existing work was kept.",
    );
  return blob;
}

export function parseNativeBatchDraft(raw: string, source: Data, opened: Data) {
  if (
    !raw.length ||
    new TextEncoder().encode(raw).length > nativeBatchDraftBytes
  )
    throw new Error(
      "Choose an unfinished batch draft JSON file no larger than 64 KiB.",
    );
  // Retain the shared duplicate-key/depth/Unicode admission before ordinary JSON.
  // Raw Real and Enum text is never parsed as a proposed native value here.
  parseSourceJSON(raw);
  return checkedDocument(JSON.parse(raw), source, opened);
}
