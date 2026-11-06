import { sha256Blob } from "./activityContracts";
import { connectionSame, connectionSeal } from "./nativeConnectionContract";

type Data = Record<string, any>;
export const cafRemovalProfile = "caf-connection-removal-copy/1";
export const cafRemovalScope =
  "Local CAF copy removing one recorded connection and its aligned continuation row. Preserve all other XML bytes, objects, order, layout and destination configuration. Native execution, unwired fallback, CCT/PCT acceptance and controller transfer remain unverified.";
const flagKeys = [
  "controller_write",
  "field_transfer_enabled",
  "native_execution_verified",
  "vendor_acceptance_verified",
  "can_apply",
];
const hashKeys = [
  "source_sha256",
  "source_xml_sha256",
  "diagram_sha256",
  "connection_property_sha256",
  "continuation_property_sha256",
  "connection_record_sha256",
  "continuation_record_sha256",
  "selection_sha256",
];
const selectionKeys = [
  "profile",
  "scope",
  ...hashKeys,
  "diagram_ref",
  "diagram_class_id",
  "diagram_class_version",
  "wire_index",
  "connection_count",
  "old",
  "source_ref",
  "source_port",
  "target_ref",
  "target_port",
  "continuation",
  "target_remaining_writer_count",
  ...flagKeys,
];
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, max = 65535) =>
  Number.isInteger(v) && Number(v) >= 0 && Number(v) <= max;
const reference = (v: unknown) =>
  typeof v === "string" && [...v].length > 0 && [...v].length <= 512;
const closed = (v: unknown, keys: string[]): v is Data =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const flags = (v: Data) => flagKeys.every((k) => v[k] === false);
const tuple = (v: unknown) =>
  Array.isArray(v) && v.length === 4 && v.every((n) => integer(n));
const continuation = (v: unknown) =>
  closed(v, ["flag", "text"]) &&
  typeof v.flag === "boolean" &&
  typeof v.text === "string" &&
  [...v.text].length <= 8192;
export type CafRemovalWire = {
  index: number;
  raw: number[];
  source_ref: string;
  source_port: number;
  target_ref: string;
  target_port: number;
  continuation: { flag: boolean; text: string };
};
export type CafRemovalDiagram = {
  ref: string;
  class_id: string;
  class_version: string;
  blocks: Array<{ index: number; ref: string }>;
  connections: CafRemovalWire[];
};
export type CafRemovalSourceRequest = {
  source_sha256: string;
  diagram_ref: string;
  wire_index: number;
};

export async function cafRemovalSource(
  value: Data,
  request: CafRemovalSourceRequest,
  diagram: CafRemovalDiagram,
  wire: CafRemovalWire,
) {
  if (
    !closed(value, selectionKeys) ||
    !flags(value) ||
    value.profile !== cafRemovalProfile ||
    value.scope !== cafRemovalScope ||
    hashKeys.some((k) => !hash(value[k])) ||
    !["536", "575"].includes(value.diagram_class_id) ||
    value.diagram_class_version !== "1.0" ||
    !reference(value.diagram_ref) ||
    !reference(value.source_ref) ||
    !reference(value.target_ref) ||
    !integer(value.wire_index, 65534) ||
    !integer(value.connection_count) ||
    value.connection_count < 1 ||
    value.wire_index >= value.connection_count ||
    !tuple(value.old) ||
    !continuation(value.continuation) ||
    !integer(value.source_port) ||
    !integer(value.target_port) ||
    !integer(value.target_remaining_writer_count) ||
    value.source_sha256 !== request.source_sha256 ||
    value.diagram_ref !== request.diagram_ref ||
    value.wire_index !== request.wire_index ||
    value.diagram_ref !== diagram.ref ||
    value.diagram_class_id !== diagram.class_id ||
    value.diagram_class_version !== diagram.class_version ||
    value.connection_count !== diagram.connections.length ||
    value.wire_index !== wire.index ||
    !connectionSame(value.old, wire.raw) ||
    value.source_ref !== wire.source_ref ||
    value.source_port !== wire.source_port ||
    value.target_ref !== wire.target_ref ||
    value.target_port !== wire.target_port ||
    value.old[0] !==
      diagram.blocks.find((b) => b.ref === wire.source_ref)?.index ||
    value.old[1] !== wire.source_port ||
    value.old[2] !==
      diagram.blocks.find((b) => b.ref === wire.target_ref)?.index ||
    value.old[3] !== wire.target_port ||
    !connectionSame(value.continuation, wire.continuation) ||
    value.target_remaining_writer_count !==
      diagram.connections.filter(
        (w) =>
          w.index !== wire.index &&
          w.target_ref === wire.target_ref &&
          w.target_port === wire.target_port,
      ).length
  )
    return false;
  const { selection_sha256, ...body } = value;
  return (await connectionSeal(body)) === selection_sha256;
}

