import type { NativeArchiveSource } from "./NativeRecords";
import { connectionSame as same } from "./nativeConnectionContract";
import {
  combinedCapabilityEvidence,
  combinedCapabilityOperationIds,
  combinedCapabilityProfile,
} from "./nativeCombinedCapabilityContract";
import {
  defaultBatchSource,
  defaultBatchCompilation,
} from "./nativeDefaultBatchContract";

type Data = Record<string, any>;
export const batchCapabilityProfile = "native-backup-operation-capabilities/20";
export const batchCapabilityOperationIds = [
  ...combinedCapabilityOperationIds,
  "typed-default-batch-compile",
];
const exact = (v: Data, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const integer = (v: unknown, max: number) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const errorText = (v: unknown) =>
  typeof v === "string" && v.length > 0 && Array.from(v).length <= 512;

function witness(w: Data, data: Data, source: NativeArchiveSource, e: Data) {
  if (!exact(w, ["source", "request", "compilation"])) return false;
  const opened = w.source,
    q = data.qualification;
  if (
    !opened ||
    !same(opened.files, source.files) ||
    !defaultBatchSource(opened, {
      ...source,
      device: source.target.device,
      captured_at: data.captured_at,
      identity: data.identity,
      parameter_merge: q.parameter_merge,
    }) ||
    opened.fields.length !== e.field_count ||
    e.selected_count !== Math.min(opened.fields.length, 16)
  )
    return false;
  const expected = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: opened.source_sha256,
    effective_sha256: opened.effective_sha256,
    changes: opened.fields.slice(0, 16).map((row: Data) => {
      const f = row.field;
      return {
        kind: row.kind,
        record_ref: f.ref,
        encoded_sha256: f.encoded_sha256,
        ...(row.kind === "real"
          ? { value_text: f.effective_bits === "00000000" ? "1" : "0" }
          : row.kind === "boolean"
            ? { value: !f.effective_value }
            : { value: f.effective_value === 0 ? 1 : 0 }),
      };
    }),
  };
  return (
    same(w.request, expected) &&
    defaultBatchCompilation(
      w.compilation,
      opened,
      expected,
      w.compilation?.compiled_sha256,
    ) &&
    w.compilation.changed_count === e.selected_count
  );
}

export function batchCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== batchCapabilityProfile ||
      data.capture_id !== source.capture_id ||
      data.snapshot_sha256 !== source.snapshot_sha256 ||
      data.sha256 !== source.sha256 ||
      !same(data.files, source.files) ||
      !same(data.target, source.target) ||
      data.read_only !== true ||
      data.can_apply !== false ||
      data.controller_queries !== false ||
      data.field_actions !== false ||
      data.current_identity_verified !== false ||
      !Array.isArray(data.operations) ||
      data.operations.length !== batchCapabilityOperationIds.length ||
      !data.operations.every(
        (r: Data, i: number) => r?.id === batchCapabilityOperationIds[i],
      )
    )
      return false;
    const q = data.qualification,
      previous = { ...q };
    delete previous.typed_default_batch;
    if (
      !combinedCapabilityEvidence(
        {
          ...data,
          capability_profile: combinedCapabilityProfile,
          qualification: previous,
          operations: data.operations.slice(0, -1),
        },
        source,
      )
    )
      return false;
    const e = q.typed_default_batch;
    if (
      !exact(e, [
        "status",
        "error",
        "field_limit",
        "field_count",
        "selected_count",
        "compile_attempts",
        "witness",
      ]) ||
      e.field_limit !== 16 ||
      !(e.field_count === null || integer(e.field_count, 4096)) ||
      !integer(e.selected_count, 16) ||
      !integer(e.compile_attempts, 1)
    )
      return false;
    if (e.witness !== null) {
      if (
        e.status !== "source-qualified" ||
        e.error !== null ||
        e.compile_attempts !== 1 ||
        e.selected_count < 1 ||
        q.recorded_identity_verified !== true ||
        q.identity_matches_snapshot !== true ||
        !witness(e.witness, data, source, e)
      )
        return false;
    } else if (
      !errorText(e.error) ||
      (e.status === "unsupported-source"
        ? e.compile_attempts !== 0 ||
          e.selected_count !== 0 ||
          ![null, 0].includes(e.field_count)
        : e.status !== "not-evaluated" ||
          e.compile_attempts !== 1 ||
          !integer(e.field_count, 4096) ||
          e.field_count < 1 ||
          e.selected_count !== Math.min(e.field_count, 16))
    )
      return false;
    const row = data.operations.at(-1);
    return (
      row.status === e.status &&
      [row.operation, row.basis, row.next_step].every(
        (v) => typeof v === "string" && v.length > 0,
      )
    );
  } catch {
    return false;
  }
}
