import { sha256Blob } from "./activityContracts";
import { connectionSame as same } from "./nativeConnectionContract";
import {
  batchRecoveryOriginJSON,
  defaultBatchRecoveryEvidence,
} from "./nativeDefaultBatchRecoveryContract";
import {
  defaultBatchTransferReceipt,
  defaultBatchTransferReview,
} from "./nativeDefaultBatchTransferContract";
type Data = Record<string, any>;
export const batchRecoveryTransferProfile =
  "native-default-batch-recovery-transfer/1";
export const batchRecoveryTransferScope =
  "Apply only previous effective typed defaults derived from a resolved, verified original batch receipt and matching retained current source. Revalidate that lineage before preview and durable intent; preserve fresh unselected settings. Require a new confirmed one-use restore and complete native/effective readback. No old-token replay, general rollback, graph allocation, CCT or physical acceptance.";
const metadata = [
  "recovery_profile",
  "recovery_scope",
  "recovery_origin",
  "recovery_origin_sha256",
];
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const strip = (v: Data) =>
  Object.fromEntries(Object.entries(v).filter(([k]) => !metadata.includes(k)));
const project = (v: Data) => ({
  ...v,
  intent: v.intent ? strip(v.intent) : v.intent,
});
export type BatchRecoveryTransferContext = {
  report: Data;
  parent: Data;
  generation: number;
  current: () => boolean;
};
const typed = (kind: string, v: Data) =>
  kind === "real"
    ? exact(v, ["bits"]) &&
      /^[a-f0-9]{8}$/.test(v.bits) &&
      Number.isFinite(
        new DataView(
          Uint8Array.from(v.bits.match(/../g)!, (b: any) =>
            parseInt(b, 16),
          ).buffer,
        ).getFloat32(0, false),
      )
    : exact(v, ["value"]) &&
      (kind === "boolean"
        ? typeof v.value === "boolean"
        : kind === "enum" &&
          Number.isSafeInteger(v.value) &&
          v.value >= 0 &&
          v.value <= 65535);
function after(kind: string, hex: string) {
  if (kind === "real" && /^44[a-f0-9]{8}2f$/.test(hex))
    return { bits: hex.slice(2, -2) };
  if (kind === "boolean" && /^1[01]2f$/.test(hex))
    return { value: hex[1] === "1" };
  if (kind === "enum" && /^9[12](?:[a-f0-9]{2}){1,2}2f$/.test(hex))
    return { value: Number.parseInt(hex.slice(2, -2), 16) };
  throw new Error("Unknown recorded recovery encoding.");
}
async function lineage(v: Data) {
  try {
    const o = v.recovery_origin,
      edit = v.batch_edit,
      c = v.compilation;
    if (
      v.recovery_profile !== batchRecoveryTransferProfile ||
      v.recovery_scope !== batchRecoveryTransferScope ||
      Object.keys(v).some(
        (k) => k.startsWith("recovery_") && !metadata.includes(k),
      ) ||
      !hash(v.recovery_origin_sha256) ||
      !exact(o, [
        "profile",
        "parent_receipt_id",
        "parent_intent_sha256",
        "original_dispatch",
        "verified_proof",
        "original_backup_id",
        "original_snapshot_sha256",
        "current_capture_id",
        "current_snapshot_sha256",
        "recorded_native_payload_sha256",
        "fields",
        "enum_semantics_verified",
      ]) ||
      o.profile !== "native-default-batch-recovery-draft/1" ||
      !id(o.parent_receipt_id) ||
      !hash(o.parent_intent_sha256) ||
      o.original_dispatch !== "possible" ||
      !id(o.original_backup_id) ||
      !hash(o.original_snapshot_sha256) ||
      o.current_capture_id !== edit?.capture_id ||
      o.current_snapshot_sha256 !== edit.snapshot_sha256 ||
      !hash(o.recorded_native_payload_sha256) ||
      o.enum_semantics_verified !== false ||
      !exact(o.verified_proof, ["kind", "sha256", "time"]) ||
      !["result", "readback-event"].includes(o.verified_proof.kind) ||
      !hash(o.verified_proof.sha256) ||
      !Number.isFinite(Date.parse(o.verified_proof.time)) ||
      !Array.isArray(o.fields) ||
      o.fields.length < 1 ||
      o.fields.length > 16 ||
      o.fields.length !== c?.batch_guard?.fields?.length
    )
      return false;
    for (const [index, f] of o.fields.entries()) {
      const g = c.batch_guard.fields[index],
        s = c.selected[index];
      if (
        !exact(f, [
          "kind",
          "record_ref",
          "class_id",
          "property",
          "previous",
          "recorded_after",
          "current",
          "already_recorded",
          "current_encoded_sha256",
        ]) ||
        f.kind !== g.kind ||
        f.record_ref !== g.record_ref ||
        f.class_id !== g.class_id ||
        f.property !== 3113 ||
        f.current_encoded_sha256 !== g.encoded_sha256 ||
        !typed(f.kind, f.previous) ||
        !typed(f.kind, f.recorded_after) ||
        !typed(f.kind, f.current) ||
        !same(
          f.current,
          f.kind === "real" ? { bits: g.prior_bits } : { value: g.prior_value },
        ) ||
        !same(f.previous, after(f.kind, s.after_encoding_hex)) ||
        f.already_recorded !== same(f.current, f.previous) ||
        (!same(f.current, f.previous) && !same(f.current, f.recorded_after))
      )
        return false;
    }
    return (
      (await sha256Blob(new Blob([batchRecoveryOriginJSON(o)]))) ===
      v.recovery_origin_sha256
    );
  } catch {
    return false;
  }
}

