type Data = Record<string, any>;
export type NativeDefaultRecoveryDocument = { data: Data; blob: Blob };
export const realRecoveryProfile = "native-real-default-recovery-draft/1";

const hash = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const bits = (value: unknown) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const bytes = new DataView(new ArrayBuffer(4));
  bytes.setFloat32(0, value, false);
  return bytes.getUint32(0, false).toString(16).padStart(8, "0");
};
const sameTarget = (left: Data, right: Data) =>
  ["address", "router", "dnet"].every(
    (key) => (left[key] ?? null) === (right[key] ?? null),
  );

export function previousRealDefaultMatches(
  data: Data,
  source: Data,
  receipt: Data,
) {
  const origin = data.origin,
    parent = receipt.intent,
    edit = parent?.compilation?.selected_edit,
    field = source.fields?.find((row: Data) => row.ref === origin?.record_ref),
    proof = origin?.verified_proof;
  if (
    data.profile !== realRecoveryProfile ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    !origin ||
    origin.profile !== realRecoveryProfile ||
    !parent ||
    parent.change_kind !== "signal-default" ||
    !field ||
    !edit ||
    receipt.pending !== false ||
    origin.parent_receipt_id !== parent.id ||
    origin.parent_intent_sha256 !== parent.evidence_sha256 ||
    origin.original_dispatch !== "possible" ||
    origin.original_backup_id !== parent.backup_id ||
    !hash(origin.original_snapshot_sha256) ||
    origin.current_capture_id !== source.capture_id ||
    origin.current_snapshot_sha256 !== source.snapshot_sha256 ||
    origin.record_ref !== parent.default_edit?.record_ref ||
    origin.class_id !== field.class_id ||
    origin.property !== 3113 ||
    origin.previous_effective_bits !== edit.before_bits ||
    origin.recorded_after_bits !== edit.after_bits ||
    origin.current_effective_bits !== field.effective_bits ||
    origin.proposal_bits !== edit.before_bits ||
    bits(data.previous_effective_value) !== edit.before_bits ||
    bits(data.recorded_after_value) !== edit.after_bits ||
    bits(data.current_effective_value) !== field.effective_bits ||
    data.source?.capture_id !== source.capture_id ||
    data.source?.snapshot_sha256 !== source.snapshot_sha256 ||
    data.source?.source_identity_matches !== true ||
    data.source?.target?.device !== source.device ||
    !sameTarget(data.source?.target ?? {}, source.target) ||
    !sameTarget(parent.target ?? {}, source.target) ||
    parent.identity?.device !== source.device ||
    data.read_only !== true ||
    data.controller_queries !== false ||
    data.field_actions !== false ||
    data.can_apply !== false ||
    typeof data.already_recorded !== "boolean" ||
    !proof ||
    !hash(proof.sha256)
  )
    return false;
  const verified =
    proof.kind === "result"
      ? receipt.result?.status === "verified" &&
        receipt.result.evidence_sha256 === proof.sha256 &&
        receipt.result.finished_at === proof.time
      : proof.kind === "readback-event" &&
        receipt.events?.some(
          (event: Data) =>
            event.stage === "readback" &&
            event.detail?.status === "verified" &&
            event.evidence_sha256 === proof.sha256 &&
            event.created_at === proof.time,
        );
  if (!verified) return false;
  if (data.already_recorded)
    return (
      data.proposal === null &&
      data.new_review_required === false &&
      field.effective_bits === edit.before_bits
    );
  const proposal = data.proposal;
  return (
    data.new_review_required === true &&
    field.effective_bits === edit.after_bits &&
    proposal?.capture_id === source.capture_id &&
    proposal.snapshot_sha256 === source.snapshot_sha256 &&
    proposal.record_ref === field.ref &&
    proposal.encoded_sha256 === field.encoded_sha256 &&
    proposal.recovery_parent_receipt === parent.id &&
    typeof proposal.value_text === "string" &&
    bits(Number(proposal.value_text)) === edit.before_bits
  );
}
