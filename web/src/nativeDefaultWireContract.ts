import { connectionSame as same } from "./nativeConnectionContract";
import { rememberWireDraft } from "./nativeWireDrafts";

type Data = Record<string, any>;
export const defaultWireBase =
  "/bacnet/controller/native-application/inspection/default-wire";
export const defaultWireProfile = "native-effective-default-wire-compiler/1";
/** Defaults need no retained slot; release only this exact selection at capacity. */
export function rememberDefaultWireChoice(
  drafts: Map<string, string>,
  key: string,
  value: string,
  fallback: string,
) {
  if (value === fallback) {
    drafts.delete(key);
    return true;
  }
  return rememberWireDraft(drafts, key, value);
}
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max = 65535) =>
  Number.isInteger(v) && (v as number) >= 0 && (v as number) <= max;
const ref = (v: unknown) =>
  typeof v === "string" && v.length > 0 && v.length <= 512;
const filesMatch = (a: Data, b: Data) =>
  ["3", "11", "12"].every(
    (k) =>
      hash(a?.[k]?.sha256) &&
      integer(a?.[k]?.bytes, 8388608) &&
      a[k].sha256 === b?.[k]?.sha256 &&
      a[k].bytes === b?.[k]?.bytes,
  );
function envelope(value: Data, source: Data) {
  return (
    !!value &&
    value.profile === defaultWireProfile &&
    value.source_kind === "native-backup-archive" &&
    value.capture_id === source.capture_id &&
    value.snapshot_sha256 === source.snapshot_sha256 &&
    value.captured_at === source.captured_at &&
    same(value.target, { ...source.target, device: source.device }) &&
    same(value.identity, source.identity) &&
    value.source_identity_matches === true &&
    hash(value.source_sha256) &&
    value.sha256 === value.source_sha256 &&
    hash(value.effective_sha256) &&
    same(value.parameter_merge, source.parameter_merge) &&
    value.parameter_merge?.source_sha256 === value.source_sha256 &&
    value.parameter_merge?.output_sha256 === value.effective_sha256 &&
    value.parameter_merge?.static_sha256 === value.files?.["11"]?.sha256 &&
    value.parameter_merge?.dynamic_sha256 === value.files?.["12"]?.sha256 &&
    value.files?.["3"]?.sha256 === value.source_sha256 &&
    filesMatch(value.files, value.files) &&
    value.saved_settings_merged === true &&
    value.source_immutable === true &&
    [
      "controller_queries",
      "controller_write",
      "field_transfer_enabled",
      "can_apply",
      "field_actions",
      "identity_verified",
      "current_identity_verified",
    ].every((k) => value[k] === false)
  );
}
export function defaultWireSource(value: Data, source: Data) {
  return (
    envelope(value, source) &&
    same(value.fields, source.fields) &&
    Array.isArray(value.diagrams) &&
    value.diagrams.length <= 4096 &&
    new Set(value.diagrams.map((d: Data) => d?.ref)).size ===
      value.diagrams.length &&
    value.diagrams.every(
      (d: Data) =>
        d &&
        ref(d.ref) &&
        [536, 575].includes(d.class_id) &&
        typeof d.name === "string" &&
        hash(d.archive_record_sha256) &&
        hash(d.effective_record_sha256) &&
        integer(d.wire_count, 4096) &&
        typeof d.available === "boolean" &&
        (d.error === null || typeof d.error === "string") &&
        d.available === (d.wire_count > 0 && d.error === null),
    )
  );
}
export function defaultWireSelection(
  value: Data,
  source: Data,
  opened: Data,
  request: Data,
) {
  const s = value?.selection,
    diagram = opened.diagrams.find((d: Data) => d.ref === request.diagram_ref);
  if (
    !envelope(value, source) ||
    !same(value.request, request) ||
    value.source_sha256 !== opened.source_sha256 ||
    value.effective_sha256 !== opened.effective_sha256 ||
    !filesMatch(value.files, opened.files) ||
    !diagram ||
    !s ||
    s.diagram_ref !== diagram.ref ||
    s.record_sha256 !== diagram.effective_record_sha256 ||
    !hash(s.property_sha256) ||
    s.wire_index !== request.wire_index ||
    !integer(s.block_count, 512) ||
    !Array.isArray(s.wires) ||
    s.wires.length !== diagram.wire_count ||
    !Array.isArray(s.candidates) ||
    s.candidates.length > s.block_count ||
    typeof s.available !== "boolean" ||
    !same(s.selected_wire, s.wires[request.wire_index]) ||
    s.wires.some(
      (w: Data, i: number) =>
        !w ||
        w.index !== i ||
        !ref(w.source_ref) ||
        !ref(w.target_ref) ||
        !Array.isArray(w.old) ||
        w.old.length !== 4 ||
        !w.old.every((v: any) => integer(v)) ||
        !integer(w.old[0], s.block_count - 1) ||
        !integer(w.old[2], s.block_count - 1) ||
        w.source_port !== w.old[1] ||
        w.target_port !== w.old[3] ||
        !integer(w.source_index_offset, 8388608) ||
        ![1, 2, 3, 4].includes(w.source_index_bytes),
    ) ||
    new Set(s.candidates.map((c: Data) => c?.ref)).size !==
      s.candidates.length ||
    s.candidates.some(
      (c: Data) =>
        !c ||
        !ref(c.ref) ||
        !integer(c.index, s.block_count - 1) ||
        !integer(c.class_id) ||
        typeof c.name !== "string" ||
        typeof c.object !== "string" ||
        c.current_source !== (c.ref === s.selected_wire.source_ref),
    )
  )
    return false;
  return (
    s.candidates.some(
      (c: Data) =>
        c.ref === s.selected_wire.source_ref &&
        c.index === s.selected_wire.old[0],
    ) && s.available === s.candidates.length > 1
  );
}

