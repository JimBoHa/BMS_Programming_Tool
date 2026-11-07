import type { NativeArchiveSource } from "./NativeRecords";
import { connectionSame as same } from "./nativeConnectionContract";
import {
  batchCapabilityEvidence,
  batchCapabilityOperationIds,
  batchCapabilityProfile,
} from "./nativeBatchCapabilityContract";
import { defaultBatchSource } from "./nativeDefaultBatchContract";
import {
  defaultBatchTransferCompilation,
  defaultBatchTransferProfile,
} from "./nativeDefaultBatchTransferContract";
type Data = Record<string, any>;
export const batchTransferCapabilityProfile =
  "native-backup-operation-capabilities/21";
export const batchTransferCapabilityOperationIds = [
  ...batchCapabilityOperationIds,
  "typed-default-batch-transfer-prerequisites",
];
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const integer = (v: any, max: number) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const error = (v: unknown) =>
  typeof v === "string" && v.length > 0 && [...v].length <= 512;

export function batchTransferCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== batchTransferCapabilityProfile ||
      !Array.isArray(data.operations) ||
      data.operations.length !== batchTransferCapabilityOperationIds.length ||
      !data.operations.every(
        (r: Data, i: number) =>
          r?.id === batchTransferCapabilityOperationIds[i],
      )
    )
      return false;
    const previous = { ...data.qualification };
    delete previous.typed_default_batch_transfer;
    if (
      !batchCapabilityEvidence(
        {
          ...data,
          capability_profile: batchCapabilityProfile,
          qualification: previous,
          operations: data.operations.slice(0, -1),
        },
        source,
      )
    )
      return false;
    const q = data.qualification,
      e = q.typed_default_batch_transfer;
    if (
      !exact(e, [
        "status",
        "error",
        "field_limit",
        "field_count",
        "candidate_count",
        "selected_count",
        "compile_attempts",
        "source",
        "fields",
        "witness",
      ]) ||
      e.field_limit !== 16 ||
      !(e.field_count === null || integer(e.field_count, 4096)) ||
      !integer(e.candidate_count, 4096) ||
      !integer(e.selected_count, 16) ||
      !integer(e.compile_attempts, 1) ||
      !Array.isArray(e.fields)
    )
      return false;
    if (e.source === null) {
      if (
        e.status !== "unsupported-source" ||
        !error(e.error) ||
        e.field_count !== null ||
        e.candidate_count !== 0 ||
        e.selected_count !== 0 ||
        e.compile_attempts !== 0 ||
        e.fields.length !== 0 ||
        e.witness !== null
      )
        return false;
    } else {
      const opened = e.source;
      if (
        !defaultBatchSource(opened, {
          ...source,
          device: source.target.device,
          captured_at: data.captured_at,
          identity: data.identity,
          parameter_merge: q.parameter_merge,
        }) ||
        q.recorded_identity_verified !== true ||
        q.identity_matches_snapshot !== true ||
        opened.fields.length !== e.field_count ||
        e.fields.length !== e.field_count
      )
        return false;
      const candidates: Data[] = [];
      for (const [index, row] of opened.fields.entries()) {
        const f = row.field,
          candidate = row.kind !== "enum" || f.saved_storage !== null;
        const expected = {
          kind: row.kind,
          record_ref: f.ref,
          class_id: f.class_id,
          property: f.property,
          encoded_sha256: f.encoded_sha256,
          prerequisite: candidate
            ? "candidate-for-review"
            : "requires-fixed-enum-slot",
        };
        if (!same(e.fields[index], expected)) return false;
        if (candidate) candidates.push(row);
      }
      if (candidates.length !== e.candidate_count) return false;
      if (!candidates.length) {
        if (
          e.status !== "unsupported-source" ||
          !error(e.error) ||
          e.selected_count !== 0 ||
          e.compile_attempts !== 0 ||
          e.witness !== null
        )
          return false;
      } else {
        if (
          e.selected_count !== Math.min(candidates.length, 16) ||
          e.compile_attempts !== 1
        )
          return false;
        if (e.witness === null) {
          if (e.status !== "not-evaluated" || !error(e.error)) return false;
        } else {
          const w = e.witness;
          if (
            e.status !== "source-qualified" ||
            e.error !== null ||
            !exact(w, ["transfer_profile", "request", "compilation"]) ||
            w.transfer_profile !== defaultBatchTransferProfile
          )
            return false;
          const request = {
            capture_id: source.capture_id,
            snapshot_sha256: source.snapshot_sha256,
            source_sha256: opened.source_sha256,
            effective_sha256: opened.effective_sha256,
            changes: candidates.slice(0, 16).map((row) => ({
              kind: row.kind,
              record_ref: row.field.ref,
              encoded_sha256: row.field.encoded_sha256,
              ...(row.kind === "real"
                ? {
                    value_text:
                      row.field.effective_bits === "00000000" ? "1" : "0",
                  }
                : row.kind === "boolean"
                  ? { value: !row.field.effective_value }
                  : { value: row.field.effective_value === 0 ? 1 : 0 }),
            })),
          };
          if (
            !same(w.request, request) ||
            !defaultBatchTransferCompilation(w.compilation, request, opened) ||
            w.compilation.changed_count !== e.selected_count
          )
            return false;
        }
      }
    }
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
