import { sha256Text } from "./activityContracts";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { isSourceNumber, parseSourceJSON } from "./programSource";
import { controllerKey } from "./workflow";

type Data = Record<string, any>;
export const TERMINAL_TRANSFER_PROFILE =
  "native-local-universal-input-transfer/2";
export const inputTransferProfile = (edit: Data) =>
  edit.action === "terminal"
    ? TERMINAL_TRANSFER_PROFILE
    : "native-local-universal-input-transfer/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max: number) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
// Python review seals retain numeric tokens. JSON.parse/stringify cannot retain
// 1.0, signed zero or integers above binary64; sort decoded keys by code point.
function canonical(v: any): string {
  if (isSourceNumber(v)) return v.token;
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  const string = (s: string) =>
    JSON.stringify(s).replace(
      /[\u007f-\uffff]/g,
      (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
    );
  if (v && typeof v === "object") {
    const compare = (a: string, b: string) => {
      const x = [...a],
        y = [...b];
      for (let i = 0; i < Math.min(x.length, y.length); i++) {
        const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!;
        if (d) return d;
      }
      return x.length - y.length;
    };
    return (
      "{" +
      Object.keys(v)
        .sort(compare)
        .map((k) => string(k) + ":" + canonical(v[k]))
        .join(",") +
      "}"
    );
  }
  if (typeof v === "string") return string(v);
  if (v === null || typeof v === "boolean") return JSON.stringify(v);
  throw Error("Unsupported exact terminal review value.");
}
export async function terminalDocumentSeal(blob: Blob, field: boolean) {
  const raw = parseSourceJSON(await blob.text());
  if (!raw || Array.isArray(raw) || !hash(raw.review_sha256)) return false;
  const { review_sha256, token, ...body } = raw;
  if (
    field &&
    (typeof token !== "string" || !/^[A-Za-z0-9_-]{32}$/.test(token))
  )
    return false;
  if (!field && token !== undefined) return false;
  return (await sha256Text(canonical(body))) === review_sha256;
}

export async function terminalEvidenceSeal(blob: Blob) {
  const raw = parseSourceJSON(await blob.text());
  if (!raw || Array.isArray(raw) || !hash(raw.evidence_sha256)) return false;
  const { evidence_sha256, ...body } = raw;
  return (await sha256Text(canonical(body))) === evidence_sha256;
}

export async function terminalCopyDocumentSeals(
  document: { data: Data; blob: Blob },
  effective: boolean,
) {
  const text = await document.blob.text(),
    raw = parseSourceJSON(text);
  if (
    !raw ||
    Array.isArray(raw) ||
    raw.token !== undefined ||
    !same(JSON.parse(text), document.data)
  )
    return false;
  const layers: [any, string][] = [
    [raw, "review_sha256"],
    [raw.compilation, "compilation_sha256"],
  ];
  if (effective)
    layers.push([raw.compilation?.terminal_edit, "compilation_sha256"]);
  for (const [layer, key] of layers) {
    if (!layer || Array.isArray(layer) || !hash(layer[key])) return false;
    const { [key]: digest, ...body } = layer;
    if ((await sha256Text(canonical(body))) !== digest) return false;
  }
  return true;
}

export async function terminalTransferReview(
  document: { data: Data; blob: Blob },
  source: Data,
  request: Data,
  field: boolean,
) {
  const r = document.data,
    c = r?.compilation,
    p = c?.terminal_compilation;
  const selected = source?.inputs?.find(
    (x: Data) => x.object_id === `analog-input,${request.object_instance}`,
  );
  if (
    !selected ||
    request.action !== "terminal" ||
    request.configuration_sha256 !== selected.configuration_sha256 ||
    request.configuration !== null ||
    request.name !== null ||
    request.allocation_receipt !== null ||
    !integer(request.slot, 6) ||
    request.slot < 1 ||
    request.slot === selected.slot ||
    !Array.isArray(source.available_slots) ||
    !source.available_slots.includes(request.slot) ||
    r.capture_id !== source.capture_id ||
    r.snapshot_sha256 !== source.snapshot_sha256 ||
    !r.target ||
    !source.target ||
    controllerKey({ ...r.target, device: r.identity?.device }) !==
      controllerKey({ ...source.target, device: source.identity?.device }) ||
    !same(r.identity, source.identity) ||
    (field
      ? r.profile !== "native-application-transfer/1" ||
        r.operation_profile !== TERMINAL_TRANSFER_PROFILE ||
        !same(r.input_edit, request)
      : r.profile !== TERMINAL_TRANSFER_PROFILE ||
        !same(r.edit, request) ||
        r.controller_queries !== false ||
        r.controller_writes !== false) ||
    c?.profile !== TERMINAL_TRANSFER_PROFILE ||
    !same(c.input_edit, request) ||
    c.object_id !== selected.object_id ||
    c.record_ref !== selected.record_ref ||
    c.other_records_preserved !== true ||
    c.wires_changed !== false ||
    c.allocated_record_hex !== null ||
    !integer(c.native_record_count, 20000) ||
    c.native_record_count < 2 ||
    c.original_native_record_count !== c.native_record_count ||
    !same(
      Object.keys(c.stored_configuration || {}).sort(),
      Object.keys(selected.configuration || {}).sort(),
    ) ||
    !Object.keys(selected.configuration).every(
      (k) =>
        typeof c.stored_configuration[k] === "number" &&
        Object.is(c.stored_configuration[k], selected.configuration[k]),
    )
  )
    return false;
  if (
    !p ||
    p.profile !== "tagged-moi-local-terminal-copy/2" ||
    p.ref !== selected.record_ref ||
    p.object !== selected.object_id ||
    p.old_slot !== selected.slot ||
    p.destination_slot !== request.slot ||
    p.old_device_type !== `UI IN${selected.slot}` ||
    p.new_device_type !== `UI IN${request.slot}` ||
    p.changed !== true ||
    !hash(p.compilation_sha256) ||
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
  const [slot, label] = p.payloads;
  const hex = (s: string) =>
    Array.from(new TextEncoder().encode("\0" + s), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
  if (
    !slot ||
    !label ||
    ![slot, label].every(
      (x) => integer(x.offset, 8 * 1024 * 1024) && x.offset >= 14,
    ) ||
    typeof slot.before !== "string" ||
    !/^(?:[a-f0-9]{2}){1,4}$/.test(slot.before) ||
    Number.parseInt(slot.before, 16) !== selected.slot ||
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
      { property: 519, before: p.old_slot, after: p.destination_slot },
    ])
  )
    return false;
  const { compilation_sha256, ...body } = p;
  return (
    (await connectionSeal(body)) === compilation_sha256 &&
    (await terminalDocumentSeal(document.blob, field))
  );
}
