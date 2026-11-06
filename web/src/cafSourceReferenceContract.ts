import { sha256Blob } from "./activityContracts";
import {
  comparisonRequest,
  comparisonReportSource,
  comparisonSourceMatches,
  correlationProfile,
  type ComparisonSource,
} from "./cafNativeCorrelationSources";

type Data = Record<string, any>;
export const referenceScope =
  "User-selected historical CAF/source reference. Original identity comparison only; source availability and current controller application are not revalidated. No application association, full-program match, compiler compatibility or field authority.";
export const referenceClassifications: Record<string, string> = {
  "recorded-identities-equal":
    "Recorded identities equal within the checked scope",
  "recorded-differences": "Recorded identity differences found",
  "identity-incomplete": "Recorded identity evidence is incomplete",
};
const statuses = [
  "same-record-identity",
  "different-record-identity",
  "caf-only",
  "native-only",
  "identity-unavailable",
  "ambiguous-identity",
];
const hash = (v: unknown): v is string =>
  typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const identifier = (v: unknown): v is string =>
  typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const object = (v: any): v is Data =>
  !!v && typeof v === "object" && !Array.isArray(v);
const integer = (v: unknown, max = 40000) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const text = (v: unknown, max = 4096): v is string =>
  typeof v === "string" && [...v].length <= max;
const same = (a: any, b: any): boolean => {
  if (a === b) return true;
  if (
    !a ||
    !b ||
    typeof a !== "object" ||
    typeof b !== "object" ||
    Array.isArray(a) !== Array.isArray(b)
  )
    return false;
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every((k) => Object.hasOwn(b, k) && same(a[k], b[k]))
  );
};
export const referenceFlags = (v: Data) =>
  object(v) &&
  v.scope === referenceScope &&
  v.source_availability_revalidated === false &&
  v.read_only === true &&
  [
    "controller_queries",
    "controller_writes",
    "field_actions",
    "full_program_match_verified",
    "compiler_compatibility_verified",
    "application_association_granted",
    "can_apply",
  ].every((k) => v[k] === false);
const coverage = (v: Data) =>
  object(v) &&
  [
    "caf_objects",
    "native_engineering_records",
    "native_metadata_records",
    "union_references",
    "caf_reference_conflicts",
  ].every((k) => integer(v[k])) &&
  object(v.record_status_counts) &&
  Object.keys(v.record_status_counts).every(
    (k) => statuses.includes(k) && integer(v.record_status_counts[k]),
  ) &&
  Object.values(v.record_status_counts).reduce(
    (sum: number, n: any) => sum + n,
    0,
  ) === v.union_references &&
  Array.isArray(v.not_compared) &&
  v.not_compared.length === 4 &&
  v.not_compared.every((v: unknown) => text(v));
const target = (v: Data) =>
  object(v) &&
  text(v.address, 512) &&
  v.address.length > 0 &&
  typeof v.device === "string" &&
  /^device,\d+$/.test(v.device) &&
  integer(Number(v.device.slice(7)), 4194302) &&
  (v.router === null || v.router === undefined || text(v.router, 512)) &&
  (v.dnet === null || v.dnet === undefined || integer(v.dnet, 65535));

export function savedReference(v: Data, caf: string): Data | null {
  if (!object(v) || !identifier(v.id)) return null;
  if (v.state === "unavailable")
    return v.caf_sha256 === caf &&
      text(v.error) &&
      Object.keys(v).sort().join() === "caf_sha256,error,id,state"
      ? v
      : null;
  const s = v.source,
    p = v.pagination;
  if (
    v.profile !== "caf-source-reference/1" ||
    v.state !== "saved" ||
    v.caf_sha256 !== caf ||
    !hash(caf) ||
    !["backup", "file"].includes(v.source_kind) ||
    !referenceFlags(v) ||
    v.source_availability_revalidated !== false ||
    !object(s) ||
    !identifier(s.capture_id) ||
    !hash(s.sha256) ||
    !target(s.target) ||
    !text(s.captured_at) ||
    !text(v.created_at) ||
    !hash(v.report_sha256) ||
    !hash(v.comparison_report_sha256) ||
    !Object.hasOwn(referenceClassifications, v.classification) ||
    !coverage(v.coverage) ||
    !object(p) ||
    p.query !== "" ||
    p.offset !== 0 ||
    p.limit !== 128 ||
    p.total_matches !== v.coverage.union_references ||
    p.records_retained !== Math.min(128, p.total_matches) ||
    p.next_offset !== (p.total_matches > 128 ? 128 : null) ||
    (v.source_kind === "backup"
      ? !hash(s.snapshot_sha256) ||
        s.receipt_sha256 !== undefined ||
        s.file_object !== undefined
      : !hash(s.receipt_sha256) ||
        s.snapshot_sha256 !== undefined ||
        typeof s.file_object !== "string" ||
        !/^file,\d+$/.test(s.file_object))
  )
    return null;
  return v;
}

