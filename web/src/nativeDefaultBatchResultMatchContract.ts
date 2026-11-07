import { connectionSame as same } from "./nativeConnectionContract";
import { defaultBatchRecoveryParent } from "./nativeDefaultBatchRecoveryContract";
import {
  batchRecoveryTransferReceipt,
  batchRecoveryTransferProfile,
} from "./nativeDefaultBatchRecoveryTransferContract";
type Data = Record<string, any>;
export const batchResultMatchProfile = "native-default-batch-result-match/1";
export const batchResultMatchScope =
  "Local retained-source comparison with a reconstructed, historically verified typed batch result. Report captured route/identity, expanded application, effective saved values and original directory differences separately. No current-device verification, parent revalidation, compilation authority, recovery proposal, field review or transfer.";
export const batchResultMatchBase =
  "/bacnet/controller/native-application/default-batch/result/compare";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const recovery = (v: Data) =>
  !!v && Object.keys(v).some((k) => k.startsWith("recovery_"));
export function batchResultParentProblem(receipt: Data) {
  if (receipt.pending !== false)
    return "Read back and resolve the original batch outcome before comparing its result.";
  if (
    !receipt.intent ||
    (receipt.result
      ? receipt.result.may_have_applied
      : receipt.intent.may_have_applied) !== true
  )
    return "This receipt records no possible batch restore.";
  if (
    receipt.result?.status !== "verified" &&
    !receipt.events?.some(
      (e: Data) => e?.stage === "readback" && e.detail?.status === "verified",
    )
  )
    return "This receipt has no retained verified batch outcome.";
  return null;
}
export async function batchResultMatchParent(receipt: Data) {
  return (
    batchResultParentProblem(receipt) === null &&
    (recovery(receipt.intent)
      ? batchRecoveryTransferReceipt(receipt)
      : defaultBatchRecoveryParent(receipt))
  );
}
function typed(kind: string, value: any, wideEnum = false) {
  if (kind === "real") {
    if (
      !exact(value, ["bits"]) ||
      typeof value.bits !== "string" ||
      !/^[a-f0-9]{8}$/.test(value.bits)
    )
      return false;
    const v = new DataView(
      Uint8Array.from(value.bits.match(/../g)!, (b: string) =>
        parseInt(b, 16),
      ).buffer,
    ).getFloat32(0, false);
    return Number.isFinite(v);
  }
  return (
    exact(value, ["value"]) &&
    (kind === "boolean"
      ? typeof value.value === "boolean"
      : kind === "enum" &&
        Number.isSafeInteger(value.value) &&
        value.value >= 0 &&
        value.value <= (wideEnum ? 4294967295 : 65535))
  );
}
function encoded(kind: string, hex: string) {
  return kind === "real"
    ? { bits: hex.slice(2, -2) }
    : {
        value:
          kind === "boolean" ? hex === "112f" : parseInt(hex.slice(2, -2), 16),
      };
}
export function batchMatchValue(kind: string, value: Data) {
  return kind === "real"
    ? new DataView(
        Uint8Array.from(value.bits.match(/../g)!, (b: string) =>
          parseInt(b, 16),
        ).buffer,
      ).getFloat32(0, false)
    : value.value;
}
export async function batchResultMatchEvidence(
  v: Data,
  source: Data,
  opened: Data,
  receipt: Data,
) {
  try {
    const p = receipt.intent,
      c = p?.compilation;
    if (
      !(await batchResultMatchParent(receipt)) ||
      !exact(v, [
        "profile",
        "scope",
        "receipt_id",
        "intent_sha256",
        "verified_proof",
        "recorded_recovery_child",
        "original_backup_id",
        "original_snapshot_sha256",
        "recorded_target",
        "current_target",
        "recorded_identity",
        "expected_native_sha256",
        "current_native_sha256",
        "current_effective_sha256",
        "current_effective_native_sha256",
        "source",
        "state",
        "comparisons",
        "selected",
        "read_only",
        "controller_queries",
        "field_actions",
        "can_apply",
        "field_transfer_enabled",
        "current_device_verified",
        "parent_revalidated",
        "enum_semantics_verified",
        "evidence_sha256",
      ]) ||
      v.profile !== batchResultMatchProfile ||
      v.scope !== batchResultMatchScope ||
      v.read_only !== true ||
      [
        "controller_queries",
        "field_actions",
        "can_apply",
        "field_transfer_enabled",
        "current_device_verified",
        "parent_revalidated",
        "enum_semantics_verified",
      ].some((k) => v[k] !== false) ||
      v.receipt_id !== p.id ||
      v.intent_sha256 !== p.evidence_sha256 ||
      v.original_backup_id !== p.backup_id ||
      !id(v.original_backup_id) ||
      !hash(v.original_snapshot_sha256) ||
      v.recorded_recovery_child !==
        (p.recovery_profile === batchRecoveryTransferProfile) ||
      !same(v.recorded_target, p.target) ||
      !same(v.current_target, source.target) ||
      !same(v.recorded_identity, p.identity) ||
      source.capture_id !== opened.capture_id ||
      source.snapshot_sha256 !== opened.snapshot_sha256 ||
      ![
        v.expected_native_sha256,
        v.current_native_sha256,
        v.current_effective_sha256,
        v.current_effective_native_sha256,
        v.evidence_sha256,
      ].every(hash) ||
      v.expected_native_sha256 !== p.native_payload_sha256 ||
      v.current_effective_sha256 !== opened.effective_sha256 ||
      !exact(v.source, [
        "capture_id",
        "snapshot_sha256",
        "source_sha256",
        "effective_sha256",
        "target",
        "identity",
        "captured_at",
        "source_identity_matches",
        "files",
      ]) ||
      Object.keys(v.source).some((k) => !same(v.source[k], opened[k])) ||
      !exact(v.verified_proof, ["kind", "sha256", "time"]) ||
      !hash(v.verified_proof.sha256) ||
      typeof v.verified_proof.time !== "string" ||
      !Number.isFinite(Date.parse(v.verified_proof.time)) ||
      !Array.isArray(v.selected) ||
      !v.selected.length ||
      v.selected.length > 16 ||
      v.selected.length !== c?.selected?.length
    )
      return false;
    const proof = v.verified_proof;
    if (
      !(
        proof.kind === "result" &&
        receipt.result?.status === "verified" &&
        receipt.result.evidence_sha256 === proof.sha256 &&
        receipt.result.finished_at === proof.time
      ) &&
      !(
        proof.kind === "readback-event" &&
        receipt.events?.some(
          (e: Data) =>
            e.stage === "readback" &&
            e.detail?.status === "verified" &&
            e.evidence_sha256 === proof.sha256 &&
            e.created_at === proof.time,
        )
      )
    )
      return false;
    for (const [i, row] of v.selected.entries()) {
      const selected = c.selected[i],
        g = c.batch_guard.fields[i],
        candidate = opened.fields.find(
          (r: Data) => r.field.ref === row.record_ref,
        );
      let current: Data | null = null,
        schema: boolean | null = null;
      if (candidate) {
        const f = candidate.field,
          kind = candidate.kind;
        const value =
          kind === "real"
            ? { bits: f.effective_bits }
            : { value: f.effective_value };
        if (!typed(kind, value, true)) return false;
        current = {
          kind,
          class_id: f.class_id,
          property: f.property,
          value,
          encoded_sha256: f.encoded_sha256,
        };
        if (row.kind === "enum")
          schema =
            kind === "enum" &&
            same(f.saved_storage, g.saved_storage) &&
            f.states_text_encoded_sha256 === g.states_text_encoded_sha256;
      }
      const expected = encoded(selected.kind, selected.after_encoding_hex),
        matches =
          current !== null &&
          current.kind === selected.kind &&
          current.class_id === selected.class_id &&
          current.property === 3113 &&
          same(current.value, expected);
      if (
        !exact(row, [
          "kind",
          "record_ref",
          "class_id",
          "property",
          "expected",
          "current",
          "matches",
          "enum_schema_matches",
        ]) ||
        row.kind !== selected.kind ||
        row.record_ref !== selected.record_ref ||
        row.class_id !== selected.class_id ||
        row.property !== 3113 ||
        !typed(row.kind, row.expected) ||
        !same(row.expected, expected) ||
        !same(row.current, current) ||
        row.matches !== matches ||
        row.enum_schema_matches !== schema
      )
        return false;
    }
    const comparisons = {
      route_matches: same(source.target, p.target),
      identity_matches: same(opened.identity, p.identity),
      expanded_application_matches:
        v.current_native_sha256 === v.expected_native_sha256,
      effective_application_matches:
        v.current_effective_native_sha256 === v.expected_native_sha256,
      selected_values_match: v.selected.every((r: Data) => r.matches === true),
      original_saved_directory_matches:
        opened.files["11"].sha256 === c.files["11"].sha256,
    };
    const matched =
      opened.source_identity_matches === true &&
      [
        "route_matches",
        "identity_matches",
        "expanded_application_matches",
        "effective_application_matches",
        "selected_values_match",
      ].every((k) => (comparisons as Data)[k]);
    return (
      same(v.comparisons, comparisons) &&
      v.state === (matched ? "application-and-values-match" : "different")
    );
  } catch {
    return false;
  }
}
