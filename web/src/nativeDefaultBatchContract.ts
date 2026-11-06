import { connectionSame as same } from "./nativeConnectionContract";
type Data = Record<string, any>;
export const defaultBatchProfile = "native-effective-default-batch-compiler/1";
export const defaultBatchBase =
  "/bacnet/controller/native-application/inspection/default-batch";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: any, max = 8 * 1024 * 1024) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const object = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const profiles: Record<string, string> = {
  real: "native-effective-signal-default-compiler/1",
  boolean: "native-effective-boolean-default-compiler/1",
  enum: "native-effective-enum-default-compiler/1",
};
const editProfiles: Record<string, string> = {
  real: "tagged-moi-signal-default-copy/1",
  boolean: "tagged-moi-boolean-default-copy/1",
  enum: "tagged-moi-enum-default-copy/1",
};
const commonKeys = [
  "profile",
  "scope",
  "source_kind",
  "capture_id",
  "snapshot_sha256",
  "captured_at",
  "target",
  "identity",
  "source_identity_matches",
  "source_identity_error",
  "sha256",
  "files",
  "read_only",
  "controller_queries",
  "field_actions",
  "identity_verified",
  "source_sha256",
  "effective_sha256",
  "parameter_merge",
  "edit_limit",
  "source_immutable",
  "saved_settings_merged",
  "current_identity_verified",
  "controller_write",
  "field_transfer_enabled",
  "can_apply",
];
function bits(number: number) {
  const view = new DataView(new ArrayBuffer(4));
  view.setFloat32(0, number, false);
  return view.getUint32(0, false).toString(16).padStart(8, "0");
}
function real(text: unknown) {
  if (
    typeof text !== "string" ||
    !text.length ||
    text.length > 128 ||
    !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(
      text.trim(),
    )
  )
    return null;
  const value = Number(text),
    stored = Math.fround(value);
  if (
    !Number.isFinite(value) ||
    !Number.isFinite(stored) ||
    (stored === 0 && text.split(/[eE]/)[0].replace(/[+\-.0\s]/g, "") !== "")
  )
    return null;
  return { bits: bits(stored), value: stored };
}
function taggedEnum(hex: any, value: number) {
  return (
    typeof hex === "string" &&
    /^9[1-4](?:[a-f0-9]{2}){1,4}2f$/.test(hex) &&
    hex.length === (Number(hex[1]) + 2) * 2 &&
    Number.parseInt(hex.slice(2, -2), 16) === value
  );
}
function fieldRow(row: Data, files: Data) {
  if (
    !object(row, ["kind", "profile", "name", "field"]) ||
    row.profile !== profiles[row.kind] ||
    typeof row.name !== "string" ||
    row.name.length > 4096
  )
    return false;
  const f = row.field;
  if (
    !f ||
    typeof f.ref !== "string" ||
    !f.ref.length ||
    f.ref.length > 512 ||
    !hash(f.encoded_sha256) ||
    f.property !== 3113 ||
    typeof f.saved_value_differs !== "boolean"
  )
    return false;
  const common = [
    "ref",
    "class_id",
    "property",
    "encoded_sha256",
    "archive_value",
    "effective_value",
    "saved_value_differs",
  ];
  if (row.kind === "real")
    return (
      object(f, [...common, "archive_bits", "effective_bits"]) &&
      [526, 527].includes(f.class_id) &&
      ["archive", "effective"].every(
        (k) =>
          Number.isFinite(f[k + "_value"]) &&
          bits(f[k + "_value"]) === f[k + "_bits"],
      )
    );
  if (row.kind === "boolean")
    return (
      object(f, [...common, "datatype"]) &&
      f.datatype === "Boolean" &&
      [530, 531].includes(f.class_id) &&
      typeof f.archive_value === "boolean" &&
      typeof f.effective_value === "boolean"
    );
  if (
    row.kind !== "enum" ||
    !object(f, [
      ...common,
      "datatype",
      "saved_storage",
      "maximum_code",
      "states_text_evidence",
      "states_text_encoded_sha256",
      "enum_semantics_verified",
    ]) ||
    f.datatype !== "Enumerated" ||
    ![528, 529].includes(f.class_id) ||
    ![f.archive_value, f.effective_value, f.maximum_code].every((v) =>
      integer(v, 4294967295),
    ) ||
    f.effective_value > f.maximum_code ||
    f.enum_semantics_verified !== false ||
    !(
      f.states_text_encoded_sha256 === null ||
      hash(f.states_text_encoded_sha256)
    )
  )
    return false;
  const storage = f.saved_storage;
  return storage === null
    ? f.maximum_code === 4294967295
    : object(storage, [
        "kind",
        "datatype",
        "bytes",
        "maximum_code",
        "static_record_offset",
        "dynamic_value_offset",
      ]) &&
        storage.kind === "captured-fixed-enum-slot" &&
        storage.datatype === 9 &&
        storage.bytes === 2 &&
        storage.maximum_code === 65535 &&
        f.maximum_code === 65535 &&
        integer(storage.static_record_offset) &&
        storage.static_record_offset + 16 <= files["11"].bytes &&
        integer(storage.dynamic_value_offset) &&
        storage.dynamic_value_offset + 3 <= files["12"].bytes;
}
export function defaultBatchSource(data: Data, source: Data) {
  try {
    return (
      object(data, [...commonKeys, "fields"]) &&
      data.profile === defaultBatchProfile &&
      typeof data.scope === "string" &&
      data.scope.length > 0 &&
      data.source_kind === "native-backup-archive" &&
      data.capture_id === source.capture_id &&
      data.snapshot_sha256 === source.snapshot_sha256 &&
      data.captured_at === source.captured_at &&
      same(data.target, { ...source.target, device: source.device }) &&
      same(data.identity, source.identity) &&
      data.identity?.["vendor-identifier"] === 5 &&
      data.source_identity_matches === true &&
      data.source_identity_error === null &&
      data.read_only === true &&
      data.identity_verified === false &&
      data.current_identity_verified === false &&
      data.controller_queries === false &&
      data.controller_write === false &&
      data.field_actions === false &&
      data.field_transfer_enabled === false &&
      data.can_apply === false &&
      data.source_immutable === true &&
      data.saved_settings_merged === true &&
      data.edit_limit === 16 &&
      same(data.parameter_merge, source.parameter_merge) &&
      object(data.files, ["3", "11", "12"]) &&
      ["3", "11", "12"].every(
        (k) =>
          object(data.files[k], ["sha256", "bytes"]) &&
          hash(data.files[k].sha256) &&
          integer(data.files[k].bytes, 2 * 1024 * 1024),
      ) &&
      data.sha256 === data.source_sha256 &&
      data.source_sha256 === data.files["3"].sha256 &&
      data.parameter_merge.source_sha256 === data.files["3"].sha256 &&
      data.parameter_merge.static_sha256 === data.files["11"].sha256 &&
      data.parameter_merge.dynamic_sha256 === data.files["12"].sha256 &&
      data.parameter_merge.output_sha256 === data.effective_sha256 &&
      hash(data.parameter_merge.native_output_sha256) &&
      Array.isArray(data.fields) &&
      data.fields.length <= 4096 &&
      data.fields.every((r: Data) => fieldRow(r, data.files)) &&
      new Set(data.fields.map((r: Data) => r.field.ref)).size ===
        data.fields.length
    );
  } catch {
    return false;
  }
}
export function defaultBatchRequest(
  source: Data,
  opened: Data,
  drafts: Record<string, string>,
) {
  const refs = Object.keys(drafts);
  if (!refs.length || refs.length > 16)
    throw new Error("Select 1–16 existing defaults for this local copy.");
  const changes = refs.map((ref) => {
    const row = opened.fields.find((r: Data) => r.field.ref === ref);
    if (!row)
      throw new Error(
        "A selected field is unavailable in this retained source.",
      );
    const kind = row.kind,
      text = drafts[ref],
      f = row.field;
    const base = { kind, record_ref: ref, encoded_sha256: f.encoded_sha256 };
    if (kind === "real") {
      if (!real(text))
        throw new Error(`Enter finite float32 decimal text for ${ref}.`);
      return { ...base, value_text: text };
    }
    if (kind === "boolean") {
      if (!["true", "false"].includes(text))
        throw new Error(`Choose true or false for ${ref}.`);
      return { ...base, value: text === "true" };
    }
    if (
      !/^[0-9]{1,10}$/.test(text.trim()) ||
      !integer(Number(text), f.maximum_code)
    )
      throw new Error(
        `Enter a numeric Enum code within 0–${f.maximum_code} for ${ref}. Meanings remain unverified.`,
      );
    return { ...base, value: Number(text) };
  });
  return {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: opened.source_sha256,
    effective_sha256: opened.effective_sha256,
    changes,
  };
}
function editMatches(edit: Data, change: Data, f: Data, selected: Data) {
  const keys = [
    "profile",
    "scope",
    "source_sha256",
    "native_source_sha256",
    "record_ref",
    "class_id",
    "property",
    "encoded_sha256",
    "controller_write",
    "changed",
    "plan_sha256",
    "output_sha256",
  ];
  const extra =
    change.kind === "real"
      ? [
          "value_text",
          "before_value",
          "stored_value",
          "before_bits",
          "after_bits",
          "native_byte_offset",
          "decimal_precision_changed",
          "numeric_policy",
          "native_output_sha256",
        ]
      : change.kind === "boolean"
        ? [
            "datatype",
            "before_value",
            "after_value",
            "before_tag",
            "after_tag",
            "native_byte_offset",
            "saved_settings_merged",
          ]
        : [
            "datatype",
            "before_value",
            "after_value",
            "before_encoding_hex",
            "after_encoding_hex",
            "before_value_width",
            "after_value_width",
            "states_text_evidence",
            "enum_semantics_verified",
            "saved_settings_merged",
            "unrelated_native_bytes_preserved",
          ];
  if (!object(edit, [...keys, ...extra])) return false;
  if (
    !edit ||
    edit.profile !== editProfiles[change.kind] ||
    edit.record_ref !== change.record_ref ||
    edit.class_id !== f.class_id ||
    edit.property !== 3113 ||
    edit.encoded_sha256 !== f.encoded_sha256 ||
    edit.controller_write !== false ||
    !hash(edit.source_sha256) ||
    !hash(edit.native_source_sha256) ||
    !hash(edit.plan_sha256) ||
    !hash(edit.output_sha256) ||
    edit.changed !== selected.changed
  )
    return false;
  if (change.kind === "real") {
    const wanted = real(change.value_text);
    return (
      !!wanted &&
      edit.value_text === change.value_text &&
      Object.is(edit.before_value, f.effective_value) &&
      typeof edit.decimal_precision_changed === "boolean" &&
      typeof edit.numeric_policy === "string" &&
      edit.before_bits === f.effective_bits &&
      edit.after_bits === wanted.bits &&
      Object.is(edit.stored_value, wanted.value) &&
      selected.before_encoding_hex === "44" + f.effective_bits + "2f" &&
      selected.after_encoding_hex === "44" + wanted.bits + "2f" &&
      edit.changed === (f.effective_bits !== wanted.bits) &&
      integer(edit.native_byte_offset) &&
      hash(edit.native_output_sha256)
    );
  }
  if (change.kind === "boolean")
    return (
      edit.datatype === "Boolean" &&
      edit.before_value === f.effective_value &&
      edit.after_value === change.value &&
      edit.before_tag === (f.effective_value ? "11" : "10") &&
      edit.after_tag === (change.value ? "11" : "10") &&
      selected.before_encoding_hex === edit.before_tag + "2f" &&
      selected.after_encoding_hex === edit.after_tag + "2f" &&
      edit.changed === (f.effective_value !== change.value) &&
      edit.saved_settings_merged === false &&
      integer(edit.native_byte_offset)
    );
  return (
    edit.datatype === "Enumerated" &&
    edit.before_value === f.effective_value &&
    edit.after_value === change.value &&
    taggedEnum(edit.before_encoding_hex, edit.before_value) &&
    taggedEnum(edit.after_encoding_hex, change.value) &&
    selected.before_encoding_hex === edit.before_encoding_hex &&
    selected.after_encoding_hex === edit.after_encoding_hex &&
    edit.before_value_width === Number(edit.before_encoding_hex[1]) &&
    edit.after_value_width === Number(edit.after_encoding_hex[1]) &&
    edit.after_value_width >= edit.before_value_width &&
    edit.changed === (f.effective_value !== change.value) &&
    edit.enum_semantics_verified === false &&
    edit.saved_settings_merged === false &&
    edit.unrelated_native_bytes_preserved === true &&
    same(edit.states_text_evidence, f.states_text_evidence)
  );
}
export function defaultBatchReview(data: Data, opened: Data, request: Data) {
  try {
    if (
      !object(data, [
        ...commonKeys,
        "request",
        "compilation",
        "output_sha256",
        "review_sha256",
      ]) ||
      !commonKeys.every((k) => same(data[k], opened[k])) ||
      !same(data.request, request) ||
      !hash(data.review_sha256) ||
      !hash(data.output_sha256)
    )
      return false;
    const c = data.compilation,
      edits = request.changes,
      count = edits.length;
    if (
      !object(c, [
        "profile",
        "scope",
        "files",
        "parameter_merge",
        "effective_sha256",
        "effective_native_sha256",
        "compiled_sha256",
        "compiled_native_sha256",
        "compiled_native_bytes",
        "effective_native_bytes",
        "native_record_count",
        "edit_count",
        "changed_count",
        "selected",
        "independent",
        "forward",
        "reverse",
        "both_orders_identical",
        "other_merged_bytes_preserved",
        "saved_settings_merged",
        "enum_semantics_verified",
        "controller_queries",
        "controller_write",
        "field_transfer_enabled",
      ])
    )
      return false;
    if (
      !c ||
      c.profile !== defaultBatchProfile ||
      c.scope !== opened.scope ||
      !same(c.files, opened.files) ||
      !same(c.parameter_merge, opened.parameter_merge) ||
      c.effective_sha256 !== opened.effective_sha256 ||
      c.effective_native_sha256 !==
        opened.parameter_merge.native_output_sha256 ||
      c.compiled_sha256 !== data.output_sha256 ||
      !hash(c.compiled_native_sha256) ||
      !integer(c.compiled_native_bytes) ||
      !integer(c.effective_native_bytes) ||
      !integer(c.native_record_count, 20000) ||
      c.native_record_count < count ||
      c.edit_count !== count ||
      !integer(c.changed_count, 16) ||
      c.other_merged_bytes_preserved !== true ||
      c.both_orders_identical !== true ||
      c.saved_settings_merged !== true ||
      c.enum_semantics_verified !== false ||
      c.controller_queries !== false ||
      c.controller_write !== false ||
      c.field_transfer_enabled !== false ||
      ![c.selected, c.independent, c.forward, c.reverse].every(
        (a) => Array.isArray(a) && a.length === count,
      ) ||
      count < 1 ||
      count > 16 ||
      new Set(edits.map((e: Data) => e.record_ref)).size !== count
    )
      return false;
    for (let i = 0; i < count; i++) {
      const change = edits[i],
        row = opened.fields.find(
          (r: Data) =>
            r.kind === change.kind && r.field.ref === change.record_ref,
        ),
        s = c.selected[i],
        independent = c.independent[i];
      if (
        !object(s, [
          "kind",
          "record_ref",
          "class_id",
          "property",
          "encoded_sha256",
          "before_encoding_hex",
          "after_encoding_hex",
          "before_record_sha256",
          "independent_after_record_sha256",
          "original_value_start_offset",
          "original_value_end_offset",
          "changed",
          "enum_semantics_verified",
        ])
      )
        return false;
      if (
        !row ||
        !object(independent, ["kind", "record_ref", "compilation"]) ||
        independent.kind !== change.kind ||
        independent.record_ref !== change.record_ref ||
        !s ||
        s.kind !== change.kind ||
        s.record_ref !== change.record_ref ||
        s.class_id !== row.field.class_id ||
        s.property !== 3113 ||
        s.encoded_sha256 !== change.encoded_sha256 ||
        s.enum_semantics_verified !== false ||
        !hash(s.before_record_sha256) ||
        !hash(s.independent_after_record_sha256) ||
        !integer(s.original_value_start_offset) ||
        !integer(s.original_value_end_offset) ||
        s.original_value_end_offset <= s.original_value_start_offset ||
        s.original_value_end_offset > c.effective_native_bytes ||
        s.changed !== (s.before_encoding_hex !== s.after_encoding_hex)
      )
        return false;
      const p = independent.compilation;
      const compiledKeys = [
        "profile",
        "scope",
        "files",
        "parameter_merge",
        "selected_edit",
        "compiled_sha256",
        "compiled_native_sha256",
        "native_record_count",
        "other_merged_bytes_preserved",
        "controller_write",
        "field_transfer_enabled",
      ];
      if (
        !object(p, [
          ...compiledKeys,
          ...(change.kind === "real"
            ? ["selected_field_changed"]
            : change.kind === "boolean"
              ? ["saved_settings_merged"]
              : [
                  "saved_settings_merged",
                  "saved_storage",
                  "maximum_code",
                  "enum_semantics_verified",
                ]),
        ])
      )
        return false;
      if (
        !p ||
        p.profile !== profiles[change.kind] ||
        !same(p.files, opened.files) ||
        !same(p.parameter_merge, opened.parameter_merge) ||
        p.other_merged_bytes_preserved !== true ||
        p.controller_write !== false ||
        p.field_transfer_enabled !== false ||
        p.native_record_count !== c.native_record_count ||
        !hash(p.compiled_sha256) ||
        !hash(p.compiled_native_sha256) ||
        !editMatches(p.selected_edit, change, row.field, s) ||
        p.selected_edit.source_sha256 !== opened.effective_sha256 ||
        p.selected_edit.native_source_sha256 !== c.effective_native_sha256 ||
        p.selected_edit.output_sha256 !== p.compiled_sha256
      )
        return false;
      if (
        change.kind === "enum" &&
        (p.enum_semantics_verified !== false ||
          p.saved_settings_merged !== true ||
          p.maximum_code !== row.field.maximum_code ||
          !same(p.saved_storage, row.field.saved_storage) ||
          change.value > row.field.maximum_code)
      )
        return false;
      if (change.kind === "boolean" && p.saved_settings_merged !== true)
        return false;
      if (
        change.kind === "real" &&
        (p.selected_field_changed !== s.changed ||
          p.selected_edit.native_output_sha256 !== p.compiled_native_sha256 ||
          p.selected_edit.native_byte_offset !==
            s.original_value_start_offset + 1)
      )
        return false;
    }
    for (const [steps, order] of [
      [c.forward, edits],
      [c.reverse, [...edits].reverse()],
    ]) {
      let previous = opened.effective_sha256;
      for (const [index, step] of (steps as Data[]).entries()) {
        const change = order[index],
          row = opened.fields.find(
            (r: Data) => r.field.ref === change.record_ref,
          ),
          selected = c.selected.find(
            (r: Data) => r.record_ref === change.record_ref,
          );
        if (
          !object(step, ["kind", "record_ref", "edit"]) ||
          step.kind !== change.kind ||
          step.record_ref !== change.record_ref ||
          !editMatches(step.edit, change, row.field, selected) ||
          step.edit.source_sha256 !== previous
        )
          return false;
        previous = step.edit.output_sha256;
      }
      if (previous !== c.compiled_sha256) return false;
    }
    return (
      c.changed_count === c.selected.filter((r: Data) => r.changed).length &&
      (c.changed_count > 0 || c.compiled_sha256 === c.effective_sha256)
    );
  } catch {
    return false;
  }
}
