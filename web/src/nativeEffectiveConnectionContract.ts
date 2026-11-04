import type { NativeArchiveSource } from "./NativeRecords";
import {
  connectionEnvelope,
  connectionSelection,
  connectionCompilation,
  connectionSame,
  connectionSeal,
  effectiveConnectionProfile,
} from "./nativeConnectionContract";

type Data = Record<string, any>;
export const effectiveConnectionBase =
  "/bacnet/controller/native-application/inspection/effective-connection-copy";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
function envelope(value: Data, source: NativeArchiveSource, request: Data) {
  const p = value?.parameter_merge;
  return (
    connectionEnvelope(value, source, "effective") &&
    value.source_immutable === true &&
    value.current_identity_verified === false &&
    value.controller_write === false &&
    hash(value.effective_sha256) &&
    value.archive_record_sha256 === request.record_sha256 &&
    !!p &&
    p.source_sha256 === source.sha256 &&
    p.output_sha256 === value.effective_sha256 &&
    p.static_sha256 === source.files["11"].sha256 &&
    p.dynamic_sha256 === source.files["12"].sha256 &&
    hash(p.native_output_sha256) &&
    Number.isInteger(p.matched_parameters) &&
    p.matched_parameters >= 0 &&
    p.matched_parameters <= 20000 &&
    Array.isArray(p.changed_parameters) &&
    p.changed_parameters.length <= p.matched_parameters &&
    Array.isArray(p.retained_runtime_parameters) &&
    p.retained_runtime_parameters.length <= 20000 &&
    p.vendor_runtime_required === false
  );
}
export function effectiveConnectionSource(
  value: Data,
  source: NativeArchiveSource,
  request: Data,
) {
  return (
    envelope(value, source, request) &&
    hash(value.selection?.record_sha256) &&
    connectionSelection(value.selection, {
      ...request,
      record_sha256: value.selection.record_sha256,
    })
  );
}
export async function effectiveConnectionReview(
  value: Data,
  source: NativeArchiveSource,
  request: Data,
  opened: Data,
) {
  const c = value?.compilation;
  if (
    !envelope(value, source, request) ||
    !connectionSame(value.request, request) ||
    !hash(value.review_sha256) ||
    !hash(value.output_sha256) ||
    value.effective_sha256 !== request.effective_sha256 ||
    value.effective_sha256 !== opened.effective_sha256 ||
    !connectionSame(value.parameter_merge, opened.parameter_merge) ||
    !c ||
    c.profile !== effectiveConnectionProfile ||
    typeof c.scope !== "string" ||
    !connectionSame(c.files, source.files) ||
    !connectionSame(c.parameter_merge, opened.parameter_merge) ||
    c.archive_sha256 !== source.sha256 ||
    c.effective_sha256 !== request.effective_sha256 ||
    c.compiled_sha256 !== value.output_sha256 ||
    c.compiled_native_sha256 !== c.connection_edit?.output_native_sha256 ||
    !Number.isInteger(c.native_record_count) ||
    c.native_record_count <= opened.selection.block_count ||
    c.native_record_count > 20000 ||
    c.other_merged_bytes_preserved !== true ||
    c.saved_settings_merged !== true ||
    c.controller_write !== false ||
    c.field_transfer_enabled !== false ||
    !hash(c.compilation_sha256) ||
    c.connection_edit?.source_native_sha256 !==
      opened.parameter_merge.native_output_sha256 ||
    !(await connectionCompilation(
      c.connection_edit,
      value.output_sha256,
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
  return (await connectionSeal(body)) === compilation_sha256;
}
