import type { RecordedPointName } from "./nativePointNameLedger";
export const POINT_RECOVERY_RECORDED = "native-point-name-recovery-recorded/1";
export const POINT_RECOVERY_SCOPE =
  "Recorded point-name origin seal and child-receipt bindings only. Parent receipt and " +
  "original-source availability, current point names and transfer authority are not established.";
export type RecordedPointNameRecovery = {
  state: "recorded";
  profile: string;
  object_id: string;
  record_ref: string;
  instance: number;
  before: string;
  after: string;
  character_encoding: number;
  parent_receipt_id: string;
  parent_intent_sha256: string;
  verified_proof: {
    kind: "result" | "readback-event";
    sha256: string;
    time: string;
  };
  original_backup_id: string;
  original_snapshot_sha256: string;
  current_capture_id: string;
  current_snapshot_sha256: string;
  origin_sha256: string;
  scope: string;
};
export function recordedPointNameRecovery(
  value: unknown,
  point: RecordedPointName | null,
  child: string,
  device?: string,
): RecordedPointNameRecovery | null {
  const v = value as any;
  const keys = [
    "state",
    "profile",
    "object_id",
    "record_ref",
    "instance",
    "before",
    "after",
    "character_encoding",
    "parent_receipt_id",
    "parent_intent_sha256",
    "verified_proof",
    "original_backup_id",
    "original_snapshot_sha256",
    "current_capture_id",
    "current_snapshot_sha256",
    "origin_sha256",
    "scope",
  ];
  const digest = (a: any) => typeof a === "string" && /^[a-f0-9]{64}$/.test(a);
  const id = (a: any) => typeof a === "string" && /^[a-f0-9]{32}$/.test(a);
  const name = (a: any) =>
    typeof a === "string" &&
    a.length > 0 &&
    a.trim() === a &&
    !/[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(a) &&
    new TextEncoder().encode(a).length <= 128;
  if (
    !point ||
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    Object.keys(v).length !== keys.length ||
    !keys.every((k) => Object.hasOwn(v, k)) ||
    v.state !== "recorded" ||
    v.profile !== POINT_RECOVERY_RECORDED ||
    v.scope !== POINT_RECOVERY_SCOPE ||
    v.object_id !== point.object_id ||
    v.record_ref !== point.record_ref ||
    v.before !== point.before ||
    v.after !== point.after ||
    !name(v.before) ||
    !name(v.after) ||
    v.character_encoding !== point.character_encoding ||
    point.name_confirmation_recorded !== true ||
    !Number.isInteger(v.instance) ||
    v.instance < 0 ||
    v.instance > 4194302 ||
    device !== "device," + v.instance ||
    !id(child) ||
    !id(v.parent_receipt_id) ||
    v.parent_receipt_id === child ||
    !id(v.original_backup_id) ||
    !id(v.current_capture_id) ||
    v.original_backup_id === v.current_capture_id ||
    ![
      v.parent_intent_sha256,
      v.original_snapshot_sha256,
      v.current_snapshot_sha256,
      v.origin_sha256,
    ].every(digest) ||
    !v.verified_proof ||
    Object.keys(v.verified_proof).sort().join(",") !== "kind,sha256,time" ||
    !["result", "readback-event"].includes(v.verified_proof.kind) ||
    !digest(v.verified_proof.sha256) ||
    typeof v.verified_proof.time !== "string" ||
    !/(Z|[+-]\d{2}:\d{2})$/.test(v.verified_proof.time) ||
    !Number.isFinite(Date.parse(v.verified_proof.time))
  )
    return null;
  return v;
}
