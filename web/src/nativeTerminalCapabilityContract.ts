import type { NativeArchiveSource } from "./NativeRecords";
import { removalCapabilityEvidence } from "./nativeRemovalCapabilityContract";

type Data = Record<string, any>;
export const terminalCapabilityProfile =
  "native-backup-operation-capabilities/15";
export const terminalOperationIds = [
  "local-terminal-copy",
  "effective-local-terminal-copy",
  "analog-terminal-transfer",
];
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const slot = (v: unknown) =>
  Number.isSafeInteger(v) && Number(v) >= 1 && Number(v) <= 6;
const error = (v: unknown) =>
  v === null ||
  (typeof v === "string" && v.length > 0 && Array.from(v).length <= 512);
const reference = (v: unknown) =>
  typeof v === "string" && v.length > 0 && Array.from(v).length <= 512;
const common = [
  "source_sha256",
  "ref",
  "object",
  "old_slot",
  "destination_slot",
  "compiler_profile",
  "output_sha256",
  "compilation_sha256",
  "free_slots",
  "saved_settings_merged",
  "field_transfer_enabled",
  "physical_terminal_or_wiring_verified",
];
const local = [
  "record_sha256",
  "slot_property_sha256",
  "device_type_property_sha256",
  "class_id",
];
const field = [
  "effective_sha256",
  "parameter_merge",
  "configuration_sha256",
  "operation_profile",
];
export function terminalCapabilityWitness(
  v: Data,
  basis: string,
  source: NativeArchiveSource,
  root: string,
  encoded = false,
) {
  if (!v || Array.isArray(v)) return false;
  const analog = basis === "analog",
    effective = basis !== "archive";
  if (encoded && (analog || !reference(root))) return false;
  const keys = [
    ...common,
    ...(analog ? field : local),
    ...(basis === "effective" ? ["parameter_merge"] : []),
    ...(encoded
      ? ["device_type_character_encoding", "device_type_encoding_preserved"]
      : []),
  ];
  if (
    encoded &&
    (![0, 4].includes(v.device_type_character_encoding) ||
      v.device_type_encoding_preserved !== true)
  )
    return false;
  const match =
    typeof v.object === "string" &&
    /^(analog-input|binary-input),(0|[1-9][0-9]*)$/.exec(v.object);
  if (
    Object.keys(v).length !== keys.length ||
    !keys.every((k) => Object.hasOwn(v, k)) ||
    !match ||
    Number(match[2]) > 4194302 ||
    !reference(v.ref) ||
    v.ref !== `${root}/${match[1] === "analog-input" ? 0 : 3}_${match[2]}` ||
    !slot(v.old_slot) ||
    !slot(v.destination_slot) ||
    v.old_slot === v.destination_slot ||
    !Array.isArray(v.free_slots) ||
    !v.free_slots.length ||
    !v.free_slots.every(slot) ||
    new Set(v.free_slots).size !== v.free_slots.length ||
    v.free_slots.some(
      (n: number, i: number) => i > 0 && n <= v.free_slots[i - 1],
    ) ||
    v.free_slots.includes(v.old_slot) ||
    v.destination_slot !== v.free_slots[0] ||
    v.saved_settings_merged !== effective ||
    v.field_transfer_enabled !== false ||
    v.physical_terminal_or_wiring_verified !== false ||
    !hash(v.output_sha256) ||
    !hash(v.compilation_sha256)
  )
    return false;
  if (
    !analog &&
    (!local.slice(0, 3).every((k) => hash(v[k])) ||
      v.class_id !== (match[1] === "analog-input" ? 240 : 242))
  )
    return false;
  if (
    analog &&
    (match[1] !== "analog-input" ||
      !hash(v.configuration_sha256) ||
      v.operation_profile !== "native-local-universal-input-transfer/2" ||
      !hash(v.effective_sha256))
  )
    return false;
  if (
    v.compiler_profile !==
    `tagged-moi-local-terminal-copy/${encoded ? "3" : analog ? "2" : "1"}`
  )
    return false;
  if (!effective) return v.source_sha256 === source.sha256;
  const merge = v.parameter_merge;
  return (
    !!merge &&
    merge.source_sha256 === source.sha256 &&
    merge.static_sha256 === source.files["11"].sha256 &&
    merge.dynamic_sha256 === source.files["12"].sha256 &&
    hash(merge.output_sha256) &&
    (analog
      ? v.source_sha256 === source.sha256 &&
        v.effective_sha256 === merge.output_sha256
      : v.source_sha256 === merge.output_sha256)
  );
}

export function terminalCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== terminalCapabilityProfile ||
      !removalCapabilityEvidence(
        {
          ...data,
          capability_profile: "native-backup-operation-capabilities/14",
        },
        source,
      )
    )
      return false;
    const q = data.qualification;
    if (
      ![
        q.recorded_identity_verified,
        q.identity_matches_snapshot,
        q.captured_plain_ipv4,
      ].every((v) => typeof v === "boolean")
    )
      return false;
    for (const [i, basis] of ["archive", "effective", "analog"].entries()) {
      const value = q[basis + "_terminal"],
        failure = q[basis + "_terminal_error"];
      if (
        !error(failure) ||
        (value === null
          ? failure === null
          : failure !== null ||
            !reference(q.native_identity?.root_ref) ||
            !terminalCapabilityWitness(
              value,
              basis,
              source,
              q.native_identity.root_ref,
            ))
      )
        return false;
      if (
        value !== null &&
        basis !== "archive" &&
        (q.recorded_identity_verified !== true ||
          q.identity_matches_snapshot !== true)
      )
        return false;
      const rows = data.operations.filter(
        (r: Data) => r.id === terminalOperationIds[i],
      );
      const status =
        basis === "analog" && q.recorded_identity_verified !== true
          ? "source-mismatch"
          : value === null
            ? "unsupported-source"
            : basis !== "analog"
              ? "source-qualified"
              : q.captured_plain_ipv4 === true
                ? "preflight-required"
                : "transport-unavailable";
      if (
        rows.length !== 1 ||
        rows[0].status !== status ||
        !["operation", "basis", "next_step"].every(
          (k) => typeof rows[0][k] === "string",
        )
      )
        return false;
    }
    return (
      data.operations.length === 30 &&
      new Set(data.operations.map((r: Data) => r.id)).size === 30
    );
  } catch {
    return false;
  }
}
