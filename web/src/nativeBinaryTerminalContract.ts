import { controllerKey } from "./workflow";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { terminalDocumentSeal } from "./nativeTerminalTransferContract";
type Data = Record<string, any>;
export const binaryTerminalProfile = "native-local-universal-input-transfer/3";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max: number) =>
  Number.isSafeInteger(v) && Number(v) >= 0 && Number(v) <= max;
const targetKey = (v: Data) =>
  controllerKey({ ...v.target, device: v.identity?.device });
const config = (v: Data) =>
  !!v &&
  same(Object.keys(v).sort(), [
    "active_text",
    "inactive_text",
    "polarity",
    "states_text_index",
  ]) &&
  typeof v.active_text === "string" &&
  typeof v.inactive_text === "string" &&
  integer(v.states_text_index, 4294967295) &&
  [null, 0, 1].includes(v.polarity);
const counters = (v: Data) =>
  !!v &&
  !Array.isArray(v) &&
  Object.keys(v).length <= 2 &&
  Object.entries(v).every(
    ([k, x]) => ["15", "33"].includes(k) && integer(x, 4294967295),
  );

export function binaryTerminalSource(v: Data, parent: Data) {
  try {
    const c = v?.controller,
      slots = v?.hardware?.capacity?.universal_inputs;
    if (
      !parent ||
      parent.profile !== "native-local-universal-input-transfer/1" ||
      v.profile !== binaryTerminalProfile ||
      v.capture_id !== parent.capture_id ||
      v.snapshot_sha256 !== parent.snapshot_sha256 ||
      !hash(v.snapshot_sha256) ||
      !same(v.target, parent.target) ||
      !same(v.identity, parent.identity) ||
      v.identity?.["vendor-identifier"] !== 5 ||
      !c ||
      !hash(c.source_sha256) ||
      !hash(c.native_sha256) ||
      c.name !== v.identity["object-name"] ||
      c.model !== v.identity["model-name"] ||
      !integer(c.instance, 4194302) ||
      (v.identity.device !== undefined &&
        v.identity.device !== `device,${c.instance}`) ||
      typeof c.root_ref !== "string" ||
      !c.root_ref.length ||
      !same(c.format_versions, parent.format_versions) ||
      ![
        [60, 60],
        [62, 62],
        [66, 65],
      ].some(
        ([a, b]) => c.format_versions.acs === a && c.format_versions.dmcs === b,
      ) ||
      v.controller_queries !== false ||
      v.controller_writes !== false ||
      v.field_transfer_enabled !== false ||
      v.counter_values_are_live !== false ||
      !Array.isArray(slots) ||
      ![3, 6].includes(slots.length) ||
      slots.some((x, i) => x !== i + 1) ||
      !same(slots, parent.hardware?.capacity?.universal_inputs) ||
      !same(v.available_slots, parent.available_slots) ||
      !Array.isArray(v.available_slots) ||
      v.available_slots.some(
        (x: number, i: number) =>
          !slots.includes(x) || (i > 0 && x <= v.available_slots[i - 1]),
      ) ||
      !Array.isArray(v.inputs) ||
      v.inputs.length > 16
    )
      return false;
    const ids = new Set(),
      occupied = new Set();
    for (const row of v.inputs) {
      const match =
        typeof row?.object_id === "string" &&
        /^binary-input,(0|[1-9][0-9]*)$/.exec(row.object_id);
      if (
        !match ||
        !integer(Number(match[1]), 4194302) ||
        row.record_ref !== `${c.root_ref}/3_${match[1]}` ||
        !slots.includes(row.slot) ||
        ids.has(row.object_id) ||
        occupied.has(row.slot) ||
        v.available_slots.includes(row.slot) ||
        typeof row.name !== "string" ||
        ![0, 4].includes(row.device_type_character_encoding)
      )
        return false;
      if (row.configuration_error === null) {
        if (
          !hash(row.configuration_sha256) ||
          !config(row.configuration) ||
          !counters(row.captured_counter_values)
        )
          return false;
      } else if (
        typeof row.configuration_error !== "string" ||
        !row.configuration_error.length ||
        row.configuration_sha256 !== undefined
      )
        return false;
      ids.add(row.object_id);
      occupied.add(row.slot);
    }
    return true;
  } catch {
    return false;
  }
}

