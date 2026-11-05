import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";

type Data = Record<string, any>;
export type TerminalBasis = "archive" | "effective";
const compilerProfile = "tagged-moi-local-terminal-copy/1";
const profile = (basis: TerminalBasis) =>
  basis === "effective"
    ? "native-effective-local-terminal-copy/1"
    : "native-archive-local-terminal-copy/1";
export const terminalBase = (basis: TerminalBasis) =>
  "/bacnet/controller/native-application/inputs/" +
  (basis === "effective" ? "effective-" : "") +
  "terminal-copy";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max: number) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const ref = (v: unknown) =>
  typeof v === "string" && v.length > 0 && v.length <= 512;

export function terminalArchive(
  v: Data,
  selected: Data,
): v is NativeArchiveSource & Data {
  return (
    !!v &&
    v.profile === "native-backup-record-inspection/1" &&
    v.source_kind === "native-backup-archive" &&
    v.capture_id === selected.id &&
    v.snapshot_sha256 === selected.evidence_sha256 &&
    hash(v.sha256) &&
    !!v.target &&
    controllerKey(v.target) ===
      controllerKey({ ...selected.target, device: selected.device }) &&
    same(v.identity, selected.identity) &&
    !!v.files &&
    ["3", "11", "12"].every(
      (k) =>
        hash(v.files[k]?.sha256) && integer(v.files[k]?.bytes, 8 * 1024 * 1024),
    ) &&
    v.files["3"].sha256 === v.sha256 &&
    v.read_only === true &&
    v.controller_queries === false &&
    v.field_actions === false &&
    v.identity_verified === false
  );
}

function envelope(v: Data, source: NativeArchiveSource, basis: TerminalBasis) {
  if (
    !v ||
    v.profile !== profile(basis) ||
    v.compiler_profile !== compilerProfile ||
    v.source_kind !== "native-backup-archive" ||
    v.capture_id !== source.capture_id ||
    v.snapshot_sha256 !== source.snapshot_sha256 ||
    v.sha256 !== source.sha256 ||
    v.source_sha256 !== source.sha256 ||
    !v.target ||
    controllerKey(v.target) !== controllerKey(source.target) ||
    !same(v.files, source.files) ||
    typeof v.scope !== "string" ||
    v.source_immutable !== true ||
    v.read_only !== true ||
    v.controller_queries !== false ||
    v.field_actions !== false ||
    v.identity_verified !== false ||
    v.current_identity_verified !== false ||
    v.saved_settings_merged !== (basis === "effective") ||
    v.controller_write !== false ||
    v.field_transfer_enabled !== false ||
    v.can_apply !== false
  )
    return false;
  if (basis === "archive") return true;
  const p = v.parameter_merge;
  return (
    hash(v.effective_sha256) &&
    !!p &&
    p.source_sha256 === source.sha256 &&
    p.output_sha256 === v.effective_sha256 &&
    p.static_sha256 === source.files["11"].sha256 &&
    p.dynamic_sha256 === source.files["12"].sha256 &&
    hash(p.native_output_sha256) &&
    integer(p.matched_parameters, 20000) &&
    Array.isArray(p.changed_parameters) &&
    p.changed_parameters.length <= p.matched_parameters &&
    Array.isArray(p.retained_runtime_parameters) &&
    p.retained_runtime_parameters.length <= 20000 &&
    p.vendor_runtime_required === false
  );
}

