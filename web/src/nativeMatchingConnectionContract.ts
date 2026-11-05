import type { NativeArchiveSource } from "./NativeRecords";
import type { ControllerContext } from "./workflow";
import {
  connectionCompilation,
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";

type Data = Record<string, any>;
export const matchingConnectionProfile =
  "native-effective-matching-connection-transfer/1";
export const matchingConnectionBase =
  "/bacnet/controller/native-application/matching-connection/transfer";
export const matchingConnectionGuard =
  "native-matching-connection-configuration-guard/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const integer = (v: unknown, max = 65535) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const tuple = (v: any) =>
  Array.isArray(v) && v.length === 4 && v.every((x) => integer(x));
const object = (v: any): v is Data =>
  !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: any, wanted: string[]) =>
  object(v) &&
  Object.keys(v).length === wanted.length &&
  wanted.every((k) => Object.hasOwn(v, k));
const reference = (v: unknown) =>
  typeof v === "string" &&
  [...v].length > 0 &&
  [...v].length <= 512 &&
  !/[\u0000-\u001f\u007f]/.test(v) &&
  new TextDecoder().decode(new TextEncoder().encode(v)) === v;
const proposalKeys = [
  "capture_id",
  "snapshot_sha256",
  "source_sha256",
  "diagram_ref",
  "record_sha256",
  "prototype_index",
  "source_ref",
  "target_ref",
  "property_sha256",
  "metadata_property_sha256",
  "prototype_old",
  "connection_count",
  "effective_sha256",
  "effective_record_sha256",
];

export function matchingConnectionTarget(a: any, b: any) {
  return (
    object(a) &&
    object(b) &&
    typeof a.address === "string" &&
    typeof a.device === "string" &&
    /^device,(0|[1-9][0-9]*)$/.test(a.device) &&
    Number(a.device.split(",")[1]) <= 4194302 &&
    a.address === b.address &&
    a.device === b.device &&
    (a.router || null) === (b.router || null) &&
    (a.dnet ?? null) === (b.dnet ?? null)
  );
}

export function matchingConnectionProposal(v: any) {
  return (
    keys(v, proposalKeys) &&
    id(v.capture_id) &&
    [
      "snapshot_sha256",
      "source_sha256",
      "record_sha256",
      "property_sha256",
      "effective_sha256",
      "effective_record_sha256",
    ].every((k) => hash(v[k])) &&
    (v.metadata_property_sha256 === null || hash(v.metadata_property_sha256)) &&
    ["diagram_ref", "source_ref", "target_ref"].every((k) => reference(v[k])) &&
    v.source_ref !== v.target_ref &&
    tuple(v.prototype_old) &&
    integer(v.connection_count, 4095) &&
    v.connection_count > 0 &&
    integer(v.prototype_index, 4095) &&
    v.prototype_index < v.connection_count
  );
}

function guardMatches(v: any, proposal: Data) {
  return (
    keys(v, [
      "profile",
      "diagram_ref",
      "prototype_index",
      "prototype_old",
      "connection_count",
      "source_ref",
      "target_ref",
      "property_sha256",
      "metadata_property_sha256",
      "configuration_sha256",
    ]) &&
    v.profile === matchingConnectionGuard &&
    hash(v.configuration_sha256) &&
    [
      "diagram_ref",
      "prototype_index",
      "prototype_old",
      "connection_count",
      "source_ref",
      "target_ref",
      "property_sha256",
      "metadata_property_sha256",
    ].every((k) => same(v[k], proposal[k]))
  );
}

