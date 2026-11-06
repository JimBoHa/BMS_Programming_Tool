import {
  connectionSame as same,
  connectionSeal as seal,
} from "./nativeConnectionContract";
import { constantKinds, type ConstantKind } from "./cafConstantContract";
type Data = Record<string, any>;
export type CreationContext = {
  kind: ConstantKind;
  diagram_ref: string;
  prototype_ref: string;
};
export type CreationSelection = CreationContext & {
  selection_sha256: string;
  x: string;
  y: string;
};
export const creationDraftScope =
  "Unfinished coordinates for one original recorded CAF copy prototype only. Restoration rechecks its source inspector, but grants no coordinate validation, export success, compilation, application association or controller authority.";
const flags = [
  "controller_queries",
  "controller_writes",
  "can_apply",
  "coordinates_validated",
  "export_success_restored",
];
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: any) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const integer = (v: any, max = Number.MAX_SAFE_INTEGER) =>
  Number.isInteger(v) && v >= 0 && v <= max;
const closed = (v: any, keys: string[]): v is Data =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const text = (v: any, max: number, min = 0) =>
  typeof v === "string" && [...v].length >= min && [...v].length <= max;
const contextKeys = ["kind", "diagram_ref", "prototype_ref"];
export function creationContext(v: any): v is CreationContext {
  return (
    closed(v, contextKeys) &&
    typeof v.kind === "string" &&
    Object.hasOwn(constantKinds, v.kind) &&
    text(v.diagram_ref, 512, 1) &&
    text(v.prototype_ref, 512, 1)
  );
}
export function creationSelection(v: any): v is CreationSelection {
  return (
    closed(v, [...contextKeys, "selection_sha256", "x", "y"]) &&
    creationContext({
      kind: v.kind,
      diagram_ref: v.diagram_ref,
      prototype_ref: v.prototype_ref,
    }) &&
    hash(v.selection_sha256) &&
    text(v.x, 8192) &&
    text(v.y, 8192)
  );
}
export const selectionContext = (v: CreationSelection): CreationContext => ({
  kind: v.kind,
  diagram_ref: v.diagram_ref,
  prototype_ref: v.prototype_ref,
});
export function creationDraftToken(v: Data | null) {
  return v && id(v.id) && integer(v.revision, 2147483647) && v.revision > 0
    ? { id: v.id, revision: v.revision }
    : null;
}
export async function creationCheckpoint(
  v: Data,
  archive: string,
  context: CreationContext,
  source?: Data | null,
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
    v.profile !== "caf-creation-draft/1" ||
    !hash(archive) ||
    v.caf_sha256 !== archive ||
    !creationDraftToken(v) ||
    !hash(v.checkpoint_sha256) ||
    ![v.created_at, v.updated_at].every(
      (t) =>
        typeof t === "string" &&
        t.length <= 80 &&
        /(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(t) &&
        Number.isFinite(Date.parse(t)),
    ) ||
    !creationSelection(v.selection) ||
    !same(selectionContext(v.selection), context)
  )
    return false;
  const e = v.source_evidence;
  if (
    !closed(e, [
      "source_profile",
      "selection_sha256",
      "diagram_sha256",
      "prototype_sha256",
    ]) ||
    !text(e.source_profile, 256, 1) ||
    ![e.selection_sha256, e.diagram_sha256, e.prototype_sha256].every(hash) ||
    e.selection_sha256 !== v.selection.selection_sha256
  )
    return false;
  if (
    source &&
    (source.source_sha256 !== archive ||
      source.diagram_ref !== context.diagram_ref ||
      source.prototype_ref !== context.prototype_ref ||
      e.source_profile !== source.profile ||
      e.selection_sha256 !== source.selection_sha256 ||
      e.diagram_sha256 !== source.diagram_sha256 ||
      e.prototype_sha256 !== source.prototype_sha256)
  )
    return false;
  const { checkpoint_sha256, ...body } = v;
  return checkpoint_sha256 === (await seal(body));
}
function envelope(
  v: Data,
  operation: string,
  archive: string,
  context: CreationContext,
  extra: string[],
) {
  return (
    closed(v, [
      "profile",
      "caf_sha256",
      "context",
      "scope",
      ...flags,
      "source_revalidated",
      ...extra,
    ]) &&
    v.profile === `caf-creation-draft-${operation}/1` &&
    hash(archive) &&
    v.caf_sha256 === archive &&
    creationContext(v.context) &&
    same(v.context, context) &&
    v.scope === creationDraftScope &&
    flags.every((k) => v[k] === false) &&
    v.source_revalidated === ["save", "restore"].includes(operation)
  );
}
export async function creationDraftStatus(
  v: Data,
  archive: string,
  context: CreationContext,
) {
  if (
    !envelope(v, "status", archive, context, ["checkpoint", "capacity"]) ||
    !closed(v.capacity, ["count", "limit", "bytes", "byte_limit"]) ||
    v.capacity.limit !== 32 ||
    v.capacity.byte_limit !== 8 * 1024 * 1024 ||
    !integer(v.capacity.count) ||
    !integer(v.capacity.bytes)
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
      text(v.checkpoint.error, 1000)
    );
  return creationCheckpoint(v.checkpoint, archive, context);
}
export async function creationDraftResult(
  v: Data,
  operation: "save" | "restore",
  archive: string,
  context: CreationContext,
  source: Data,
  expected: Data | null,
  selection?: CreationSelection,
  saved?: Data,
) {
  if (
    !envelope(v, operation, archive, context, ["checkpoint"]) ||
    !(await creationCheckpoint(v.checkpoint, archive, context, source))
  )
    return false;
  const result = v.checkpoint;
  if (operation === "restore")
    return same(creationDraftToken(result), expected) && same(result, saved);
  return (
    same(result.selection, selection) &&
    (expected
      ? result.id === expected.id && result.revision === expected.revision + 1
      : result.revision === 1)
  );
}
export function creationDraftRemoved(
  v: Data,
  archive: string,
  context: CreationContext,
  expected: Data,
) {
  return (
    envelope(v, "remove", archive, context, ["id", "revision", "removed"]) &&
    v.removed === true &&
    same({ id: v.id, revision: v.revision }, expected)
  );
}
