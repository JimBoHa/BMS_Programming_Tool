import { sha256Blob } from "./activityContracts";
import { connectionSame as same } from "./nativeConnectionContract";
import {
  defaultBatchTransferCompilation,
  defaultBatchTransferProposal,
  defaultBatchTransferReceipt,
  defaultBatchTransferTarget,
} from "./nativeDefaultBatchTransferContract";
type Data = Record<string, any>;
export const batchRecoveryProfile = "native-default-batch-recovery-draft/1";
export const batchRecoveryBase =
  "/bacnet/controller/native-application/default-batch/recovery/prepare";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
function originJSON(v: any): string {
  if (Array.isArray(v)) return "[" + v.map(originJSON).join(",") + "]";
  if (v && typeof v === "object")
    return (
      "{" +
      Object.keys(v)
        .sort()
        .map((k) => originJSON(k) + ":" + originJSON(v[k]))
        .join(",") +
      "}"
    );
  if (typeof v === "number" && !Number.isSafeInteger(v))
    throw new Error("Recovery origin contains a noninteger.");
  return JSON.stringify(v).replace(
    /[\u007f-\uffff]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
  );
}
export const batchRecoveryOriginJSON = originJSON;
const bitsOf = (value: number) => {
  if (!Number.isFinite(value)) return null;
  const view = new DataView(new ArrayBuffer(4));
  view.setFloat32(0, value, false);
  return view.getUint32(0, false).toString(16).padStart(8, "0");
};
function afterValue(kind: string, hex: string) {
  if (kind === "real" && /^44[a-f0-9]{8}2f$/.test(hex))
    return { bits: hex.slice(2, -2) };
  if (kind === "boolean" && /^1[01]2f$/.test(hex))
    return { value: hex[1] === "1" };
  if (kind === "enum" && /^9[12](?:[a-f0-9]{2}){1,2}2f$/.test(hex))
    return { value: Number.parseInt(hex.slice(2, -2), 16) };
  throw new Error("Unsupported recorded typed encoding.");
}

// Historical display/preparation only; field admission keeps its own contract.
export async function defaultBatchRecoveryParent(receipt: Data) {
  try {
    if (
      receipt.pending !== false ||
      !receipt.intent ||
      (receipt.result
        ? receipt.result.may_have_applied
        : receipt.intent.may_have_applied) !== true
    )
      return false;
    if (await defaultBatchTransferReceipt(receipt)) return true;
    const event = receipt.events?.find(
      (e: Data) => e.stage === "readback" && e.detail?.status === "verified",
    );
    return (
      !!event &&
      hash(event.evidence_sha256) &&
      Number.isFinite(Date.parse(event.created_at)) &&
      (await defaultBatchTransferReceipt({
        ...receipt,
        latest_readback: event.detail,
      }))
    );
  } catch {
    return false;
  }
}

