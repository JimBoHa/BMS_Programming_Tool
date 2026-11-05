export const TERMINAL_LEDGER_PROFILE =
  "native-local-universal-input-transfer/2";
export const TERMINAL_LEDGER_SCOPE =
  "Recorded analog terminal movement and preserved configuration only. No source/parent revalidation, controller query, current value, wiring/accuracy verification or transfer authority.";
export type RecordedTerminal = {
  state: "recorded";
  profile: string;
  action: "terminal";
  object_id: string;
  record_ref: string;
  old_slot: number;
  slot: number;
  old_terminal_label: string;
  terminal_label: string;
  configuration_sha256: string;
  stored_configuration: Record<string, number>;
  source_sha256: string;
  source_native_sha256: string;
  output_sha256: string;
  output_native_sha256: string;
  compilation_sha256: string;
  wiring_confirmation_recorded: boolean;
  scope: string;
};
const fields = [
  "setup",
  "field_units",
  "input_low",
  "input_high",
  "output_low",
  "output_high",
  "units",
  "minimum",
  "maximum",
];
const exact = (v: any, keys: string[]) =>
  v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
export function recordedTerminal(v: any): RecordedTerminal | null {
  if (
    !exact(v, [
      "state",
      "profile",
      "action",
      "object_id",
      "record_ref",
      "old_slot",
      "slot",
      "old_terminal_label",
      "terminal_label",
      "configuration_sha256",
      "stored_configuration",
      "source_sha256",
      "source_native_sha256",
      "output_sha256",
      "output_native_sha256",
      "compilation_sha256",
      "wiring_confirmation_recorded",
      "scope",
    ]) ||
    v.state !== "recorded" ||
    v.profile !== TERMINAL_LEDGER_PROFILE ||
    v.scope !== TERMINAL_LEDGER_SCOPE ||
    v.action !== "terminal" ||
    typeof v.object_id !== "string" ||
    !/^analog-input,(0|[1-9][0-9]*)$/.test(v.object_id) ||
    Number(v.object_id.split(",")[1]) > 4194302 ||
    typeof v.record_ref !== "string" ||
    [...v.record_ref].length > 512 ||
    /[\u0000-\u001f\uD800-\uDFFF]/u.test(v.record_ref) ||
    !new RegExp(`^[^/]+/0_${v.object_id.split(",")[1]}$`).test(v.record_ref) ||
    ![v.old_slot, v.slot].every(
      (n) => Number.isSafeInteger(n) && n >= 1 && n <= 6,
    ) ||
    v.old_slot === v.slot ||
    v.old_terminal_label !== `UI IN${v.old_slot}` ||
    v.terminal_label !== `UI IN${v.slot}` ||
    typeof v.wiring_confirmation_recorded !== "boolean" ||
    ![
      "configuration_sha256",
      "source_sha256",
      "source_native_sha256",
      "output_sha256",
      "output_native_sha256",
      "compilation_sha256",
    ].every((k) => typeof v[k] === "string" && /^[a-f0-9]{64}$/.test(v[k])) ||
    !exact(v.stored_configuration, fields)
  )
    return null;
  for (const name of fields) {
    const value = v.stored_configuration[name];
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    if (["setup", "field_units", "units"].includes(name)) {
      if (!Number.isInteger(value) || value < 0 || value > 65535) return null;
    } else if (!Object.is(value, Math.fround(value))) return null;
  }
  return v;
}
