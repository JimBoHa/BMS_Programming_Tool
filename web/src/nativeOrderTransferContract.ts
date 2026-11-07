import type { NativeArchiveSource } from "./NativeRecords";
import type { ControllerContext } from "./workflow";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { matchingConnectionTarget } from "./nativeMatchingConnectionContract";
import {
  nativeOrderAllowed,
  nativeOrderPermutation,
  nativeOrderProfile,
  nativeOrderScope,
  nativeOrderEditProfile,
  nativeOrderReview,
  nativeOrderSelection,
} from "./nativeExecutionOrderContract";

type Data = Record<string, any>;
export const orderTransferProfile =
  "native-effective-execution-order-transfer/1";
export const orderTransferBase =
  "/bacnet/controller/native-application/execution-order/transfer";
export const orderTransferGuard =
  "native-execution-order-configuration-guard/1";
export const orderTransferTarget = matchingConnectionTarget;
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: any) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const integer = (v: any, max = 20000) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const object = (v: any): v is Data =>
  !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: any, wanted: string[]) =>
  object(v) &&
  Object.keys(v).length === wanted.length &&
  wanted.every((k) => Object.hasOwn(v, k));
const proposalKeys = [
  "capture_id",
  "snapshot_sha256",
  "source_sha256",
  "diagram_ref",
  "record_sha256",
  "effective_sha256",
  "effective_record_sha256",
  "selection_sha256",
  "proposed_order",
];
export function orderTransferProposal(v: any) {
  return (
    keys(v, proposalKeys) &&
    id(v.capture_id) &&
    [
      "snapshot_sha256",
      "source_sha256",
      "record_sha256",
      "effective_sha256",
      "effective_record_sha256",
      "selection_sha256",
    ].every((k) => hash(v[k])) &&
    typeof v.diagram_ref === "string" &&
    v.diagram_ref.length > 0 &&
    [...v.diagram_ref].length <= 512 &&
    Array.isArray(v.proposed_order) &&
    nativeOrderPermutation(v.proposed_order, v.proposed_order.length)
  );
}
async function sealed(v: Data, key: string) {
  const { [key]: digest, ...body } = v;
  return hash(digest) && (await connectionSeal(body)) === digest;
}
async function guardMatches(g: any, proposal: Data, selection: Data) {
  return (
    keys(g, [
      "profile",
      "diagram_ref",
      "original_order",
      "payload_widths",
      "property_sha256",
      "edge_relationships_sha256",
      "configuration_sha256",
    ]) &&
    g.profile === orderTransferGuard &&
    g.diagram_ref === proposal.diagram_ref &&
    same(g.original_order, selection.original_order) &&
    same(
      g.payload_widths,
      selection.slots.map((s: Data) => s.payload_bytes),
    ) &&
    g.property_sha256 === selection.property_sha256 &&
    hash(g.configuration_sha256) &&
    g.edge_relationships_sha256 ===
      (await connectionSeal(selection.edge_relationships))
  );
}
export async function orderTransferCompilation(c: any, proposal: Data) {
  if (
    !keys(c, [
      "profile",
      "scope",
      "files",
      "parameter_merge",
      "archive_sha256",
      "effective_sha256",
      "order_edit",
      "compiled_sha256",
      "compiled_native_sha256",
      "native_record_count",
      "saved_settings_merged",
      "other_merged_bytes_preserved",
      "controller_write",
      "field_transfer_enabled",
      "compilation_sha256",
      "order_guard",
      "parameter_transfer_qualification",
      "order_compilation_sha256",
    ]) ||
    c.profile !== nativeOrderProfile ||
    c.scope !== nativeOrderScope ||
    !keys(c.files, ["3", "11", "12"]) ||
    !["3", "11", "12"].every(
      (k) =>
        keys(c.files[k], ["bytes", "sha256"]) &&
        integer(c.files[k].bytes, 2 * 1024 * 1024) &&
        hash(c.files[k].sha256),
    ) ||
    c.files["3"].bytes === 0 ||
    c.archive_sha256 !== proposal.source_sha256 ||
    c.files["3"].sha256 !== proposal.source_sha256 ||
    !["compiled_sha256", "compiled_native_sha256", "effective_sha256"].every(
      (k) => hash(c[k]),
    ) ||
    !integer(c.native_record_count) ||
    c.saved_settings_merged !== true ||
    c.other_merged_bytes_preserved !== true ||
    c.controller_write !== false ||
    c.field_transfer_enabled !== false
  )
    return false;
  const e = c.order_edit,
    s = e?.selection,
    p = c.parameter_merge;
  if (
    !keys(e, [
      "profile",
      "selection",
      "proposed_order",
      "patches",
      "output_sha256",
      "output_native_sha256",
      "other_expanded_bytes_preserved",
      "native_structure_readback_verified",
      "controller_write",
      "field_transfer_enabled",
      "compilation_sha256",
    ]) ||
    e.profile !== nativeOrderEditProfile ||
    !(await nativeOrderSelection(
      s,
      proposal.diagram_ref,
      s?.diagram_class_id,
    )) ||
    c.native_record_count < s.members.length + 2 ||
    !nativeOrderAllowed(s, proposal.proposed_order) ||
    same(s.original_order, proposal.proposed_order) ||
    !same(e.proposed_order, proposal.proposed_order) ||
    e.output_sha256 !== c.compiled_sha256 ||
    e.output_native_sha256 !== c.compiled_native_sha256 ||
    s.source_sha256 !== c.effective_sha256 ||
    e.output_sha256 === s.source_sha256 ||
    e.output_native_sha256 === s.source_native_sha256 ||
    e.other_expanded_bytes_preserved !== true ||
    e.native_structure_readback_verified !== true ||
    e.controller_write !== false ||
    e.field_transfer_enabled !== false ||
    !(await guardMatches(c.order_guard, proposal, s)) ||
    !object(p) ||
    p.source_sha256 !== proposal.source_sha256 ||
    p.output_sha256 !== c.effective_sha256 ||
    p.native_output_sha256 !== s.source_native_sha256 ||
    p.static_sha256 !== c.files["11"].sha256 ||
    p.dynamic_sha256 !== c.files["12"].sha256 ||
    p.vendor_runtime_required !== false ||
    !integer(p.matched_parameters) ||
    !Array.isArray(p.changed_parameters) ||
    p.changed_parameters.length > p.matched_parameters ||
    !Array.isArray(p.retained_runtime_parameters) ||
    p.retained_runtime_parameters.length > 20000
  )
    return false;
  const patches = s.slots
    .filter(
      (slot: Data, i: number) => slot.index !== proposal.proposed_order[i],
    )
    .map((slot: Data) => ({
      ...slot,
      new_index: proposal.proposed_order[slot.position],
    }));
  const q = c.parameter_transfer_qualification;
  if (
    !same(e.patches, patches) ||
    patches.length === 0 ||
    !keys(q, ["profile", "qualified_fields", "model_inventory_used"]) ||
    q.profile !== "native-omitted-application-field-types/1" ||
    !integer(q.qualified_fields) ||
    q.qualified_fields !==
      p.changed_parameters.filter((v: Data) => v.added).length ||
    q.model_inventory_used !== false
  )
    return false;
  const {
    order_guard: _g,
    parameter_transfer_qualification: _q,
    order_compilation_sha256: _digest,
    ...base
  } = c;
  return (
    (await sealed(e, "compilation_sha256")) &&
    (await sealed(base, "compilation_sha256")) &&
    (await sealed(c, "order_compilation_sha256"))
  );
}
export async function orderTransferReview(
  data: Data,
  source: NativeArchiveSource,
  proposal: Data,
  opened: Data,
  controller: ControllerContext,
) {
  try {
    const c = data.compilation,
      local = data.local_review;
    const { token: _token, review_sha256: _digest, ...body } = data;
    return (
      controller.interfaceOpen === true &&
      controller.ownedCommands === 0 &&
      orderTransferProposal(proposal) &&
      data.profile === "native-application-transfer/1" &&
      data.operation_profile === orderTransferProfile &&
      data.change_kind === "execution-order" &&
      data.can_apply === true &&
      data.vendor_runtime_required === false &&
      data.capture_id === source.capture_id &&
      data.snapshot_sha256 === source.snapshot_sha256 &&
      proposal.capture_id === source.capture_id &&
      proposal.snapshot_sha256 === source.snapshot_sha256 &&
      proposal.source_sha256 === source.sha256 &&
      orderTransferTarget(source.target, controller) &&
      orderTransferTarget(
        { ...data.target, device: data.identity?.device },
        controller,
      ) &&
      same(data.identity, opened.identity) &&
      data.identity["vendor-identifier"] === 5 &&
      integer(data.old_instance, 4194302) &&
      controller.device === `device,${data.old_instance}` &&
      data.new_instance === data.old_instance &&
      data.old_name === data.identity["object-name"] &&
      data.new_name === data.old_name &&
      same(data.connector_config, JSON.parse(controller.interfaceKey)) &&
      data.application_sha256 === source.sha256 &&
      data.static_parameters_sha256 === source.files["11"].sha256 &&
      same(data.order_edit, proposal) &&
      same(data.order_guard, c.order_guard) &&
      [
        "default_edit",
        "wire_edit",
        "input_edit",
        "connection_edit",
        "batch_edit",
        "combined_edit",
        "recovery_origin",
        "recovery_origin_sha256",
      ].every((k) => data[k] === undefined) &&
      /^[A-Za-z0-9_-]{32}$/.test(data.token || "") &&
      hash(data.review_sha256) &&
      typeof data.expires_at === "string" &&
      Number.isFinite(Date.parse(data.expires_at)) &&
      (await orderTransferCompilation(c, proposal)) &&
      same(c.files, source.files) &&
      same(c.parameter_merge, opened.parameter_merge) &&
      c.effective_sha256 === proposal.effective_sha256 &&
      c.effective_sha256 === opened.effective_sha256 &&
      data.payload_sha256 === c.compiled_sha256 &&
      (await nativeOrderReview(
        local,
        source,
        {
          ref: proposal.diagram_ref,
          record_sha256: proposal.record_sha256,
          class_id: opened.selection.diagram_class_id,
        },
        opened,
        proposal,
      )) &&
      same(local.compilation.order_edit, c.order_edit) &&
      local.output_sha256 === c.compiled_sha256 &&
      (await connectionSeal(body)) === data.review_sha256
    );
  } catch {
    return false;
  }
}
export async function orderTransferReceipt(
  data: Data,
  reference?: Data,
): Promise<boolean> {
  try {
    if (!object(data) || typeof data.pending !== "boolean") return false;
    const i = data.intent;
    if (!i)
      return (
        reference?.id === undefined &&
        data.pending === false &&
        data.result?.status === "not_sent" &&
        data.result.may_have_applied === false &&
        data.result.protocol_accepted === false
      );
    const edit = i.order_edit,
      c = i.compilation;
    if (
      !id(i.id) ||
      i.profile !== "native-application-transfer/1" ||
      !(await sealed(i, "evidence_sha256")) ||
      i.change_kind !== "execution-order" ||
      i.operation_profile !== orderTransferProfile ||
      !orderTransferProposal(edit) ||
      !(await orderTransferCompilation(c, edit)) ||
      !same(i.order_guard, c.order_guard) ||
      i.order_change_confirmed !== true ||
      i.application_transfer_confirmed !== true ||
      !id(i.review_capture_id) ||
      i.review_capture_id !== edit.capture_id ||
      i.review_snapshot_sha256 !== edit.snapshot_sha256 ||
      !id(i.backup_id) ||
      !hash(i.review_sha256) ||
      i.payload_sha256 !== c.compiled_sha256 ||
      i.native_payload_sha256 !== c.compiled_native_sha256 ||
      !integer(i.old_instance, 4194302) ||
      i.new_instance !== i.old_instance ||
      i.identity?.device !== `device,${i.old_instance}` ||
      i.identity["vendor-identifier"] !== 5 ||
      i.old_name !== i.identity["object-name"] ||
      i.new_name !== i.old_name ||
      [
        "default_edit",
        "wire_edit",
        "input_edit",
        "connection_edit",
        "batch_edit",
        "combined_edit",
        "recovery_origin",
        "recovery_origin_sha256",
      ].some((k) => i[k] !== undefined)
    )
      return false;
    if (
      reference &&
      ((reference.id !== undefined &&
        (i.id !== reference.id || i.operation_id !== reference.operation_id)) ||
        !same(edit, reference.order_edit) ||
        !same(i.order_guard, reference.order_guard) ||
        i.review_sha256 !== reference.review_sha256 ||
        !same(i.target, reference.target) ||
        !same(i.identity, reference.identity) ||
        !same(i.connector_config, reference.connector_config) ||
        c.files["3"].sha256 !== reference.compilation?.files?.["3"]?.sha256 ||
        c.files["11"].sha256 !== reference.compilation?.files?.["11"]?.sha256 ||
        c.native_record_count !== reference.compilation.native_record_count ||
        !same(
          c.order_edit.proposed_order,
          reference.compilation.order_edit.proposed_order,
        ))
    )
      return false;
    const observed = data.latest_readback || data.result;
    if (!object(observed))
      return (
        data.pending === true && data.result === null && !data.latest_readback
      );
    if (observed.status === "unknown")
      return (
        data.pending === true ||
        (!!data.latest_readback &&
          (await orderTransferReceipt(
            { ...data, latest_readback: null },
            reference,
          )))
      );
    if (observed.status === "not_sent")
      return (
        data.pending === false &&
        observed.may_have_applied === false &&
        observed.protocol_accepted === false
      );
    if (
      !["verified", "recovered_original"].includes(observed.status) ||
      data.pending !== false ||
      observed.operational !== true ||
      observed.system_status !== 0 ||
      !id(observed.verification_capture_id) ||
      !hash(observed.native_sha256) ||
      observed.native_sha256 !== observed.expected_native_sha256
    )
      return false;
    const p = observed.preservation;
    if (
      !object(p) ||
      p.controller_writes !== false ||
      !integer(p.saved_application_parameters_verified) ||
      !integer(p.post_saved_parameters) ||
      !Array.isArray(p.runtime_counter_changes) ||
      p.runtime_counter_changes.length > 20000 ||
      !Array.isArray(p.device_calculated_changes) ||
      p.device_calculated_changes.length > 20000 ||
      p.source_application_sha256 !== c.files["3"].sha256 ||
      !hash(p.source_saved_parameters_sha256) ||
      !hash(p.verified_application_sha256) ||
      p.preserved_native_sha256 !== observed.native_sha256
    )
      return false;
    if (observed.status === "recovered_original")
      return (
        observed.proposed_change_verified === false &&
        observed.native_sha256 !== i.native_payload_sha256 &&
        observed.recovery?.profile ===
          "native-original-application-readback/1" &&
        observed.recovery.original_backup_id === i.backup_id &&
        observed.recovery.original_reviewed_native_sha256 ===
          i.native_payload_sha256 &&
        p.profile === "native-application-preservation/1" &&
        p.application_identical_except_instance === true &&
        p.application_identical_except_name === false &&
        same(p.allowed_identity_changes, ["instance"])
      );
    const order = p.selected_order;
    return (
      observed.native_sha256 === i.native_payload_sha256 &&
      p.profile === "native-effective-execution-order-preservation/1" &&
      p.application_matches_reviewed_order_and_fresh_settings === true &&
      p.other_merged_application_bytes_preserved === true &&
      p.identity_unchanged === true &&
      object(order) &&
      order.diagram_ref === edit.diagram_ref &&
      same(order.before, i.order_guard.original_order) &&
      same(order.after, edit.proposed_order) &&
      same(order.payload_widths, i.order_guard.payload_widths) &&
      order.edge_relationships_sha256 ===
        i.order_guard.edge_relationships_sha256 &&
      order.effective_order_verified === true
    );
  } catch {
    return false;
  }
}
