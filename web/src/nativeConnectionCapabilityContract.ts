import type { NativeArchiveSource } from "./NativeRecords";

type Data = Record<string, any>;
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const count = (v: unknown, low: number, high: number) =>
  Number.isSafeInteger(v) && (v as number) >= low && (v as number) <= high;
const reference = (v: unknown) =>
  typeof v === "string" && v.length > 0 && Array.from(v).length <= 512;
const error = (v: unknown) =>
  v === null ||
  (typeof v === "string" && v.length > 0 && Array.from(v).length <= 512);
const witnessKeys = [
  "diagram_ref",
  "prototype_index",
  "prototype_old",
  "source_ref",
  "target_ref",
  "source_index",
  "target_index",
  "source_candidate_count",
  "target_candidate_count",
  "connection_count",
  "block_count",
  "continuation_metadata",
  "source_sha256",
  "record_sha256",
  "property_sha256",
  "metadata_property_sha256",
];

function witness(v: Data, sourceSha256: string) {
  return (
    !!v &&
    !Array.isArray(v) &&
    Object.keys(v).length === witnessKeys.length &&
    witnessKeys.every((key) => Object.hasOwn(v, key)) &&
    v.source_sha256 === sourceSha256 &&
    reference(v.diagram_ref) &&
    reference(v.source_ref) &&
    reference(v.target_ref) &&
    v.source_ref !== v.target_ref &&
    count(v.block_count, 2, 512) &&
    count(v.source_index, 0, v.block_count - 1) &&
    count(v.target_index, 0, v.block_count - 1) &&
    // A new six-tag tuple plus its closing tag must fit the existing 20,000-tag property budget.
    v.source_index !== v.target_index &&
    count(v.connection_count, 1, 3332) &&
    count(v.prototype_index, 0, v.connection_count - 1) &&
    Array.isArray(v.prototype_old) &&
    v.prototype_old.length === 4 &&
    v.prototype_old.every((n: unknown) => count(n, 0, 65535)) &&
    v.prototype_old[0] < v.block_count &&
    v.prototype_old[2] < v.block_count &&
    count(v.source_candidate_count, 1, v.block_count) &&
    count(v.target_candidate_count, 1, v.block_count - 1) &&
    hash(v.record_sha256) &&
    hash(v.property_sha256) &&
    (v.metadata_property_sha256 === null
      ? v.continuation_metadata === "not-recorded"
      : hash(v.metadata_property_sha256) &&
        v.continuation_metadata === "recorded-boolean-string")
  );
}

export function connectionCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  const q = data?.qualification;
  if (
    !q ||
    !Array.isArray(data.operations) ||
    !error(q.archive_matching_connection_error) ||
    !error(q.effective_matching_connection_error)
  )
    return false;
  const original = q.archive_matching_connection,
    effective = q.effective_matching_connection;
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
  return (
    data.operations?.find((r: Data) => r.id === "matching-connection-copy")
      ?.status ===
      (original === null ? "unsupported-source" : "source-qualified") &&
    data.operations?.find((r: Data) => r.id === "effective-connection-compile")
      ?.status ===
      (effective === null ? "unsupported-source" : "source-qualified")
  );
}
