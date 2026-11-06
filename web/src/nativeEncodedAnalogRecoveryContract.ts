import {
  encodedAnalogConfiguration,
  encodedAnalogConfigurationStorage,
} from "./nativeEncodedAnalogTerminalContract";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { terminalEvidenceSeal } from "./nativeTerminalTransferContract";
import { controllerKey } from "./workflow";

type Data = Record<string, any>;
export const encodedAnalogRecoveryDraftProfile =
  "native-encoded-analog-terminal-recovery-draft/1";
export const encodedAnalogRecoveryTransferProfile =
  "native-encoded-analog-terminal-recovery-transfer/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const slot = (v: unknown) =>
  Number.isSafeInteger(v) && Number(v) >= 1 && Number(v) <= 6;
const originKeys = [
  "profile",
  "parent_receipt_id",
  "parent_intent_sha256",
  "original_dispatch",
  "verified_proof",
  "original_backup_id",
  "original_snapshot_sha256",
  "current_capture_id",
  "current_snapshot_sha256",
  "object_id",
  "record_ref",
  "previous_slot",
  "recorded_after_slot",
  "current_slot",
  "proposal_slot",
  "current_configuration_sha256",
];
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
function originShape(o: Data) {
  const match =
    typeof o?.object_id === "string" &&
    /^analog-input,(0|[1-9][0-9]*)$/.exec(o.object_id);
  return (
    exact(o, originKeys) &&
    o.profile === encodedAnalogRecoveryDraftProfile &&
    id(o.parent_receipt_id) &&
    hash(o.parent_intent_sha256) &&
    id(o.original_backup_id) &&
    hash(o.original_snapshot_sha256) &&
    id(o.current_capture_id) &&
    hash(o.current_snapshot_sha256) &&
    o.original_dispatch === "possible" &&
    !!match &&
    Number(match[1]) <= 4194302 &&
    typeof o.record_ref === "string" &&
    o.record_ref.length <= 512 &&
    new RegExp(`^[^/\\x00-\\x1f]+/0_${match[1]}$`).test(o.record_ref) &&
    [
      o.previous_slot,
      o.recorded_after_slot,
      o.current_slot,
      o.proposal_slot,
    ].every(slot) &&
    o.previous_slot !== o.recorded_after_slot &&
    o.proposal_slot === o.previous_slot &&
    [o.previous_slot, o.recorded_after_slot].includes(o.current_slot) &&
    hash(o.current_configuration_sha256) &&
    exact(o.verified_proof, ["kind", "sha256", "time"]) &&
    ["result", "readback-event"].includes(o.verified_proof.kind) &&
    hash(o.verified_proof.sha256) &&
    typeof o.verified_proof.time === "string" &&
    Number.isFinite(Date.parse(o.verified_proof.time))
  );
}
export async function encodedAnalogRecoveryDraft(
  document: { data: Data; blob: Blob },
  source: Data,
  parent: Data,
) {
  try {
    const r = document.data,
      o = r?.origin,
      s = r?.source;
    const device = source?.identity?.device ?? `device,${parent?.new_instance}`;
    const old = parent?.compilation?.terminal_compilation;
    const selected = source?.inputs?.find(
      (p: Data) => p.object_id === o?.object_id,
    );
    if (
      !exact(r, [
        "profile",
        "scope",
        "source",
        "origin",
        "origin_sha256",
        "current_effective_sha256",
        "already_recorded",
        "proposal",
        "inverse_compilation",
        "inverse_output_sha256",
        "read_only",
        "controller_queries",
        "controller_writes",
        "field_actions",
        "can_apply",
        "new_review_required",
        "parent_lineage_enforced_by_field_transfer",
        "evidence_sha256",
      ]) ||
      !originShape(o) ||
      !same(JSON.parse(await document.blob.text()), r) ||
      r?.profile !== encodedAnalogRecoveryDraftProfile ||
      source?.profile !== "native-local-universal-input-transfer/4" ||
      !selected ||
      selected.configuration_error !== null ||
      !old ||
      parent.compilation.profile !==
        "native-local-universal-input-transfer/4" ||
      old.profile !== "tagged-moi-local-terminal-copy/3" ||
      !same(parent.identity, source.identity) ||
      !encodedAnalogConfiguration(parent.compilation.stored_configuration) ||
      !encodedAnalogConfigurationStorage(
        parent.compilation.configuration_storage,
        parent.compilation.stored_configuration,
      ) ||
      !same(
        parent.compilation.configuration_storage,
        selected.configuration_storage,
      ) ||
      !Object.keys(selected.configuration).every((k) =>
        Object.is(
          parent.compilation.stored_configuration[k],
          selected.configuration[k],
        ),
      ) ||
      parent.operation_profile !== "native-local-universal-input-transfer/4" ||
      parent.input_edit?.action !== "encoded-terminal" ||
      parent.input_edit.object_instance !== Number(o.object_id.split(",")[1]) ||
      parent.input_edit.slot !== old.destination_slot ||
      parent.input_edit.configuration_sha256 !==
        parent.compilation.configuration_sha256 ||
      old.object !== parent.compilation.object_id ||
      old.ref !== parent.compilation.record_ref ||
      old.output_sha256 !== parent.payload_sha256 ||
      old.output_native_sha256 !== parent.native_payload_sha256 ||
      r.read_only !== true ||
      r.controller_queries !== false ||
      r.controller_writes !== false ||
      r.field_actions !== false ||
      r.can_apply !== false ||
      r.parent_lineage_enforced_by_field_transfer !== false ||
      typeof r.already_recorded !== "boolean" ||
      r.new_review_required !== !r.already_recorded ||
      !hash(r.current_effective_sha256) ||
      r.current_effective_sha256 !== source.controller?.source_sha256 ||
      s?.capture_id !== source.capture_id ||
      s.snapshot_sha256 !== source.snapshot_sha256 ||
      !same(s.identity, source.identity) ||
      controllerKey(s.target) !== controllerKey({ ...source.target, device }) ||
      o?.original_backup_id !== parent.backup_id ||
      !hash(o?.original_snapshot_sha256) ||
      o?.profile !== encodedAnalogRecoveryDraftProfile ||
      o.parent_receipt_id !== parent.id ||
      o.parent_intent_sha256 !== parent.evidence_sha256 ||
      o.current_capture_id !== source.capture_id ||
      o.current_snapshot_sha256 !== source.snapshot_sha256 ||
      o.record_ref !== selected.record_ref ||
      o.object_id !== parent.compilation.object_id ||
      o.record_ref !== parent.compilation.record_ref ||
      o.current_slot !== selected.slot ||
      o.current_configuration_sha256 !== selected.configuration_sha256 ||
      ![o.previous_slot, o.recorded_after_slot, o.current_slot].every(slot) ||
      o.previous_slot !== old.old_slot ||
      o.recorded_after_slot !== old.destination_slot ||
      o.proposal_slot !== o.previous_slot ||
      o.previous_slot === o.recorded_after_slot ||
      o.current_slot !==
        (r.already_recorded ? o.previous_slot : o.recorded_after_slot) ||
      o.original_dispatch !== "possible" ||
      !["result", "readback-event"].includes(o.verified_proof?.kind) ||
      !hash(o.verified_proof?.sha256) ||
      typeof o.verified_proof?.time !== "string" ||
      !hash(r.origin_sha256)
    )
      return false;
    if (r.already_recorded) {
      if (
        r.proposal !== null ||
        r.inverse_compilation !== null ||
        r.inverse_output_sha256 !== null
      )
        return false;
    } else {
      const e = r.proposal?.edit,
        c = r.inverse_compilation,
        p = c?.terminal_compilation;
      if (
        r.proposal?.capture_id !== source.capture_id ||
        r.proposal.snapshot_sha256 !== source.snapshot_sha256 ||
        !same(e, {
          action: "encoded-terminal",
          object_instance: Number(o.object_id.split(",")[1]),
          slot: o.previous_slot,
          configuration_sha256: selected.configuration_sha256,
          name: null,
          configuration: null,
          allocation_receipt: null,
        }) ||
        !source.available_slots?.includes(o.previous_slot) ||
        c?.profile !== "native-local-universal-input-transfer/4" ||
        !same(c.input_edit, e) ||
        c.object_id !== o.object_id ||
        c.record_ref !== o.record_ref ||
        !encodedAnalogConfiguration(c.stored_configuration) ||
        !encodedAnalogConfigurationStorage(
          c.configuration_storage,
          c.stored_configuration,
        ) ||
        !same(c.configuration_storage, selected.configuration_storage) ||
        !Object.keys(selected.configuration).every((k) =>
          Object.is(c.stored_configuration[k], selected.configuration[k]),
        ) ||
        c.other_records_preserved !== true ||
        c.wires_changed !== false ||
        c.allocated_record_hex !== null ||
        !p ||
        p.profile !== "tagged-moi-local-terminal-copy/3" ||
        p.object !== o.object_id ||
        p.ref !== o.record_ref ||
        p.old_slot !== o.current_slot ||
        p.destination_slot !== o.previous_slot ||
        p.old_device_type !== `UI IN${o.current_slot}` ||
        p.new_device_type !== `UI IN${o.previous_slot}` ||
        p.changed !== true ||
        p.device_type_encoding_preserved !== true ||
        ![0, 4].includes(p.device_type_character_encoding) ||
        p.device_type_character_encoding !==
          selected.device_type_character_encoding ||
        p.controller_write !== false ||
        p.field_transfer_enabled !== false ||
        p.physical_terminal_or_wiring_verified !== false ||
        ![
          "other_expanded_bytes_preserved",
          "native_structure_readback_verified",
          "identities_modes_graph_and_record_framing_preserved",
        ].every((k) => p[k] === true) ||
        p.source_sha256 !== r.current_effective_sha256 ||
        p.source_sha256 !== c.parameter_merge?.output_sha256 ||
        c.parameter_merge?.source_sha256 !== s.sha256 ||
        c.parameter_merge?.static_sha256 !== s.files?.["11"]?.sha256 ||
        c.parameter_merge?.dynamic_sha256 !== s.files?.["12"]?.sha256 ||
        p.output_native_sha256 !== c.compiled_native_sha256 ||
        !hash(r.inverse_output_sha256) ||
        p.output_sha256 !== r.inverse_output_sha256 ||
        !hash(p.compilation_sha256)
      )
        return false;
      const { compilation_sha256, ...body } = p;
      if ((await connectionSeal(body)) !== compilation_sha256) return false;
      const bytes = p.payloads,
        hex = (text: string) =>
          p.device_type_character_encoding === 4
            ? "04" +
              [...text]
                .map((c) => c.charCodeAt(0).toString(16).padStart(4, "0"))
                .join("")
            : [...new TextEncoder().encode("\0" + text)]
                .map((n) => n.toString(16).padStart(2, "0"))
                .join("");
      if (!Array.isArray(bytes) || bytes.length !== 2) return false;
      const [a, b] = bytes;
      if (
        ![a, b].every(
          (x) =>
            x &&
            Number.isSafeInteger(x.offset) &&
            x.offset >= 14 &&
            x.offset <= 8 * 1024 * 1024,
        ) ||
        typeof a.before !== "string" ||
        !/^(?:[a-f0-9]{2}){1,4}$/.test(a.before) ||
        parseInt(a.before, 16) !== o.current_slot ||
        a.after !==
          o.previous_slot.toString(16).padStart(a.before.length, "0") ||
        b.before !== hex(`UI IN${o.current_slot}`) ||
        b.after !== hex(`UI IN${o.previous_slot}`) ||
        !(
          a.offset + a.before.length / 2 <= b.offset ||
          b.offset + b.before.length / 2 <= a.offset
        )
      )
        return false;
    }
    return (
      (await connectionSeal(o)) === r.origin_sha256 &&
      (await terminalEvidenceSeal(document.blob))
    );
  } catch {
    return false;
  }
}

