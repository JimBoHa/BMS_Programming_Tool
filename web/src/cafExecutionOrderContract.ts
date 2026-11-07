import { sha256Blob } from "./activityContracts";
import { connectionSame, connectionSeal } from "./nativeConnectionContract";

type Data = Record<string, any>;
export const orderProfile = "caf-execution-order-copy/1";
export const orderScope =
  "Local CAF copy reordering existing blocks while preserving every recorded wire's before/same/after execution relationship. All other XML bytes, objects, membership, connections, continuation and layout remain unchanged. Native execution, resources, CCT/PCT acceptance and controller transfer remain unverified.";
const flags = [
  "controller_write",
  "field_transfer_enabled",
  "native_execution_verified",
  "vendor_acceptance_verified",
  "can_apply",
];
const hashes = [
  "source_sha256",
  "source_xml_sha256",
  "diagram_sha256",
  "order_property_sha256",
  "selection_sha256",
];
const keys = [
  "profile",
  "scope",
  ...hashes,
  "diagram_ref",
  "diagram_class_id",
  "diagram_class_version",
  "original_order",
  "members",
  "edge_relationships",
  ...flags,
];
const hash = (x: unknown) => typeof x === "string" && /^[a-f0-9]{64}$/.test(x);
const closed = (x: any, keys: string[]) =>
  !!x &&
  typeof x === "object" &&
  !Array.isArray(x) &&
  Object.keys(x).length === keys.length &&
  keys.every((k) => Object.hasOwn(x, k));