export function cafRemovalRequest(source: Data) {
  return Object.fromEntries(
    [
      "source_sha256",
      "diagram_ref",
      "wire_index",
      "selection_sha256",
      "diagram_sha256",
      "connection_property_sha256",
      "continuation_property_sha256",
      "connection_record_sha256",
      "continuation_record_sha256",
      "connection_count",
      "old",
      "continuation",
    ].map((k) => [k, source[k]]),
  );
}

export async function cafRemovalReview(
  value: Data,
  request: Data,
  source: Data,
  objectCount: number,
) {
  const r = value?.removal;
  if (
    !closed(value, [
      "profile",
      "request",
      "removal",
      ...flagKeys,
      "review_sha256",
    ]) ||
    !flags(value) ||
    value.profile !== "caf-connection-removal-review/1" ||
    !hash(value.review_sha256) ||
    !connectionSame(value.request, request) ||
    !connectionSame(request, cafRemovalRequest(source)) ||
    !closed(r, [
      "profile",
      "selection",
      "output_sha256",
      "output_xml_sha256",
      "removed_connection_count",
      "remaining_connection_count",
      "preserved",
      ...flagKeys,
      "removal_sha256",
    ]) ||
    !flags(r) ||
    r.profile !== "caf-connection-removal-result/1" ||
    !connectionSame(r.selection, source) ||
    !hash(r.output_sha256) ||
    !hash(r.output_xml_sha256) ||
    !hash(r.removal_sha256) ||
    r.output_sha256 === source.source_sha256 ||
    r.output_xml_sha256 === source.source_xml_sha256 ||
    r.removed_connection_count !== 1 ||
    r.remaining_connection_count !== source.connection_count - 1 ||
    !closed(r.preserved, [
      "original_object_count",
      "graph_blocks",
      "graph_execution_order",
      "graph_layout",
      "destination_configuration",
      "unrelated_xml_bytes",
      "zip_metadata",
    ]) ||
    !Number.isSafeInteger(objectCount) ||
    objectCount < 1 ||
    r.preserved.original_object_count !== objectCount ||
    [
      "graph_blocks",
      "graph_execution_order",
      "graph_layout",
      "destination_configuration",
      "unrelated_xml_bytes",
      "zip_metadata",
    ].some((k) => r.preserved[k] !== true)
  )
    return false;
  const { removal_sha256, ...removal } = r;
  const { review_sha256, ...review } = value;
  return (
    (await connectionSeal(removal)) === removal_sha256 &&
    (await connectionSeal(review)) === review_sha256
  );
}

export async function cafRemovalExport(
  result: { blob: Blob; headers: Headers },
  review: Data,
) {
  return (
    result.headers.get("X-Studio-Source-Sha256") ===
      review.request.source_sha256 &&
    result.headers.get("X-Studio-Review-Sha256") === review.review_sha256 &&
    result.headers.get("X-Studio-Removal-Sha256") ===
      review.removal.removal_sha256 &&
    result.headers.get("X-Studio-Request-Sha256") ===
      (await connectionSeal(review.request)) &&
    result.headers.get("X-Studio-Artifact-Sha256") ===
      review.removal.output_sha256 &&
    (await sha256Blob(result.blob)) === review.removal.output_sha256
  );
}

/** A separate removal handoff: constant creation identities are never fabricated. */
export type RemovedCafCopy = {
  blob: Blob;
  name: string;
  sha256: string;
  sourceArchive: string;
  diagram: string;
  selectionSha256: string;
  reviewSha256: string;
};
export type OpenRemovedCafCopy = (
  copy: RemovedCafCopy,
  current: () => boolean,
) => Promise<boolean>;
export type CafRemovalHint = { archive: string; diagram: string };
export async function removedCafFile(
  copy: RemovedCafCopy,
  current: () => boolean,
) {
  if (!current()) return null;
  if (
    !copy ||
    !(copy.blob instanceof Blob) ||
    !hash(copy.sha256) ||
    !hash(copy.sourceArchive) ||
    copy.sha256 === copy.sourceArchive ||
    !hash(copy.selectionSha256) ||
    !hash(copy.reviewSha256) ||
    !reference(copy.diagram) ||
    typeof copy.name !== "string" ||
    !copy.name ||
    !/\.caf$/i.test(copy.name) ||
    /[\\/\r\n\x00]/.test(copy.name) ||
    (await sha256Blob(copy.blob)) !== copy.sha256
  )
    throw new Error(
      "CAF removal copy identity or bytes changed. Save a fresh reviewed copy.",
    );
  if (!current()) return null;
  return new File([copy.blob], copy.name, { type: "application/octet-stream" });
}
