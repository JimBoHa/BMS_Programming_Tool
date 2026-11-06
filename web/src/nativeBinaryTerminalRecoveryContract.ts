import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { terminalEvidenceSeal } from "./nativeTerminalTransferContract";
import { controllerKey } from "./workflow";

type Data = Record<string, any>;
export const binaryTerminalRecoveryDraftProfile =
  "native-binary-terminal-recovery-draft/1";
export const binaryTerminalRecoveryTransferProfile =
  "native-binary-terminal-recovery-transfer/1";
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
const configuration = (v: any) =>
  exact(v, ["active_text", "inactive_text", "polarity", "states_text_index"]) &&
  typeof v.active_text === "string" &&
  typeof v.inactive_text === "string" &&
  Number.isSafeInteger(v.states_text_index) &&
  v.states_text_index >= 0 &&
  v.states_text_index <= 4294967295 &&
  [null, 0, 1].includes(v.polarity);
const counters = (v: any) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length <= 2 &&
  Object.entries(v).every(
    ([key, value]) =>
      ["15", "33"].includes(key) &&
      Number.isSafeInteger(value) &&
      Number(value) >= 0 &&
      Number(value) <= 4294967295,
  );
const mixedLineage = (v: Data) =>
  !v ||
  typeof v !== "object" ||
  Array.isArray(v) ||
  Object.keys(v).some(
    (key) =>
      key.startsWith("encoded_analog_recovery_") ||
      key.startsWith("recovery_") ||
      key.startsWith("terminal_recovery_") ||
      (key.startsWith("binary_terminal_recovery_") &&
        ![
          "binary_terminal_recovery_profile",
          "binary_terminal_recovery_parent_receipt",
          "binary_terminal_recovery_origin",
          "binary_terminal_recovery_origin_sha256",
          "binary_terminal_recovery_lineage_enforced",
        ].includes(key)),
  );