export function terminalSource(
  v: Data,
  source: NativeArchiveSource,
  basis: TerminalBasis,
) {
  if (!envelope(v, source, basis)) return false;
  const s = v.inventory,
    c = s?.controller,
    slots = s?.hardware?.capacity?.universal_inputs;
  if (
    !s ||
    s.profile !== compilerProfile ||
    typeof s.scope !== "string" ||
    s.source_sha256 !==
      (basis === "effective" ? v.effective_sha256 : source.sha256) ||
    s.controller_write !== false ||
    s.field_transfer_enabled !== false ||
    !c ||
    c.source_sha256 !== s.source_sha256 ||
    !hash(c.native_sha256) ||
    typeof c.name !== "string" ||
    typeof c.model !== "string" ||
    !integer(c.instance, 4194302) ||
    `device,${c.instance}` !== source.target.device ||
    !ref(c.root_ref) ||
    !integer(c.root_class, 1023) ||
    !["gzip-moi-v2", "moi-v2"].includes(c.encoding) ||
    ![
      [60, 60],
      [62, 62],
      [66, 65],
    ].some(
      ([a, b]) => c.format_versions?.acs === a && c.format_versions?.dmcs === b,
    ) ||
    !Array.isArray(slots) ||
    ![3, 6].includes(slots.length) ||
    slots.some((n, i) => n !== i + 1) ||
    !Array.isArray(s.inputs) ||
    !s.inputs.length ||
    s.inputs.length > 16 ||
    !Array.isArray(s.unassigned_slots)
  )
    return false;
  const refs = new Set<string>(),
    objects = new Set<string>(),
    occupied = new Set<number>();
  for (const p of s.inputs) {
    if (
      !p ||
      !ref(p.ref) ||
      ![240, 242].includes(p.class_id) ||
      typeof p.object !== "string" ||
      !(p.name === null || typeof p.name === "string") ||
      !new RegExp(
        `^${p.class_id === 240 ? "analog" : "binary"}-input,[0-9]+$`,
      ).test(p.object) ||
      !hash(p.record_sha256) ||
      !hash(p.slot_property_sha256) ||
      !hash(p.device_type_property_sha256) ||
      (basis === "effective" && !hash(p.archive_record_sha256)) ||
      refs.has(p.ref) ||
      objects.has(p.object) ||
      occupied.has(p.slot)
    )
      return false;
    const kind = p.class_id === 240 ? 0 : 3,
      instance = Number(p.object.split(",")[1]);
    if (
      !integer(instance, 4194302) ||
      p.ref !== `${c.root_ref}/${kind}_${instance}`
    )
      return false;
    if (p.internal === true) {
      if (
        p.movable !== false ||
        p.class_id !== 240 ||
        p.slot !== 4 ||
        p.device_type !== "AI1-Int" ||
        slots.length !== 3
      )
        return false;
    } else if (
      p.internal !== false ||
      p.movable !== true ||
      !slots.includes(p.slot) ||
      p.device_type !== `UI IN${p.slot}`
    )
      return false;
    refs.add(p.ref);
    objects.add(p.object);
    occupied.add(p.slot);
  }
  return (
    s.inputs.some((p: Data) => p.movable) &&
    same(
      s.unassigned_slots,
      slots.filter((n) => !occupied.has(n)),
    )
  );
}

export function terminalProposal(
  source: Data,
  query: Data,
  row: Data,
  destination: number,
  basis: TerminalBasis,
) {
  return {
    ...query,
    ref: row.ref,
    record_sha256:
      basis === "effective" ? row.archive_record_sha256 : row.record_sha256,
    slot_property_sha256: row.slot_property_sha256,
    device_type_property_sha256: row.device_type_property_sha256,
    old_slot: row.slot,
    destination_slot: destination,
    ...(basis === "effective"
      ? {
          effective_sha256: source.effective_sha256,
          effective_record_sha256: row.record_sha256,
        }
      : {}),
  };
}