export function referenceList(v: Data, caf: string): Data[] {
  if (
    !object(v) ||
    v.profile !== "caf-source-references/1" ||
    v.caf_sha256 !== caf ||
    !referenceFlags(v) ||
    !Array.isArray(v.references) ||
    v.references.length > 256 ||
    !object(v.capacity) ||
    !integer(v.capacity.count, 256) ||
    v.capacity.limit !== 256 ||
    v.capacity.count > v.capacity.limit ||
    !integer(v.capacity.bytes, Number.MAX_SAFE_INTEGER) ||
    v.capacity.byte_limit !== 33554432 ||
    v.capacity.bytes > v.capacity.byte_limit ||
    new Set(v.references.map((r: Data) => r.id)).size !== v.references.length ||
    v.references.some((r: Data) => !savedReference(r, caf))
  )
    throw new Error(
      "Saved reference list does not match this CAF or its recorded-only scope.",
    );
  return v.references;
}

export function referenceRequest(source: ComparisonSource, caf: string) {
  const {
    query: _query,
    offset: _offset,
    limit: _limit,
    ...request
  } = comparisonRequest(source, caf, "", 0);
  return { source_kind: source.kind, ...request };
}

export function referenceSave(
  v: Data,
  source: ComparisonSource,
  caf: string,
): Data {
  const row = savedReference(v?.reference, caf),
    s = row?.source;
  if (
    !object(v) ||
    v.profile !== "caf-source-reference-save/1" ||
    !referenceFlags(v) ||
    !row ||
    row.state !== "saved" ||
    typeof v.created !== "boolean" ||
    v.deduplicated !== !v.created ||
    row.source_kind !== source.kind ||
    s.capture_id !== source.id ||
    !same(s.target, source.target) ||
    s.captured_at !== source.captured_at ||
    (source.kind === "backup"
      ? s.snapshot_sha256 !== source.signature
      : s.receipt_sha256 !== source.signature ||
        s.sha256 !== source.raw.sha256 ||
        s.file_object !== source.raw.file_object)
  )
    throw new Error(
      "Saved reference does not match the selected original CAF and retained source.",
    );
  return row;
}

export async function referenceReport(
  result: { data: Data; blob: Blob; headers?: Headers },
  row: Data,
  caf: string,
) {
  const { data: v } = result,
    s = row.source,
    kind = row.source_kind;
  const native = comparisonReportSource(v, kind);
  const source: ComparisonSource = {
    kind,
    id: s.capture_id,
    signature: kind === "backup" ? s.snapshot_sha256 : s.receipt_sha256,
    target: s.target,
    captured_at: s.captured_at,
    identity: {},
    raw: native || {},
  };
  const request = { ...comparisonRequest(source, caf, "", 0), limit: 128 };
  if (
    !savedReference(row, caf) ||
    row.state !== "saved" ||
    !object(v) ||
    v.profile !== correlationProfile(kind) ||
    !comparisonSourceMatches(v, source) ||
    native.sha256 !== s.sha256 ||
    !same(native.target, s.target) ||
    (kind === "file" && native.file_object !== s.file_object) ||
    v.caf?.sha256 !== caf ||
    v.caf?.source !== "original-opened-archive" ||
    !same(v.request, request) ||
    v.read_only !== true ||
    [
      "controller_queries",
      "field_actions",
      "full_program_match_verified",
      "compiler_compatibility_verified",
      "application_association_granted",
      "can_apply",
    ].some((k) => v[k] !== false) ||
    v.classification !== row.classification ||
    !same(v.coverage, row.coverage) ||
    v.report_sha256 !== row.comparison_report_sha256 ||
    v.query !== "" ||
    v.offset !== 0 ||
    v.limit !== 128 ||
    v.total_matches !== row.pagination.total_matches ||
    v.next_offset !== row.pagination.next_offset ||
    !Array.isArray(v.records) ||
    v.records.length !== row.pagination.records_retained ||
    v.records.some(
      (r: Data) =>
        !object(r) ||
        !text(r.ref, 512) ||
        !statuses.includes(r.status) ||
        [r.caf_class, r.native_class].some(
          (n) => n !== null && !integer(n, 65535),
        ) ||
        [r.caf_object_id, r.native_object_id].some(
          (n) => n !== null && !integer(n, 4194303),
        ),
    ) ||
    new Set(v.records.map((r: Data) => r.ref)).size !== v.records.length ||
    !Array.isArray(v.device_checks) ||
    v.device_checks.length !== 5 ||
    v.device_checks.map((r: Data) => r.field).join() !==
      "root_ref,root_class,instance,name,model" ||
    v.device_checks.some(
      (r: Data) =>
        !["equal", "different", "unavailable"].includes(r.status) ||
        [r.caf, r.native].some(
          (n) => n !== null && !text(n) && !integer(n, 4194303),
        ),
    ) ||
    result.headers?.get("X-Studio-Artifact-Sha256") !== row.report_sha256 ||
    (await sha256Blob(result.blob)) !== row.report_sha256
  )
    throw new Error(
      "Original saved report does not match this reference, CAF and recorded source.",
    );
  return result;
}
