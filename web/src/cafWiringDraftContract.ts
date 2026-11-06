import {
  connectionSame as same,
  connectionSeal as seal,
} from "./nativeConnectionContract";
type Data = Record<string, any>;
export type WiringSelection = {
  diagram_ref: string;
  wire_index: number;
  connection_count: number;
  old: number[];
  rewire_source_ref: string;
  connection_source_ref: string;
  connection_target_ref: string;
};
export const wiringDraftScope =
  "Unfinished original-source wiring selections only. Restore rechecks the original graph and grants no export success, compatibility, compilation or field authority.";
const flags = [
  "controller_queries",
  "controller_writes",
  "can_apply",
  "graph_compatibility_validated",
  "export_success_restored",
];
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: any) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const integer = (v: any, max = 65535) =>
  Number.isInteger(v) && v >= 0 && v <= max;
const closed = (v: any, keys: string[]): v is Data =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const ref = (v: any, empty = false) =>
  typeof v === "string" &&
  [...v].length >= (empty ? 0 : 1) &&
  [...v].length <= 512;
const keys = [
  "diagram_ref",
  "wire_index",
  "connection_count",
  "old",
  "rewire_source_ref",
  "connection_source_ref",
  "connection_target_ref",
];
function selectionShape(v: any): v is WiringSelection {
  return (
    closed(v, keys) &&
    ref(v.diagram_ref) &&
    integer(v.wire_index, 65534) &&
    integer(v.connection_count) &&
    v.connection_count > 0 &&
    v.wire_index < v.connection_count &&
    Array.isArray(v.old) &&
    v.old.length === 4 &&
    v.old.every((n: any) => integer(n)) &&
    [
      v.rewire_source_ref,
      v.connection_source_ref,
      v.connection_target_ref,
    ].every((r) => ref(r, true)) &&
    [
      v.rewire_source_ref,
      v.connection_source_ref,
      v.connection_target_ref,
    ].some(Boolean)
  );
}
export function wiringSelection(v: any, graph: Data): v is WiringSelection {
  return (
    selectionShape(v) &&
    v.diagram_ref === graph.ref &&
    v.connection_count === graph.connections.length &&
    same(v.old, graph.connections[v.wire_index]?.raw) &&
    [
      v.rewire_source_ref,
      v.connection_source_ref,
      v.connection_target_ref,
    ].every((r) => !r || graph.blocks.some((b: Data) => b.ref === r))
  );
}

