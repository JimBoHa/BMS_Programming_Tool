import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";
import { nativeBackupOperationIds } from "./nativeBackupOperationIds";
import { connectionSame as same } from "./nativeConnectionContract";
import { terminalCapabilityEvidence } from "./nativeEncodedAnalogCapabilityContract";
import {
  defaultWireSource,
  defaultWireSelection,
  defaultWireCompilation,
} from "./nativeDefaultWireContract";

type Data = Record<string, any>;
export const combinedCapabilityProfile =
  "native-backup-operation-capabilities/19";
export const combinedOperationIds = [
  "combined-default-wire-compile",
  "combined-default-wire-transfer",
];
export const combinedCapabilityOperationIds = [
  ...nativeBackupOperationIds,
  "local-terminal-copy",
  "effective-local-terminal-copy",
  "analog-terminal-transfer",
  "encoded-local-terminal-copy",
  "encoded-effective-local-terminal-copy",
  "binary-terminal-transfer",
  "encoded-analog-terminal-transfer",
  ...combinedOperationIds,
];
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const bounded = (v: unknown, max: number) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const exact = (v: Data, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const errorText = (v: unknown) =>
  typeof v === "string" && v.length > 0 && Array.from(v).length <= 512;
function realField(v: Data) {
  if (
    !v ||
    ![526, 527].includes(v.class_id) ||
    v.property !== 3113 ||
    typeof v.ref !== "string" ||
    !v.ref.length ||
    v.ref.length > 512 ||
    !hash(v.encoded_sha256) ||
    !/^[a-f0-9]{8}$/.test(v.effective_bits ?? "")
  )
    return false;
  const bits = new DataView(new ArrayBuffer(4));
  bits.setUint32(0, Number.parseInt(v.effective_bits, 16), false);
  return (
    Number.isFinite(v.effective_value) &&
    Object.is(v.effective_value, bits.getFloat32(0, false))
  );
}

export function combinedCapabilityWitness(
  w: Data,
  source: NativeArchiveSource,
  data: Data,
) {
  if (!exact(w, ["signal", "source", "selection", "edit", "compilation"]))
    return false;
  const signal = w.signal,
    opened = w.source,
    edit = w.edit,
    c = w.compilation;
  if (
    !exact(signal, [
      "profile",
      "scope",
      "capture_id",
      "snapshot_sha256",
      "captured_at",
      "target",
      "device",
      "identity",
      "parameter_merge",
      "fields",
      "controller_queries",
      "controller_write",
    ]) ||
    signal.profile !== "native-effective-signal-default-compiler/1" ||
    signal.capture_id !== source.capture_id ||
    signal.snapshot_sha256 !== source.snapshot_sha256 ||
    signal.captured_at !== data.captured_at ||
    signal.device !== source.target.device ||
    !same(signal.identity, data.identity) ||
    signal.identity?.["vendor-identifier"] !== 5 ||
    signal.controller_queries !== false ||
    signal.controller_write !== false ||
    controllerKey({ ...signal.target, device: signal.device }) !==
      controllerKey(source.target) ||
    !Array.isArray(signal.fields) ||
    !signal.fields.length ||
    signal.fields.length > 4096 ||
    !signal.fields.every(realField) ||
    new Set(signal.fields.map((f: Data) => f.ref)).size !==
      signal.fields.length ||
    !opened ||
    opened.sha256 !== source.sha256 ||
    !(["3", "11", "12"] as const).every(
      (k) =>
        opened.files?.[k]?.sha256 === source.files[k].sha256 &&
        opened.files[k].bytes === source.files[k].bytes,
    ) ||
    !defaultWireSource(opened, signal) ||
    !exact(edit, [
      "capture_id",
      "snapshot_sha256",
      "source_sha256",
      "effective_sha256",
      "diagram_ref",
      "record_sha256",
      "wire_index",
      "effective_record_sha256",
      "property_sha256",
      "old",
      "source_ref",
      "record_ref",
      "encoded_sha256",
      "value_text",
    ]) ||
    edit.capture_id !== source.capture_id ||
    edit.snapshot_sha256 !== source.snapshot_sha256 ||
    edit.source_sha256 !== source.sha256 ||
    edit.effective_sha256 !== opened.effective_sha256 ||
    !c
  )
    return false;
  const field = signal.fields.find((f: Data) => f.ref === edit.record_ref);
  if (
    !field ||
    edit.value_text !== (field.effective_bits === "00000000" ? "1" : "0")
  )
    return false;
  const query = Object.fromEntries(
    [
      "capture_id",
      "snapshot_sha256",
      "source_sha256",
      "effective_sha256",
      "diagram_ref",
      "record_sha256",
      "wire_index",
    ].map((k) => [k, edit[k]]),
  );
  return (
    defaultWireSelection(w.selection, signal, opened, query) &&
    defaultWireCompilation(
      c,
      opened,
      w.selection,
      edit,
      field,
      c.compiled_sha256,
    ) &&
    c.selected_default.changed === true &&
    c.selected_wire.changed === true
  );
}

export function combinedCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== combinedCapabilityProfile ||
      !Array.isArray(data.operations) ||
      data.operations.length !== combinedCapabilityOperationIds.length ||
      !data.operations.every(
        (r: Data, i: number) => r?.id === combinedCapabilityOperationIds[i],
      )
    )
      return false;
    const q = data.qualification,
      previous = { ...q };
    delete previous.combined_default_wire;
    if (
      !terminalCapabilityEvidence(
        {
          ...data,
          capability_profile: "native-backup-operation-capabilities/18",
          qualification: previous,
          operations: data.operations.slice(0, -2),
        },
        source,
      )
    )
      return false;
    const e = q.combined_default_wire;
    if (
      !exact(e, [
        "status",
        "error",
        "pair_attempts",
        "pair_limit",
        "witness",
        "transfer_qualification",
        "transfer_error",
      ]) ||
      e.pair_limit !== 16 ||
      !bounded(e.pair_attempts, 16)
    )
      return false;
    const supported = e.witness !== null;
    if (supported) {
      if (
        e.status !== "source-qualified" ||
        e.error !== null ||
        e.pair_attempts < 1 ||
        q.recorded_identity_verified !== true ||
        q.identity_matches_snapshot !== true ||
        !combinedCapabilityWitness(e.witness, source, data)
      )
        return false;
      const t = e.transfer_qualification;
      if (t === null) {
        if (!errorText(e.transfer_error)) return false;
      } else if (
        !exact(t, ["profile", "qualified_fields", "model_inventory_used"]) ||
        t.profile !== "native-omitted-application-field-types/1" ||
        t.model_inventory_used !== false ||
        !bounded(t.qualified_fields, 20000) ||
        e.transfer_error !== null
      )
        return false;
    } else if (
      !["unsupported-source", "not-evaluated"].includes(e.status) ||
      !errorText(e.error) ||
      e.transfer_qualification !== null ||
      e.transfer_error !== null ||
      (e.status === "not-evaluated" && e.pair_attempts < 1)
    )
      return false;
    const transferStatus =
      q.recorded_identity_verified !== true
        ? "source-mismatch"
        : !supported
          ? e.status
          : e.transfer_qualification === null
            ? "unsupported-source"
            : q.captured_plain_ipv4 === true
              ? "preflight-required"
              : "transport-unavailable";
    return data.operations
      .slice(-2)
      .every(
        (r: Data, i: number) =>
          r.status === (i === 0 ? e.status : transferStatus) &&
          [r.operation, r.basis, r.next_step].every(
            (v) => typeof v === "string" && v.length > 0,
          ),
      );
  } catch {
    return false;
  }
}
