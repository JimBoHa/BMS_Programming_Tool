import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";
import { connectionSame as same } from "./nativeConnectionContract";
import { removalCapabilityEvidence } from "./nativeRemovalCapabilityContract";
import { nativeBackupOperationIds } from "./nativeBackupOperationIds";
import { nativeOrderReview } from "./nativeExecutionOrderContract";
import { orderTransferCompilation } from "./nativeOrderTransferContract";

type Data = Record<string, any>;
export const orderCapabilityProfile = "native-backup-operation-capabilities/22";
export const orderCapabilityOperationIds = [
  ...nativeBackupOperationIds,
  "effective-execution-order-compile",
  "execution-order-transfer-prerequisites",
];
const limits = { diagrams: 8, compile_attempts: 8, witness_bytes: 96 * 1024 };
const keys = (v: any, wanted: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === wanted.length &&
  wanted.every((k) => Object.hasOwn(v, k));
const uint = (v: any, max: number) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const error = (v: any) =>
  typeof v === "string" && [...v].length > 0 && [...v].length <= 512;
function witnessSize(w: Data) {
  return JSON.stringify(w).replace(
    /[^\x00-\x7f]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
  ).length;
}
export async function orderCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.profile !== "native-backup-record-inspection/1" ||
      data.source_kind !== "native-backup-archive" ||
      data.capture_id !== source.capture_id ||
      data.snapshot_sha256 !== source.snapshot_sha256 ||
      data.sha256 !== source.sha256 ||
      !same(data.files, source.files) ||
      controllerKey(data.target) !== controllerKey(source.target) ||
      data.read_only !== true ||
      data.can_apply !== false ||
      data.controller_queries !== false ||
      data.field_actions !== false ||
      data.current_identity_verified !== false ||
      data?.capability_profile !== orderCapabilityProfile ||
      !Array.isArray(data.operations) ||
      data.operations.length !== orderCapabilityOperationIds.length ||
      !data.operations.every(
        (r: Data, i: number) => r?.id === orderCapabilityOperationIds[i],
      )
    )
      return false;
    const previous = { ...data.qualification };
    delete previous.execution_order;
    if (
      !removalCapabilityEvidence(
        {
          ...data,
          capability_profile: "native-backup-operation-capabilities/14",
          qualification: previous,
          operations: data.operations.slice(0, -2),
        },
        source,
      )
    )
      return false;
    const e = data.qualification.execution_order;
    if (
      !keys(e, [
        "status",
        "error",
        "limits",
        "diagram_count",
        "examined_diagrams",
        "compile_attempts",
        "witness",
        "transfer_error",
      ]) ||
      !keys(e.limits, ["diagrams", "compile_attempts", "witness_bytes"]) ||
      !same(e.limits, limits) ||
      !(e.diagram_count === null || uint(e.diagram_count, 20000)) ||
      !uint(
        e.examined_diagrams,
        Math.min(e.diagram_count ?? 0, limits.diagrams),
      ) ||
      !uint(
        e.compile_attempts,
        Math.min(e.examined_diagrams, limits.compile_attempts),
      )
    )
      return false;
    const local = data.operations.at(-2),
      field = data.operations.at(-1);
    if (local.status !== e.status) return false;
    if (e.witness === null)
      return (
        ["unsupported-source", "source-mismatch", "not-evaluated"].includes(
          e.status,
        ) &&
        error(e.error) &&
        e.transfer_error === null &&
        field.status === e.status
      );
    const w = e.witness;
    if (
      e.status !== "source-qualified" ||
      e.error !== null ||
      e.compile_attempts < 1 ||
      !keys(w, ["record", "request", "review", "transfer_compilation"]) ||
      !keys(w.record, ["ref", "record_sha256", "class_id"]) ||
      witnessSize(w) > limits.witness_bytes ||
      ![536, 575].includes(w.record.class_id) ||
      w.request.diagram_ref !== w.record.ref ||
      w.request.record_sha256 !== w.record.record_sha256 ||
      !(await nativeOrderReview(
        w.review,
        source,
        w.record,
        w.review?.source,
        w.request,
      )) ||
      same(w.request.proposed_order, w.review.source.selection.original_order)
    )
      return false;
    if (w.transfer_compilation === null)
      return error(e.transfer_error) && field.status === "unsupported-source";
    if (
      e.transfer_error !== null ||
      !(await orderTransferCompilation(w.transfer_compilation, w.request))
    )
      return false;
    const {
      order_guard: _g,
      parameter_transfer_qualification: _q,
      order_compilation_sha256: _sha,
      ...base
    } = w.transfer_compilation;
    return (
      same(base, w.review.compilation) &&
      field.status ===
        (data.qualification.captured_plain_ipv4
          ? "preflight-required"
          : "transport-unavailable")
    );
  } catch {
    return false;
  }
}
