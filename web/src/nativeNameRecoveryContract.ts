type Data = Record<string, any>;
export const nameRecoveryProfile = "native-controller-name-recovery-draft/1";
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
const sameEvidence = (left: any, right: any) =>
  JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
export const sameNameTarget = (a: Data, b: Data) =>
  ["address", "router", "dnet"].every(
    (key) => (a[key] ?? null) === (b[key] ?? null),
  );
const hash = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);

export function previousNameMatches(data: Data, capture: Data, receipt: Data) {
  const origin = data.origin,
    parent = receipt.intent,
    proof = origin?.verified_proof;
  const instance = Number(capture.identity?.device?.split(",")[1]);
  if (
    data.profile !== nameRecoveryProfile ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    !origin ||
    origin.profile !== nameRecoveryProfile ||
    !parent ||
    parent.change_kind !== "name" ||
    receipt.pending !== false ||
    parent.name_change_confirmed !== true ||
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
    origin.root_ref !== capture.application?.root_ref ||
    origin.root_class !== capture.application?.root_class ||
    origin.property !== 2390 ||
    !Number.isInteger(instance) ||
    origin.instance !== instance ||
    parent.old_instance !== instance ||
    parent.new_instance !== instance ||
    origin.previous_name !== parent.old_name ||
    origin.recorded_after_name !== parent.new_name ||
    origin.proposal_name !== parent.old_name ||
    origin.current_name !== capture.identity?.["object-name"] ||
    data.previous_name !== origin.previous_name ||
    data.current_name !== origin.current_name ||
    data.recorded_after_name !== origin.recorded_after_name ||
    data.source?.capture_id !== capture.id ||
    data.source?.snapshot_sha256 !== capture.snapshot_evidence_sha256 ||
    data.source?.source_identity_matches !== true ||
    data.source?.sha256 !== capture.files?.["3"]?.sha256 ||
    data.source?.target?.device !== capture.identity?.device ||
    !sameNameTarget(data.source?.target ?? {}, capture.target ?? {}) ||
    !sameNameTarget(parent.target ?? {}, capture.target ?? {}) ||
    !Object.entries(parent.identity ?? {}).every(([key, value]) =>
      key === "object-name" ? true : capture.identity?.[key] === value,
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
      data.current_name === parent.old_name
    );
  const proposal = data.proposal;
  return (
    data.current_name === parent.new_name &&
    data.new_review_required === true &&
    proposal?.capture_id === capture.id &&
    proposal.snapshot_sha256 === capture.snapshot_evidence_sha256 &&
    proposal.new_instance === instance &&
    proposal.new_name === parent.old_name &&
    proposal.recovery_parent_receipt === parent.id
  );
}

export function nameRecoveryReviewMatches(
  plan: Data,
  report: Data,
  capture: Data,
) {
  return (
    plan.change_kind === "name" &&
    plan.capture_id === capture.id &&
    plan.snapshot_sha256 === capture.snapshot_evidence_sha256 &&
    plan.old_instance === report.origin.instance &&
    plan.new_instance === report.origin.instance &&
    plan.old_name === report.current_name &&
    plan.new_name === report.previous_name &&
    plan.recovery_origin_sha256 === report.origin_sha256 &&
    sameEvidence(plan.recovery_origin, report.origin) &&
    plan.compilation?.identity_edit?.change_kind === "name" &&
    plan.compilation.identity_edit.old_name === report.current_name &&
    plan.compilation.identity_edit.new_name === report.previous_name &&
    plan.compilation.identity_edit.root_ref === report.origin.root_ref &&
    plan.compilation.identity_edit.root_class === report.origin.root_class &&
    plan.compilation.identity_edit.old_instance === report.origin.instance &&
    plan.compilation.identity_edit.new_instance === report.origin.instance &&
    sameNameTarget(plan.target ?? {}, capture.target ?? {})
  );
}

export function nameRecoveryReceiptMatches(receipt: Data, expected: Data) {
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
    origin.profile !== nameRecoveryProfile ||
    intent.change_kind !== "name" ||
    intent.id === origin.parent_receipt_id ||
    intent.review_capture_id !==
      (expected.capture_id ?? expected.review_capture_id) ||
    intent.recovery_origin_sha256 !== expected.recovery_origin_sha256 ||
    !sameEvidence(intent.recovery_origin, origin) ||
    !sameNameTarget(intent.target ?? {}, expected.target ?? {}) ||
    intent.old_instance !== origin.instance ||
    intent.new_instance !== origin.instance ||
    intent.old_name !== origin.current_name ||
    intent.new_name !== origin.previous_name ||
    intent.name_change_confirmed !== true ||
    intent.application_transfer_confirmed !== true ||
    edit?.change_kind !== "name" ||
    edit.old_name !== origin.current_name ||
    edit.new_name !== origin.previous_name ||
    edit.old_instance !== origin.instance ||
    edit.new_instance !== origin.instance ||
    edit.root_ref !== origin.root_ref ||
    edit.root_class !== origin.root_class
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
      observed.preservation?.application_identical_except_name === true &&
      sameEvidence(observed.preservation.allowed_identity_changes, ["name"]) &&
      hash(observed.native_sha256) &&
      observed.native_sha256 === observed.expected_native_sha256)
  );
}