export function wiringDraftToken(v: Data | null) {
  return v && id(v.id) && integer(v.revision, 2147483647) && v.revision > 0
    ? { id: v.id, revision: v.revision }
    : null;
}
export async function wiringCheckpoint(
  v: Data,
  source: string,
  graph: Data,
  revalidate = true,
) {
  if (
    !closed(v, [
      "profile",
      "id",
      "caf_sha256",
      "revision",
      "created_at",
      "updated_at",
      "selection",
      "source_evidence",
      "checkpoint_sha256",
    ]) ||
    v.profile !== "caf-wiring-draft/1" ||
    v.caf_sha256 !== source ||
    !wiringDraftToken(v) ||
    !hash(v.checkpoint_sha256) ||
    ![v.created_at, v.updated_at].every(
      (t) =>
        typeof t === "string" &&
        t.length <= 80 &&
        /(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(t) &&
        Number.isFinite(Date.parse(t)),
    ) ||
    !selectionShape(v.selection) ||
    v.selection.diagram_ref !== graph.ref ||
    (revalidate && !wiringSelection(v.selection, graph))
  )
    return false;
  const e = v.source_evidence,
    wire = graph.connections[v.selection.wire_index];
  if (
    !closed(e, [
      "diagram_sha256",
      "diagram_class_id",
      "diagram_class_version",
      "blocks_sha256",
      "source_ref",
      "target_ref",
      "continuation_flag",
      "continuation_text",
    ]) ||
    !hash(e.diagram_sha256) ||
    !hash(e.blocks_sha256) ||
    !["536", "575"].includes(e.diagram_class_id) ||
    e.diagram_class_version !== "1.0" ||
    !ref(e.source_ref) ||
    !ref(e.target_ref) ||
    typeof e.continuation_flag !== "boolean" ||
    typeof e.continuation_text !== "string" ||
    [...e.continuation_text].length > 8192
  )
    return false;
  if (revalidate) {
    const members = graph.blocks.map((b: Data) => ({
      index: b.index,
      ref: b.ref,
      class_id: b.class_id,
      class_version: b.class_version,
    }));
    if (
      !wire ||
      e.diagram_class_id !== graph.class_id ||
      graph.class_version !== "1.0" ||
      e.source_ref !== wire.source_ref ||
      e.target_ref !== wire.target_ref ||
      e.continuation_flag !== wire.continuation.flag ||
      e.continuation_text !== wire.continuation.text ||
      e.blocks_sha256 !== (await seal(members))
    )
      return false;
  }

  const { checkpoint_sha256, ...body } = v;
  return checkpoint_sha256 === (await seal(body));
}
function envelope(
  v: Data,
  operation: string,
  source: string,
  diagram: string,
  extra: string[],
) {
  return (
    closed(v, [
      "profile",
      "caf_sha256",
      "diagram_ref",
      "scope",
      ...flags,
      "source_revalidated",
      ...extra,
    ]) &&
    v.profile === `caf-wiring-draft-${operation}/1` &&
    v.caf_sha256 === source &&
    hash(source) &&
    v.diagram_ref === diagram &&
    v.scope === wiringDraftScope &&
    flags.every((k) => v[k] === false) &&
    v.source_revalidated === ["save", "restore"].includes(operation)
  );
}
export async function wiringDraftStatus(v: Data, source: string, graph: Data) {
  if (
    !envelope(v, "status", source, graph.ref, ["checkpoint", "capacity"]) ||
    !closed(v.capacity, ["count", "limit", "bytes", "byte_limit"]) ||
    v.capacity.limit !== 32 ||
    v.capacity.byte_limit !== 8 * 1024 * 1024 ||
    !integer(v.capacity.count, Number.MAX_SAFE_INTEGER) ||
    !integer(v.capacity.bytes, Number.MAX_SAFE_INTEGER)
  )
    return false;
  if (v.checkpoint === null) return true;
  if (v.checkpoint?.state === "unavailable")
    return (
      closed(v.checkpoint, ["state", "id", "revision", "error"]) &&
      (v.checkpoint.id === null || id(v.checkpoint.id)) &&
      (v.checkpoint.revision === null ||
        (integer(v.checkpoint.revision, 2147483647) &&
          v.checkpoint.revision > 0)) &&
      typeof v.checkpoint.error === "string" &&
      v.checkpoint.error.length <= 1000
    );
  return wiringCheckpoint(v.checkpoint, source, graph, false);
}
export async function wiringDraftResult(
  v: Data,
  operation: "save" | "restore",
  source: string,
  graph: Data,
  expected: Data | null,
  selection?: WiringSelection,
) {
  if (
    !envelope(v, operation, source, graph.ref, ["checkpoint"]) ||
    !(await wiringCheckpoint(v.checkpoint, source, graph))
  )
    return false;
  const saved = v.checkpoint;
  if (operation === "restore") return same(wiringDraftToken(saved), expected);
  return (
    same(saved.selection, selection) &&
    (expected
      ? saved.id === expected.id && saved.revision === expected.revision + 1
      : saved.revision === 1)
  );
}
export function wiringDraftRemoved(
  v: Data,
  source: string,
  diagram: string,
  expected: Data,
) {
  return (
    envelope(v, "remove", source, diagram, ["id", "revision", "removed"]) &&
    v.removed === true &&
    same({ id: v.id, revision: v.revision }, expected)
  );
}
