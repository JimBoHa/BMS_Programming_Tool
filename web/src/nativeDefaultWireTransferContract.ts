import { connectionSame as same } from "./nativeConnectionContract";
import {
  defaultWireReview,
  defaultWireProfile,
} from "./nativeDefaultWireContract";

type Data = Record<string, any>;
export const defaultWireTransferProfile =
  "native-effective-default-wire-transfer/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const qualified = (c: Data) =>
  c?.parameter_transfer_qualification?.profile ===
    "native-omitted-application-field-types/1" &&
  c.parameter_transfer_qualification.model_inventory_used === false &&
  Number.isSafeInteger(c.parameter_transfer_qualification.qualified_fields) &&
  c.parameter_transfer_qualification.qualified_fields >= 0 &&
  c.parameter_transfer_qualification.qualified_fields <= 20000;
function guardMatches(guard: Data, edit: Data, bits: string) {
  const wire = guard?.wire_guard;
  return (
    guard?.profile === "native-default-wire-configuration-guard/1" &&
    guard.record_ref === edit.record_ref &&
    guard.encoded_sha256 === edit.encoded_sha256 &&
    guard.prior_bits === bits &&
    /^[a-f0-9]{8}$/.test(bits) &&
    wire?.profile === "native-wire-source-configuration-guard/1" &&
    wire.diagram_ref === edit.diagram_ref &&
    wire.wire_index === edit.wire_index &&
    wire.source_ref === edit.source_ref &&
    same(wire.old, edit.old) &&
    hash(wire.configuration_sha256)
  );
}
export function defaultWireTransferReviewMatches(
  data: Data,
  source: Data,
  proposal: Data,
  field: Data,
  opened: Data,
  selected: Data,
) {
  const c = data.compilation,
    guard = data.combined_guard;
  const device = Number(source.device.split(",")[1]);
  if (
    data.operation_profile !== defaultWireTransferProfile ||
    data.change_kind !== "default-wire" ||
    !same(data.combined_edit, proposal) ||
    !same(data.identity, source.identity) ||
    data.default_edit !== undefined ||
    data.wire_edit !== undefined ||
    data.old_instance !== device ||
    data.new_instance !== device ||
    data.old_name !== source.identity["object-name"] ||
    data.new_name !== data.old_name ||
    data.application_sha256 !== opened.source_sha256 ||
    data.static_parameters_sha256 !== opened.files["11"].sha256 ||
    data.vendor_runtime_required !== false ||
    !qualified(c) ||
    !guardMatches(guard, proposal, field.effective_bits) ||
    !same(c?.combined_guard, guard) ||
    !(c?.selected_default?.changed || c?.selected_wire?.changed)
  )
    return false;
  // Check the actual field envelope above. Reuse only the local compilation
  // validator below; this projection does not grant a local result field authority.
  return defaultWireReview(
    {
      ...opened,
      request: proposal,
      compilation: c,
      output_sha256: data.payload_sha256,
      review_sha256: data.review_sha256,
    },
    source,
    opened,
    selected,
    proposal,
    field,
  );
}

