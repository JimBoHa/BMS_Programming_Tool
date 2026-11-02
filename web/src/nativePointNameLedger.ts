export const POINT_NAME_LEDGER_PROFILE = "native-point-name-transfer/1";
export const POINT_NAME_LEDGER_SCOPE =
  "Recorded point-name edit and compilation bindings only. No original-backup revalidation, " +
  "current published name, controller query or transfer authority.";
export type RecordedPointName = {
  state: "recorded";
  profile: string;
  object_id: string;
  record_ref: string;
  before: string;
  after: string;
  character_encoding: number;
  before_record_sha256: string;
  compiled_native_sha256: string;
  name_confirmation_recorded: boolean;
  scope: string;
};
export function recordedPointName(v: any): RecordedPointName | null {
  const keys = [
    "state",
    "profile",
    "object_id",
    "record_ref",
    "before",
    "after",
    "character_encoding",
    "before_record_sha256",
    "compiled_native_sha256",
    "name_confirmation_recorded",
    "scope",
  ];
  if (
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    Object.keys(v).length !== keys.length ||
    !keys.every((k) => Object.hasOwn(v, k)) ||
    v.state !== "recorded" ||
    v.profile !== POINT_NAME_LEDGER_PROFILE ||
    v.scope !== POINT_NAME_LEDGER_SCOPE ||
    typeof v.object_id !== "string" ||
    !/^(analog-(input|output|value)|binary-(input|output|value)|multi-state-(input|output|value)),(0|[1-9][0-9]*)$/.test(
      v.object_id,
    ) ||
    Number(v.object_id.split(",")[1]) > 4194302 ||
    typeof v.record_ref !== "string" ||
    !v.record_ref.includes("/") ||
    [...v.record_ref].length > 512 ||
    /[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(v.record_ref) ||
    typeof v.before !== "string" ||
    /[\uD800-\uDFFF]/u.test(v.before) ||
    new TextEncoder().encode(v.before).length > 4096 ||
    typeof v.after !== "string" ||
    !v.after ||
    v.after.trim() !== v.after ||
    /[\u0000-\u001f\u007f\uD800-\uDFFF]/u.test(v.after) ||
    new TextEncoder().encode(v.after).length > 128 ||
    v.before === v.after ||
    !Number.isInteger(v.character_encoding) ||
    ![0, 3, 4, 5].includes(v.character_encoding) ||
    ![v.before_record_sha256, v.compiled_native_sha256].every(
      (x) => typeof x === "string" && /^[a-f0-9]{64}$/.test(x),
    ) ||
    typeof v.name_confirmation_recorded !== "boolean"
  )
    return null;
  return v;
}