export function binaryTerminalEdit(
  source: Data,
  object: string,
  destination: string,
) {
  const row = source?.inputs.find((r: Data) => r.object_id === object),
    slot = Number(destination);
  if (
    !row ||
    row.configuration_error !== null ||
    !destination ||
    !integer(slot, 6) ||
    !source.available_slots.includes(slot)
  )
    return null;
  return {
    action: "binary-terminal",
    object_instance: Number(object.split(",")[1]),
    slot,
    configuration_sha256: row.configuration_sha256,
    name: null,
    configuration: null,
    allocation_receipt: null,
  };
}

export async function binaryTerminalReview(
  document: { data: Data; blob: Blob },
  source: Data,
  request: Data,
  field: boolean,
) {
  try {
    const r = document.data,
      c = r?.compilation,
      p = c?.terminal_compilation,
      row = source.inputs.find(
        (x: Data) => x.object_id === `binary-input,${request.object_instance}`,
      );
    if (
      !row ||
      !same(
        request,
        binaryTerminalEdit(source, row.object_id, String(request.slot)),
      ) ||
      !same(JSON.parse(await document.blob.text()), r) ||
      r.capture_id !== source.capture_id ||
      r.snapshot_sha256 !== source.snapshot_sha256 ||
      targetKey(r) !== targetKey(source) ||
      !same(r.identity, source.identity) ||
      (field
        ? r.profile !== "native-application-transfer/1" ||
          r.operation_profile !== binaryTerminalProfile ||
          r.change_kind !== "input" ||
          !same(r.input_edit, request)
        : r.profile !== binaryTerminalProfile ||
          !same(r.edit, request) ||
          r.controller_queries !== false ||
          r.controller_writes !== false) ||
      c?.profile !== binaryTerminalProfile ||
      !same(c.input_edit, request) ||
      c.configuration_sha256 !== row.configuration_sha256 ||
      c.object_id !== row.object_id ||
      c.record_ref !== row.record_ref ||
      !same(c.stored_configuration, row.configuration) ||
      !same(c.captured_counter_values, row.captured_counter_values) ||
      c.other_records_preserved !== true ||
      c.wires_changed !== false ||
      c.allocated_record_hex !== null ||
      !integer(c.native_record_count, 20000) ||
      c.native_record_count < 2 ||
      c.original_native_record_count !== c.native_record_count ||
      !p ||
      p.profile !== "tagged-moi-local-terminal-copy/3" ||
      p.object !== row.object_id ||
      p.ref !== row.record_ref ||
      p.old_slot !== row.slot ||
      p.destination_slot !== request.slot ||
      p.old_device_type !== `UI IN${row.slot}` ||
      p.new_device_type !== `UI IN${request.slot}` ||
      p.changed !== true ||
      p.device_type_character_encoding !== row.device_type_character_encoding ||
      p.device_type_encoding_preserved !== true ||
      p.source_sha256 !== source.controller.source_sha256 ||
      p.source_native_sha256 !== source.controller.native_sha256 ||
      p.source_sha256 !== c.parameter_merge?.output_sha256 ||
      p.source_native_sha256 !== c.parameter_merge?.native_output_sha256 ||
      p.output_native_sha256 !== c.compiled_native_sha256 ||
      p.output_sha256 !== (field ? r.payload_sha256 : r.output_sha256) ||
      ![
        "source_sha256",
        "source_native_sha256",
        "record_sha256",
        "slot_property_sha256",
        "device_type_property_sha256",
        "output_sha256",
        "output_native_sha256",
        "compilation_sha256",
      ].every((k) => hash(p[k])) ||
      ![
        "other_expanded_bytes_preserved",
        "native_structure_readback_verified",
        "identities_modes_graph_and_record_framing_preserved",
      ].every((k) => p[k] === true) ||
      ![
        "saved_settings_merged",
        "controller_write",
        "field_transfer_enabled",
        "physical_terminal_or_wiring_verified",
      ].every((k) => p[k] === false) ||
      !Array.isArray(p.payloads) ||
      p.payloads.length !== 2
    )
      return false;
    const [slot, label] = p.payloads,
      hex = (text: string) =>
        row.device_type_character_encoding === 4
          ? "04" +
            [...text]
              .map((c) => c.charCodeAt(0).toString(16).padStart(4, "0"))
              .join("")
          : [...new TextEncoder().encode("\0" + text)]
              .map((n) => n.toString(16).padStart(2, "0"))
              .join("");
    if (
      ![slot, label].every(
        (x) => x && integer(x.offset, 8 * 1024 * 1024) && x.offset >= 14,
      ) ||
      typeof slot.before !== "string" ||
      !/^(?:[a-f0-9]{2}){1,4}$/.test(slot.before) ||
      Number.parseInt(slot.before, 16) !== row.slot ||
      slot.after !==
        request.slot.toString(16).padStart(slot.before.length, "0") ||
      label.before !== hex(p.old_device_type) ||
      label.after !== hex(p.new_device_type) ||
      !(
        slot.offset + slot.before.length / 2 <= label.offset ||
        label.offset + label.before.length / 2 <= slot.offset
      ) ||
      !same(c.changes, [
        { property: 31, before: p.old_device_type, after: p.new_device_type },
        { property: 519, before: row.slot, after: request.slot },
      ])
    )
      return false;
    if (
      field &&
      (!/^[A-Za-z0-9_-]{32}$/.test(r.token) ||
        r.can_apply !== true ||
        !(Date.parse(r.expires_at) > Date.now()) ||
        r.application_sha256 !== c.parameter_merge.source_sha256 ||
        r.static_parameters_sha256 !== c.parameter_merge.static_sha256)
    )
      return false;
    const { compilation_sha256, ...body } = p;
    return (
      (await connectionSeal(body)) === compilation_sha256 &&
      (await terminalDocumentSeal(document.blob, field))
    );
  } catch {
    return false;
  }
}

