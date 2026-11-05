import type { NativeArchiveSource } from "./NativeRecords";
import { matchingConnectionTransferCapability } from "./nativeConnectionCapabilityContract";

type Data = Record<string, any>;
const profile = "native-backup-operation-capabilities/14";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const count = (v: unknown, min: number, max: number) =>
  Number.isSafeInteger(v) && (v as number) >= min && (v as number) <= max;
const reference = (v: unknown) =>
  typeof v === "string" && v.length > 0 && Array.from(v).length <= 512;
const error = (v: unknown) =>
  v === null ||
  (typeof v === "string" && v.length > 0 && Array.from(v).length <= 512);
const keys = [
  "diagram_ref",
  "wire_index",
  "old",
  "source_ref",
  "target_ref",
  "connection_count",
  "block_count",
  "continuation_metadata",
  "source_sha256",
  "record_sha256",
  "property_sha256",
  "metadata_property_sha256",
  "native_fallback_or_retention_verified",
  "field_transfer_enabled",
];
function witness(v: Data, sourceSha256: string) {
  return (
    !!v &&
    !Array.isArray(v) &&
    Object.keys(v).length === keys.length &&
    keys.every((k) => Object.hasOwn(v, k)) &&
    v.source_sha256 === sourceSha256 &&
    reference(v.diagram_ref) &&
    reference(v.source_ref) &&
    reference(v.target_ref) &&
    count(v.block_count, 1, 512) &&
    count(v.connection_count, 1, 3333) &&
    count(v.wire_index, 0, v.connection_count - 1) &&
    Array.isArray(v.old) &&
    v.old.length === 4 &&
    v.old.every((n: unknown) => count(n, 0, 65535)) &&
    v.old[0] < v.block_count &&
    v.old[2] < v.block_count &&
    (v.old[0] === v.old[2]) === (v.source_ref === v.target_ref) &&
    hash(v.record_sha256) &&
    hash(v.property_sha256) &&
    (v.metadata_property_sha256 === null
      ? v.continuation_metadata === "not-recorded"
      : hash(v.metadata_property_sha256) &&
        v.continuation_metadata === "recorded-boolean-string") &&
    v.native_fallback_or_retention_verified === false &&
    v.field_transfer_enabled === false
  );
}
export function removalCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== profile ||
      !matchingConnectionTransferCapability(
        {
          ...data,
          capability_profile: "native-backup-operation-capabilities/13",
        },
        source,
      )
    )
      return false;
    const q = data.qualification;
    if (
      !error(q.archive_connection_removal_error) ||
      !error(q.effective_connection_removal_error)
    )
      return false;
    const original = q.archive_connection_removal,
      effective = q.effective_connection_removal;
    if (!(original === null || witness(original, source.sha256))) return false;
    if (effective !== null) {
      const merge = q.parameter_merge;
      if (
        q.recorded_identity_verified !== true ||
        q.identity_matches_snapshot !== true ||
        !merge ||
        merge.source_sha256 !== source.sha256 ||
        merge.static_sha256 !== source.files["11"].sha256 ||
        merge.dynamic_sha256 !== source.files["12"].sha256 ||
        !hash(merge.output_sha256) ||
        !witness(effective, merge.output_sha256)
      )
        return false;
    }
    for (const [id, evidence] of [
      ["connection-removal-copy", original],
      ["effective-connection-removal-compile", effective],
    ]) {
      const rows = data.operations.filter((r: Data) => r.id === id);
      if (
        rows.length !== 1 ||
        rows[0].status !==
          (evidence === null ? "unsupported-source" : "source-qualified")
      )
        return false;
    }
    return true;
  } catch {
    return false;
  }
}