function realBits(text: unknown) {
  if (
    typeof text !== "string" ||
    !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(
      text.trim(),
    )
  )
    return null;
  const value = Number(text),
    view = new DataView(new ArrayBuffer(4));
  view.setFloat32(0, value, false);
  if (
    !Number.isFinite(value) ||
    !Number.isFinite(view.getFloat32(0, false)) ||
    (view.getFloat32(0, false) === 0 &&
      text.split(/[eE]/)[0].replace(/[+\-.0\s]/g, "") !== "")
  )
    return null;
  return view.getUint32(0, false).toString(16).padStart(8, "0");
}
function editShape(edit: Data) {
  if (
    !edit ||
    !/^[a-f0-9]{32}$/.test(edit.capture_id ?? "") ||
    ![
      "snapshot_sha256",
      "source_sha256",
      "record_sha256",
      "property_sha256",
      "effective_sha256",
      "effective_record_sha256",
      "encoded_sha256",
    ].every((k) => hash(edit[k])) ||
    !["diagram_ref", "record_ref", "source_ref"].every(
      (k) =>
        typeof edit[k] === "string" &&
        edit[k].length > 0 &&
        edit[k].length <= 512,
    ) ||
    !Number.isInteger(edit.wire_index) ||
    edit.wire_index < 0 ||
    edit.wire_index > 4095 ||
    !Array.isArray(edit.old) ||
    edit.old.length !== 4 ||
    !edit.old.every(
      (v: unknown) =>
        Number.isInteger(v) && (v as number) >= 0 && (v as number) <= 65535,
    ) ||
    typeof edit.value_text !== "string" ||
    edit.value_text.length > 128 ||
    !realBits(edit.value_text)
  )
    return false;
  return (
    Object.keys(edit).sort().join() ===
    [
      "capture_id",
      "snapshot_sha256",
      "source_sha256",
      "diagram_ref",
      "record_sha256",
      "wire_index",
      "property_sha256",
      "old",
      "source_ref",
      "effective_sha256",
      "effective_record_sha256",
      "record_ref",
      "encoded_sha256",
      "value_text",
    ]
      .sort()
      .join()
  );
}
export function defaultWireTransferReceiptMatches(
  data: Data,
  reference?: Data,
) {
  const intent = data.intent;
  if (!intent)
    return (
      data.pending === false &&
      data.result?.status === "not_sent" &&
      data.result.may_have_applied === false &&
      data.result.protocol_accepted === false
    );
  const edit = intent.combined_edit,
    c = intent.compilation;
  const real = c?.selected_default,
    wire = c?.selected_wire;
  if (
    intent.change_kind !== "default-wire" ||
    intent.operation_profile !== defaultWireTransferProfile ||
    !editShape(edit) ||
    !c ||
    c.profile !== defaultWireProfile ||
    !qualified(c) ||
    !real ||
    !wire ||
    intent.identity?.["vendor-identifier"] !== 5 ||
    intent.old_instance !==
      Number(String(intent.identity?.device).split(",")[1]) ||
    intent.new_instance !== intent.old_instance ||
    intent.old_name !== intent.identity?.["object-name"] ||
    intent.new_name !== intent.old_name ||
    [
      "default_change_confirmed",
      "wire_change_confirmed",
      "application_transfer_confirmed",
    ].some((k) => intent[k] !== true) ||
    !hash(intent.payload_sha256) ||
    !hash(intent.native_payload_sha256) ||
    c.compiled_sha256 !== intent.payload_sha256 ||
    c.compiled_native_sha256 !== intent.native_payload_sha256 ||
    c.other_merged_bytes_preserved !== true ||
    c.both_orders_identical !== true ||
    c.disjoint_fields !== true ||
    c.saved_settings_merged !== true ||
    c.controller_write !== false ||
    c.field_transfer_enabled !== false ||
    real.record_ref !== edit.record_ref ||
    real.encoded_sha256 !== edit.encoded_sha256 ||
    ![526, 527].includes(real.class_id) ||
    real.property !== 3113 ||
    real.value_text !== edit.value_text ||
    real.after_bits !== realBits(edit.value_text) ||
    !guardMatches(intent.combined_guard, edit, real.before_bits) ||
    !same(c.combined_guard, intent.combined_guard) ||
    wire.diagram_ref !== edit.diagram_ref ||
    wire.wire_index !== edit.wire_index ||
    wire.source_ref !== edit.source_ref ||
    !same(wire.old, edit.old) ||
    !Array.isArray(wire.new) ||
    wire.new.length !== 4 ||
    !wire.new.every(
      (v: unknown) =>
        Number.isInteger(v) && (v as number) >= 0 && (v as number) <= 65535,
    ) ||
    !same(wire.new.slice(1), edit.old.slice(1)) ||
    !(real.changed || wire.changed) ||
    real.source_sha256 !== c.effective_sha256 ||
    wire.source_sha256 !== c.effective_sha256 ||
    c.parameter_merge?.output_sha256 !== c.effective_sha256 ||
    c.parameter_merge?.static_sha256 !== c.files?.["11"]?.sha256 ||
    c.parameter_merge?.dynamic_sha256 !== c.files?.["12"]?.sha256
  )
    return false;
  if (
    reference &&
    (!same(edit, reference.combined_edit) ||
      !same(intent.combined_guard, reference.combined_guard) ||
      intent.review_sha256 !== reference.review_sha256)
  )
    return false;
  const observed =
    data.latest_readback ||
    data.events?.filter((e: Data) => e.stage === "readback").at(-1)?.detail ||
    data.result;
  if (observed?.status === "not_sent")
    return (
      data.pending === false &&
      observed.may_have_applied === false &&
      observed.protocol_accepted === false
    );
  if (observed?.status === "unknown") return data.pending === true;
  if (observed?.status === "recovered_original")
    return (
      data.pending === false &&
      observed.operational === true &&
      observed.system_status === 0 &&
      observed.proposed_change_verified === false &&
      observed.recovery?.profile === "native-original-application-readback/1" &&
      observed.recovery.original_backup_id === intent.backup_id &&
      observed.recovery.original_reviewed_native_sha256 ===
        intent.native_payload_sha256 &&
      observed.preservation?.profile === "native-application-preservation/1" &&
      observed.preservation.application_identical_except_instance === true
    );
  if (observed?.status !== "verified") return false;
  const proof = observed.preservation;
  return (
    data.pending === false &&
    observed.operational === true &&
    observed.system_status === 0 &&
    observed.native_sha256 === intent.native_payload_sha256 &&
    proof?.profile === "native-effective-default-wire-preservation/1" &&
    proof.application_identical_except_selected_default_and_wire === true &&
    proof.identity_unchanged === true &&
    proof.selected_default?.record_ref === edit.record_ref &&
    proof.selected_default.before_bits === real.before_bits &&
    proof.selected_default.after_bits === real.after_bits &&
    proof.selected_default.effective_bits === real.after_bits &&
    proof.selected_wire?.diagram_ref === edit.diagram_ref &&
    proof.selected_wire.wire_index === edit.wire_index &&
    proof.selected_wire.source_ref === edit.source_ref &&
    proof.selected_wire.target_ref === wire.target_ref &&
    same(proof.selected_wire.old, edit.old) &&
    same(proof.selected_wire.new, wire.new) &&
    proof.selected_wire.effective_connection_verified === true
  );
}
