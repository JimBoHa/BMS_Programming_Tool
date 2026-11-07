import { sha256 } from "@noble/hashes/sha2.js";
import { recordedDefaultBatch } from "./NativeDefaultBatchLedgerView";
import { batchRecoveryOriginJSON } from "./nativeDefaultBatchRecoveryContract";
import { connectionSame as same } from "./nativeConnectionContract";
type Data = Record<string, any>;
export const batchRecoveryRecordedProfile =
  "native-default-batch-recovery-recorded/1";
export const batchRecoveryRecordedScope =
  "Recorded previous typed batch origin seal and child-receipt bindings only. Parent receipts, backup files and current controller state are not revalidated. This projection grants no recovery or transfer authority; Enum meanings remain unverified.";
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const digest = (v: Uint8Array) =>
  Array.from(sha256(v), (b) => b.toString(16).padStart(2, "0")).join("");
const bytes = (v: string) =>
  Uint8Array.from(v.match(/../g) || [], (b) => parseInt(b, 16));
export function recordedBatchValue(kind: string, v: Data) {
  return kind === "real"
    ? new DataView(bytes(v.bits).buffer).getFloat32(0, false)
    : v.value;
}
const typed = (kind: string, v: any) =>
  kind === "real"
    ? exact(v, ["bits"]) &&
      typeof v.bits === "string" &&
      /^[a-f0-9]{8}$/.test(v.bits) &&
      Number.isFinite(recordedBatchValue(kind, v))
    : exact(v, ["value"]) &&
      (kind === "boolean"
        ? typeof v.value === "boolean"
        : kind === "enum" &&
          Number.isSafeInteger(v.value) &&
          v.value >= 0 &&
          v.value <= 65535);
function tag(kind: string, hex: string) {
  return kind === "real"
    ? { bits: hex.slice(2, -2) }
    : {
        value:
          kind === "boolean" ? hex === "112f" : parseInt(hex.slice(2, -2), 16),
      };
}
export function recordedBatchRecovery(
  row: Data | null | undefined,
): Data | null {
  try {
    const v = row?.native_default_batch_recovery,
      base = recordedDefaultBatch(row?.native_default_batch),
      o = v?.origin;
    if (
      !row ||
      row.source !== "native" ||
      row.native_change_kind !== "default-batch" ||
      !base ||
      !exact(v, [
        "state",
        "profile",
        "scope",
        "child_receipt_id",
        "instance",
        "review_capture_id",
        "review_snapshot_sha256",
        "origin",
        "origin_sha256",
        "compiled_native_sha256",
        "field_authority",
        "parent_revalidated",
        "source_revalidated",
        "current_device_verified",
      ]) ||
      v.state !== "recorded" ||
      v.profile !== batchRecoveryRecordedProfile ||
      v.scope !== batchRecoveryRecordedScope ||
      !id(row.id) ||
      v.child_receipt_id !== row.id ||
      !Number.isSafeInteger(v.instance) ||
      v.instance < 0 ||
      v.instance > 4194302 ||
      row.target?.device !== `device,${v.instance}` ||
      [
        "field_authority",
        "parent_revalidated",
        "source_revalidated",
        "current_device_verified",
      ].some((k) => v[k] !== false) ||
      !hash(v.origin_sha256) ||
      v.compiled_native_sha256 !== base.compiled_native_sha256 ||
      !exact(o, [
        "profile",
        "parent_receipt_id",
        "parent_intent_sha256",
        "original_dispatch",
        "verified_proof",
        "original_backup_id",
        "original_snapshot_sha256",
        "current_capture_id",
        "current_snapshot_sha256",
        "recorded_native_payload_sha256",
        "fields",
        "enum_semantics_verified",
      ]) ||
      o.profile !== "native-default-batch-recovery-draft/1" ||
      !id(o.parent_receipt_id) ||
      o.parent_receipt_id === row.id ||
      !id(o.original_backup_id) ||
      !id(o.current_capture_id) ||
      o.original_backup_id === o.current_capture_id ||
      o.current_capture_id !== v.review_capture_id ||
      o.current_snapshot_sha256 !== v.review_snapshot_sha256 ||
      ![
        o.parent_intent_sha256,
        o.original_snapshot_sha256,
        o.current_snapshot_sha256,
        o.recorded_native_payload_sha256,
      ].every(hash) ||
      o.original_dispatch !== "possible" ||
      o.enum_semantics_verified !== false ||
      !exact(o.verified_proof, ["kind", "sha256", "time"]) ||
      !["result", "readback-event"].includes(o.verified_proof.kind) ||
      !hash(o.verified_proof.sha256) ||
      typeof o.verified_proof.time !== "string" ||
      !/(Z|[+-]\d{2}:\d{2})$/.test(o.verified_proof.time) ||
      !Number.isFinite(Date.parse(o.verified_proof.time)) ||
      !Array.isArray(o.fields) ||
      o.fields.length !== base.selected.length ||
      row.object !== `${o.fields.length} typed defaults`
    )
      return null;
    for (const [i, f] of o.fields.entries()) {
      const s = base.selected[i];
      if (
        !exact(f, [
          "kind",
          "record_ref",
          "class_id",
          "property",
          "previous",
          "recorded_after",
          "current",
          "already_recorded",
          "current_encoded_sha256",
        ]) ||
        f.kind !== s.kind ||
        f.record_ref !== s.record_ref ||
        f.class_id !== s.class_id ||
        f.property !== 3113 ||
        ![f.previous, f.recorded_after, f.current].every((v) =>
          typed(f.kind, v),
        ) ||
        !same(f.previous, tag(f.kind, s.after_encoding_hex)) ||
        !same(f.current, tag(f.kind, s.before_encoding_hex)) ||
        f.current_encoded_sha256 !== digest(bytes(s.before_encoding_hex)) ||
        f.already_recorded !== same(f.current, f.previous) ||
        (!same(f.current, f.previous) && !same(f.current, f.recorded_after))
      )
        return null;
    }
    return digest(new TextEncoder().encode(batchRecoveryOriginJSON(o))) ===
      v.origin_sha256
      ? v
      : null;
  } catch {
    return null;
  }
}
