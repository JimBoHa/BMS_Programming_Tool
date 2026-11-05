export const binaryLedgerProfile = "native-recorded-binary-terminal/1";
export const binaryLedgerScope =
  "Recorded binary terminal movement, unchanged configuration and historical counter values only. No source/parent revalidation, current value, controller query, physical wiring or new transfer authority.";
type Data = Record<string, any>;
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const integer = (v: unknown, max: number) =>
  Number.isSafeInteger(v) && Number(v) >= 0 && Number(v) <= max;
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export function recordedBinaryTerminal(v: unknown): Data | null {
  const r = v as Data;
  if (
    !exact(r, [
      "state",
      "profile",
      "operation_profile",
      "action",
      "object_id",
      "record_ref",
      "old_slot",
      "slot",
      "old_terminal_label",
      "terminal_label",
      "configuration_sha256",
      "stored_configuration",
      "captured_counter_values",
      "device_type_character_encoding",
      "source_sha256",
      "source_native_sha256",
      "output_sha256",
      "output_native_sha256",
      "compilation_sha256",
      "confirmations_recorded",
      "transfer_authority",
      "scope",
    ]) ||
    r.state !== "recorded" ||
    r.profile !== binaryLedgerProfile ||
    r.operation_profile !== "native-local-universal-input-transfer/3" ||
    r.action !== "binary-terminal" ||
    r.scope !== binaryLedgerScope ||
    r.confirmations_recorded !== true ||
    r.transfer_authority !== false ||
    typeof r.object_id !== "string" ||
    !/^binary-input,(0|[1-9][0-9]*)$/.test(r.object_id) ||
    !integer(Number(r.object_id.split(",")[1]), 4194302) ||
    typeof r.record_ref !== "string" ||
    r.record_ref.length > 512 ||
    !new RegExp(`^[^/\\x00-\\x1f]+/3_${r.object_id.split(",")[1]}$`).test(
      r.record_ref,
    ) ||
    !integer(r.old_slot, 6) ||
    r.old_slot < 1 ||
    !integer(r.slot, 6) ||
    r.slot < 1 ||
    r.slot === r.old_slot ||
    r.old_terminal_label !== `UI IN${r.old_slot}` ||
    r.terminal_label !== `UI IN${r.slot}` ||
    ![0, 4].includes(r.device_type_character_encoding) ||
    ![
      "configuration_sha256",
      "source_sha256",
      "source_native_sha256",
      "output_sha256",
      "output_native_sha256",
      "compilation_sha256",
    ].every((k) => hash(r[k]))
  )
    return null;
  const c = r.stored_configuration,
    counts = r.captured_counter_values;
  if (
    !exact(c, [
      "active_text",
      "inactive_text",
      "states_text_index",
      "polarity",
    ]) ||
    typeof c.active_text !== "string" ||
    typeof c.inactive_text !== "string" ||
    c.active_text.length > 65535 ||
    c.inactive_text.length > 65535 ||
    !integer(c.states_text_index, 4294967295) ||
    ![null, 0, 1].includes(c.polarity) ||
    !counts ||
    typeof counts !== "object" ||
    Array.isArray(counts) ||
    Object.keys(counts).length > 2 ||
    !Object.entries(counts).every(
      ([k, x]) => ["15", "33"].includes(k) && integer(x, 4294967295),
    )
  )
    return null;
  return r;
}
