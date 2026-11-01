type Data = Record<string, any>;
export const booleanRecoveryProfile = "native-boolean-default-recovery-draft/1";
const hash = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const tag = (value: unknown) =>
  typeof value === "boolean" ? (value ? "11" : "10") : null;
const sameTarget = (a: Data, b: Data) =>
  ["address", "router", "dnet"].every(
    (key) => (a[key] ?? null) === (b[key] ?? null),
  );

export function previousBooleanDefaultMatches(
  data: Data,
  source: Data,
  receipt: Data,
  selected: Data,
) {
  const origin = data.origin,
    parent = receipt.intent,
    edit = parent?.compilation?.selected_edit,
    field = source.fields?.find((row: Data) => row.ref === origin?.record_ref),
    proof = origin?.verified_proof;
  if (
    data.profile !== booleanRecoveryProfile ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    !origin ||
    origin.profile !== booleanRecoveryProfile ||
    !parent ||
    !field ||
    !edit ||
    parent.change_kind !== "boolean-default" ||
    parent.operation_profile !==
      "native-effective-boolean-default-transfer/1" ||
    receipt.pending !== false ||
    origin.parent_receipt_id !== parent.id ||
    origin.parent_intent_sha256 !== parent.evidence_sha256 ||
    origin.original_dispatch !== "possible" ||
    origin.original_backup_id !== parent.backup_id ||
    !hash(origin.original_snapshot_sha256) ||
    origin.current_capture_id !== source.capture_id ||
    origin.current_snapshot_sha256 !== source.snapshot_sha256 ||
    origin.record_ref !== parent.default_edit?.record_ref ||
    origin.record_ref !== selected.ref ||
    origin.class_id !== field.class_id ||
    ![530, 531].includes(field.class_id) ||
    origin.class_id !== selected.class_id ||
    origin.property !== 3113 ||
    field.encoded_sha256 !== selected.encoded_sha256 ||
    field.effective_value !== selected.effective_value ||
    typeof origin.previous_effective_value !== "boolean" ||
    typeof origin.recorded_after_value !== "boolean" ||
    typeof origin.current_effective_value !== "boolean" ||
    typeof origin.proposal_value !== "boolean" ||
    origin.previous_effective_value !== edit.before_value ||
    origin.recorded_after_value !== edit.after_value ||
    origin.current_effective_value !== field.effective_value ||
    origin.proposal_value !== edit.before_value ||
    origin.previous_tag !== tag(edit.before_value) ||
    origin.recorded_after_tag !== tag(edit.after_value) ||
    origin.current_tag !== tag(field.effective_value) ||
    origin.proposal_tag !== tag(edit.before_value) ||
    edit.before_tag !== tag(edit.before_value) ||
    edit.after_tag !== tag(edit.after_value) ||
    data.previous_effective_value !== edit.before_value ||
    data.recorded_after_value !== edit.after_value ||
    data.current_effective_value !== field.effective_value ||
    data.source?.capture_id !== source.capture_id ||
    data.source?.snapshot_sha256 !== source.snapshot_sha256 ||
    data.source?.source_identity_matches !== true ||
    data.source?.target?.device !== source.device ||
    data.source?.sha256 !== source.source_sha256 ||
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
      field.effective_value === edit.before_value
    );
  const proposal = data.proposal;
  return (
    data.new_review_required === true &&
    field.effective_value === edit.after_value &&
    proposal?.capture_id === source.capture_id &&
    proposal.snapshot_sha256 === source.snapshot_sha256 &&
    proposal.source_sha256 === source.source_sha256 &&
    proposal.record_ref === field.ref &&
    proposal.encoded_sha256 === field.encoded_sha256 &&
    proposal.recovery_parent_receipt === parent.id &&
    typeof proposal.value === "boolean" &&
    proposal.value === edit.before_value
  );
}
