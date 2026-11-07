import { sha256Blob } from "./activityContracts";
import {
  connectionSame as same,
  connectionSeal,
  connectionDraftKey,
} from "./nativeConnectionContract";
import { controllerKey } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";

type Data = Record<string, any>;
export const nativeOrderProfile = "native-effective-execution-order-compiler/1";
export const nativeOrderEditProfile = "tagged-moi-execution-order-copy/1";
export const nativeOrderScope =
  "Local execution-order compilation from an identity-qualified retained File 3/11/12 saved merge. Preserve original membership, graph, layout and continuation across the merge, then preserve each recorded wire phase and every other merged expanded byte. Captured saved values are historical. No fresh-setting guarantee, controller query, transfer, new identities, general compiler/resources/runtime or CCT/physical acceptance.";
export const nativeOrderEditScope =
  "Local native execution-order copy of existing members. Preserve every recorded wire's before/same/after relationship, original Unsigned widths and all other expanded bytes. No new blocks, links, field transfer, native runtime, resources or CCT/physical acceptance.";
export const nativeOrderBase =
  "/bacnet/controller/native-application/inspection/execution-order";
const hash = (x: any) => typeof x === "string" && /^[a-f0-9]{64}$/.test(x);
const uint = (x: any, max = 0xffffffff) =>
  Number.isSafeInteger(x) && x >= 0 && x <= max;
const closed = (x: any, keys: string[]) =>
  !!x &&
  typeof x === "object" &&
  !Array.isArray(x) &&
  Object.keys(x).length === keys.length &&
  keys.every((k) => Object.hasOwn(x, k));
export function nativeOrderPermutation(x: any, n: number): x is number[] {
  return (
    uint(n, 512) &&
    n > 0 &&
    Array.isArray(x) &&
    x.length === n &&
    new Set(x).size === n &&
    x.every((v) => uint(v, n - 1))
  );
}
const relation = (order: number[], a: number, b: number) =>
  a === b ? "same" : order.indexOf(a) < order.indexOf(b) ? "before" : "after";