export function binaryTerminalReceipt(r: Data, context: Data) {
  const i = r?.intent,
    c = i?.compilation,
    p = c?.terminal_compilation;
  return (
    !!i &&
    /^[a-f0-9]{32}$/.test(i.id) &&
    hash(i.evidence_sha256) &&
    typeof r.pending === "boolean" &&
    i.change_kind === "input" &&
    i.operation_profile === binaryTerminalProfile &&
    i.input_edit?.action === "binary-terminal" &&
    i.input_edit.configuration === null &&
    i.input_edit.name === null &&
    i.input_edit.allocation_receipt === null &&
    hash(i.input_edit.configuration_sha256) &&
    integer(i.input_edit.object_instance, 4194302) &&
    integer(i.input_edit.slot, 6) &&
    i.input_edit.slot > 0 &&
    targetKey(i) === targetKey(context) &&
    same(i.identity, context.identity) &&
    c?.profile === binaryTerminalProfile &&
    c.configuration_sha256 === i.input_edit.configuration_sha256 &&
    config(c.stored_configuration) &&
    same(c.input_edit, i.input_edit) &&
    c.object_id === `binary-input,${i.input_edit.object_instance}` &&
    p?.profile === "tagged-moi-local-terminal-copy/3" &&
    p.destination_slot === i.input_edit.slot &&
    p.object === c.object_id &&
    p.device_type_encoding_preserved === true &&
    [0, 4].includes(p.device_type_character_encoding) &&
    p.output_sha256 === i.payload_sha256 &&
    hash(p.compilation_sha256)
  );
}

export function binaryTerminalVerified(r: Data) {
  const result = r?.latest_readback || r?.result,
    c = r?.intent?.compilation,
    edit = r?.intent?.input_edit;
  if (
    r?.pending !== false ||
    result?.status !== "verified" ||
    result.operational !== true ||
    result.system_status !== 0 ||
    result.preservation?.profile !== binaryTerminalProfile ||
    result.preservation.identity_unchanged !== true ||
    result.preservation.other_configuration_preserved !== true ||
    !same(result.preservation.selected_edit, edit) ||
    result.published_input?.object_id !== c?.object_id ||
    result.published_input.present !== true ||
    !Array.isArray(result.published_input.properties)
  )
    return false;
  const values = new Map(
    result.published_input.properties.map((x: Data) => [x.property, x]),
  );
  if (
    values.size !== result.published_input.properties.length ||
    !result.published_input.properties.every(
      (x: Data) => x.matches === true && same(x.actual, x.expected),
    )
  )
    return false;
  for (const [pid, value] of [
    [31, `UI IN${edit.slot}`],
    [519, edit.slot],
    [4, c.stored_configuration.active_text],
    [46, c.stored_configuration.inactive_text],
    [931, c.stored_configuration.states_text_index],
    ...(c.stored_configuration.polarity === null
      ? []
      : [[84, c.stored_configuration.polarity]]),
  ]) {
    const row = values.get(pid) as Data | undefined;
    if (
      !row ||
      row.matches !== true ||
      row.actual !== value ||
      row.expected !== value
    )
      return false;
  }
  return true;
}
