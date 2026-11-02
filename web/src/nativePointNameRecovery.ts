/** Historical proposal evidence stays distinct from a new point-name transfer. */
export const pointNameRecoveryProfile = "native-point-name-recovery-draft/1";
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const sameTarget = (a: any, b: any) =>
  ["address", "router", "dnet"].every(
    (k) => (a?.[k] ?? null) === (b?.[k] ?? null),
  );
const canonical = (v: any): any =>
  Array.isArray(v)
    ? v.map(canonical)
    : v && typeof v === "object"
      ? Object.fromEntries(
          Object.keys(v)
            .sort()
            .map((k) => [k, canonical(v[k])]),
        )
      : v;
export const samePointRecoveryEvidence = (a: any, b: any) =>
  JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

export function previousPointNameMatches(
  data: any,
  capture: any,
  field: any,
  receipt: any,
) {
  const o = data?.origin,
    parent = receipt?.intent,
    selected = parent?.compilation?.selected_edit,
    proof = o?.verified_proof;
  const device = capture?.device ?? capture?.identity?.device;
  if (
    data?.profile !== pointNameRecoveryProfile ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    o?.profile !== pointNameRecoveryProfile ||
    !parent ||
    !selected ||
    receipt.pending !== false ||
    parent.change_kind !== "point-name" ||
    parent.operation_profile !== "native-point-name-transfer/1" ||
    parent.point_name_confirmed !== true ||
    parent.application_transfer_confirmed !== true ||
    !Number.isInteger(parent.old_instance) ||
    parent.old_instance < 0 ||
    parent.old_instance > 4194302 ||
    parent.new_instance !== parent.old_instance ||
    device !== "device," + parent.old_instance ||
    parent.old_name !== parent.new_name ||
    o.parent_receipt_id !== parent.id ||
    o.parent_intent_sha256 !== parent.evidence_sha256 ||
    o.original_dispatch !== "possible" ||
    o.original_backup_id !== parent.backup_id ||
    !hash(o.original_snapshot_sha256) ||
    o.original_after_native_sha256 !== parent.native_payload_sha256 ||
    o.current_capture_id !== capture.id ||
    o.current_snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
    o.current_archive_sha256 !== capture.files?.["3"]?.sha256 ||
    o.object_id !== field.object_id ||
    o.record_ref !== field.record_ref ||
    o.current_name_sha256 !== field.encoded_sha256 ||
    o.native_class !== field.native_class ||
    o.property !== 2390 ||
    o.character_encoding !== selected.character_encoding ||
    o.object_id !== parent.point_name_edit?.object_id ||
    o.record_ref !== parent.point_name_edit?.record_ref ||
    o.previous_name !== selected.before ||
    o.recorded_after_name !== selected.after ||
    selected.after !== parent.point_name_edit?.new_name ||
    selected.changed !== true ||
    o.proposal_name !== o.previous_name ||
    o.current_name !== field.name ||
    data.previous_name !== o.previous_name ||
    data.current_name !== o.current_name ||
    data.recorded_after_name !== o.recorded_after_name ||
    data.source?.capture_id !== capture.id ||
    data.source?.snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
    data.source?.sha256 !== o.current_archive_sha256 ||
    data.source?.source_identity_matches !== true ||
    data.source?.target?.device !== device ||
    !sameTarget(data.source?.target, capture.target) ||
    !sameTarget(parent.target, capture.target) ||
    !Object.entries(parent.identity ?? {}).every(
      ([key, value]) => capture.identity?.[key] === value,
    ) ||
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
        receipt.result.may_have_applied === true &&
        receipt.result.evidence_sha256 === proof.sha256 &&
        receipt.result.finished_at === proof.time
      : proof.kind === "readback-event" &&
        receipt.events?.some(
          (e: any) =>
            e.stage === "readback" &&
            e.detail?.status === "verified" &&
            e.evidence_sha256 === proof.sha256 &&
            e.created_at === proof.time,
        );
  if (!verified) return false;
  if (data.already_recorded)
    return (
      data.proposal === null &&
      data.new_review_required === false &&
      data.current_name === data.previous_name
    );
  const p = data.proposal;
  return (
    data.current_name === data.recorded_after_name &&
    data.new_review_required === true &&
    p?.capture_id === capture.id &&
    p.snapshot_sha256 === capture.snapshot_evidence_sha256 &&
    p.object_id === field.object_id &&
    p.record_ref === field.record_ref &&
    p.encoded_sha256 === field.encoded_sha256 &&
    p.new_name === data.previous_name &&
    p.recovery_parent_receipt === parent.id
  );
}

export function activePointNameRecovery(work: any) {
  const r = work.recovery,
    report = r?.data,
    p = report?.proposal;
  return r?.active === true &&
    p &&
    work.capture?.id === p.capture_id &&
    work.capture?.snapshot_evidence_sha256 === p.snapshot_sha256 &&
    work.field?.object_id === p.object_id &&
    work.field?.record_ref === p.record_ref &&
    work.field?.encoded_sha256 === p.encoded_sha256 &&
    work.name === p.new_name
    ? report
    : null;
}

export function pointNameRecoveryTransferMatches(value: any, expected: any) {
  if (expected.recovery_origin_sha256 === undefined)
    return (
      value.recovery_origin_sha256 === undefined &&
      value.recovery_origin === undefined
    );
  return (
    hash(expected.recovery_origin_sha256) &&
    value.recovery_origin_sha256 === expected.recovery_origin_sha256 &&
    samePointRecoveryEvidence(
      value.recovery_origin,
      expected.recovery_origin,
    ) &&
    value.recovery_origin?.profile === pointNameRecoveryProfile
  );
}
