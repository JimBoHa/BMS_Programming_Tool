import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";

export const ENUM_EFFECTIVE_PROFILE =
  "native-effective-enum-default-compiler/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, maximum = 4294967295) =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= maximum;
export type EnumArchiveField = {
  ref: string;
  class_id: number;
  encoded_sha256: string;
  value: number;
};

function filesMatch(files: any, source: NativeArchiveSource) {
  return (["3", "11", "12"] as const).every(
    (key) =>
      files?.[key]?.sha256 === source.files[key].sha256 &&
      files[key].bytes === source.files[key].bytes,
  );
}
function envelope(data: any, source: NativeArchiveSource) {
  return (
    data?.profile === ENUM_EFFECTIVE_PROFILE &&
    data.capture_id === source.capture_id &&
    data.snapshot_sha256 === source.snapshot_sha256 &&
    data.source_sha256 === source.sha256 &&
    data.parameter_merge?.source_sha256 === source.sha256 &&
    data.parameter_merge?.output_sha256 === data.effective_sha256 &&
    data.parameter_merge?.static_sha256 === source.files["11"].sha256 &&
    data.parameter_merge?.dynamic_sha256 === source.files["12"].sha256 &&
    hash(data.effective_sha256) &&
    controllerKey(data.target ?? {}) === controllerKey(source.target) &&
    filesMatch(data.files, source) &&
    data.source_identity_matches === true &&
    data.identity?.["vendor-identifier"] === 5 &&
    data.device === source.target.device &&
    data.source_immutable === true &&
    data.saved_settings_merged === true &&
    data.enum_semantics_verified === false &&
    data.current_identity_verified === false &&
    data.controller_queries === false &&
    data.controller_write === false &&
    data.field_transfer_enabled === false
  );
}
function storageValid(field: any, source: NativeArchiveSource) {
  const slot = field.saved_storage;
  if (slot === null) return field.maximum_code === 4294967295;
  return (
    !!slot &&
    Object.keys(slot).sort().join(",") ===
      "bytes,datatype,dynamic_value_offset,kind,maximum_code,static_record_offset" &&
    slot.kind === "captured-fixed-enum-slot" &&
    slot.datatype === 9 &&
    slot.bytes === 2 &&
    slot.maximum_code === 65535 &&
    field.maximum_code === slot.maximum_code &&
    integer(slot.static_record_offset) &&
    slot.static_record_offset + 16 <= source.files["11"].bytes &&
    integer(slot.dynamic_value_offset) &&
    slot.dynamic_value_offset + 3 <= source.files["12"].bytes
  );
}
export function effectiveEnumSource(
  data: any,
  source: NativeArchiveSource,
  field: EnumArchiveField,
) {
  const matches = Array.isArray(data?.fields)
    ? data.fields.filter((row: any) => row?.ref === field.ref)
    : [];
  const selected = matches[0];
  if (
    !envelope(data, source) ||
    !Array.isArray(data.fields) ||
    data.fields.length > 4096 ||
    matches.length !== 1 ||
    selected.class_id !== field.class_id ||
    ![528, 529].includes(selected.class_id) ||
    selected.property !== 3113 ||
    selected.datatype !== "Enumerated" ||
    selected.archive_value !== field.value ||
    !hash(selected.encoded_sha256) ||
    !storageValid(selected, source) ||
    !integer(selected.effective_value, selected.maximum_code) ||
    selected.saved_value_differs !==
      (selected.encoded_sha256 !== field.encoded_sha256) ||
    selected.enum_semantics_verified !== false ||
    !(
      selected.states_text_encoded_sha256 === null ||
      hash(selected.states_text_encoded_sha256)
    )
  )
    throw new Error(
      "Effective Enum source differs from the selected original field or captured storage. Inspect this backup again.",
    );
  return selected;
}
export function checkEffectiveEnumReview(
  data: any,
  source: NativeArchiveSource,
  selected: any,
  loaded: any,
  request: Record<string, unknown>,
) {
  const edit = data?.edit,
    compiled = data?.compilation;
  if (
    !envelope(data, source) ||
    data.effective_sha256 !== loaded.effective_sha256 ||
    !hash(data.review_sha256) ||
    !hash(data.output_sha256) ||
    !data.request ||
    Object.keys(data.request).length !== Object.keys(request).length ||
    !Object.entries(request).every(
      ([key, value]) => data.request[key] === value,
    ) ||
    data.archive_value !== selected.archive_value ||
    edit?.profile !== "tagged-moi-enum-default-copy/1" ||
    edit.source_sha256 !== loaded.effective_sha256 ||
    edit.record_ref !== selected.ref ||
    edit.class_id !== selected.class_id ||
    edit.property !== 3113 ||
    edit.datatype !== "Enumerated" ||
    edit.encoded_sha256 !== selected.encoded_sha256 ||
    edit.before_value !== selected.effective_value ||
    edit.after_value !== request.value ||
    edit.changed !== (selected.effective_value !== request.value) ||
    edit.enum_semantics_verified !== false ||
    edit.controller_write !== false ||
    edit.saved_settings_merged !== false ||
    edit.unrelated_native_bytes_preserved !== true ||
    !hash(edit.plan_sha256) ||
    edit.output_sha256 !== data.output_sha256 ||
    compiled?.profile !== ENUM_EFFECTIVE_PROFILE ||
    compiled.compiled_sha256 !== data.output_sha256 ||
    !hash(compiled.compiled_native_sha256) ||
    !filesMatch(compiled.files, source) ||
    compiled.saved_settings_merged !== true ||
    compiled.other_merged_bytes_preserved !== true ||
    compiled.enum_semantics_verified !== false ||
    compiled.controller_write !== false ||
    compiled.field_transfer_enabled !== false ||
    compiled.maximum_code !== selected.maximum_code ||
    JSON.stringify(compiled.selected_edit) !== JSON.stringify(edit) ||
    JSON.stringify(compiled.saved_storage) !==
      JSON.stringify(selected.saved_storage)
  )
    throw new Error(
      "Effective Enum review differs from this exact merged source, code or storage. Review the current proposal again.",
    );
}