function originShape(o: Data) {
  const match =
    typeof o?.object_id === "string" &&
    /^binary-input,(0|[1-9][0-9]*)$/.exec(o.object_id);
  return (
    exact(o, originKeys) &&
    o.profile === binaryTerminalRecoveryDraftProfile &&
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
    new RegExp(`^[^/\\x00-\\x1f]+/3_${match[1]}$`).test(o.record_ref) &&
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
export async function binaryTerminalRecoveryDraft(
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
      mixedLineage(parent) ||
      !same(JSON.parse(await document.blob.text()), r) ||
      r?.profile !== binaryTerminalRecoveryDraftProfile ||
      source?.profile !== "native-local-universal-input-transfer/3" ||
      !selected ||
      selected.configuration_error !== null ||
      !old ||
      parent.compilation.profile !==
        "native-local-universal-input-transfer/3" ||
      old.profile !== "tagged-moi-local-terminal-copy/3" ||
      parent.profile !== "native-application-transfer/1" ||
      parent.change_kind !== "input" ||
      parent.old_name !== parent.new_name ||
      parent.new_name !== source.identity?.["object-name"] ||
      controllerKey({
        ...parent.target,
        device: `device,${parent.new_instance}`,
      }) !== controllerKey({ ...source.target, device }) ||
      !Number.isSafeInteger(parent.old_instance) ||
      parent.old_instance !== parent.new_instance ||
      parent.old_instance !== source.controller?.instance ||
      ![
        "physical_wiring_confirmed",
        "input_change_confirmed",
        "application_transfer_confirmed",
      ].every((key) => parent[key] === true) ||
      !hash(parent.payload_sha256) ||
      !hash(parent.native_payload_sha256) ||
      !same(parent.identity, source.identity) ||
      !configuration(parent.compilation.stored_configuration) ||
      !configuration(selected.configuration) ||
      !same(parent.compilation.stored_configuration, selected.configuration) ||
      !counters(parent.compilation.captured_counter_values) ||
      !counters(selected.captured_counter_values) ||
      !same(
        Object.keys(parent.compilation.captured_counter_values).sort(),
        Object.keys(selected.captured_counter_values).sort(),
      ) ||
      parent.operation_profile !== "native-local-universal-input-transfer/3" ||
      !same(parent.input_edit, {
        action: "binary-terminal",
        object_instance: Number(o.object_id.split(",")[1]),
        slot: old.destination_slot,
        configuration_sha256: parent.compilation.configuration_sha256,
        name: null,
        configuration: null,
        allocation_receipt: null,
      }) ||
      !same(parent.compilation.input_edit, parent.input_edit) ||
      parent.compilation.other_records_preserved !== true ||
      parent.compilation.wires_changed !== false ||
      parent.compilation.allocated_record_hex !== null ||
      parent.input_edit?.action !== "binary-terminal" ||
      parent.input_edit.object_instance !== Number(o.object_id.split(",")[1]) ||
      parent.input_edit.slot !== old.destination_slot ||
      parent.input_edit.configuration_sha256 !==
        parent.compilation.configuration_sha256 ||
      old.device_type_encoding_preserved !== true ||
      old.device_type_character_encoding !==
        selected.device_type_character_encoding ||
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
      o?.profile !== binaryTerminalRecoveryDraftProfile ||
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
          action: "binary-terminal",
          object_instance: Number(o.object_id.split(",")[1]),
          slot: o.previous_slot,
          configuration_sha256: selected.configuration_sha256,
          name: null,
          configuration: null,
          allocation_receipt: null,
        }) ||
        !source.available_slots?.includes(o.previous_slot) ||
        c?.profile !== "native-local-universal-input-transfer/3" ||
        !same(c.input_edit, e) ||
        c.object_id !== o.object_id ||
        c.record_ref !== o.record_ref ||
        !configuration(c.stored_configuration) ||
        !same(c.stored_configuration, selected.configuration) ||
        !counters(c.captured_counter_values) ||
        !same(c.captured_counter_values, selected.captured_counter_values) ||
        c.configuration_sha256 !== selected.configuration_sha256 ||
        !Number.isSafeInteger(c.native_record_count) ||
        c.native_record_count < 2 ||
        c.native_record_count > 20000 ||
        c.original_native_record_count !== c.native_record_count ||
        !same(c.changes, [
          {
            property: 31,
            before: `UI IN${o.current_slot}`,
            after: `UI IN${o.previous_slot}`,
          },
          { property: 519, before: o.current_slot, after: o.previous_slot },
        ]) ||
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
        p.saved_settings_merged !== false ||
        p.controller_write !== false ||
        p.field_transfer_enabled !== false ||
        p.physical_terminal_or_wiring_verified !== false ||
        ![
          "other_expanded_bytes_preserved",
          "native_structure_readback_verified",
          "identities_modes_graph_and_record_framing_preserved",
        ].every((k) => p[k] === true) ||
        p.source_native_sha256 !== source.controller?.native_sha256 ||
        p.source_native_sha256 !== c.parameter_merge?.native_output_sha256 ||
        p.source_sha256 !== r.current_effective_sha256 ||
        p.source_sha256 !== c.parameter_merge?.output_sha256 ||
        c.parameter_merge?.source_sha256 !== s.sha256 ||
        c.parameter_merge?.static_sha256 !== s.files?.["11"]?.sha256 ||
        c.parameter_merge?.dynamic_sha256 !== s.files?.["12"]?.sha256 ||
        p.output_native_sha256 !== c.compiled_native_sha256 ||
        !hash(r.inverse_output_sha256) ||
        p.output_sha256 !== r.inverse_output_sha256 ||
        ![
          "source_sha256",
          "source_native_sha256",
          "record_sha256",
          "slot_property_sha256",
          "device_type_property_sha256",
          "output_sha256",
          "output_native_sha256",
          "compilation_sha256",
        ].every((key) => hash(p[key]))
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

export function binaryTerminalRecoveryReview(
  review: Data,
  prepared: Data | null,
) {
  const keys = [
    "binary_terminal_recovery_profile",
    "binary_terminal_recovery_parent_receipt",
    "binary_terminal_recovery_origin",
    "binary_terminal_recovery_origin_sha256",
    "binary_terminal_recovery_lineage_enforced",
  ];
  if (mixedLineage(review)) return false;
  if (!prepared) return keys.every((k) => !Object.hasOwn(review, k));
  return (
    review.binary_terminal_recovery_profile ===
      binaryTerminalRecoveryTransferProfile &&
    review.binary_terminal_recovery_lineage_enforced === true &&
    review.binary_terminal_recovery_parent_receipt ===
      prepared.origin.parent_receipt_id &&
    review.binary_terminal_recovery_origin_sha256 === prepared.origin_sha256 &&
    same(review.binary_terminal_recovery_origin, prepared.origin)
  );
}

export function sameBinaryTerminalRecoveryLineage(
  actual: Data,
  expected: Data,
) {
  if (mixedLineage(actual) || mixedLineage(expected)) return false;
  return [
    "binary_terminal_recovery_profile",
    "binary_terminal_recovery_parent_receipt",
    "binary_terminal_recovery_origin",
    "binary_terminal_recovery_origin_sha256",
    "binary_terminal_recovery_lineage_enforced",
  ].every(
    (k) =>
      Object.hasOwn(actual, k) === Object.hasOwn(expected, k) &&
      same(actual[k], expected[k]),
  );
}

export async function binaryTerminalRecoveryReceipt(
  intent: Data,
  expected?: Data,
) {
  const keys = [
    "binary_terminal_recovery_profile",
    "binary_terminal_recovery_parent_receipt",
    "binary_terminal_recovery_origin",
    "binary_terminal_recovery_origin_sha256",
    "binary_terminal_recovery_lineage_enforced",
  ];
  if (mixedLineage(intent)) return false;
  if (keys.every((k) => !Object.hasOwn(intent, k))) return true;
  const o = intent.binary_terminal_recovery_origin,
    c = intent.compilation,
    p = c?.terminal_compilation;
  return (
    keys.every((k) => Object.hasOwn(intent, k)) &&
    intent.binary_terminal_recovery_profile ===
      binaryTerminalRecoveryTransferProfile &&
    intent.binary_terminal_recovery_lineage_enforced === true &&
    originShape(o) &&
    o.current_slot === o.recorded_after_slot &&
    intent.binary_terminal_recovery_parent_receipt === o.parent_receipt_id &&
    intent.binary_terminal_recovery_origin_sha256 ===
      (await connectionSeal(o)) &&
    intent.review_capture_id === o.current_capture_id &&
    intent.operation_profile === "native-local-universal-input-transfer/3" &&
    intent.input_edit?.action === "binary-terminal" &&
    intent.input_edit.object_instance === Number(o.object_id.split(",")[1]) &&
    intent.input_edit.slot === o.previous_slot &&
    intent.input_edit.configuration_sha256 === o.current_configuration_sha256 &&
    c?.profile === "native-local-universal-input-transfer/3" &&
    c.configuration_sha256 === o.current_configuration_sha256 &&
    configuration(c.stored_configuration) &&
    counters(c.captured_counter_values) &&
    (!expected ||
      (counters(expected.compilation?.captured_counter_values) &&
        same(
          Object.keys(c.captured_counter_values).sort(),
          Object.keys(expected.compilation.captured_counter_values).sort(),
        ))) &&
    c.object_id === o.object_id &&
    c.record_ref === o.record_ref &&
    p?.profile === "tagged-moi-local-terminal-copy/3" &&
    p.old_slot === o.current_slot &&
    p.destination_slot === o.previous_slot &&
    [
      "physical_wiring_confirmed",
      "input_change_confirmed",
      "application_transfer_confirmed",
    ].every((k) => intent[k] === true)
  );
}
