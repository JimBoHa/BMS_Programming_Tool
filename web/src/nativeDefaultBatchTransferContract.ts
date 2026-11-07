import { connectionSame as same } from "./nativeConnectionContract";
import {
  defaultBatchCompilation,
  defaultBatchRequest,
} from "./nativeDefaultBatchContract";
import { matchingConnectionTarget } from "./nativeMatchingConnectionContract";
type Data = Record<string, any>;
export const defaultBatchTransferProfile =
  "native-effective-default-batch-transfer/1";
export const defaultBatchTransferBase =
  "/bacnet/controller/native-application/default-batch/transfer";
export const defaultBatchTransferTarget = matchingConnectionTarget;
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const integer = (v: any, max = 20000) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const keys = (v: any, wanted: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === wanted.length &&
  wanted.every((k) => Object.hasOwn(v, k));
const bitsValue = (hex: string) => {
  const view = new DataView(new ArrayBuffer(4));
  view.setUint32(0, Number.parseInt(hex, 16), false);
  return view.getFloat32(0, false);
};
export function defaultBatchTransferProposal(edit: Data, opened: Data | null) {
  try {
    if (
      !opened ||
      !keys(edit, [
        "capture_id",
        "snapshot_sha256",
        "source_sha256",
        "effective_sha256",
        "changes",
      ]) ||
      !id(edit.capture_id) ||
      ![edit.snapshot_sha256, edit.source_sha256, edit.effective_sha256].every(
        hash,
      ) ||
      !Array.isArray(edit.changes) ||
      edit.changes.length < 1 ||
      edit.changes.length > 16
    )
      return false;
    const drafts = Object.create(null);
    for (const change of edit.changes) {
      if (
        !keys(change, [
          "kind",
          "record_ref",
          "encoded_sha256",
          change.kind === "real" ? "value_text" : "value",
        ]) ||
        typeof change.record_ref !== "string" ||
        !change.record_ref.length ||
        [...change.record_ref].length > 512 ||
        /[\u0000-\u001f\u007f]/.test(change.record_ref) ||
        new TextDecoder().decode(
          new TextEncoder().encode(change.record_ref),
        ) !== change.record_ref ||
        !hash(change.encoded_sha256) ||
        Object.hasOwn(drafts, change.record_ref)
      )
        return false;
      drafts[change.record_ref] =
        change.kind === "real" ? change.value_text : String(change.value);
      const row = opened.fields.find(
        (r: Data) => r.field.ref === change.record_ref,
      );
      if (!row || (change.kind === "enum" && !row.field.saved_storage))
        return false;
    }
    return same(defaultBatchRequest(edit, opened, drafts), edit);
  } catch {
    return false;
  }
}
function compilationWitness(c: Data, edit: Data, opened?: Data) {
  try {
    const guard = c.batch_guard,
      q = c.parameter_transfer_qualification;
    if (
      !keys(guard, ["profile", "fields"]) ||
      guard.profile !== "native-default-batch-configuration-guard/1" ||
      !Array.isArray(guard.fields) ||
      guard.fields.length !== edit.changes.length ||
      !Array.isArray(c.independent) ||
      c.independent.length !== edit.changes.length ||
      !keys(q, ["profile", "qualified_fields", "model_inventory_used"]) ||
      q.profile !== "native-omitted-application-field-types/1" ||
      q.model_inventory_used !== false ||
      !integer(q.qualified_fields) ||
      q.qualified_fields !==
        c.parameter_merge.changed_parameters.filter(
          (r: Data) => r.added === true,
        ).length
    )
      return false;
    const fields: Data[] = [];
    for (const [index, change] of edit.changes.entries()) {
      const g = guard.fields[index],
        independent = c.independent[index].compilation,
        e = independent.selected_edit;
      const common = [
        "kind",
        "record_ref",
        "class_id",
        "property",
        "encoded_sha256",
      ];
      if (
        !keys(g, [
          ...common,
          ...(change.kind === "real"
            ? ["prior_bits"]
            : change.kind === "boolean"
              ? ["prior_value"]
              : ["prior_value", "saved_storage", "states_text_encoded_sha256"]),
        ]) ||
        g.kind !== change.kind ||
        g.record_ref !== change.record_ref ||
        g.encoded_sha256 !== change.encoded_sha256 ||
        g.property !== 3113 ||
        !(
          change.kind === "real"
            ? [526, 527]
            : change.kind === "boolean"
              ? [530, 531]
              : [528, 529]
        ).includes(g.class_id) ||
        g.class_id !== e.class_id
      )
        return false;
      const f: Data = {
        ref: g.record_ref,
        class_id: g.class_id,
        property: 3113,
        encoded_sha256: g.encoded_sha256,
      };
      if (change.kind === "real") {
        if (
          !/^[a-f0-9]{8}$/.test(g.prior_bits) ||
          !Number.isFinite(bitsValue(g.prior_bits))
        )
          return false;
        Object.assign(f, {
          effective_bits: g.prior_bits,
          effective_value: bitsValue(g.prior_bits),
        });
      } else {
        if (
          change.kind === "boolean"
            ? typeof g.prior_value !== "boolean"
            : !integer(g.prior_value, 65535)
        )
          return false;
        Object.assign(f, { effective_value: g.prior_value });
      }
      if (change.kind === "enum") {
        const slot = g.saved_storage;
        if (
          !keys(slot, [
            "kind",
            "datatype",
            "bytes",
            "maximum_code",
            "static_record_offset",
            "dynamic_value_offset",
          ]) ||
          slot.kind !== "captured-fixed-enum-slot" ||
          slot.datatype !== 9 ||
          slot.bytes !== 2 ||
          slot.maximum_code !== 65535 ||
          !integer(slot.static_record_offset, 2 * 1024 * 1024) ||
          slot.static_record_offset + 16 > c.files["11"].bytes ||
          !integer(slot.dynamic_value_offset, 2 * 1024 * 1024) ||
          slot.dynamic_value_offset + 3 > c.files["12"].bytes ||
          !(
            g.states_text_encoded_sha256 === null ||
            hash(g.states_text_encoded_sha256)
          )
        )
          return false;
        Object.assign(f, {
          saved_storage: slot,
          maximum_code: 65535,
          states_text_evidence: e.states_text_evidence,
        });
      }
      if (opened) {
        const actual = opened.fields.find(
          (r: Data) => r.kind === change.kind && r.field.ref === g.record_ref,
        )?.field;
        if (
          !actual ||
          Object.entries(f).some(([k, v]) => !same(actual[k], v)) ||
          (change.kind === "enum" &&
            actual.states_text_encoded_sha256 !== g.states_text_encoded_sha256)
        )
          return false;
      }
      fields.push({ kind: change.kind, field: f });
    }
    const {
      batch_guard: _guard,
      parameter_transfer_qualification: _q,
      ...local
    } = c;
    const witness = opened || {
      scope: c.scope,
      files: c.files,
      parameter_merge: c.parameter_merge,
      effective_sha256: c.effective_sha256,
      source_sha256: c.files["3"].sha256,
      fields,
    };
    return (
      c.changed_count > 0 &&
      defaultBatchTransferProposal(
        opened ? edit : { ...edit, effective_sha256: c.effective_sha256 },
        witness,
      ) &&
      defaultBatchCompilation(local, witness, edit, c.compiled_sha256)
    );
  } catch {
    return false;
  }
}
function identity(i: Data) {
  return (
    integer(i.old_instance, 4194302) &&
    i.new_instance === i.old_instance &&
    i.identity?.device === `device,${i.old_instance}` &&
    i.identity["vendor-identifier"] === 5 &&
    i.old_name === i.identity["object-name"] &&
    i.new_name === i.old_name &&
    [
      "default_edit",
      "wire_edit",
      "combined_edit",
      "connection_edit",
      "input_edit",
      "recovery_origin",
      "allocation_origin",
    ].every((k) => i[k] === undefined)
  );
}
export async function defaultBatchTransferReview(
  data: Data,
  source: Data,
  proposal: Data,
  opened: Data,
  controller: Data,
) {
  try {
    return (
      controller.interfaceOpen === true &&
      controller.ownedCommands === 0 &&
      data.profile === "native-application-transfer/1" &&
      data.operation_profile === defaultBatchTransferProfile &&
      data.change_kind === "default-batch" &&
      data.can_apply === true &&
      data.vendor_runtime_required === false &&
      data.capture_id === source.capture_id &&
      data.capture_id === proposal.capture_id &&
      data.snapshot_sha256 === source.snapshot_sha256 &&
      data.snapshot_sha256 === proposal.snapshot_sha256 &&
      defaultBatchTransferTarget(
        { ...source.target, device: source.device },
        controller,
      ) &&
      defaultBatchTransferTarget(
        { ...data.target, device: data.identity?.device },
        controller,
      ) &&
      same(data.connector_config, JSON.parse(controller.interfaceKey)) &&
      same(data.identity, opened.identity) &&
      identity(data) &&
      same(data.batch_edit, proposal) &&
      same(data.batch_guard, data.compilation?.batch_guard) &&
      data.application_sha256 === opened.source_sha256 &&
      data.static_parameters_sha256 === opened.files["11"].sha256 &&
      data.payload_sha256 === data.compilation?.compiled_sha256 &&
      /^[A-Za-z0-9_-]{32}$/.test(data.token || "") &&
      hash(data.review_sha256) &&
      Number.isFinite(Date.parse(data.expires_at)) &&
      compilationWitness(data.compilation, proposal, opened)
    );
  } catch {
    return false;
  }
}
export async function defaultBatchTransferReceipt(
  data: Data,
  reference?: Data,
): Promise<boolean> {
  try {
    if (typeof data?.pending !== "boolean") return false;
    const i = data.intent,
      observed = data.latest_readback || data.result;
    if (!i)
      return (
        reference?.id === undefined &&
        data.pending === false &&
        data.result?.status === "not_sent" &&
        data.result.may_have_applied === false &&
        data.result.protocol_accepted === false
      );
    const c = i.compilation;
    if (
      !id(i.id) ||
      !hash(i.evidence_sha256) ||
      i.profile !== "native-application-transfer/1" ||
      i.change_kind !== "default-batch" ||
      i.operation_profile !== defaultBatchTransferProfile ||
      !identity(i) ||
      !compilationWitness(c, i.batch_edit) ||
      !same(i.batch_guard, c.batch_guard) ||
      i.defaults_change_confirmed !== true ||
      i.application_transfer_confirmed !== true ||
      !id(i.backup_id) ||
      !id(i.review_capture_id) ||
      i.review_capture_id !== i.batch_edit.capture_id ||
      !hash(i.review_sha256) ||
      i.payload_sha256 !== c.compiled_sha256 ||
      i.native_payload_sha256 !== c.compiled_native_sha256
    )
      return false;
    if (
      reference &&
      ((reference.id !== undefined &&
        (i.id !== reference.id || i.operation_id !== reference.operation_id)) ||
        !same(i.batch_edit, reference.batch_edit) ||
        !same(i.batch_guard, reference.batch_guard) ||
        i.review_sha256 !== reference.review_sha256 ||
        !same(i.target, reference.target) ||
        !same(i.identity, reference.identity) ||
        !same(i.connector_config, reference.connector_config) ||
        c.files["3"].sha256 !== reference.compilation?.files?.["3"]?.sha256 ||
        c.files["11"].sha256 !== reference.compilation?.files?.["11"]?.sha256 ||
        c.native_record_count !== reference.compilation?.native_record_count)
    )
      return false;
    if (!observed)
      return (
        data.pending === true && data.result === null && !data.latest_readback
      );
    if (observed.status === "unknown")
      return (
        data.pending === true ||
        (!!data.latest_readback &&
          (await defaultBatchTransferReceipt(
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
    const p = observed.preservation;
    if (
      data.pending !== false ||
      !["verified", "recovered_original"].includes(observed.status) ||
      !id(observed.verification_capture_id) ||
      !hash(observed.native_sha256) ||
      !hash(p?.verified_application_sha256) ||
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
    if (
      observed.native_sha256 !== i.native_payload_sha256 ||
      p.profile !== "native-effective-default-batch-preservation/1" ||
      p.application_identical_except_selected_defaults !== true ||
      p.identity_unchanged !== true ||
      p.enum_semantics_verified !== false ||
      p.controller_writes !== false ||
      !integer(p.saved_application_parameters_verified) ||
      !integer(p.post_saved_parameters) ||
      !hash(p.source_application_sha256) ||
      !hash(p.source_saved_parameters_sha256) ||
      !Array.isArray(p.selected_defaults) ||
      p.selected_defaults.length !== i.batch_edit.changes.length
    )
      return false;
    return p.selected_defaults.every((row: Data, index: number) => {
      const selected = c.selected[index],
        g = i.batch_guard.fields[index];
      if (
        row.kind !== selected.kind ||
        row.record_ref !== selected.record_ref ||
        row.class_id !== selected.class_id ||
        row.effective_value_verified !== true
      )
        return false;
      return row.kind === "real"
        ? row.before_bits === g.prior_bits &&
            row.after_bits === selected.after_encoding_hex.slice(2, -2)
        : row.before_value === g.prior_value &&
            row.after_value === i.batch_edit.changes[index].value;
    });
  } catch {
    return false;
  }
}
