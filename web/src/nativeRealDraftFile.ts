import { parseSourceJSON, sourceEqual } from "./programSource";

type Data = Record<string, any>;
export const nativeRealDraftProfile = "native-real-unfinished-draft/1";
export const nativeRealDraftBytes = 16 * 1024;
const object = (v: any, required: string[], optional: string[] = []) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  required.every((k) => Object.hasOwn(v, k)) &&
  Object.keys(v).every((k) => required.includes(k) || optional.includes(k));
const text = (v: any, max: number, nonempty = false) =>
  typeof v === "string" &&
  v.length <= max &&
  (!nonempty || v.length > 0) &&
  !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(
    v,
  );
const hash = (v: any, size = 64) =>
  typeof v === "string" && new RegExp(`^[a-f0-9]{${size}}$`).test(v);
function bindingShape(v: Data) {
  const target = v?.target;
  return (
    object(v, [
      "capture_id",
      "snapshot_sha256",
      "captured_at",
      "device",
      "target",
      "record_ref",
      "class_id",
      "property",
      "encoded_sha256",
      "effective_bits",
    ]) &&
    hash(v.capture_id, 32) &&
    hash(v.snapshot_sha256) &&
    text(v.captured_at, 128, true) &&
    typeof v.device === "string" &&
    /^device,(0|[1-9][0-9]*)$/.test(v.device) &&
    Number(v.device.split(",")[1]) <= 4194302 &&
    object(target, ["address", "router", "dnet"], ["device"]) &&
    text(target.address, 1024, true) &&
    (target.router === null || text(target.router, 1024, true)) &&
    (target.dnet === null ||
      (Number.isInteger(target.dnet) &&
        target.dnet >= 0 &&
        target.dnet <= 65535)) &&
    (target.device === undefined || target.device === v.device) &&
    text(v.record_ref, 512, true) &&
    [526, 527].includes(v.class_id) &&
    v.property === 3113 &&
    hash(v.encoded_sha256) &&
    hash(v.effective_bits, 8)
  );
}
export function nativeRealDraftBinding(source: Data, field: Data) {
  const binding = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    captured_at: source.captured_at,
    device: source.device,
    target: source.target,
    record_ref: field.ref,
    class_id: field.class_id,
    property: field.property,
    encoded_sha256: field.encoded_sha256,
    effective_bits: field.effective_bits,
  };
  if (
    source.profile !== "native-effective-signal-default-compiler/1" ||
    source.controller_queries !== false ||
    source.controller_write !== false ||
    !bindingShape(binding) ||
    !Array.isArray(source.fields) ||
    !source.fields.some((f: Data) => sourceEqual(f, field))
  )
    throw new Error(
      "Open the actual retained native source and select its Real field first.",
    );
  return structuredClone(binding);
}
function checkedDocument(value: Data) {
  if (
    !object(value, [
      "profile",
      "field_authority",
      "controller_queries",
      "native_review_created",
      "current_identity_verified",
      "source",
      "buffer",
    ]) ||
    value.profile !== nativeRealDraftProfile ||
    value.field_authority !== false ||
    value.controller_queries !== false ||
    value.native_review_created !== false ||
    value.current_identity_verified !== false ||
    !bindingShape(value.source) ||
    !object(value.buffer, ["value_text"]) ||
    !text(value.buffer.value_text, 128)
  )
    throw new Error(
      "Unfinished Real draft has unknown fields or exceeds its raw text limits.",
    );
  return value;
}
export function nativeRealDraftDocument(
  source: Data,
  field: Data,
  valueText: string,
) {
  const document = checkedDocument({
    profile: nativeRealDraftProfile,
    field_authority: false,
    controller_queries: false,
    native_review_created: false,
    current_identity_verified: false,
    source: nativeRealDraftBinding(source, field),
    buffer: { value_text: valueText },
  });
  const blob = new Blob([JSON.stringify(document, null, 2)], {
    type: "application/json",
  });
  if (blob.size > nativeRealDraftBytes)
    throw new Error(
      "Unfinished Real draft exceeds 16 KiB; existing work was kept.",
    );
  return blob;
}
export function parseNativeRealDraft(raw: string, source: Data, field: Data) {
  if (
    !raw.length ||
    new TextEncoder().encode(raw).length > nativeRealDraftBytes
  )
    throw new Error(
      "Choose an unfinished Real draft JSON file no larger than 16 KiB.",
    );
  // The shared parser rejects duplicate keys, excessive nesting and malformed
  // Unicode before ordinary JSON values are admitted. Raw text is never parsed
  // as a Real, rounded or submitted to a native compiler here.
  parseSourceJSON(raw);
  const document = checkedDocument(JSON.parse(raw));
  if (!sourceEqual(document.source, nativeRealDraftBinding(source, field)))
    throw new Error(
      "This draft belongs to a different retained source, route or Real field. Existing text was kept.",
    );
  return document.buffer.value_text as string;
}
