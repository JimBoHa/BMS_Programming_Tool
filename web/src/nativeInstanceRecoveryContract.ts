import { sameNameTarget } from "./nativeNameRecoveryContract";

type Data = Record<string, any>;
export const instanceRecoveryProfile =
  "native-controller-instance-recovery-draft/1";
export const instanceRecoverySourceProfile =
  "native-controller-instance-recovery-source/1";
const hash = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const instance = (value: unknown) =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value >= 0 &&
  value <= 4194302;
const canonical = (value: any): any =>
  Array.isArray(value)
    ? value.map(canonical)
    : value && typeof value === "object"
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, canonical(value[key])]),
        )
      : value;
const same = (a: any, b: any) =>
  JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

export function previousInstanceMatches(
  data: Data,
  capture: Data,
  receipt: Data,
) {
  const origin = data.origin,
    parent = receipt.intent,
    proof = origin?.verified_proof;
  if (
    data.profile !== instanceRecoveryProfile ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    !origin ||
    origin.profile !== instanceRecoveryProfile ||
    !parent ||
    parent.change_kind !== "instance" ||
    receipt.pending !== false ||
    parent.allocation_confirmed !== true ||
    parent.application_transfer_confirmed !== true ||
    origin.parent_receipt_id !== parent.id ||
    origin.parent_intent_sha256 !== parent.evidence_sha256 ||
    origin.original_dispatch !== "possible" ||
    origin.original_backup_id !== parent.backup_id ||
    !hash(origin.original_snapshot_sha256) ||
    origin.original_after_native_sha256 !== parent.native_payload_sha256 ||
    origin.current_capture_id !== capture.id ||
    origin.current_snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
    origin.current_archive_sha256 !== capture.files?.["3"]?.sha256 ||
    origin.current_static_sha256 !== capture.files?.["11"]?.sha256 ||
    !hash(origin.verified_after_snapshot_sha256) ||
    !hash(origin.verified_after_static_sha256) ||
    !hash(origin.verified_after_preservation_sha256) ||
    !hash(origin.proposal_preservation_sha256) ||
    origin.normalized_static_sha256 !== origin.verified_after_static_sha256 ||
    !Number.isInteger(origin.normalized_root_selectors) ||
    origin.normalized_root_selectors < 0 ||
    origin.normalized_root_selectors > 10000 ||
    origin.root_ref !== capture.application?.root_ref ||
    origin.root_class !== capture.application?.root_class ||
    origin.property !== 75 ||
    ![
      origin.previous_instance,
      origin.recorded_after_instance,
      origin.current_instance,
      origin.proposal_instance,
    ].every(instance) ||
    origin.previous_instance === origin.recorded_after_instance ||
    origin.previous_instance !== parent.old_instance ||
    origin.recorded_after_instance !== parent.new_instance ||
    origin.proposal_instance !== parent.old_instance ||
    origin.current_instance !== capture.application?.instance ||
    capture.identity?.device !== `device,${origin.current_instance}` ||
    origin.unchanged_name !== parent.old_name ||
    origin.unchanged_name !== parent.new_name ||
    origin.unchanged_name !== capture.identity?.["object-name"] ||
    data.previous_instance !== origin.previous_instance ||
    data.recorded_after_instance !== origin.recorded_after_instance ||
    data.current_instance !== origin.current_instance ||
    data.unchanged_name !== origin.unchanged_name ||
    data.source?.capture_id !== capture.id ||
    data.source?.snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
    data.source?.source_identity_matches !== true ||
    data.source?.sha256 !== capture.files?.["3"]?.sha256 ||
    data.source?.target?.device !== capture.identity.device ||
    !sameNameTarget(data.source?.target ?? {}, capture.target ?? {}) ||
    !sameNameTarget(parent.target ?? {}, capture.target ?? {}) ||
    !Object.entries(parent.identity ?? {}).every(
      ([key, value]) => key === "device" || capture.identity?.[key] === value,
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
        receipt.result.evidence_sha256 === proof.sha256 &&
        receipt.result.finished_at === proof.time &&
        receipt.result.verification_capture_id ===
          origin.verified_after_capture_id
      : proof.kind === "readback-event" &&
        receipt.events?.some(
          (event: Data) =>
            event.stage === "readback" &&
            event.detail?.status === "verified" &&
            event.evidence_sha256 === proof.sha256 &&
            event.created_at === proof.time &&
            event.detail.verification_capture_id ===
              origin.verified_after_capture_id,
        );
  if (!verified) return false;
  if (data.already_recorded)
    return (
      data.proposal === null &&
      data.new_review_required === false &&
      origin.current_instance === origin.previous_instance
    );
  const proposal = data.proposal;
  return (
    data.new_review_required === true &&
    origin.current_instance === origin.recorded_after_instance &&
    origin.normalized_root_selectors === 0 &&
    origin.current_static_sha256 === origin.verified_after_static_sha256 &&
    capture.application.native_sha256 === origin.original_after_native_sha256 &&
    proposal?.capture_id === capture.id &&
    proposal.snapshot_sha256 === capture.snapshot_evidence_sha256 &&
    proposal.new_instance === parent.old_instance &&
    proposal.recovery_parent_receipt === parent.id
  );
}

export function instanceRecoveryReviewMatches(
  plan: Data,
  report: Data,
  capture: Data,
) {
  const edit = plan.compilation?.identity_edit;
  return (
    plan.change_kind === "instance" &&
    plan.capture_id === capture.id &&
    plan.snapshot_sha256 === capture.snapshot_evidence_sha256 &&
    plan.old_instance === report.current_instance &&
    plan.new_instance === report.previous_instance &&
    plan.old_name === report.unchanged_name &&
    plan.new_name === report.unchanged_name &&
    plan.recovery_origin_sha256 === report.origin_sha256 &&
    same(plan.recovery_origin, report.origin) &&
    same(plan.identity, capture.identity) &&
    sameNameTarget(plan.target ?? {}, capture.target ?? {}) &&
    edit?.profile === "tagged-moi-device-identity/1" &&
    edit.change_kind === undefined &&
    edit.old_instance === report.current_instance &&
    edit.new_instance === report.previous_instance &&
    edit.name === report.unchanged_name &&
    edit.root_ref === report.origin.root_ref &&
    edit.root_class === report.origin.root_class
  );
}

export function instanceRecoveryReceiptMatches(receipt: Data, expected: Data) {
  const intent = receipt.intent,
    origin = expected.recovery_origin;
  if (!intent)
    return (
      receipt.result?.status === "not_sent" &&
      receipt.result.may_have_applied === false
    );
  const edit = intent.compilation?.identity_edit;
  if (
    !origin ||
    origin.profile !== instanceRecoveryProfile ||
    intent.change_kind !== "instance" ||
    intent.id === origin.parent_receipt_id ||
    intent.review_capture_id !==
      (expected.capture_id ?? expected.review_capture_id) ||
    intent.recovery_origin_sha256 !== expected.recovery_origin_sha256 ||
    !same(intent.recovery_origin, origin) ||
    !sameNameTarget(intent.target ?? {}, expected.target ?? {}) ||
    intent.old_instance !== origin.current_instance ||
    intent.new_instance !== origin.previous_instance ||
    intent.old_name !== origin.unchanged_name ||
    intent.new_name !== origin.unchanged_name ||
    intent.allocation_confirmed !== true ||
    intent.application_transfer_confirmed !== true ||
    intent.name_change_confirmed !== false ||
    edit?.profile !== "tagged-moi-device-identity/1" ||
    edit.change_kind !== undefined ||
    edit.old_instance !== origin.current_instance ||
    edit.new_instance !== origin.previous_instance ||
    edit.name !== origin.unchanged_name ||
    edit.root_ref !== origin.root_ref ||
    edit.root_class !== origin.root_class ||
    intent.compilation.parameters?.source_sha256 !==
      origin.current_archive_sha256 ||
    intent.compilation.parameters?.static_sha256 !==
      origin.current_static_sha256
  )
    return false;
  const observed =
    receipt.latest_readback ||
    receipt.events?.filter((event: Data) => event.stage === "readback").at(-1)
      ?.detail ||
    receipt.result;
  return (
    observed?.status !== "verified" ||
    (receipt.pending === false &&
      observed.system_status === 0 &&
      observed.preservation?.application_identical_except_instance === true &&
      same(observed.preservation.allowed_identity_changes, ["instance"]) &&
      hash(observed.native_sha256) &&
      observed.native_sha256 === observed.expected_native_sha256)
  );
}