export function encodedAnalogRecoveryReview(
  review: Data,
  prepared: Data | null,
) {
  const keys = [
    "encoded_analog_recovery_profile",
    "encoded_analog_recovery_parent_receipt",
    "encoded_analog_recovery_origin",
    "encoded_analog_recovery_origin_sha256",
    "encoded_analog_recovery_lineage_enforced",
  ];
  if (!prepared) return keys.every((k) => !Object.hasOwn(review, k));
  return (
    review.encoded_analog_recovery_profile ===
      encodedAnalogRecoveryTransferProfile &&
    review.encoded_analog_recovery_lineage_enforced === true &&
    review.encoded_analog_recovery_parent_receipt ===
      prepared.origin.parent_receipt_id &&
    review.encoded_analog_recovery_origin_sha256 === prepared.origin_sha256 &&
    same(review.encoded_analog_recovery_origin, prepared.origin)
  );
}

export function sameEncodedAnalogRecoveryLineage(actual: Data, expected: Data) {
  return [
    "encoded_analog_recovery_profile",
    "encoded_analog_recovery_parent_receipt",
    "encoded_analog_recovery_origin",
    "encoded_analog_recovery_origin_sha256",
    "encoded_analog_recovery_lineage_enforced",
  ].every(
    (k) =>
      Object.hasOwn(actual, k) === Object.hasOwn(expected, k) &&
      same(actual[k], expected[k]),
  );
}