async function intrinsicCompilation(c: any, proposal: Data): Promise<boolean> {
  if (
    !keys(c, [
      "profile",
      "scope",
      "files",
      "parameter_merge",
      "archive_sha256",
      "effective_sha256",
      "connection_edit",
      "compiled_sha256",
      "compiled_native_sha256",
      "native_record_count",
      "other_merged_bytes_preserved",
      "saved_settings_merged",
      "controller_write",
      "field_transfer_enabled",
      "compilation_sha256",
      "connection_guard",
      "parameter_transfer_qualification",
      "connection_compilation_sha256",
    ]) ||
    c.profile !== "native-effective-connection-compiler/1" ||
    typeof c.scope !== "string" ||
    !keys(c.files, ["3", "11", "12"]) ||
    !["3", "11", "12"].every(
      (k) =>
        keys(c.files[k], ["bytes", "sha256"]) &&
        hash(c.files[k].sha256) &&
        integer(c.files[k].bytes, 2 * 1024 * 1024),
    ) ||
    c.files["3"].bytes === 0 ||
    c.files["3"].sha256 !== proposal.source_sha256 ||
    c.archive_sha256 !== proposal.source_sha256 ||
    ![
      "effective_sha256",
      "compiled_sha256",
      "compiled_native_sha256",
      "compilation_sha256",
      "connection_compilation_sha256",
    ].every((k) => hash(c[k])) ||
    !integer(c.native_record_count, 20000) ||
    c.native_record_count === 0 ||
    c.other_merged_bytes_preserved !== true ||
    c.saved_settings_merged !== true ||
    c.controller_write !== false ||
    c.field_transfer_enabled !== false ||
    !guardMatches(c.connection_guard, proposal)
  )
    return false;
  const p = c.parameter_merge,
    q = c.parameter_transfer_qualification,
    e = c.connection_edit;
  if (
    !object(p) ||
    p.source_sha256 !== c.archive_sha256 ||
    p.output_sha256 !== c.effective_sha256 ||
    !hash(p.native_output_sha256) ||
    p.static_sha256 !== c.files["11"].sha256 ||
    p.dynamic_sha256 !== c.files["12"].sha256 ||
    !integer(p.matched_parameters, 20000) ||
    !Array.isArray(p.changed_parameters) ||
    p.changed_parameters.length > p.matched_parameters ||
    !Array.isArray(p.retained_runtime_parameters) ||
    p.retained_runtime_parameters.length > 20000 ||
    p.vendor_runtime_required !== false ||
    !keys(q, ["profile", "qualified_fields", "model_inventory_used"]) ||
    q.profile !== "native-omitted-application-field-types/1" ||
    q.model_inventory_used !== false ||
    !integer(q.qualified_fields, 20000) ||
    q.qualified_fields !==
      p.changed_parameters.filter((row: Data) => row?.added === true).length ||
    !object(e) ||
    e.profile !== "tagged-moi-connection-copy/1" ||
    e.source_sha256 !== c.effective_sha256 ||
    e.source_native_sha256 !== p.native_output_sha256 ||
    !hash(e.record_sha256) ||
    [
      "diagram_ref",
      "property_sha256",
      "metadata_property_sha256",
      "prototype_index",
      "prototype_old",
      "source_ref",
      "target_ref",
    ].some((k) => !same(e[k], proposal[k])) ||
    !tuple(e.new) ||
    e.new[1] !== proposal.prototype_old[1] ||
    e.new[3] !== proposal.prototype_old[3] ||
    e.new[0] === e.new[2] ||
    e.connection_count_before !== proposal.connection_count ||
    e.connection_count_after !== proposal.connection_count + 1 ||
    e.output_sha256 !== c.compiled_sha256 ||
    e.output_native_sha256 !== c.compiled_native_sha256 ||
    e.other_expanded_bytes_preserved !== true ||
    e.native_structure_readback_verified !== true ||
    e.saved_settings_merged !== false ||
    e.controller_write !== false ||
    e.field_transfer_enabled !== false ||
    !hash(e.compilation_sha256) ||
    typeof e.scope !== "string" ||
    !integer(e.record_bytes_before, 8 * 1024 * 1024) ||
    !integer(e.record_bytes_after, 8 * 1024 * 1024) ||
    e.record_bytes_after <= e.record_bytes_before ||
    ![0, 4].includes(e.record_prefix_growth) ||
    e.native_bytes_growth !==
      e.record_bytes_after - e.record_bytes_before + e.record_prefix_growth ||
    !/^[a-f0-9]{12,44}$/.test(e.prototype_encoding_hex || "") ||
    !/^[a-f0-9]{12,44}$/.test(e.new_encoding_hex || "") ||
    !(proposal.metadata_property_sha256 === null
      ? e.continuation_prototype_sha256 === null
      : hash(e.continuation_prototype_sha256))
  )
    return false;
  const { compilation_sha256: editHash, ...editBody } = e;
  const { connection_compilation_sha256: transferHash, ...transferBody } = c;
  const {
    compilation_sha256: compilerHash,
    connection_guard: _guard,
    parameter_transfer_qualification: _qualification,
    ...compilerBody
  } = transferBody;
  return (
    (await connectionSeal(editBody)) === editHash &&
    (await connectionSeal(compilerBody)) === compilerHash &&
    (await connectionSeal(transferBody)) === transferHash
  );
}

