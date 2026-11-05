import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { terminalEvidenceSeal } from "./nativeTerminalTransferContract";
import { controllerKey } from "./workflow";

type Data = Record<string, any>;
export const terminalRecoveryDraftProfile =
  "native-analog-terminal-recovery-draft/1";
export const terminalRecoveryTransferProfile =
  "native-analog-terminal-recovery-transfer/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const slot = (v: unknown) =>
  Number.isSafeInteger(v) && Number(v) >= 1 && Number(v) <= 6;
export async function terminalRecoveryDraft(
  document: { data: Data; blob: Blob },
  source: Data,
  parent: Data,
) {
  const r = document.data,
    o = r?.origin,
    s = r?.source;
  const device = source?.identity?.device ?? `device,${parent?.new_instance}`;
  const old = parent?.compilation?.terminal_compilation;
  const selected = source?.inputs?.find(
    (p: Data) => p.object_id === o?.object_id,
  );
  if (
    r?.profile !== terminalRecoveryDraftProfile ||
    !selected ||
    !old ||
    parent.operation_profile !== "native-local-universal-input-transfer/2" ||
    parent.input_edit?.action !== "terminal" ||
    r.read_only !== true ||
    r.controller_queries !== false ||
    r.controller_writes !== false ||
    r.field_actions !== false ||
    r.can_apply !== false ||
    r.parent_lineage_enforced_by_field_transfer !== false ||
    typeof r.already_recorded !== "boolean" ||
    r.new_review_required !== !r.already_recorded ||
    !hash(r.current_effective_sha256) ||
    s?.capture_id !== source.capture_id ||
    s.snapshot_sha256 !== source.snapshot_sha256 ||
    !same(s.identity, source.identity) ||
    controllerKey(s.target) !== controllerKey({ ...source.target, device }) ||
    o?.original_backup_id !== parent.backup_id ||
    !hash(o?.original_snapshot_sha256) ||
    o?.profile !== terminalRecoveryDraftProfile ||
    o.parent_receipt_id !== parent.id ||
    o.parent_intent_sha256 !== parent.evidence_sha256 ||
    o.current_capture_id !== source.capture_id ||
    o.current_snapshot_sha256 !== source.snapshot_sha256 ||
    o.record_ref !== selected.record_ref ||
    o.object_id !== parent.compilation.object_id ||
    o.record_ref !== parent.compilation.record_ref ||
    o.current_slot !== selected.slot ||
    o.current_configuration_sha256 !== selected.configuration_sha256 ||
    ![o.previous_slot, o.recorded_after_slot, o.current_slot].every(slot) ||
    o.previous_slot !== old.old_slot ||
    o.recorded_after_slot !== old.destination_slot ||
    o.proposal_slot !== o.previous_slot ||
    o.previous_slot === o.recorded_after_slot ||
    o.current_slot !==
      (r.already_recorded ? o.previous_slot : o.recorded_after_slot) ||
    o.original_dispatch !== "possible" ||
    !["result", "readback-event"].includes(o.verified_proof?.kind) ||
    !hash(o.verified_proof?.sha256) ||
    typeof o.verified_proof?.time !== "string" ||
    !hash(r.origin_sha256)
  )
    return false;
  if (r.already_recorded) {
    if (
      r.proposal !== null ||
      r.inverse_compilation !== null ||
      r.inverse_output_sha256 !== null
    )
      return false;
  } else {
    const e = r.proposal?.edit,
      c = r.inverse_compilation,
      p = c?.terminal_compilation;
    if (
      r.proposal?.capture_id !== source.capture_id ||
      r.proposal.snapshot_sha256 !== source.snapshot_sha256 ||
      !same(e, {
        action: "terminal",
        object_instance: Number(o.object_id.split(",")[1]),
        slot: o.previous_slot,
        configuration_sha256: selected.configuration_sha256,
        name: null,
        configuration: null,
        allocation_receipt: null,
      }) ||
      !source.available_slots?.includes(o.previous_slot) ||
      c?.profile !== "native-local-universal-input-transfer/2" ||
      !same(c.input_edit, e) ||
      c.object_id !== o.object_id ||
      c.record_ref !== o.record_ref ||
      !same(
        Object.keys(c.stored_configuration ?? {}).sort(),
        Object.keys(selected.configuration).sort(),
      ) ||
      !Object.keys(selected.configuration).every(
        (k) =>
          typeof c.stored_configuration[k] === "number" &&
          Object.is(c.stored_configuration[k], selected.configuration[k]),
      ) ||
      c.other_records_preserved !== true ||
      c.wires_changed !== false ||
      c.allocated_record_hex !== null ||
      !p ||
      p.profile !== "tagged-moi-local-terminal-copy/2" ||
      p.object !== o.object_id ||
      p.ref !== o.record_ref ||
      p.old_slot !== o.current_slot ||
      p.destination_slot !== o.previous_slot ||
      p.old_device_type !== `UI IN${o.current_slot}` ||
      p.new_device_type !== `UI IN${o.previous_slot}` ||
      p.changed !== true ||
      p.controller_write !== false ||
      p.field_transfer_enabled !== false ||
      p.physical_terminal_or_wiring_verified !== false ||
      ![
        "other_expanded_bytes_preserved",
        "native_structure_readback_verified",
        "identities_modes_graph_and_record_framing_preserved",
      ].every((k) => p[k] === true) ||
      p.source_sha256 !== r.current_effective_sha256 ||
      p.source_sha256 !== c.parameter_merge?.output_sha256 ||
      c.parameter_merge?.source_sha256 !== s.sha256 ||
      c.parameter_merge?.static_sha256 !== s.files?.["11"]?.sha256 ||
      c.parameter_merge?.dynamic_sha256 !== s.files?.["12"]?.sha256 ||
      p.output_native_sha256 !== c.compiled_native_sha256 ||
      !hash(r.inverse_output_sha256) ||
      p.output_sha256 !== r.inverse_output_sha256 ||
      !hash(p.compilation_sha256)
    )
      return false;
    const { compilation_sha256, ...body } = p;
    if ((await connectionSeal(body)) !== compilation_sha256) return false;
  }
  return (
    (await connectionSeal(o)) === r.origin_sha256 &&
    (await terminalEvidenceSeal(document.blob))
  );
}

export function terminalRecoveryReview(review: Data, prepared: Data | null) {
  const keys = [
    "terminal_recovery_profile",
    "recovery_parent_receipt",
    "recovery_origin",
    "recovery_origin_sha256",
    "terminal_recovery_lineage_enforced",
  ];
  if (!prepared) return keys.every((k) => !Object.hasOwn(review, k));
  return (
    review.terminal_recovery_profile === terminalRecoveryTransferProfile &&
    review.terminal_recovery_lineage_enforced === true &&
    review.recovery_parent_receipt === prepared.origin.parent_receipt_id &&
    review.recovery_origin_sha256 === prepared.origin_sha256 &&
    same(review.recovery_origin, prepared.origin)
  );
}

export function sameTerminalRecoveryLineage(actual: Data, expected: Data) {
  return [
    "terminal_recovery_profile",
    "recovery_parent_receipt",
    "recovery_origin",
    "recovery_origin_sha256",
    "terminal_recovery_lineage_enforced",
  ].every(
    (k) =>
      Object.hasOwn(actual, k) === Object.hasOwn(expected, k) &&
      same(actual[k], expected[k]),
  );
}
