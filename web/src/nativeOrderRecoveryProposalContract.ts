import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import {
  nativeOrderRequest,
  nativeOrderReview,
} from "./nativeExecutionOrderContract";
import { orderResultMatchEvidence } from "./nativeOrderResultMatchContract";
import type { NativeArchiveSource } from "./NativeRecords";
type Data = Record<string, any>;
export const orderRecoveryProposalProfile =
  "native-previous-execution-order-proposal/1";
export const orderRecoveryProposalBase =
  "/bacnet/controller/native-application/execution-order/recovery/prepare";
export const orderRecoveryProposalScope =
  "Local previous-order assistance from an original historically verified execution-order transfer and an exactly matching retained after application, effective order and static saved directory. Compile the original permutation with current captured saved settings, preserving existing members, Unsigned widths, wire phase and every other merged byte. No current-device verification, field query, old-plan replay, recovery lineage, review authority or automatic rollback. A separately confirmed fresh controller review, transfer and full readback remain required; general compiler, CCT and physical acceptance are separate.";
const closed = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
export async function orderRecoveryProposalEvidence(
  v: Data,
  source: NativeArchiveSource,
  opened: Data,
  receipt: Data,
  comparison: Data,
) {
  try {
    const keys = [
      "profile",
      "scope",
      "comparison",
      "origin",
      "origin_sha256",
      "proposal",
      "preview",
      "read_only",
      "controller_queries",
      "field_actions",
      "can_apply",
      "field_transfer_enabled",
      "current_device_verified",
      "new_review_required",
      "recovery_lineage_recorded",
      "evidence_sha256",
    ];
    if (
      !closed(v, keys) ||
      v.profile !== orderRecoveryProposalProfile ||
      v.scope !== orderRecoveryProposalScope ||
      !same(v.comparison, comparison) ||
      !(await orderResultMatchEvidence(comparison, source, opened, receipt)) ||
      comparison.state !== "application-and-order-match" ||
      comparison.comparisons.original_saved_directory_matches !== true
    )
      return false;
    const flags = {
      read_only: true,
      controller_queries: false,
      field_actions: false,
      can_apply: false,
      field_transfer_enabled: false,
      current_device_verified: false,
      new_review_required: true,
      recovery_lineage_recorded: false,
    };
    if (Object.entries(flags).some(([k, expected]) => v[k] !== expected))
      return false;
    const origin = {
      parent_receipt_id: receipt.intent.id,
      parent_intent_sha256: comparison.intent_sha256,
      verified_proof: comparison.verified_proof,
      original_backup_id: comparison.original_backup_id,
      original_snapshot_sha256: comparison.original_snapshot_sha256,
      comparison_sha256: comparison.evidence_sha256,
    };
    if (
      !same(v.origin, origin) ||
      v.origin_sha256 !== (await connectionSeal(origin))
    )
      return false;
    const record = {
      ref: comparison.diagram_ref,
      class_id: opened.selection.diagram_class_id,
      record_sha256: opened.archive_record_sha256,
    };
    const request = nativeOrderRequest(
      source,
      record,
      opened,
      receipt.intent.order_guard.original_order,
    );
    if (
      !same(v.proposal, request) ||
      same(v.proposal.proposed_order, opened.selection.original_order) ||
      !(await nativeOrderReview(v.preview, source, record, opened, request))
    )
      return false;
    const { evidence_sha256, ...body } = v;
    return (await connectionSeal(body)) === evidence_sha256;
  } catch {
    return false;
  }
}
