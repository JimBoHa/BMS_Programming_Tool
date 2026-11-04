import { sha256Blob, sha256Text } from "./activityContracts";
import { controllerKey } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";

type Data = Record<string, any>;
export const connectionBase =
  "/bacnet/controller/native-application/inspection/connection-copy";
export const connectionProfile = "native-archive-connection-copy/1";
export const connectionCompiler = "tagged-moi-connection-copy/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max = 65535) =>
  Number.isInteger(v) && (v as number) >= 0 && (v as number) <= max;
const reference = (v: unknown) =>
  typeof v === "string" && v.length > 0 && v.length <= 512;
const tuple = (v: any) =>
  Array.isArray(v) && v.length === 4 && v.every((n) => integer(n));
const same = (a: any, b: any): boolean => {
  if (a === b) return true;
  if (Array.isArray(a))
    return (
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((v, i) => same(v, b[i]))
    );
  if (a && b && typeof a === "object" && typeof b === "object") {
    const keys = Object.keys(a);
    return (
      keys.length === Object.keys(b).length &&
      keys.every((k) => Object.hasOwn(b, k) && same(a[k], b[k]))
    );
  }
  return false;
};

export function connectionEnvelope(value: Data, source: NativeArchiveSource) {
  return (
    !!value &&
    value.profile === connectionProfile &&
    value.compiler_profile === connectionCompiler &&
    value.source_kind === "native-backup-archive" &&
    value.capture_id === source.capture_id &&
    value.snapshot_sha256 === source.snapshot_sha256 &&
    value.sha256 === source.sha256 &&
    value.source_sha256 === source.sha256 &&
    !!value.target &&
    controllerKey(value.target) === controllerKey(source.target) &&
    (["3", "11", "12"] as const).every(
      (key) =>
        value.files?.[key]?.sha256 === source.files[key].sha256 &&
        value.files?.[key]?.bytes === source.files[key].bytes,
    ) &&
    value.read_only === true &&
    value.controller_queries === false &&
    value.field_actions === false &&
    value.identity_verified === false &&
    value.saved_settings_merged === false &&
    value.field_transfer_enabled === false &&
    value.can_apply === false
  );
}

export function connectionSource(
  value: Data,
  source: NativeArchiveSource,
  request: Data,
) {
  const s = value?.selection;
  if (
    !connectionEnvelope(value, source) ||
    !s ||
    s.diagram_ref !== request.diagram_ref ||
    s.record_sha256 !== request.record_sha256 ||
    !hash(s.property_sha256) ||
    !(
      s.metadata_property_sha256 === null || hash(s.metadata_property_sha256)
    ) ||
    s.prototype_index !== request.prototype_index ||
    !integer(s.block_count, 512) ||
    !Array.isArray(s.wires) ||
    s.wires.length > 4096 ||
    s.connection_count !== s.wires.length ||
    !Array.isArray(s.sources) ||
    !Array.isArray(s.targets) ||
    s.sources.length > s.block_count ||
    s.targets.length > s.block_count ||
    typeof s.available !== "boolean" ||
    typeof s.budget_available !== "boolean" ||
    s.continuation_metadata !==
      (s.metadata_property_sha256 === null
        ? "not-recorded"
        : "recorded-boolean-string")
  )
    return false;
  if (
    s.wires.some(
      (w: Data, i: number) =>
        !w ||
        w.index !== i ||
        !tuple(w.old) ||
        !reference(w.source_ref) ||
        !reference(w.target_ref) ||
        !integer(w.old[0], s.block_count - 1) ||
        !integer(w.old[2], s.block_count - 1) ||
        w.source_port !== w.old[1] ||
        w.target_port !== w.old[3],
    )
  )
    return false;
  for (const list of [s.sources, s.targets]) {
    if (
      new Set(list.map((r: Data) => r?.ref)).size !== list.length ||
      new Set(list.map((r: Data) => r?.index)).size !== list.length ||
      list.some(
        (r: Data) =>
          !r ||
          !reference(r.ref) ||
          !integer(r.index, s.block_count - 1) ||
          !integer(r.class_id) ||
          typeof r.name !== "string" ||
          typeof r.object !== "string",
      )
    )
      return false;
  }
  if (!s.wires.length)
    return (
      s.prototype === null &&
      s.source_ref === null &&
      !s.sources.length &&
      !s.targets.length &&
      !s.available &&
      request.prototype_index === 0 &&
      request.source_ref === null
    );
  const prototype = s.wires[request.prototype_index];
  if (
    !prototype ||
    !same(s.prototype, prototype) ||
    s.source_ref !== (request.source_ref ?? prototype.source_ref)
  )
    return false;
  const selected = s.sources.find((r: Data) => r.ref === s.source_ref);
  return (
    !!selected &&
    s.wires.some(
      (w: Data) =>
        w.source_ref === selected.ref &&
        w.old[0] === selected.index &&
        w.source_port === prototype.source_port,
    ) &&
    s.targets.every(
      (r: Data) =>
        r.ref !== selected.ref &&
        r.index !== selected.index &&
        !s.wires.some(
          (w: Data) =>
            w.target_ref === r.ref && w.target_port === prototype.target_port,
        ),
    ) &&
    s.available === (s.targets.length > 0 && s.budget_available)
  );
}