export async function matchingConnectionReview(
  data: Data,
  source: NativeArchiveSource,
  proposal: Data,
  opened: Data,
  controller: ControllerContext,
): Promise<boolean> {
  try {
    const c = data.compilation;
    return (
      controller.interfaceOpen === true &&
      controller.ownedCommands === 0 &&
      matchingConnectionProposal(proposal) &&
      data.profile === "native-application-transfer/1" &&
      data.operation_profile === matchingConnectionProfile &&
      data.change_kind === "connection" &&
      data.can_apply === true &&
      data.vendor_runtime_required === false &&
      data.capture_id === source.capture_id &&
      data.snapshot_sha256 === source.snapshot_sha256 &&
      proposal.capture_id === source.capture_id &&
      proposal.snapshot_sha256 === source.snapshot_sha256 &&
      proposal.source_sha256 === source.sha256 &&
      matchingConnectionTarget(source.target, controller) &&
      matchingConnectionTarget(
        { ...data.target, device: data.identity?.device },
        controller,
      ) &&
      same(data.identity, opened.identity) &&
      data.identity?.["vendor-identifier"] === 5 &&
      integer(data.old_instance, 4194302) &&
      controller.device === `device,${data.old_instance}` &&
      data.new_instance === data.old_instance &&
      data.old_name === data.identity["object-name"] &&
      data.new_name === data.old_name &&
      same(data.connector_config, JSON.parse(controller.interfaceKey)) &&
      data.application_sha256 === source.sha256 &&
      data.static_parameters_sha256 === source.files["11"].sha256 &&
      same(data.connection_edit, proposal) &&
      guardMatches(data.connection_guard, proposal) &&
      same(data.connection_guard, c?.connection_guard) &&
      data.default_edit === undefined &&
      data.wire_edit === undefined &&
      data.input_edit === undefined &&
      data.recovery_origin === undefined &&
      data.recovery_origin_sha256 === undefined &&
      /^[A-Za-z0-9_-]{32}$/.test(data.token || "") &&
      hash(data.review_sha256) &&
      typeof data.expires_at === "string" &&
      Number.isFinite(Date.parse(data.expires_at)) &&
      (await intrinsicCompilation(c, proposal)) &&
      same(c.files, source.files) &&
      same(c.parameter_merge, opened.parameter_merge) &&
      c.native_record_count > opened.selection.block_count &&
      c.effective_sha256 === proposal.effective_sha256 &&
      c.effective_sha256 === opened.effective_sha256 &&
      data.payload_sha256 === c.compiled_sha256 &&
      (await connectionCompilation(
        c.connection_edit,
        c.compiled_sha256,
        {
          ...proposal,
          source_sha256: proposal.effective_sha256,
          record_sha256: proposal.effective_record_sha256,
        },
        opened.selection,
      ))
    );
  } catch {
    return false;
  }
}