export async function terminalReview(
  v: Data,
  source: NativeArchiveSource,
  request: Data,
  loaded: Data,
  basis: TerminalBasis,
) {
  if (
    !terminalSource(loaded, source, basis) ||
    !envelope(v, source, basis) ||
    !same(v.request, request) ||
    !hash(v.output_sha256) ||
    !hash(v.review_sha256)
  )
    return false;
  const row = loaded.inventory.inputs.find((p: Data) => p.ref === request.ref);
  if (
    !row?.movable ||
    request.old_slot !== row.slot ||
    !Number.isSafeInteger(request.destination_slot) ||
    !loaded.inventory.unassigned_slots.includes(request.destination_slot) ||
    !same(
      request,
      terminalProposal(
        loaded,
        {
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
          source_sha256: source.sha256,
        },
        row,
        request.destination_slot,
        basis,
      ),
    )
  )
    return false;
  const c = v.compilation,
    effective = basis === "effective",
    edit = effective ? c?.terminal_edit : c;
  if (
    effective &&
    (!c ||
      c.profile !== profile(basis) ||
      typeof c.scope !== "string" ||
      !same(c.files, source.files) ||
      !same(c.parameter_merge, loaded.parameter_merge) ||
      !same(v.parameter_merge, loaded.parameter_merge) ||
      v.effective_sha256 !== loaded.effective_sha256 ||
      c.archive_sha256 !== source.sha256 ||
      c.effective_sha256 !== loaded.effective_sha256 ||
      c.compiled_sha256 !== v.output_sha256 ||
      c.compiled_native_sha256 !== edit?.output_native_sha256 ||
      !integer(c.native_record_count, 20000) ||
      c.native_record_count !== loaded.inventory.controller.record_count ||
      c.other_merged_bytes_preserved !== true ||
      c.saved_settings_merged !== true ||
      c.controller_write !== false ||
      c.field_transfer_enabled !== false ||
      !hash(c.compilation_sha256))
  )
    return false;
  if (
    !edit ||
    edit.profile !== compilerProfile ||
    typeof edit.scope !== "string" ||
    edit.source_sha256 !== loaded.inventory.source_sha256 ||
    edit.source_native_sha256 !== loaded.inventory.controller.native_sha256 ||
    edit.ref !== row.ref ||
    edit.record_sha256 !== row.record_sha256 ||
    edit.slot_property_sha256 !== row.slot_property_sha256 ||
    edit.device_type_property_sha256 !== row.device_type_property_sha256 ||
    edit.object !== row.object ||
    edit.old_slot !== row.slot ||
    edit.destination_slot !== request.destination_slot ||
    edit.old_device_type !== row.device_type ||
    edit.new_device_type !== `UI IN${request.destination_slot}` ||
    edit.changed !== true ||
    edit.output_sha256 !== v.output_sha256 ||
    !hash(edit.output_native_sha256) ||
    !hash(edit.compilation_sha256) ||
    edit.other_expanded_bytes_preserved !== true ||
    edit.native_structure_readback_verified !== true ||
    edit.identities_modes_graph_and_record_framing_preserved !== true ||
    edit.saved_settings_merged !== false ||
    edit.controller_write !== false ||
    edit.field_transfer_enabled !== false ||
    edit.physical_terminal_or_wiring_verified !== false ||
    !Array.isArray(edit.payloads) ||
    edit.payloads.length !== 2
  )
    return false;
  const [slot, label] = edit.payloads,
    oldLabel = Array.from(
      new TextEncoder().encode("\0" + row.device_type),
      (x) => x.toString(16).padStart(2, "0"),
    ).join(""),
    newLabel = Array.from(
      new TextEncoder().encode("\0" + edit.new_device_type),
      (x) => x.toString(16).padStart(2, "0"),
    ).join("");
  if (
    !slot ||
    !label ||
    !integer(slot.offset, 8 * 1024 * 1024) ||
    !integer(label.offset, 8 * 1024 * 1024) ||
    slot.offset < 14 ||
    label.offset < 14 ||
    typeof slot.before !== "string" ||
    !/^(?:[a-f0-9]{2}){1,4}$/.test(slot.before) ||
    typeof slot.after !== "string" ||
    slot.after !==
      request.destination_slot.toString(16).padStart(slot.before.length, "0") ||
    Number.parseInt(slot.before, 16) !== row.slot ||
    label.before !== oldLabel ||
    label.after !== newLabel ||
    !(
      slot.offset + slot.before.length / 2 <= label.offset ||
      label.offset + oldLabel.length / 2 <= slot.offset
    )
  )
    return false;
  const { compilation_sha256, ...editBody } = edit;
  if ((await connectionSeal(editBody)) !== compilation_sha256) return false;
  if (effective) {
    const { compilation_sha256, ...body } = c;
    if ((await connectionSeal(body)) !== compilation_sha256) return false;
  }
  const { review_sha256, ...body } = v;
  return (await connectionSeal(body)) === review_sha256;
}