// This seal contains only known strings, Booleans, null and safe integers. Match
// Python's sorted, compact, ensure_ascii=True encoding, including surrogate pairs.
function sealedJSON(v: any): string {
  if (Array.isArray(v)) return "[" + v.map(sealedJSON).join(",") + "]";
  if (v && typeof v === "object")
    return (
      "{" +
      Object.keys(v)
        .sort()
        .map((k) => sealedJSON(k) + ":" + sealedJSON(v[k]))
        .join(",") +
      "}"
    );
  if (typeof v === "number" && !Number.isSafeInteger(v))
    throw new Error("Invalid native compilation number.");
  return JSON.stringify(v).replace(
    /[\u007f-\uffff]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
  );
}

export async function connectionReview(
  value: Data,
  source: NativeArchiveSource,
  request: Data,
  selection: Data,
) {
  const c = value?.compilation;
  const src = selection.sources.find((r: Data) => r.ref === request.source_ref);
  const dst = selection.targets.find((r: Data) => r.ref === request.target_ref);
  if (
    !connectionEnvelope(value, source) ||
    !same(value.request, request) ||
    !hash(value.review_sha256) ||
    !hash(value.output_sha256) ||
    value.controller_write !== false ||
    !c ||
    !src ||
    !dst ||
    c.profile !== connectionCompiler ||
    [
      "source_sha256",
      "diagram_ref",
      "record_sha256",
      "property_sha256",
      "metadata_property_sha256",
      "prototype_index",
      "source_ref",
      "target_ref",
    ].some((key) => c[key] !== request[key]) ||
    !same(c.prototype_old, request.prototype_old) ||
    !same(c.new, [
      src.index,
      request.prototype_old[1],
      dst.index,
      request.prototype_old[3],
    ]) ||
    c.connection_count_before !== request.connection_count ||
    c.connection_count_after !== request.connection_count + 1 ||
    c.output_sha256 !== value.output_sha256 ||
    !hash(c.output_native_sha256) ||
    !hash(c.source_native_sha256) ||
    !hash(c.compilation_sha256) ||
    typeof c.scope !== "string" ||
    c.other_expanded_bytes_preserved !== true ||
    c.native_structure_readback_verified !== true ||
    c.saved_settings_merged !== false ||
    c.controller_write !== false ||
    c.field_transfer_enabled !== false ||
    !integer(c.record_bytes_before, 8 * 1024 * 1024) ||
    !integer(c.record_bytes_after, 8 * 1024 * 1024) ||
    c.record_bytes_after <= c.record_bytes_before ||
    ![0, 4].includes(c.record_prefix_growth) ||
    c.native_bytes_growth !==
      c.record_bytes_after - c.record_bytes_before + c.record_prefix_growth ||
    typeof c.prototype_encoding_hex !== "string" ||
    !/^[a-f0-9]{12,44}$/.test(c.prototype_encoding_hex) ||
    typeof c.new_encoding_hex !== "string" ||
    !/^[a-f0-9]{12,44}$/.test(c.new_encoding_hex) ||
    !(request.metadata_property_sha256 === null
      ? c.continuation_prototype_sha256 === null
      : hash(c.continuation_prototype_sha256))
  )
    return false;
  const { compilation_sha256, ...body } = c;
  return (await sha256Text(sealedJSON(body))) === compilation_sha256;
}

export async function connectionExport(
  result: { blob: Blob; headers: Headers },
  review: Data,
) {
  return (
    result.headers.get("X-Studio-Artifact-Sha256") === review.output_sha256 &&
    result.headers.get("X-Studio-Review-Sha256") === review.review_sha256 &&
    result.headers.get("X-Studio-Snapshot-Sha256") === review.snapshot_sha256 &&
    result.headers.get("X-Studio-Source-Sha256") === review.source_sha256 &&
    result.headers.get("X-Studio-Compilation-Sha256") ===
      review.compilation.compilation_sha256 &&
    (await sha256Blob(result.blob)) === review.output_sha256
  );
}

export function connectionDraftKey(source: NativeArchiveSource, record: Data) {
  return (
    "native-connection/1:" +
    JSON.stringify([
      source.capture_id,
      source.snapshot_sha256,
      source.sha256,
      source.target,
      record.ref,
      record.record_sha256,
    ])
  );
}