export async function batchRecoveryTransferReceipt(
  data: Data,
  reference?: Data,
) {
  try {
    if (!data?.intent)
      return defaultBatchTransferReceipt(
        data,
        reference ? strip(reference) : undefined,
      );
    if (!(await lineage(data.intent))) return false;
    if (
      reference &&
      metadata.some((key) => !same(data.intent[key], reference[key]))
    )
      return false;
    const recorded = project(data),
      bound = reference ? strip(reference) : undefined;
    if (await defaultBatchTransferReceipt(recorded, bound)) return true;
    const event =
      data.pending === false && Array.isArray(data.events)
        ? data.events.find(
            (e: Data) =>
              e?.stage === "readback" && e.detail?.status === "verified",
          )
        : null;
    return (
      !!event &&
      hash(event.evidence_sha256) &&
      Number.isFinite(Date.parse(event.created_at)) &&
      defaultBatchTransferReceipt(
        { ...recorded, latest_readback: event.detail },
        bound,
      )
    );
  } catch {
    return false;
  }
}

export async function preparedBatchRecoveryEvidence(
  data: Data,
  opened: Data,
  parent: Data,
) {
  if (
    parent?.intent &&
    metadata.some((key) => Object.hasOwn(parent.intent, key))
  ) {
    if (!(await batchRecoveryTransferReceipt(parent))) return false;
    return defaultBatchRecoveryEvidence(data, opened, project(parent));
  }
  return defaultBatchRecoveryEvidence(data, opened, parent);
}

export async function batchRecoveryTransferReview(
  data: Data,
  source: Data,
  proposal: Data,
  opened: Data,
  controller: Data,
  context: BatchRecoveryTransferContext,
) {
  try {
    if (
      !context.current() ||
      !(await preparedBatchRecoveryEvidence(
        context.report,
        opened,
        context.parent,
      )) ||
      !same(context.report.proposal, proposal) ||
      !(await lineage(data)) ||
      !same(data.recovery_origin, context.report.origin) ||
      data.recovery_origin_sha256 !== context.report.origin_sha256
    )
      return false;
    return defaultBatchTransferReview(
      strip(data),
      source,
      proposal,
      opened,
      controller,
    );
  } catch {
    return false;
  }
}
