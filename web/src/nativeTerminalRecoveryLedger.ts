import { recordedTerminal } from "./nativeTerminalLedger";

export const terminalRecoveryRecordedProfile =
  "native-analog-terminal-recovery-recorded/1";
export const terminalRecoveryRecordedScope =
  "Recorded terminal recovery origin seal and child-receipt bindings only. No parent/source lookup or current revalidation, controller query, current terminal/wiring verification or transfer authority.";
export function recordedTerminalRecovery(
  value: unknown,
  terminalValue: unknown,
  child: string,
  device?: string,
) {
  const v = value as any,
    t = recordedTerminal(terminalValue),
    o = v?.origin;
  const hash = (a: any) => typeof a === "string" && /^[a-f0-9]{64}$/.test(a);
  const id = (a: any) => typeof a === "string" && /^[a-f0-9]{32}$/.test(a);
  const slot = (a: any) => Number.isSafeInteger(a) && a >= 1 && a <= 6;
  const keys = [
    "state",
    "profile",
    "origin",
    "origin_sha256",
    "instance",
    "lineage_enforced_recorded",
    "parent_and_source_revalidated",
    "transfer_authority",
    "scope",
  ];
  const originKeys = [
    "profile",
    "parent_receipt_id",
    "parent_intent_sha256",
    "original_dispatch",
    "verified_proof",
    "original_backup_id",
    "original_snapshot_sha256",
    "current_capture_id",
    "current_snapshot_sha256",
    "object_id",
    "record_ref",
    "previous_slot",
    "recorded_after_slot",
    "current_slot",
    "proposal_slot",
    "current_configuration_sha256",
  ];
  if (
    !t ||
    !v ||
    Array.isArray(v) ||
    Object.keys(v).length !== keys.length ||
    !keys.every((k) => Object.hasOwn(v, k)) ||
    v.state !== "recorded" ||
    v.profile !== terminalRecoveryRecordedProfile ||
    v.scope !== terminalRecoveryRecordedScope ||
    v.lineage_enforced_recorded !== true ||
    v.parent_and_source_revalidated !== false ||
    v.transfer_authority !== false ||
    !Number.isSafeInteger(v.instance) ||
    v.instance < 0 ||
    v.instance > 4194302 ||
    device !== `device,${v.instance}` ||
    !id(child) ||
    !o ||
    Array.isArray(o) ||
    Object.keys(o).length !== originKeys.length ||
    !originKeys.every((k) => Object.hasOwn(o, k)) ||
    o.profile !== "native-analog-terminal-recovery-draft/1" ||
    !id(o.parent_receipt_id) ||
    o.parent_receipt_id === child ||
    !id(o.original_backup_id) ||
    !id(o.current_capture_id) ||
    o.original_backup_id === o.current_capture_id ||
    ![
      o.parent_intent_sha256,
      o.original_snapshot_sha256,
      o.current_snapshot_sha256,
      o.current_configuration_sha256,
      v.origin_sha256,
    ].every(hash) ||
    o.original_dispatch !== "possible" ||
    o.object_id !== t.object_id ||
    o.record_ref !== t.record_ref ||
    ![
      o.previous_slot,
      o.recorded_after_slot,
      o.current_slot,
      o.proposal_slot,
    ].every(slot) ||
    o.current_slot !== o.recorded_after_slot ||
    o.proposal_slot !== o.previous_slot ||
    o.previous_slot === o.recorded_after_slot ||
    o.current_slot !== t.old_slot ||
    o.proposal_slot !== t.slot ||
    o.current_configuration_sha256 !== t.configuration_sha256 ||
    !o.verified_proof ||
    Object.keys(o.verified_proof).sort().join(",") !== "kind,sha256,time" ||
    !["result", "readback-event"].includes(o.verified_proof.kind) ||
    !hash(o.verified_proof.sha256) ||
    typeof o.verified_proof.time !== "string" ||
    !/(Z|[+-]\d{2}:\d{2})$/.test(o.verified_proof.time) ||
    !Number.isFinite(Date.parse(o.verified_proof.time))
  )
    return null;
  return v;
}
