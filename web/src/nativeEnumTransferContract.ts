type Data = Record<string, any>;
export const enumTransferProfile = "native-effective-enum-default-transfer/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const code = (v: unknown) =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 65535;
const same = (a: Data | undefined, b: Data | undefined) =>
  !!a &&
  !!b &&
  Object.keys(a).length === Object.keys(b).length &&
  Object.entries(a).every(
    ([key, value]) => Object.hasOwn(b, key) && b[key] === value,
  );
function selection(edit: Data | undefined) {
  return (
    !!edit &&
    Object.keys(edit).sort().join() === "encoded_sha256,record_ref,value" &&
    typeof edit.record_ref === "string" &&
    edit.record_ref.length > 0 &&
    edit.record_ref.length <= 512 &&
    hash(edit.encoded_sha256) &&
    code(edit.value)
  );
}
function tagged(value: unknown, expected: number) {
  if (
    typeof value !== "string" ||
    !/^9[1-4](?:[a-f0-9]{2}){1,4}2f$/.test(value)
  )
    return false;
  const width = Number(value[1]);
  return (
    value.length === (width + 2) * 2 &&
    parseInt(value.slice(2, -2), 16) === expected
  );
}
function compilationMatches(compiled: Data | undefined, edit: Data) {
  const selected = compiled?.selected_edit,
    storage = compiled?.saved_storage,
    merge = compiled?.parameter_merge;
  return (
    !!compiled &&
    selection(edit) &&
    compiled.profile === "native-effective-enum-default-compiler/1" &&
    compiled.saved_settings_merged === true &&
    compiled.other_merged_bytes_preserved === true &&
    compiled.enum_semantics_verified === false &&
    compiled.controller_write === false &&
    compiled.field_transfer_enabled === false &&
    compiled.maximum_code === 65535 &&
    !!storage &&
    Object.keys(storage).sort().join() ===
      "bytes,datatype,dynamic_value_offset,kind,maximum_code,static_record_offset" &&
    storage.kind === "captured-fixed-enum-slot" &&
    storage.datatype === 9 &&
    storage.bytes === 2 &&
    storage.maximum_code === 65535 &&
    Number.isSafeInteger(storage.static_record_offset) &&
    storage.static_record_offset >= 0 &&
    Number.isSafeInteger(storage.dynamic_value_offset) &&
    storage.dynamic_value_offset >= 0 &&
    storage.static_record_offset + 16 <= compiled.files?.["11"]?.bytes &&
    storage.dynamic_value_offset + 3 <= compiled.files?.["12"]?.bytes &&
    ["3", "11", "12"].every(
      (key) =>
        hash(compiled.files?.[key]?.sha256) &&
        Number.isSafeInteger(compiled.files[key].bytes) &&
        compiled.files[key].bytes >= 0,
    ) &&
    merge?.source_sha256 === compiled.files["3"].sha256 &&
    merge.static_sha256 === compiled.files["11"].sha256 &&
    merge.dynamic_sha256 === compiled.files["12"].sha256 &&
    hash(merge.output_sha256) &&
    compiled.parameter_transfer_qualification?.profile ===
      "native-omitted-application-field-types/1" &&
    compiled.parameter_transfer_qualification.model_inventory_used === false &&
    Number.isSafeInteger(
      compiled.parameter_transfer_qualification.qualified_fields,
    ) &&
    compiled.parameter_transfer_qualification.qualified_fields >= 0 &&
    selected?.profile === "tagged-moi-enum-default-copy/1" &&
    selected.source_sha256 === merge.output_sha256 &&
    selected.record_ref === edit.record_ref &&
    selected.encoded_sha256 === edit.encoded_sha256 &&
    [528, 529].includes(selected.class_id) &&
    selected.property === 3113 &&
    selected.datatype === "Enumerated" &&
    code(selected.before_value) &&
    selected.after_value === edit.value &&
    selected.changed === true &&
    selected.before_value !== selected.after_value &&
    tagged(selected.before_encoding_hex, selected.before_value) &&
    tagged(selected.after_encoding_hex, selected.after_value) &&
    selected.before_value_width === Number(selected.before_encoding_hex[1]) &&
    selected.after_value_width === Number(selected.after_encoding_hex[1]) &&
    selected.after_value_width >= selected.before_value_width &&
    selected.enum_semantics_verified === false &&
    selected.controller_write === false &&
    selected.saved_settings_merged === false &&
    selected.unrelated_native_bytes_preserved === true &&
    hash(selected.plan_sha256) &&
    hash(compiled.compiled_sha256) &&
    selected.output_sha256 === compiled.compiled_sha256 &&
    hash(compiled.compiled_native_sha256)
  );
}
export function enumTransferReviewMatches(
  data: Data,
  source: Data,
  proposal: Data,
  field: Data,
) {
  const edit = data.default_edit,
    compiled = data.compilation;
  return (
    compilationMatches(compiled, edit) &&
    data.enum_semantics_verified === false &&
    data.identity?.device === source.device &&
    [
      "vendor-identifier",
      "object-name",
      "model-name",
      "firmware-revision",
      "application-software-version",
    ].every((key) => data.identity?.[key] === source.identity?.[key]) &&
    data.identity["vendor-identifier"] === 5 &&
    data.application_sha256 === proposal.source_sha256 &&
    data.application_sha256 === source.source_sha256 &&
    data.static_parameters_sha256 === source.files?.["11"]?.sha256 &&
    ["3", "11", "12"].every(
      (key) =>
        compiled.files[key].sha256 === source.files?.[key]?.sha256 &&
        compiled.files[key].bytes === source.files?.[key]?.bytes,
    ) &&
    compiled.parameter_merge.output_sha256 === source.effective_sha256 &&
    compiled.selected_edit.class_id === field.class_id &&
    compiled.selected_edit.before_value === field.effective_value &&
    edit.record_ref === field.ref &&
    edit.record_ref === proposal.record_ref &&
    edit.value === proposal.value &&
    edit.encoded_sha256 === proposal.encoded_sha256 &&
    same(compiled.saved_storage, field.saved_storage) &&
    data.payload_sha256 === compiled.compiled_sha256 &&
    data.old_instance === Number(String(source.device).split(",")[1]) &&
    data.new_instance === data.old_instance &&
    data.old_name === source.identity?.["object-name"] &&
    data.new_name === data.old_name &&
    data.wire_edit === undefined &&
    data.recovery_origin === undefined &&
    data.recovery_origin_sha256 === undefined
  );
}
export function enumTransferReceiptMatches(data: Data, reference?: Data) {
  const intent = data.intent;
  if (!intent)
    return (
      data.pending === false &&
      data.result?.status === "not_sent" &&
      data.result.may_have_applied === false &&
      data.result.protocol_accepted === false
    );
  const edit = intent.default_edit,
    compiled = intent.compilation;
  if (
    intent.change_kind !== "enum-default" ||
    intent.operation_profile !== enumTransferProfile ||
    intent.enum_semantics_verified !== false ||
    intent.identity?.["vendor-identifier"] !== 5 ||
    intent.old_instance !==
      Number(String(intent.identity?.device).split(",")[1]) ||
    intent.new_instance !== intent.old_instance ||
    intent.old_name !== intent.identity?.["object-name"] ||
    intent.new_name !== intent.old_name ||
    !compilationMatches(compiled, edit) ||
    intent.default_change_confirmed !== true ||
    intent.application_transfer_confirmed !== true ||
    intent.payload_sha256 !== compiled.compiled_sha256 ||
    intent.native_payload_sha256 !== compiled.compiled_native_sha256 ||
    !hash(intent.review_sha256) ||
    intent.recovery_origin !== undefined ||
    intent.recovery_origin_sha256 !== undefined
  )
    return false;
  if (
    reference &&
    (!same(edit, reference.default_edit) ||
      intent.review_sha256 !== reference.review_sha256 ||
      intent.review_capture_id !==
        (reference.capture_id ?? reference.review_capture_id) ||
      !["3", "11"].every(
        (key) =>
          compiled.files[key].sha256 ===
            reference.compilation?.files?.[key]?.sha256 &&
          compiled.files[key].bytes ===
            reference.compilation?.files?.[key]?.bytes,
      ) ||
      compiled.selected_edit.before_value !==
        reference.compilation?.selected_edit?.before_value ||
      compiled.selected_edit.class_id !==
        reference.compilation?.selected_edit?.class_id ||
      !same(compiled.saved_storage, reference.compilation?.saved_storage))
  )
    return false;
  const observed =
    data.latest_readback ||
    data.events?.filter((row: Data) => row.stage === "readback").at(-1)
      ?.detail ||
    data.result;
  if (observed?.status !== "verified") return true;
  const proof = observed.preservation,
    selected = proof?.selected_default;
  return (
    data.pending === false &&
    observed.operational === true &&
    observed.system_status === 0 &&
    observed.native_sha256 === intent.native_payload_sha256 &&
    proof?.profile === "native-effective-enum-default-preservation/1" &&
    proof.application_identical_except_selected_default === true &&
    proof.identity_unchanged === true &&
    proof.enum_semantics_verified === false &&
    proof.controller_writes === false &&
    selected?.record_ref === edit.record_ref &&
    selected.before_value === compiled.selected_edit.before_value &&
    selected.after_value === edit.value &&
    selected.effective_value === edit.value &&
    selected.equal_typed_code === true &&
    hash(selected.archive_encoding_sha256) &&
    hash(selected.saved_encoding_sha256)
  );
}