function real(text: string) {
  if (
    !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(
      text.trim(),
    )
  )
    return null;
  const value = Number(text),
    data = new DataView(new ArrayBuffer(4));
  data.setFloat32(0, value, false);
  const stored = data.getFloat32(0, false);
  if (
    !Number.isFinite(value) ||
    !Number.isFinite(stored) ||
    (stored === 0 && text.split(/[eE]/)[0].replace(/[+\-.0\s]/g, "") !== "")
  )
    return null;
  return {
    value: stored,
    bits: Array.from(new Uint8Array(data.buffer), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join(""),
  };
}
export function defaultWireReview(
  value: Data,
  source: Data,
  opened: Data,
  selected: Data,
  request: Data,
  field: Data,
) {
  if (
    !envelope(value, source) ||
    !same(value.request, request) ||
    !hash(value.review_sha256) ||
    value.source_sha256 !== opened.source_sha256 ||
    value.effective_sha256 !== opened.effective_sha256 ||
    !filesMatch(value.files, opened.files)
  )
    return false;
  return defaultWireCompilation(
    value.compilation,
    opened,
    selected,
    request,
    field,
    value.output_sha256,
  );
}

/** Local report consistency only; this grants no review, export or field authority. */
export function defaultWireCompilation(
  c: Data,
  opened: Data,
  selected: Data,
  request: Data,
  field: Data,
  outputSha256: unknown,
) {
  const d = c?.selected_default,
    w = c?.selected_wire;
  const candidate = selected?.selection.candidates.find(
    (r: Data) => r.ref === request.source_ref,
  );
  const original = selected?.selection.selected_wire,
    expected = real(request.value_text);
  if (
    !c ||
    c.profile !== defaultWireProfile ||
    !filesMatch(c.files, opened.files) ||
    !same(c.parameter_merge, opened.parameter_merge) ||
    c.archive_sha256 !== opened.source_sha256 ||
    c.effective_sha256 !== opened.effective_sha256 ||
    c.effective_native_sha256 !== opened.parameter_merge.native_output_sha256 ||
    !hash(outputSha256) ||
    c.compiled_sha256 !== outputSha256 ||
    !hash(c.compiled_native_sha256) ||
    !integer(c.native_record_count, 20000) ||
    c.native_record_count <= selected.selection.block_count ||
    [
      "both_orders_identical",
      "disjoint_fields",
      "other_merged_bytes_preserved",
      "saved_settings_merged",
    ].some((k) => c[k] !== true) ||
    [
      "controller_queries",
      "controller_write",
      "field_transfer_enabled",
      "can_apply",
    ].some((k) => c[k] !== false) ||
    !expected ||
    !d ||
    d.profile !== "tagged-moi-signal-default-copy/1" ||
    d.source_sha256 !== opened.effective_sha256 ||
    d.native_source_sha256 !== c.effective_native_sha256 ||
    d.record_ref !== field.ref ||
    d.class_id !== field.class_id ||
    d.property !== 3113 ||
    d.encoded_sha256 !== field.encoded_sha256 ||
    d.value_text !== request.value_text ||
    d.before_bits !== field.effective_bits ||
    d.after_bits !== expected.bits ||
    !Object.is(d.before_value, field.effective_value) ||
    !Object.is(d.stored_value, expected.value) ||
    d.changed !== (field.effective_bits !== expected.bits) ||
    typeof d.decimal_precision_changed !== "boolean" ||
    !integer(d.native_byte_offset, 8388604) ||
    !hash(d.output_sha256) ||
    !hash(d.native_output_sha256) ||
    !candidate ||
    !original ||
    !w ||
    w.profile !== "tagged-moi-wire-source-copy/1" ||
    w.source_sha256 !== opened.effective_sha256 ||
    w.source_native_sha256 !== c.effective_native_sha256 ||
    w.diagram_ref !== request.diagram_ref ||
    w.record_sha256 !== request.effective_record_sha256 ||
    w.property_sha256 !== request.property_sha256 ||
    w.wire_index !== request.wire_index ||
    !same(w.old, request.old) ||
    !same(w.new, [candidate.index, ...request.old.slice(1)]) ||
    w.source_ref !== request.source_ref ||
    w.old_source_ref !== original.source_ref ||
    w.target_ref !== original.target_ref ||
    w.source_class !== candidate.class_id ||
    w.source_index_offset !== original.source_index_offset ||
    w.source_index_bytes !== original.source_index_bytes ||
    w.changed !== (request.source_ref !== original.source_ref) ||
    w.other_expanded_bytes_preserved !== true ||
    w.native_structure_readback_verified !== true ||
    w.controller_write !== false ||
    w.field_transfer_enabled !== false ||
    !hash(w.output_sha256) ||
    !hash(w.output_native_sha256) ||
    !(
      d.native_byte_offset + 4 <= w.source_index_offset ||
      w.source_index_offset + w.source_index_bytes <= d.native_byte_offset
    )
  )
    return false;
  const sd = c.independent_default,
    sw = c.independent_wire;
  const forward = c.default_then_wire,
    reverse = c.wire_then_default;
  if (
    !sd ||
    sd.profile !== "native-effective-signal-default-compiler/1" ||
    !same(sd.selected_edit, d) ||
    !sw ||
    sw.profile !== "native-effective-wire-source-compiler/1" ||
    !same(sw.wire_edit, w) ||
    !forward ||
    forward.intermediate_sha256 !== sd.compiled_sha256 ||
    sd.compiled_sha256 !== d.output_sha256 ||
    !reverse ||
    reverse.intermediate_sha256 !== sw.compiled_sha256 ||
    sw.compiled_sha256 !== w.output_sha256
  )
    return false;
  for (const independent of [sd, sw])
    if (
      !filesMatch(independent.files, opened.files) ||
      !same(independent.parameter_merge, opened.parameter_merge) ||
      independent.other_merged_bytes_preserved !== true ||
      independent.controller_write !== false ||
      independent.field_transfer_enabled !== false
    )
      return false;
  const fw = forward.wire_edit,
    rd = reverse.default_edit;
  return (
    !!fw &&
    !!rd &&
    fw.source_sha256 === forward.intermediate_sha256 &&
    fw.source_native_sha256 === d.native_output_sha256 &&
    rd.source_sha256 === reverse.intermediate_sha256 &&
    rd.native_source_sha256 === w.output_native_sha256 &&
    fw.output_sha256 === outputSha256 &&
    rd.output_sha256 === outputSha256 &&
    fw.output_native_sha256 === c.compiled_native_sha256 &&
    rd.native_output_sha256 === c.compiled_native_sha256 &&
    [
      "diagram_ref",
      "record_sha256",
      "property_sha256",
      "wire_index",
      "old",
      "new",
      "old_source_ref",
      "source_ref",
      "target_ref",
      "source_class",
      "source_index_offset",
      "source_index_bytes",
      "changed",
    ].every((k) => same(fw[k], w[k])) &&
    [
      "record_ref",
      "class_id",
      "property",
      "encoded_sha256",
      "value_text",
      "before_bits",
      "after_bits",
      "native_byte_offset",
      "changed",
    ].every((k) => same(rd[k], d[k])) &&
    fw.other_expanded_bytes_preserved === true &&
    fw.native_structure_readback_verified === true &&
    fw.controller_write === false &&
    fw.field_transfer_enabled === false &&
    rd.controller_write === false
  );
}