export async function encodedAnalogRecoveryReceipt(intent: Data) {
  const keys = [
    "encoded_analog_recovery_profile",
    "encoded_analog_recovery_parent_receipt",
    "encoded_analog_recovery_origin",
    "encoded_analog_recovery_origin_sha256",
    "encoded_analog_recovery_lineage_enforced",
  ];
  if (keys.every((k) => !Object.hasOwn(intent, k))) return true;
  const o = intent.encoded_analog_recovery_origin,
    c = intent.compilation,
    p = c?.terminal_compilation;
  return (
    keys.every((k) => Object.hasOwn(intent, k)) &&
    intent.encoded_analog_recovery_profile ===
      encodedAnalogRecoveryTransferProfile &&
    intent.encoded_analog_recovery_lineage_enforced === true &&
    originShape(o) &&
    intent.encoded_analog_recovery_parent_receipt === o.parent_receipt_id &&
    intent.encoded_analog_recovery_origin_sha256 ===
      (await connectionSeal(o)) &&
    intent.review_capture_id === o.current_capture_id &&
    intent.input_edit?.action === "encoded-terminal" &&
    intent.input_edit.slot === o.previous_slot &&
    intent.input_edit.configuration_sha256 === o.current_configuration_sha256 &&
    c?.object_id === o.object_id &&
    c.record_ref === o.record_ref &&
    p?.old_slot === o.current_slot &&
    p.destination_slot === o.previous_slot &&
    [
      "physical_wiring_confirmed",
      "input_change_confirmed",
      "application_transfer_confirmed",
    ].every((k) => intent[k] === true)
  );
}
