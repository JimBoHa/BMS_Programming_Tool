type Data = Record<string, any>;
const hash = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const tuple = (a: unknown, b: unknown) =>
  Array.isArray(a) &&
  Array.isArray(b) &&
  a.length === 4 &&
  b.length === 4 &&
  a.every((v, i) => Number.isInteger(v) && v === b[i]);

export function wireTransferReviewMatches(
  data: Data,
  source: Data,
  proposal: Data,
  field: Data,
) {
  const compilation = data.compilation,
    edit = compilation?.wire_edit,
    guard = data.wire_guard;
  const device = Number(String(source.device).split(",")[1]);
  if (
    !data.wire_edit ||
    Object.keys(data.wire_edit).sort().join() !==
      Object.keys(proposal).sort().join() ||
    Object.entries(proposal).some(([key, value]) =>
      key === "old"
        ? !tuple(data.wire_edit[key], value)
        : data.wire_edit[key] !== value,
    )
  )
    return false;
  return (
    data.default_edit === undefined &&
    data.old_instance === device &&
    data.new_instance === device &&
    data.old_name === data.identity?.["object-name"] &&
    data.new_name === data.old_name &&
    data.application_sha256 === proposal.source_sha256 &&
    data.static_parameters_sha256 === source.files?.["11"]?.sha256 &&
    compilation?.profile === "native-effective-wire-source-compiler/1" &&
    compilation.archive_sha256 === proposal.source_sha256 &&
    compilation.effective_sha256 === proposal.effective_sha256 &&
    compilation.saved_settings_merged === true &&
    compilation.other_merged_bytes_preserved === true &&
    compilation.controller_write === false &&
    compilation.field_transfer_enabled === false &&
    ["3", "11", "12"].every(
      (key) =>
        compilation.files?.[key]?.sha256 === source.files?.[key]?.sha256 &&
        compilation.files?.[key]?.bytes === source.files?.[key]?.bytes,
    ) &&
    compilation.parameter_merge?.static_sha256 ===
      source.files?.["11"]?.sha256 &&
    compilation.parameter_merge?.dynamic_sha256 ===
      source.files?.["12"]?.sha256 &&
    compilation.parameter_merge?.output_sha256 === proposal.effective_sha256 &&
    edit?.profile === "tagged-moi-wire-source-copy/1" &&
    edit.changed === true &&
    edit.source_sha256 === proposal.effective_sha256 &&
    edit.diagram_ref === proposal.diagram_ref &&
    edit.record_sha256 === proposal.effective_record_sha256 &&
    edit.property_sha256 === proposal.property_sha256 &&
    edit.wire_index === proposal.wire_index &&
    edit.wire_index === field.wire_index &&
    tuple(edit.old, proposal.old) &&
    tuple(edit.old, field.old) &&
    tuple(edit.new, [field.source_index, ...field.old.slice(1)]) &&
    edit.source_ref === proposal.source_ref &&
    edit.old_source_ref === field.old_source_ref &&
    edit.target_ref === field.target_ref &&
    edit.source_class === field.source_class &&
    edit.other_expanded_bytes_preserved === true &&
    edit.native_structure_readback_verified === true &&
    edit.saved_settings_merged === false &&
    edit.controller_write === false &&
    edit.field_transfer_enabled === false &&
    hash(edit.output_sha256) &&
    edit.output_sha256 === compilation.compiled_sha256 &&
    data.payload_sha256 === edit.output_sha256 &&
    hash(edit.output_native_sha256) &&
    edit.output_native_sha256 === compilation.compiled_native_sha256 &&
    guard?.profile === "native-wire-source-configuration-guard/1" &&
    guard.diagram_ref === proposal.diagram_ref &&
    guard.wire_index === proposal.wire_index &&
    guard.source_ref === proposal.source_ref &&
    tuple(guard.old, proposal.old) &&
    hash(guard.configuration_sha256) &&
    compilation.wire_guard?.configuration_sha256 ===
      guard.configuration_sha256 &&
    compilation.wire_guard?.diagram_ref === guard.diagram_ref &&
    compilation.wire_guard?.wire_index === guard.wire_index &&
    compilation.wire_guard?.source_ref === guard.source_ref &&
    tuple(compilation.wire_guard?.old, guard.old)
  );
}

export function wireTransferReceiptMatches(data: Data, reference?: Data) {
  const intent = data.intent;
  if (!intent)
    return (
      data.pending === false &&
      data.result?.status === "not_sent" &&
      data.result.may_have_applied === false &&
      data.result.protocol_accepted === false
    );
  const edit = intent.wire_edit,
    compiled = intent.compilation?.wire_edit;
  if (
    intent.change_kind !== "wire-source" ||
    intent.operation_profile !== "native-effective-wire-source-transfer/1" ||
    !edit ||
    !compiled ||
    intent.wire_change_confirmed !== true ||
    intent.application_transfer_confirmed !== true ||
    !hash(intent.native_payload_sha256) ||
    !hash(intent.payload_sha256) ||
    intent.payload_sha256 !== intent.compilation.compiled_sha256 ||
    intent.native_payload_sha256 !==
      intent.compilation.compiled_native_sha256 ||
    compiled.diagram_ref !== edit.diagram_ref ||
    compiled.wire_index !== edit.wire_index ||
    compiled.source_ref !== edit.source_ref ||
    !tuple(compiled.old, edit.old) ||
    compiled.changed !== true ||
    !hash(intent.wire_guard?.configuration_sha256)
  )
    return false;
  if (reference) {
    const wanted = reference.wire_edit;
    if (
      !wanted ||
      Object.keys(edit).sort().join() !== Object.keys(wanted).sort().join() ||
      Object.entries(wanted).some(([key, value]) =>
        key === "old" ? !tuple(edit[key], value) : edit[key] !== value,
      ) ||
      intent.review_sha256 !== reference.review_sha256 ||
      intent.wire_guard.configuration_sha256 !==
        reference.wire_guard?.configuration_sha256
    )
      return false;
  }
  const observed =
    data.latest_readback ||
    data.events?.filter((row: Data) => row.stage === "readback").at(-1)
      ?.detail ||
    data.result;
  if (observed?.status !== "verified") return true;
  const proof = observed.preservation,
    wire = proof?.selected_wire;
  return (
    data.pending === false &&
    observed.operational === true &&
    observed.system_status === 0 &&
    observed.native_sha256 === intent.native_payload_sha256 &&
    proof?.profile === "native-effective-wire-source-preservation/1" &&
    proof.application_identical_except_selected_wire === true &&
    proof.identity_unchanged === true &&
    wire?.diagram_ref === edit.diagram_ref &&
    wire.wire_index === edit.wire_index &&
    wire.source_ref === edit.source_ref &&
    tuple(wire.old, edit.old) &&
    tuple(wire.new, compiled.new) &&
    wire.effective_connection_verified === true
  );
}
