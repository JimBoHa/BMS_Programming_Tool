import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";

type Data = Record<string, any>;
export type RemovalBasis = "archive" | "effective";
export const removalBase = (basis: RemovalBasis) =>
  "/bacnet/controller/native-application/inspection/" +
  (basis === "effective" ? "effective-" : "") +
  "connection-removal-copy";
const archiveProfile = "native-archive-connection-removal-copy/1";
const effectiveProfile = "native-effective-connection-removal-compiler/1";
const compilerProfile = "tagged-moi-connection-removal-copy/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max = 65535) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const reference = (v: unknown) =>
  typeof v === "string" && v.length > 0 && v.length <= 512;
const tuple = (v: any) =>
  Array.isArray(v) && v.length === 4 && v.every((n) => integer(n));

function envelope(
  v: Data,
  source: NativeArchiveSource,
  request: Data,
  basis: RemovalBasis,
) {
  if (
    !v ||
    v.profile !== (basis === "effective" ? effectiveProfile : archiveProfile) ||
    v.compiler_profile !== compilerProfile ||
    v.source_kind !== "native-backup-archive" ||
    v.capture_id !== source.capture_id ||
    v.snapshot_sha256 !== source.snapshot_sha256 ||
    v.sha256 !== source.sha256 ||
    v.source_sha256 !== source.sha256 ||
    !v.target ||
    controllerKey(v.target) !== controllerKey(source.target) ||
    !same(v.files, source.files) ||
    typeof v.scope !== "string" ||
    v.source_immutable !== true ||
    v.read_only !== true ||
    v.controller_queries !== false ||
    v.field_actions !== false ||
    v.identity_verified !== false ||
    v.current_identity_verified !== false ||
    v.saved_settings_merged !== (basis === "effective") ||
    v.field_transfer_enabled !== false ||
    v.controller_write !== false ||
    v.can_apply !== false
  )
    return false;
  if (basis === "archive") return true;
  const p = v.parameter_merge;
  return (
    v.archive_record_sha256 === request.record_sha256 &&
    hash(v.effective_sha256) &&
    !!p &&
    p.source_sha256 === source.sha256 &&
    p.output_sha256 === v.effective_sha256 &&
    p.static_sha256 === source.files["11"].sha256 &&
    p.dynamic_sha256 === source.files["12"].sha256 &&
    hash(p.native_output_sha256) &&
    integer(p.matched_parameters, 20000) &&
    Array.isArray(p.changed_parameters) &&
    p.changed_parameters.length <= p.matched_parameters &&
    Array.isArray(p.retained_runtime_parameters) &&
    p.retained_runtime_parameters.length <= 20000 &&
    p.vendor_runtime_required === false
  );
}

export function removalSelection(s: Data, request: Data, basis: RemovalBasis) {
  if (
    !s ||
    s.diagram_ref !== request.diagram_ref ||
    !hash(s.record_sha256) ||
    (basis === "archive" && s.record_sha256 !== request.record_sha256) ||
    !hash(s.property_sha256) ||
    !(
      s.metadata_property_sha256 === null || hash(s.metadata_property_sha256)
    ) ||
    s.wire_index !== request.wire_index ||
    !integer(s.wire_index, 4095) ||
    !integer(s.block_count, 512) ||
    !Array.isArray(s.wires) ||
    s.wires.length > 4096 ||
    s.connection_count !== s.wires.length ||
    s.continuation_metadata !==
      (s.metadata_property_sha256 === null
        ? "not-recorded"
        : "recorded-boolean-string") ||
    typeof s.available !== "boolean"
  )
    return false;
  const members = new Map<number, string>(),
    destinations = new Set<string>();
  for (const [i, w] of s.wires.entries()) {
    if (
      !w ||
      w.index !== i ||
      !tuple(w.old) ||
      !integer(w.old[0], s.block_count - 1) ||
      !integer(w.old[2], s.block_count - 1) ||
      !reference(w.source_ref) ||
      !reference(w.target_ref) ||
      w.source_port !== w.old[1] ||
      w.target_port !== w.old[3] ||
      !integer(w.source_index_offset, 8 * 1024 * 1024) ||
      ![1, 2, 3, 4].includes(w.source_index_bytes)
    )
      return false;
    for (const [index, ref] of [
      [w.old[0], w.source_ref],
      [w.old[2], w.target_ref],
    ] as [number, string][]) {
      if (members.has(index) && members.get(index) !== ref) return false;
      if (
        [...members].some(([other, value]) => other !== index && value === ref)
      )
        return false;
      members.set(index, ref);
    }
    const destination = JSON.stringify([w.old[2], w.old[3]]);
    if (destinations.has(destination)) return false;
    destinations.add(destination);
  }
  if (!s.wires.length)
    return s.wire_index === 0 && s.selected_wire === null && !s.available;
  return (
    !!s.wires[s.wire_index] &&
    same(s.selected_wire, s.wires[s.wire_index]) &&
    s.available
  );
}