export async function defaultBatchRecoveryEvidence(
  data: Data,
  opened: Data,
  receipt: Data,
) {
  try {
    if (
      !exact(data, [
        "profile",
        "scope",
        "source",
        "origin",
        "origin_sha256",
        "proposal",
        "compilation",
        "output_sha256",
        "already_recorded",
        "read_only",
        "controller_queries",
        "field_actions",
        "can_apply",
        "field_transfer_enabled",
        "new_review_required",
        "enum_semantics_verified",
        "evidence_sha256",
      ]) ||
      data.profile !== batchRecoveryProfile ||
      typeof data.scope !== "string" ||
      !data.scope.length ||
      !hash(data.evidence_sha256) ||
      !hash(data.origin_sha256) ||
      !same(data.source, opened) ||
      opened.source_identity_matches !== true ||
      data.read_only !== true ||
      data.controller_queries !== false ||
      data.field_actions !== false ||
      data.can_apply !== false ||
      data.field_transfer_enabled !== false ||
      data.enum_semantics_verified !== false ||
      !(await defaultBatchRecoveryParent(receipt)) ||
      receipt.pending !== false
    )
      return false;
    const i = receipt.intent,
      o = data.origin,
      result = receipt.result;
    if (
      (result ? result.may_have_applied : i.may_have_applied) !== true ||
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
      o.profile !== batchRecoveryProfile ||
      o.parent_receipt_id !== i.id ||
      o.parent_intent_sha256 !== i.evidence_sha256 ||
      o.original_dispatch !== "possible" ||
      o.original_backup_id !== i.backup_id ||
      !hash(o.original_snapshot_sha256) ||
      o.current_capture_id !== opened.capture_id ||
      o.current_snapshot_sha256 !== opened.snapshot_sha256 ||
      o.recorded_native_payload_sha256 !== i.native_payload_sha256 ||
      opened.files["11"].sha256 !== i.compilation.files["11"].sha256 ||
      !same(opened.identity, i.identity) ||
      !defaultBatchTransferTarget(
        { ...i.target, device: i.identity.device },
        opened.target,
      ) ||
      o.enum_semantics_verified !== false ||
      !Array.isArray(o.fields) ||
      o.fields.length !== i.batch_guard.fields.length
    )
      return false;
    const proof = o.verified_proof;
    if (
      !exact(proof, ["kind", "sha256", "time"]) ||
      !hash(proof.sha256) ||
      !Number.isFinite(Date.parse(proof.time))
    )
      return false;
    if (
      proof.kind === "result"
        ? !(
            result?.status === "verified" &&
            result.evidence_sha256 === proof.sha256 &&
            result.finished_at === proof.time
          )
        : !(
            proof.kind === "readback-event" &&
            receipt.events?.some(
              (event: Data) =>
                event.stage === "readback" &&
                event.detail?.status === "verified" &&
                event.evidence_sha256 === proof.sha256 &&
                event.created_at === proof.time,
            )
          )
    )
      return false;
    let already = true;
    for (const [index, g] of i.batch_guard.fields.entries()) {
      const f = opened.fields.find(
        (r: Data) => r.kind === g.kind && r.field.ref === g.record_ref,
      )?.field;
      if (
        !f ||
        f.class_id !== g.class_id ||
        (g.kind === "enum" &&
          (!same(f.saved_storage, g.saved_storage) ||
            f.states_text_encoded_sha256 !== g.states_text_encoded_sha256))
      )
        return false;
      const previous =
        g.kind === "real" ? { bits: g.prior_bits } : { value: g.prior_value };
      const after = afterValue(
        g.kind,
        i.compilation.selected[index].after_encoding_hex,
      );
      const current =
        g.kind === "real"
          ? { bits: f.effective_bits }
          : { value: f.effective_value };
      const present = same(current, previous);
      if (!present && !same(current, after)) return false;
      const expected = {
        kind: g.kind,
        record_ref: g.record_ref,
        class_id: g.class_id,
        property: 3113,
        previous,
        recorded_after: after,
        current,
        already_recorded: present,
        current_encoded_sha256: f.encoded_sha256,
      };
      if (!same(o.fields[index], expected)) return false;
      already &&= present;
    }
    if (
      data.already_recorded !== already ||
      data.new_review_required !== !already ||
      (await sha256Blob(new Blob([originJSON(o)]))) !== data.origin_sha256
    )
      return false;
    if (already)
      return (
        data.proposal === null &&
        data.compilation === null &&
        data.output_sha256 === null
      );
    const p = data.proposal;
    if (
      !defaultBatchTransferProposal(p, opened) ||
      !defaultBatchTransferCompilation(data.compilation, p, opened) ||
      data.compilation.changed_count < 1 ||
      data.output_sha256 !== data.compilation.compiled_sha256 ||
      p.changes.length !== o.fields.length
    )
      return false;
    return p.changes.every((change: Data, index: number) => {
      const field = o.fields[index];
      return (
        change.kind === field.kind &&
        change.record_ref === field.record_ref &&
        change.encoded_sha256 === field.current_encoded_sha256 &&
        (change.kind === "real"
          ? bitsOf(Number(change.value_text)) === field.previous.bits
          : change.value === field.previous.value)
      );
    });
  } catch {
    return false;
  }
}
