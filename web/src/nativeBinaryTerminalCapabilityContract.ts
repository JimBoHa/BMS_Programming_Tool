import type { NativeArchiveSource } from "./NativeRecords";
import {
  terminalCapabilityEvidence as legacyEvidence,
  terminalOperationIds as oldIds,
} from "./nativeEncodedTerminalCapabilityContract";
type Data = Record<string, any>;
export const terminalCapabilityProfile =
  "native-backup-operation-capabilities/17";
export const binaryOperationId = "binary-terminal-transfer";
export const terminalOperationIds = [...oldIds, binaryOperationId];
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const uint = (v: any, max: number) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const slot = (v: any) => uint(v, 6) && v >= 1;
export function binaryCapabilityWitness(
  v: Data,
  source: NativeArchiveSource,
  root: string,
) {
  if (
    !exact(v, [
      "source_sha256",
      "effective_sha256",
      "source_native_sha256",
      "parameter_merge",
      "object",
      "ref",
      "old_slot",
      "destination_slot",
      "configuration_sha256",
      "stored_configuration",
      "captured_counter_values",
      "counter_values_are_live",
      "device_type_character_encoding",
      "device_type_encoding_preserved",
      "operation_profile",
      "compiler_profile",
      "output_sha256",
      "output_native_sha256",
      "compilation_sha256",
      "free_slots",
      "saved_settings_merged",
      "field_transfer_enabled",
      "physical_terminal_or_wiring_verified",
    ])
  )
    return false;
  const match =
      typeof v.object === "string" &&
      /^binary-input,(0|[1-9][0-9]*)$/.exec(v.object),
    m = v.parameter_merge,
    c = v.stored_configuration,
    counts = v.captured_counter_values;
  return (
    !!match &&
    uint(Number(match[1]), 4194302) &&
    typeof root === "string" &&
    root.length > 0 &&
    root.length <= 512 &&
    v.ref === `${root}/3_${match[1]}` &&
    v.operation_profile === "native-local-universal-input-transfer/3" &&
    v.compiler_profile === "tagged-moi-local-terminal-copy/3" &&
    slot(v.old_slot) &&
    slot(v.destination_slot) &&
    v.old_slot !== v.destination_slot &&
    Array.isArray(v.free_slots) &&
    v.free_slots.length > 0 &&
    v.free_slots.every(slot) &&
    new Set(v.free_slots).size === v.free_slots.length &&
    v.free_slots.every(
      (n: number, i: number) => i === 0 || n > v.free_slots[i - 1],
    ) &&
    !v.free_slots.includes(v.old_slot) &&
    v.destination_slot === v.free_slots[0] &&
    v.source_sha256 === source.sha256 &&
    [
      "effective_sha256",
      "source_native_sha256",
      "configuration_sha256",
      "output_sha256",
      "output_native_sha256",
      "compilation_sha256",
    ].every((k) => hash(v[k])) &&
    v.saved_settings_merged === true &&
    v.field_transfer_enabled === false &&
    v.physical_terminal_or_wiring_verified === false &&
    v.counter_values_are_live === false &&
    [0, 4].includes(v.device_type_character_encoding) &&
    v.device_type_encoding_preserved === true &&
    !!m &&
    m.source_sha256 === source.sha256 &&
    m.static_sha256 === source.files["11"].sha256 &&
    m.dynamic_sha256 === source.files["12"].sha256 &&
    m.output_sha256 === v.effective_sha256 &&
    m.native_output_sha256 === v.source_native_sha256 &&
    exact(c, [
      "active_text",
      "inactive_text",
      "states_text_index",
      "polarity",
    ]) &&
    typeof c.active_text === "string" &&
    c.active_text.length <= 65535 &&
    typeof c.inactive_text === "string" &&
    c.inactive_text.length <= 65535 &&
    uint(c.states_text_index, 4294967295) &&
    [null, 0, 1].includes(c.polarity) &&
    !!counts &&
    typeof counts === "object" &&
    !Array.isArray(counts) &&
    Object.keys(counts).length <= 2 &&
    Object.entries(counts).every(
      ([k, n]) => ["15", "33"].includes(k) && uint(n, 4294967295),
    )
  );
}
export function terminalCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== terminalCapabilityProfile ||
      !Array.isArray(data.operations) ||
      data.operations.length !== 33 ||
      new Set(data.operations.map((r: Data) => r.id)).size !== 33
    )
      return false;
    const q = data.qualification,
      previous = { ...q };
    delete previous.binary_terminal;
    delete previous.binary_terminal_error;
    if (
      !legacyEvidence(
        {
          ...data,
          capability_profile: "native-backup-operation-capabilities/16",
          qualification: previous,
          operations: data.operations.filter(
            (r: Data) => r.id !== binaryOperationId,
          ),
        },
        source,
      )
    )
      return false;
    const v = q.binary_terminal,
      error = q.binary_terminal_error;
    if (v === null) {
      if (
        typeof error !== "string" ||
        !error.length ||
        Array.from(error).length > 512
      )
        return false;
    } else if (
      error !== null ||
      q.recorded_identity_verified !== true ||
      q.identity_matches_snapshot !== true ||
      !binaryCapabilityWitness(v, source, q.native_identity?.root_ref)
    )
      return false;
    const rows = data.operations.filter(
        (r: Data) => r.id === binaryOperationId,
      ),
      status =
        q.recorded_identity_verified !== true
          ? "source-mismatch"
          : v === null
            ? "unsupported-source"
            : q.captured_plain_ipv4 === true
              ? "preflight-required"
              : "transport-unavailable";
    return (
      rows.length === 1 &&
      exact(rows[0], ["id", "operation", "status", "basis", "next_step"]) &&
      rows[0].status === status &&
      ["operation", "basis", "next_step"].every(
        (k) => typeof rows[0][k] === "string",
      )
    );
  } catch {
    return false;
  }
}