export async function matchingConnectionReceipt(
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
    const edit = i.connection_edit,
      c = i.compilation;
    if (
      !id(i.id) ||
      i.profile !== "native-application-transfer/1" ||
      !hash(i.evidence_sha256) ||
      i.change_kind !== "connection" ||
      i.operation_profile !== matchingConnectionProfile ||
      !matchingConnectionProposal(edit) ||
      !(await intrinsicCompilation(c, edit)) ||
      !guardMatches(i.connection_guard, edit) ||
      !same(i.connection_guard, c.connection_guard) ||
      i.connection_change_confirmed !== true ||
      i.application_transfer_confirmed !== true ||
      !id(i.review_capture_id) ||
      i.review_capture_id !== edit.capture_id ||
      !id(i.backup_id) ||
      !hash(i.review_sha256) ||
      !hash(i.payload_sha256) ||
      !hash(i.native_payload_sha256) ||
      i.payload_sha256 !== c.compiled_sha256 ||
      i.native_payload_sha256 !== c.compiled_native_sha256 ||
      !integer(i.old_instance, 4194302) ||
      i.new_instance !== i.old_instance ||
      i.identity?.device !== `device,${i.old_instance}` ||
      i.identity["vendor-identifier"] !== 5 ||
      i.old_name !== i.identity["object-name"] ||
      i.new_name !== i.old_name ||
      i.default_edit !== undefined ||
      i.wire_edit !== undefined ||
      i.input_edit !== undefined ||
      i.recovery_origin !== undefined ||
      i.recovery_origin_sha256 !== undefined
    )
      return false;
    if (
      reference &&
      ((reference.id !== undefined &&
        (i.id !== reference.id || i.operation_id !== reference.operation_id)) ||
        !same(edit, reference.connection_edit) ||
        !same(i.connection_guard, reference.connection_guard) ||
        i.review_sha256 !== reference.review_sha256 ||
        !same(i.target, reference.target) ||
        !same(i.identity, reference.identity) ||
        !same(i.connector_config, reference.connector_config) ||
        c.files["3"].sha256 !== reference.compilation?.files?.["3"]?.sha256 ||
        c.files["11"].sha256 !== reference.compilation?.files?.["11"]?.sha256 ||
        c.native_record_count !== reference.compilation.native_record_count ||
        !same(c.connection_edit.new, reference.compilation.connection_edit.new))
    )
      return false;
    const observed = data.latest_readback || data.result;
    if (!object(observed))
      return (
        data.pending === true && data.result === null && !data.latest_readback
      );
    if (observed.status === "unknown") {
      if (data.pending === true) return true;
      // A later uncertain observation does not rewrite a previously resolved intent.
      return (
        !!data.latest_readback &&
        (await matchingConnectionReceipt(
          { ...data, latest_readback: null },
          reference,
        ))
      );
    }
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
      !integer(p.saved_application_parameters_verified, 20000) ||
      !integer(p.post_saved_parameters, 20000) ||
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
    if (observed.status === "recovered_original") {
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
    }
    const edge = p.selected_connection;
    return (
      observed.native_sha256 === i.native_payload_sha256 &&
      p.profile === "native-effective-matching-connection-preservation/1" &&
      p.application_matches_reviewed_connection_and_fresh_settings === true &&
      p.other_merged_application_bytes_preserved === true &&
      p.identity_unchanged === true &&
      object(edge) &&
      edge.diagram_ref === edit.diagram_ref &&
      edge.prototype_index === edit.prototype_index &&
      same(edge.prototype_old, edit.prototype_old) &&
      same(edge.new, c.connection_edit.new) &&
      edge.source_ref === edit.source_ref &&
      edge.target_ref === edit.target_ref &&
      edge.index === edit.connection_count &&
      edge.connection_count_before === edit.connection_count &&
      edge.connection_count_after === edit.connection_count + 1 &&
      edge.continuation_prototype_sha256 ===
        c.connection_edit.continuation_prototype_sha256 &&
      edge.effective_connection_verified === true
    );
  } catch {
    return false;
  }
}
