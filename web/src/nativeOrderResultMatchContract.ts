import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import {
  nativeOrderSelection,
  nativeOrderSource,
} from "./nativeExecutionOrderContract";
import { orderTransferReceipt } from "./nativeOrderTransferContract";
import type { NativeArchiveSource } from "./NativeRecords";
type Data = Record<string, any>;
export const orderResultMatchProfile = "native-execution-order-result-match/1";
export const orderResultMatchBase =
  "/bacnet/controller/native-application/execution-order/result/compare";
export const orderResultMatchScope =
  "Local retained-source comparison with a reconstructed, historically verified native execution-order result. Compare original route/identity, expanded/effective application and recorded membership/order/widths/wire relationships separately. No current-device verification, field query, recovery proposal, review, compilation artifact or transfer.";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));

export function orderMatchParentProblem(receipt: Data) {
  if (receipt.pending !== false)
    return "Read back and resolve the original order transfer before comparing retained results.";
  if (
    !receipt.intent ||
    (receipt.result
      ? receipt.result.may_have_applied
      : receipt.intent.may_have_applied) !== true
  )
    return "This receipt records no possible execution-order restore.";
  if (
    receipt.result?.status !== "verified" &&
    !receipt.events?.some(
      (event: Data) =>
        event?.stage === "readback" && event.detail?.status === "verified",
    )
  )
    return "This receipt has no retained verified execution-order outcome.";
  return null;
}
function selectedProof(receipt: Data) {
  const proof =
    receipt.result?.status === "verified"
      ? receipt.result
      : receipt.events?.find(
          (event: Data) =>
            event?.stage === "readback" && event.detail?.status === "verified",
        );
  return {
    proof,
    kind: receipt.result?.status === "verified" ? "result" : "readback-event",
  };
}
export async function orderMatchParent(receipt: Data) {
  try {
    if (orderMatchParentProblem(receipt)) return false;
    const i = receipt.intent,
      { proof, kind } = selectedProof(receipt);
    const observed = kind === "result" ? proof : proof?.detail;
    if (
      !proof ||
      proof.profile !== "native-application-transfer/1" ||
      proof.receipt_id !== i.id ||
      !hash(proof.evidence_sha256) ||
      (kind === "result" && proof.intent_sha256 !== i.evidence_sha256) ||
      !Number.isFinite(
        Date.parse(kind === "result" ? proof.finished_at : proof.created_at),
      ) ||
      observed?.readback?.status !== "verified_new" ||
      !same(observed.readback.identity, i.identity) ||
      Object.keys(i).some((k) => k.startsWith("recovery_"))
    )
      return false;
    // Validate the selected immutable observation for this read-only comparison.
    // The original receipt and its latest observation remain unchanged.
    return orderTransferReceipt({ ...receipt, latest_readback: observed });
  } catch {
    return false;
  }
}
const members = (s: Data) =>
  s.members.map((m: Data) => ({
    index: m.index,
    ref: m.ref,
    class_id: m.class_id,
    object: m.object,
  }));