export function removalSource(
  v: Data,
  source: NativeArchiveSource,
  request: Data,
  basis: RemovalBasis,
) {
  return (
    envelope(v, source, request, basis) &&
    removalSelection(v.selection, request, basis)
  );
}

async function compilation(
  c: Data,
  output: string,
  request: Data,
  selection: Data,
) {
  const wire = selection.selected_wire;
  if (
    !c ||
    !wire ||
    c.profile !== compilerProfile ||
    typeof c.scope !== "string" ||
    [
      "source_sha256",
      "diagram_ref",
      "record_sha256",
      "property_sha256",
      "metadata_property_sha256",
      "wire_index",
    ].some((key) => c[key] !== request[key]) ||
    !same(c.old, request.old) ||
    !same(c.old, wire.old) ||
    c.source_ref !== wire.source_ref ||
    c.target_ref !== wire.target_ref ||
    c.connection_count_before !== request.connection_count ||
    c.connection_count_after !== request.connection_count - 1 ||
    !integer(c.connection_count_after, 4095) ||
    c.output_sha256 !== output ||
    !hash(c.source_native_sha256) ||
    !hash(c.output_native_sha256) ||
    !hash(c.compilation_sha256) ||
    c.other_expanded_bytes_preserved !== true ||
    c.native_structure_readback_verified !== true ||
    c.destination_configuration_preserved !== true ||
    c.native_fallback_or_retention_verified !== false ||
    c.saved_settings_merged !== false ||
    c.controller_write !== false ||
    c.field_transfer_enabled !== false ||
    !integer(c.record_bytes_before, 8 * 1024 * 1024) ||
    !integer(c.record_bytes_after, 8 * 1024 * 1024) ||
    c.record_bytes_after >= c.record_bytes_before ||
    ![2, 6].includes(c.record_prefix_bytes) ||
    c.record_prefix_growth !== 0 ||
    c.native_bytes_growth !== c.record_bytes_after - c.record_bytes_before ||
    typeof c.removed_encoding_hex !== "string" ||
    !/^(?:[a-f0-9]{2}){6,22}$/.test(c.removed_encoding_hex) ||
    !integer(c.removed_continuation_bytes, 8 * 1024 * 1024) ||
    -c.native_bytes_growth !==
      c.removed_encoding_hex.length / 2 + c.removed_continuation_bytes ||
    !(request.metadata_property_sha256 === null
      ? c.removed_continuation_sha256 === null &&
        c.removed_continuation_bytes === 0
      : hash(c.removed_continuation_sha256) && c.removed_continuation_bytes > 0)
  )
    return false;
  const { compilation_sha256, ...body } = c;
  return (await connectionSeal(body)) === compilation_sha256;
}

export async function removalReview(
  v: Data,
  source: NativeArchiveSource,
  request: Data,
  opened: Data,
  basis: RemovalBasis,
) {
  if (
    !envelope(v, source, request, basis) ||
    !same(v.request, request) ||
    !hash(v.review_sha256) ||
    !hash(v.output_sha256) ||
    !removalSource(opened, source, request, basis) ||
    request.property_sha256 !== opened.selection.property_sha256 ||
    request.metadata_property_sha256 !==
      opened.selection.metadata_property_sha256 ||
    request.connection_count !== opened.selection.connection_count ||
    !same(request.old, opened.selection.selected_wire?.old)
  )
    return false;
  const c = v.compilation;
  if (basis === "archive") {
    if (!(await compilation(c, v.output_sha256, request, opened.selection)))
      return false;
  } else {
    if (
      request.effective_record_sha256 !== opened.selection.record_sha256 ||
      request.effective_sha256 !== opened.effective_sha256 ||
      v.effective_sha256 !== opened.effective_sha256 ||
      !same(v.parameter_merge, opened.parameter_merge) ||
      !c ||
      c.profile !== effectiveProfile ||
      typeof c.scope !== "string" ||
      !same(c.files, source.files) ||
      !same(c.parameter_merge, opened.parameter_merge) ||
      c.archive_sha256 !== source.sha256 ||
      c.effective_sha256 !== request.effective_sha256 ||
      c.compiled_sha256 !== v.output_sha256 ||
      c.compiled_native_sha256 !== c.connection_removal?.output_native_sha256 ||
      !integer(c.native_record_count, 20000) ||
      c.native_record_count <= opened.selection.block_count ||
      c.other_merged_bytes_preserved !== true ||
      c.saved_settings_merged !== true ||
      c.controller_write !== false ||
      c.field_transfer_enabled !== false ||
      !hash(c.compilation_sha256) ||
      c.connection_removal?.source_native_sha256 !==
        opened.parameter_merge.native_output_sha256 ||
      !(await compilation(
        c.connection_removal,
        v.output_sha256,
        {
          ...request,
          source_sha256: request.effective_sha256,
          record_sha256: request.effective_record_sha256,
        },
        opened.selection,
      ))
    )
      return false;
    const { compilation_sha256, ...body } = c;
    if ((await connectionSeal(body)) !== compilation_sha256) return false;
  }
  const { review_sha256, ...body } = v;
  return (await connectionSeal(body)) === review_sha256;
}
