export const ENUM_RECOVERY_RECORDED = "native-enum-recovery-recorded/1";
export const ENUM_RECOVERY_SCOPE =
  "Recorded Enum origin seal and child-receipt bindings only. This projection does not " +
  "revalidate the parent receipt or backup files, authorize recovery or establish live state. " +
  "Code meanings and allowed-state membership remain unverified.";
export const ENUM_RECOVERY_UNAVAILABLE =
  "Recorded Enum recovery metadata is incomplete or inconsistent; inspect original evidence.";
export type RecordedEnumRecovery = {
  state: "recorded";
  profile: string;
  datatype: "Enumerated";
  parent_receipt_id: string;
  parent_intent_sha256: string;
  record_ref: string;
  class_id: number;
  property: number;
  instance: number;
  before_value: number;
  after_value: number;
  before_encoding_hex: string;
  after_encoding_hex: string;
  previous_encoding_hex: string;
  recorded_after_encoding_hex: string;
  states_text_encoded_sha256: string | null;
  saved_storage: {
    kind: string;
    datatype: number;
    bytes: number;
    maximum_code: number;
    static_record_offset: number;
    dynamic_value_offset: number;
  };
  enum_semantics_verified: false;
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
type Row = {
  source: string;
  native_change_kind?: string | null;
  id: string;
  object: string;
  target: { device: string } | null;
};
const digest = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: any) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const code = (v: any) =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 65535;
const keys = (v: any, expected: string[]) =>
  v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === expected.length &&
  expected.every((k) => Object.hasOwn(v, k));
function tagged(v: any, expected: number) {
  return (
    typeof v === "string" &&
    /^9[1-4](?:[a-f0-9]{2}){1,4}2f$/.test(v) &&
    v.length === (Number(v[1]) + 2) * 2 &&
    parseInt(v.slice(2, -2), 16) === expected
  );
}
function proofTime(value: any) {
  if (typeof value !== "string" || value.length > 80) return false;
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(
      value,
    );
  if (!match || !Number.isFinite(Date.parse(value))) return false;
  const year = Number(match[1]),
    month = Number(match[2]),
    day = Number(match[3]);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return (
    year >= 1 &&
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= days[month - 1] &&
    Number(match[4]) < 24 &&
    Number(match[5]) < 60 &&
    Number(match[6]) < 60 &&
    (!match[7] || (Number(match[8]) < 24 && Number(match[9]) < 60))
  );
}
export function recordedEnumRecovery(
  value: unknown,
  row: Row,
): RecordedEnumRecovery | null {
  const v = value as any;
  if (
    !keys(v, [
      "state",
      "profile",
      "datatype",
      "parent_receipt_id",
      "parent_intent_sha256",
      "record_ref",
      "class_id",
      "property",
      "instance",
      "before_value",
      "after_value",
      "before_encoding_hex",
      "after_encoding_hex",
      "previous_encoding_hex",
      "recorded_after_encoding_hex",
      "states_text_encoded_sha256",
      "saved_storage",
      "enum_semantics_verified",
      "verified_proof",
      "original_backup_id",
      "original_snapshot_sha256",
      "current_capture_id",
      "current_snapshot_sha256",
      "origin_sha256",
      "scope",
    ]) ||
    row.source !== "native" ||
    row.native_change_kind !== "enum-default" ||
    !id(row.id) ||
    v.state !== "recorded" ||
    v.profile !== ENUM_RECOVERY_RECORDED ||
    v.datatype !== "Enumerated" ||
    v.scope !== ENUM_RECOVERY_SCOPE ||
    v.record_ref !== row.object ||
    typeof v.record_ref !== "string" ||
    v.record_ref.length < 1 ||
    [...v.record_ref].length > 512 ||
    ![528, 529].includes(v.class_id) ||
    v.property !== 3113 ||
    v.enum_semantics_verified !== false ||
    !Number.isInteger(v.instance) ||
    v.instance < 0 ||
    v.instance > 4194302 ||
    row.target?.device !== `device,${v.instance}` ||
    !id(v.parent_receipt_id) ||
    v.parent_receipt_id === row.id ||
    !id(v.original_backup_id) ||
    !id(v.current_capture_id) ||
    v.original_backup_id === v.current_capture_id ||
    ![
      v.parent_intent_sha256,
      v.original_snapshot_sha256,
      v.current_snapshot_sha256,
      v.origin_sha256,
    ].every(digest) ||
    !code(v.before_value) ||
    !code(v.after_value) ||
    v.before_value === v.after_value ||
    !tagged(v.before_encoding_hex, v.before_value) ||
    !tagged(v.after_encoding_hex, v.after_value) ||
    !tagged(v.previous_encoding_hex, v.after_value) ||
    !tagged(v.recorded_after_encoding_hex, v.before_value) ||
    !(
      v.states_text_encoded_sha256 === null ||
      digest(v.states_text_encoded_sha256)
    ) ||
    !keys(v.verified_proof, ["kind", "sha256", "time"]) ||
    !["result", "readback-event"].includes(v.verified_proof.kind) ||
    !digest(v.verified_proof.sha256) ||
    !proofTime(v.verified_proof.time) ||
    !keys(v.saved_storage, [
      "kind",
      "datatype",
      "bytes",
      "maximum_code",
      "static_record_offset",
      "dynamic_value_offset",
    ]) ||
    v.saved_storage.kind !== "captured-fixed-enum-slot" ||
    v.saved_storage.datatype !== 9 ||
    v.saved_storage.bytes !== 2 ||
    v.saved_storage.maximum_code !== 65535 ||
    ![
      v.saved_storage.static_record_offset,
      v.saved_storage.dynamic_value_offset,
    ].every((x) => Number.isSafeInteger(x) && x >= 0) ||
    v.saved_storage.static_record_offset + 16 > 128 * 1024 ||
    v.saved_storage.dynamic_value_offset + 3 > 128 * 1024
  )
    return null;
  const width = Math.max(
    Number(v.before_encoding_hex[1]),
    Math.max(1, Math.ceil(v.after_value.toString(16).length / 2)),
  );
  if (
    v.after_encoding_hex !==
    `9${width}${v.after_value.toString(16).padStart(width * 2, "0")}2f`
  )
    return null;
  return v;
}