export function nativeOrderAllowed(
  selection: Data,
  order: any,
): order is number[] {
  return (
    !!selection &&
    nativeOrderPermutation(order, selection.members.length) &&
    selection.slots.every(
      (s: Data, i: number) => order[i] < 2 ** (8 * s.payload_bytes),
    ) &&
    selection.edge_relationships.every(
      (w: Data) =>
        relation(order, w.source_index, w.target_index) === w.relationship,
    )
  );
}
export async function nativeOrderSelection(
  s: Data,
  ref: string,
  classId: number,
) {
  if (
    !closed(s, [
      "profile",
      "scope",
      "source_sha256",
      "source_native_sha256",
      "diagram_ref",
      "diagram_class_id",
      "record_sha256",
      "property_sha256",
      "original_order",
      "members",
      "slots",
      "edge_relationships",
      "selection_sha256",
    ]) ||
    s.profile !== nativeOrderEditProfile ||
    s.scope !== nativeOrderEditScope ||
    ![
      "source_sha256",
      "source_native_sha256",
      "record_sha256",
      "property_sha256",
      "selection_sha256",
    ].every((k) => hash(s[k])) ||
    s.diagram_ref !== ref ||
    s.diagram_class_id !== classId ||
    ![536, 575].includes(classId) ||
    !Array.isArray(s.members) ||
    !nativeOrderPermutation(s.original_order, s.members.length) ||
    !Array.isArray(s.slots) ||
    s.slots.length !== s.members.length ||
    !Array.isArray(s.edge_relationships) ||
    s.edge_relationships.length > 4096
  )
    return false;
  if (
    new Set(s.members.map((m: Data) => m.ref)).size !== s.members.length ||
    s.members.some(
      (m: Data, i: number) =>
        !closed(m, ["index", "ref", "name", "class_id", "object"]) ||
        m.index !== i ||
        typeof m.ref !== "string" ||
        !m.ref.startsWith(ref + ".") ||
        m.ref.length > 512 ||
        typeof m.name !== "string" ||
        [...m.name].length > 1024 ||
        !uint(m.class_id, 1023) ||
        typeof m.object !== "string",
    )
  )
    return false;
  if (
    s.slots.some(
      (slot: Data, i: number) =>
        !closed(slot, [
          "position",
          "index",
          "payload_offset",
          "payload_bytes",
          "encoded_sha256",
        ]) ||
        slot.position !== i ||
        slot.index !== s.original_order[i] ||
        !uint(slot.payload_offset, 8 * 1024 * 1024) ||
        slot.payload_offset < 14 ||
        !uint(slot.payload_bytes, 4) ||
        slot.payload_bytes < 1 ||
        !hash(slot.encoded_sha256) ||
        (i > 0 &&
          slot.payload_offset <
            s.slots[i - 1].payload_offset + s.slots[i - 1].payload_bytes) ||
        slot.index >= 2 ** (8 * slot.payload_bytes),
    )
  )
    return false;
  if (
    s.edge_relationships.some(
      (w: Data, i: number) =>
        !closed(w, [
          "wire_index",
          "source_index",
          "target_index",
          "relationship",
        ]) ||
        w.wire_index !== i ||
        !uint(w.source_index, s.members.length - 1) ||
        !uint(w.target_index, s.members.length - 1) ||
        w.relationship !==
          relation(s.original_order, w.source_index, w.target_index),
    )
  )
    return false;
  const { selection_sha256, ...body } = s;
  return (await connectionSeal(body)) === selection_sha256;
}
export async function nativeOrderSource(
  value: Data,
  source: NativeArchiveSource,
  record: Data,
) {
  try {
    const flags = {
      read_only: true,
      controller_queries: false,
      field_actions: false,
      identity_verified: false,
      source_identity_matches: true,
      source_immutable: true,
      saved_settings_merged: true,
      current_identity_verified: false,
      controller_write: false,
      field_transfer_enabled: false,
      can_apply: false,
    };
    if (
      !closed(value, [
        "profile",
        "source_kind",
        "capture_id",
        "snapshot_sha256",
        "sha256",
        "target",
        "captured_at",
        "identity",
        "source_identity_matches",
        "source_identity_error",
        "files",
        "scope",
        "read_only",
        "controller_queries",
        "field_actions",
        "identity_verified",
        "source_sha256",
        "archive_record_sha256",
        "effective_sha256",
        "parameter_merge",
        "selection",
        "source_immutable",
        "saved_settings_merged",
        "current_identity_verified",
        "controller_write",
        "field_transfer_enabled",
        "can_apply",
        "source_report_sha256",
      ]) ||
      value.identity?.["vendor-identifier"] !== 5 ||
      value.profile !== nativeOrderProfile ||
      value.scope !== nativeOrderScope ||
      value.source_kind !== "native-backup-archive" ||
      value.capture_id !== source.capture_id ||
      value.snapshot_sha256 !== source.snapshot_sha256 ||
      value.sha256 !== source.sha256 ||
      value.source_sha256 !== source.sha256 ||
      value.archive_record_sha256 !== record.record_sha256 ||
      !same(value.files, source.files) ||
      controllerKey(value.target) !== controllerKey(source.target) ||
      Object.entries(flags).some(([k, v]) => value[k] !== v) ||
      !hash(value.effective_sha256) ||
      !hash(value.source_report_sha256) ||
      value.selection?.source_sha256 !== value.effective_sha256 ||
      !(await nativeOrderSelection(
        value.selection,
        record.ref,
        record.class_id,
      ))
    )
      return false;
    const { source_report_sha256, ...body } = value;
    return (await connectionSeal(body)) === source_report_sha256;
  } catch {
    return false;
  }
}
export function nativeOrderRequest(
  source: NativeArchiveSource,
  record: Data,
  report: Data,
  order: number[],
) {
  return {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: source.sha256,
    diagram_ref: record.ref,
    record_sha256: record.record_sha256,
    effective_sha256: report.effective_sha256,
    effective_record_sha256: report.selection.record_sha256,
    selection_sha256: report.selection.selection_sha256,
    proposed_order: [...order],
  };
}
export async function nativeOrderReview(
  value: Data,
  source: NativeArchiveSource,
  record: Data,
  report: Data,
  request: Data,
) {
  try {
    const c = value?.compilation,
      e = c?.order_edit;
    if (
      !closed(value, [
        "profile",
        "source",
        "request",
        "compilation",
        "output_sha256",
        "controller_write",
        "field_transfer_enabled",
        "can_apply",
        "review_sha256",
      ]) ||
      value.profile !== nativeOrderProfile ||
      value.controller_write !== false ||
      value.field_transfer_enabled !== false ||
      value.can_apply !== false ||
      !hash(value.review_sha256) ||
      !hash(value.output_sha256) ||
      !same(value.source, report) ||
      !(await nativeOrderSource(report, source, record)) ||
      !same(value.request, request) ||
      !nativeOrderAllowed(report.selection, request.proposed_order) ||
      !same(
        request,
        nativeOrderRequest(source, record, report, request.proposed_order),
      )
    )
      return false;
    if (
      !closed(c, [
        "profile",
        "scope",
        "files",
        "parameter_merge",
        "archive_sha256",
        "effective_sha256",
        "order_edit",
        "compiled_sha256",
        "compiled_native_sha256",
        "native_record_count",
        "saved_settings_merged",
        "other_merged_bytes_preserved",
        "controller_write",
        "field_transfer_enabled",
        "compilation_sha256",
      ]) ||
      c.profile !== nativeOrderProfile ||
      c.scope !== nativeOrderScope ||
      !same(c.files, source.files) ||
      !same(c.parameter_merge, report.parameter_merge) ||
      c.archive_sha256 !== source.sha256 ||
      c.effective_sha256 !== report.effective_sha256 ||
      c.compiled_sha256 !== value.output_sha256 ||
      !hash(c.compiled_native_sha256) ||
      !hash(c.compilation_sha256) ||
      !uint(c.native_record_count, 20000) ||
      c.native_record_count < report.selection.members.length + 2 ||
      c.saved_settings_merged !== true ||
      c.other_merged_bytes_preserved !== true ||
      c.controller_write !== false ||
      c.field_transfer_enabled !== false
    )
      return false;
    if (
      !closed(e, [
        "profile",
        "selection",
        "proposed_order",
        "patches",
        "output_sha256",
        "output_native_sha256",
        "other_expanded_bytes_preserved",
        "native_structure_readback_verified",
        "controller_write",
        "field_transfer_enabled",
        "compilation_sha256",
      ]) ||
      e.profile !== nativeOrderEditProfile ||
      !same(e.selection, report.selection) ||
      !same(e.proposed_order, request.proposed_order) ||
      e.output_sha256 !== value.output_sha256 ||
      e.output_native_sha256 !== c.compiled_native_sha256 ||
      e.other_expanded_bytes_preserved !== true ||
      e.native_structure_readback_verified !== true ||
      e.controller_write !== false ||
      e.field_transfer_enabled !== false ||
      !hash(e.compilation_sha256)
    )
      return false;
    const patches = report.selection.slots
      .filter((s: Data, i: number) => s.index !== request.proposed_order[i])
      .map((s: Data) => ({
        ...s,
        new_index: request.proposed_order[s.position],
      }));
    if (!same(e.patches, patches)) return false;
    if (
      patches.length === 0 &&
      (e.output_sha256 !== report.effective_sha256 ||
        e.output_native_sha256 !== report.selection.source_native_sha256)
    )
      return false;
    if (
      patches.length > 0 &&
      (e.output_sha256 === report.effective_sha256 ||
        e.output_native_sha256 === report.selection.source_native_sha256)
    )
      return false;
    const { compilation_sha256: editSeal, ...edit } = e,
      { compilation_sha256, ...compilation } = c,
      { review_sha256, ...review } = value;
    return (
      (await connectionSeal(edit)) === editSeal &&
      (await connectionSeal(compilation)) === compilation_sha256 &&
      (await connectionSeal(review)) === review_sha256
    );
  } catch {
    return false;
  }
}
export async function nativeOrderExport(
  response: { blob: Blob; headers: Headers },
  review: Data,
) {
  return (
    response.headers.get("Content-Type")?.split(";")[0] ===
      "application/octet-stream" &&
    response.headers.get("X-Studio-Artifact-Sha256") === review.output_sha256 &&
    response.headers.get("X-Studio-Review-Sha256") === review.review_sha256 &&
    response.headers.get("X-Studio-Source-Sha256") ===
      review.request.source_sha256 &&
    response.headers.get("X-Studio-Snapshot-Sha256") ===
      review.request.snapshot_sha256 &&
    response.headers.get("X-Studio-Compilation-Sha256") ===
      review.compilation.compilation_sha256 &&
    (await sha256Blob(response.blob)) === review.output_sha256
  );
}
export const nativeOrderDraftKey = (
  source: NativeArchiveSource,
  record: Data,
) => connectionDraftKey(source, record) + "/execution-order";
export function nativeOrderDraft(
  drafts: WireCopyDrafts,
  key: string,
  selection: Data,
) {
  const text = drafts.get(key);
  if (!text) return null;
  try {
    const d = JSON.parse(text);
    if (
      !closed(d, ["selection_sha256", "proposed", "saved"]) ||
      d.selection_sha256 !== selection.selection_sha256 ||
      !nativeOrderAllowed(selection, d.proposed) ||
      typeof d.saved !== "string"
    )
      throw Error();
    return d;
  } catch {
    throw Error(
      "The retained order proposal does not match this source. Discard it explicitly before replacing it.",
    );
  }
}
export function rememberNativeOrder(
  drafts: WireCopyDrafts,
  key: string,
  selection: Data,
  order: number[],
) {
  if (!nativeOrderAllowed(selection, order))
    throw Error(
      "This move changes a wire relationship or exceeds the original index width.",
    );
  const old = nativeOrderDraft(drafts, key, selection);
  if (same(order, selection.original_order)) {
    drafts.delete(key);
    return;
  }
  const value = JSON.stringify({
    selection_sha256: selection.selection_sha256,
    proposed: [...order],
    saved: old?.saved || "",
  });
  if (!rememberWireDraft(drafts, key, value))
    throw Error(
      "The 256 retained native graph draft slots are full. Discard an older draft; no existing work was removed.",
    );
}