export async function orderResultMatchEvidence(
  v: Data,
  source: NativeArchiveSource,
  opened: Data,
  receipt: Data,
) {
  try {
    const i = receipt.intent,
      ref = i?.order_edit?.diagram_ref,
      before = i?.compilation?.order_edit?.selection;
    if (
      !(await orderMatchParent(receipt)) ||
      !opened ||
      ref !== opened.selection?.diagram_ref ||
      !exact(v, [
        "profile",
        "scope",
        "receipt_id",
        "intent_sha256",
        "verified_proof",
        "original_backup_id",
        "original_snapshot_sha256",
        "recorded_target",
        "current_target",
        "recorded_identity",
        "diagram_ref",
        "expected_native_sha256",
        "source",
        "archive_selection",
        "expected_selection",
        "comparisons",
        "state",
        "read_only",
        "controller_queries",
        "field_actions",
        "can_apply",
        "field_transfer_enabled",
        "current_device_verified",
        "parent_revalidated",
        "evidence_sha256",
      ]) ||
      v.profile !== orderResultMatchProfile ||
      v.scope !== orderResultMatchScope ||
      v.read_only !== true ||
      [
        "controller_queries",
        "field_actions",
        "can_apply",
        "field_transfer_enabled",
        "current_device_verified",
        "parent_revalidated",
      ].some((k) => v[k] !== false) ||
      v.receipt_id !== i.id ||
      v.intent_sha256 !== i.evidence_sha256 ||
      v.original_backup_id !== i.backup_id ||
      !id(v.original_backup_id) ||
      ![v.original_snapshot_sha256, v.evidence_sha256].every(hash) ||
      v.diagram_ref !== ref ||
      v.expected_native_sha256 !== i.native_payload_sha256 ||
      !same(v.recorded_target, i.target) ||
      !same(v.recorded_identity, i.identity) ||
      !same(v.current_target, {
        address: opened.target.address,
        router: opened.target.router ?? null,
        dnet: opened.target.dnet ?? null,
      }) ||
      !same(v.source, opened) ||
      !(await nativeOrderSource(v.source, source, {
        ref,
        class_id: opened.selection.diagram_class_id,
        record_sha256: opened.archive_record_sha256,
      })) ||
      !(await nativeOrderSelection(
        v.archive_selection,
        ref,
        opened.selection.diagram_class_id,
      )) ||
      v.archive_selection.source_sha256 !== source.sha256 ||
      v.archive_selection.record_sha256 !== opened.archive_record_sha256 ||
      !(await nativeOrderSelection(
        v.expected_selection,
        ref,
        before.diagram_class_id,
      )) ||
      v.expected_selection.source_sha256 !== i.payload_sha256 ||
      v.expected_selection.source_native_sha256 !== i.native_payload_sha256 ||
      !same(v.expected_selection.members, before.members) ||
      !same(v.expected_selection.original_order, i.order_edit.proposed_order) ||
      !same(
        v.expected_selection.slots.map((s: Data) => s.payload_bytes),
        i.order_guard.payload_widths,
      ) ||
      !same(v.expected_selection.edge_relationships, before.edge_relationships)
    )
      return false;
    const { proof, kind } = selectedProof(receipt);
    if (
      !exact(v.verified_proof, ["kind", "sha256", "time"]) ||
      !same(v.verified_proof, {
        kind,
        sha256: proof.evidence_sha256,
        time: kind === "result" ? proof.finished_at : proof.created_at,
      })
    )
      return false;
    const expected = v.expected_selection,
      current = opened.selection;
    const comparisons = {
      route_matches: same(v.current_target, i.target),
      identity_matches: same(opened.identity, i.identity),
      expanded_application_matches:
        v.archive_selection.source_native_sha256 === i.native_payload_sha256,
      effective_application_matches:
        current.source_native_sha256 === i.native_payload_sha256,
      original_saved_directory_matches:
        opened.files["11"].sha256 === i.compilation.files["11"].sha256,
      diagram_class_matches:
        current.diagram_class_id === expected.diagram_class_id,
      membership_matches: same(members(current), members(expected)),
      selected_order_matches: same(
        current.original_order,
        expected.original_order,
      ),
      payload_widths_match: same(
        current.slots.map((s: Data) => s.payload_bytes),
        expected.slots.map((s: Data) => s.payload_bytes),
      ),
      wire_relationships_match: same(
        current.edge_relationships,
        expected.edge_relationships,
      ),
    };
    const matched =
      opened.source_identity_matches === true &&
      Object.entries(comparisons).every(
        ([key, value]) => key === "original_saved_directory_matches" || value,
      );
    const { evidence_sha256, ...body } = v;
    return (
      same(v.comparisons, comparisons) &&
      v.state === (matched ? "application-and-order-match" : "different") &&
      (await connectionSeal(body)) === evidence_sha256
    );
  } catch {
    return false;
  }
}
