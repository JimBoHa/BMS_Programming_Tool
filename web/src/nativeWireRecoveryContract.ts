type Data = Record<string, any>;
export const wireRecoveryProfile = "native-wire-source-recovery-draft/1";
export const historicalWireRecoveryProfile =
  "native-historical-pin-wire-recovery-draft/1";
const hash = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const tuple = (a: unknown, b: unknown) =>
  Array.isArray(a) &&
  Array.isArray(b) &&
  a.length === 4 &&
  b.length === 4 &&
  a.every(
    (value, index) =>
      Number.isInteger(value) &&
      value >= 0 &&
      value <= 65535 &&
      value === b[index],
  );
const sameTarget = (a: Data, b: Data) =>
  ["address", "router", "dnet"].every(
    (key) => (a[key] ?? null) === (b[key] ?? null),
  );

export function previousWireSourceMatches(
  data: Data,
  source: Data,
  receipt: Data,
  selection: Data,
) {
  const origin = data.origin,
    parent = receipt.intent,
    edit = parent?.compilation?.wire_edit,
    wire = source.selection?.selected_wire,
    proof = origin?.verified_proof;
  const historical = data.profile === historicalWireRecoveryProfile;
  if (
    (!historical && data.profile !== wireRecoveryProfile) ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    !origin ||
    origin.profile !== data.profile ||
    !parent ||
    !edit ||
    !wire ||
    parent.change_kind !== "wire-source" ||
    parent.operation_profile !== "native-effective-wire-source-transfer/1" ||
    receipt.pending !== false ||
    origin.parent_receipt_id !== parent.id ||
    origin.parent_intent_sha256 !== parent.evidence_sha256 ||
    origin.original_dispatch !== "possible" ||
    origin.original_backup_id !== parent.backup_id ||
    !hash(origin.original_snapshot_sha256) ||
    origin.current_capture_id !== source.capture_id ||
    origin.current_snapshot_sha256 !== source.snapshot_sha256 ||
    origin.diagram_ref !== parent.wire_edit?.diagram_ref ||
    origin.diagram_ref !== selection.diagram_ref ||
    origin.wire_index !== selection.wire_index ||
    origin.wire_index !== edit.wire_index ||
    origin.wire_index !== source.selection.wire_index ||
    origin.diagram_ref !== source.selection.diagram_ref ||
    ![536, 575].includes(origin.class_id) ||
    origin.class_id !== selection.class_id ||
    origin.property !== 3118 ||
    !tuple(origin.previous_tuple, edit.old) ||
    !tuple(origin.recorded_after_tuple, edit.new) ||
    !tuple(origin.current_tuple, wire.old) ||
    !tuple(origin.proposal_tuple, edit.old) ||
    origin.previous_source_ref !== edit.old_source_ref ||
    origin.recorded_after_source_ref !== edit.source_ref ||
    origin.current_source_ref !== wire.source_ref ||
    origin.proposal_source_ref !== edit.old_source_ref ||
    origin.target_ref !== edit.target_ref ||
    origin.target_ref !== wire.target_ref ||
    origin.source_index_bytes !== wire.source_index_bytes ||
    origin.source_index_bytes !== edit.source_index_bytes ||
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
  if (historical) {
    const pin = origin.historical_pin,
      candidate = data.proposal_candidate;
    if (
      !pin ||
      !candidate ||
      pin.profile !== "native-recorded-wire-pin/1" ||
      !hash(origin.historical_pin_sha256) ||
      pin.original_capture_id !== origin.original_backup_id ||
      pin.original_snapshot_sha256 !== origin.original_snapshot_sha256 ||
      pin.original_native_sha256 !== edit.source_native_sha256 ||
      pin.after_native_sha256 !== parent.native_payload_sha256 ||
      pin.current_archive_sha256 !== source.source_sha256 ||
      pin.diagram_ref !== origin.diagram_ref ||
      pin.diagram_class !== origin.class_id ||
      pin.wire_index !== origin.wire_index ||
      !tuple(pin.old, origin.previous_tuple) ||
      pin.source_ref !== origin.previous_source_ref ||
      pin.source_class !== edit.source_class ||
      pin.target_ref !== origin.target_ref ||
      pin.source_index_bytes !== origin.source_index_bytes ||
      !hash(pin.source_configuration_sha256) ||
      typeof pin.source_object !== "string" ||
      candidate.ref !== pin.source_ref ||
      candidate.index !== pin.old[0] ||
      candidate.class_id !== pin.source_class ||
      candidate.object !== pin.source_object ||
      typeof candidate.name !== "string" ||
      candidate.current_source !== false ||
      source.selection.wires?.some(
        (row: Data) =>
          row.source_ref === pin.source_ref && row.source_port === pin.old[1],
      ) ||
      data.already_recorded
    )
      return false;
  }
  if (data.already_recorded)
    return (
      data.proposal === null &&
      data.new_review_required === false &&
      tuple(wire.old, edit.old) &&
      wire.source_ref === edit.old_source_ref
    );
  const proposal = data.proposal;
  return (
    data.new_review_required === true &&
    tuple(wire.old, edit.new) &&
    wire.source_ref === edit.source_ref &&
    proposal?.capture_id === source.capture_id &&
    proposal.snapshot_sha256 === source.snapshot_sha256 &&
    proposal.source_sha256 === source.source_sha256 &&
    proposal.diagram_ref === selection.diagram_ref &&
    proposal.wire_index === selection.wire_index &&
    proposal.record_sha256 === source.archive_record_sha256 &&
    proposal.effective_sha256 === source.effective_sha256 &&
    proposal.effective_record_sha256 === source.selection.record_sha256 &&
    proposal.property_sha256 === source.selection.property_sha256 &&
    tuple(proposal.old, wire.old) &&
    proposal.source_ref === edit.old_source_ref &&
    proposal.recovery_parent_receipt === parent.id &&
    (historical
      ? data.proposal_candidate.ref === proposal.source_ref &&
        data.proposal_candidate.index === edit.old[0]
      : source.selection.candidates?.some(
          (candidate: Data) =>
            candidate.ref === proposal.source_ref &&
            candidate.index === edit.old[0],
        ))
  );
}