const noAuthority = (x: Data) => flags.every((k) => x[k] === false);
export type OrderDiagram = {
  ref: string;
  class_id: string;
  class_version: string;
  observed_version: boolean;
  blocks: Array<{
    index: number;
    ref: string;
    name: string;
    class_name: string;
  }>;
  execution_order: number[];
  connections: Array<{ index: number; raw: number[] }>;
};
export function orderPermutation(
  order: unknown,
  count: number,
): order is number[] {
  return (
    Number.isInteger(count) &&
    count >= 1 &&
    count <= 512 &&
    Array.isArray(order) &&
    order.length === count &&
    new Set(order).size === count &&
    order.every((x) => Number.isInteger(x) && x >= 0 && x < count)
  );
}
export function orderRelationships(diagram: OrderDiagram, order: number[]) {
  return diagram.connections.map((w) => {
    const source = w.raw[0],
      target = w.raw[2];
    return {
      wire_index: w.index,
      source_index: source,
      target_index: target,
      relationship:
        order.indexOf(source) < order.indexOf(target)
          ? "before"
          : source === target
            ? "same"
            : "after",
    };
  });
}
export function orderAllowed(
  diagram: OrderDiagram,
  order: unknown,
): order is number[] {
  return (
    orderPermutation(order, diagram.blocks.length) &&
    connectionSame(
      orderRelationships(diagram, order),
      orderRelationships(diagram, diagram.execution_order),
    )
  );
}
export async function orderSource(
  value: Data,
  archive: string,
  diagram: OrderDiagram,
) {
  if (
    !closed(value, keys) ||
    !noAuthority(value) ||
    value.profile !== orderProfile ||
    value.scope !== orderScope ||
    hashes.some((k) => !hash(value[k])) ||
    value.source_sha256 !== archive ||
    value.diagram_ref !== diagram.ref ||
    !["536", "575"].includes(value.diagram_class_id) ||
    value.diagram_class_id !== diagram.class_id ||
    value.diagram_class_version !== "1.0" ||
    diagram.class_version !== "1.0" ||
    !diagram.observed_version ||
    !orderPermutation(value.original_order, diagram.blocks.length) ||
    !connectionSame(value.original_order, diagram.execution_order) ||
    diagram.connections.length > 6000 ||
    !connectionSame(
      value.members,
      diagram.blocks.map((b) => ({ index: b.index, ref: b.ref })),
    ) ||
    !connectionSame(
      value.edge_relationships,
      orderRelationships(diagram, diagram.execution_order),
    )
  )
    return false;
  const { selection_sha256, ...body } = value;
  return (await connectionSeal(body)) === selection_sha256;
}
export function orderRequest(source: Data, proposed: number[]) {
  return {
    ...Object.fromEntries(
      [
        "source_sha256",
        "diagram_ref",
        "selection_sha256",
        "diagram_sha256",
        "order_property_sha256",
        "original_order",
      ].map((k) => [k, source[k]]),
    ),
    proposed_order: [...proposed],
  };
}
export async function orderReview(
  value: Data,
  source: Data,
  request: Data,
  objectCount: number,
  diagram: OrderDiagram,
) {
  const r = value?.result;
  if (
    !closed(value, [
      "profile",
      "request",
      "result",
      ...flags,
      "review_sha256",
    ]) ||
    !noAuthority(value) ||
    value.profile !== "caf-execution-order-review/1" ||
    !hash(value.review_sha256) ||
    !connectionSame(value.request, request) ||
    !connectionSame(request, orderRequest(source, request.proposed_order)) ||
    !orderAllowed(diagram, request.proposed_order) ||
    !closed(r, [
      "profile",
      "selection",
      "proposed_order",
      "changed_positions",
      "output_sha256",
      "output_xml_sha256",
      "preserved",
      ...flags,
      "order_sha256",
    ]) ||
    !noAuthority(r) ||
    r.profile !== "caf-execution-order-result/1" ||
    !connectionSame(r.selection, source) ||
    !connectionSame(r.proposed_order, request.proposed_order) ||
    !hash(r.output_sha256) ||
    !hash(r.output_xml_sha256) ||
    !hash(r.order_sha256) ||
    r.changed_positions !==
      request.proposed_order.filter(
        (x: number, i: number) => x !== source.original_order[i],
      ).length ||
    !closed(r.preserved, [
      "original_object_count",
      "membership_and_identities",
      "wire_relationships",
      "connections_and_continuation",
      "layout_and_configuration",
      "unrelated_xml_bytes",
      "zip_metadata",
    ]) ||
    !Number.isSafeInteger(objectCount) ||
    objectCount < 1 ||
    r.preserved.original_object_count !== objectCount ||
    Object.entries(r.preserved).some(
      ([k, v]) => k !== "original_object_count" && v !== true,
    )
  )
    return false;
  if (
    r.changed_positions === 0 &&
    (r.output_sha256 !== source.source_sha256 ||
      r.output_xml_sha256 !== source.source_xml_sha256)
  )
    return false;
  if (
    r.changed_positions > 0 &&
    (r.output_sha256 === source.source_sha256 ||
      r.output_xml_sha256 === source.source_xml_sha256)
  )
    return false;
  const { order_sha256, ...result } = r,
    { review_sha256, ...review } = value;
  return (
    (await connectionSeal(result)) === order_sha256 &&
    (await connectionSeal(review)) === review_sha256
  );
}
export async function orderExport(
  result: { blob: Blob; headers: Headers },
  review: Data,
) {
  return (
    result.headers.get("Content-Type")?.split(";")[0] ===
      "application/octet-stream" &&
    result.headers.get("X-Studio-Source-Sha256") ===
      review.request.source_sha256 &&
    result.headers.get("X-Studio-Review-Sha256") === review.review_sha256 &&
    result.headers.get("X-Studio-Order-Sha256") ===
      review.result.order_sha256 &&
    result.headers.get("X-Studio-Request-Sha256") ===
      (await connectionSeal(review.request)) &&
    result.headers.get("X-Studio-Artifact-Sha256") ===
      review.result.output_sha256 &&
    (await sha256Blob(result.blob)) === review.result.output_sha256
  );
}
export type OrderDraft = {
  archive: string;
  diagram: string;
  original: number[];
  proposed: number[];
  saved: string;
};
export type OrderDrafts = Map<string, OrderDraft>;
export const orderKey = (archive: string, diagram: string) =>
  JSON.stringify([archive, diagram]);
export const orderDirty = (draft: OrderDraft) =>
  !connectionSame(draft.original, draft.proposed) &&
  JSON.stringify(draft.proposed) !== draft.saved;
export function rememberOrder(
  drafts: OrderDrafts,
  archive: string,
  diagram: OrderDiagram,
  proposed: number[],
) {
  if (!orderAllowed(diagram, proposed))
    throw Error("That move changes an existing wire's execution relationship.");
  const key = orderKey(archive, diagram.ref),
    old = drafts.get(key);
  if (connectionSame(proposed, diagram.execution_order)) {
    drafts.delete(key);
    return;
  }
  if (!old && drafts.size >= 32)
    throw Error(
      "32 execution-order drafts are retained. Discard an existing draft before adding another.",
    );
  drafts.set(key, {
    archive,
    diagram: diagram.ref,
    original: [...diagram.execution_order],
    proposed: [...proposed],
    saved: old?.saved || "",
  });
}
