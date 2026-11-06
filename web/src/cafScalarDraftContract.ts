import { sha256 } from "@noble/hashes/sha2.js";
import { cafEnumMetadata } from "./cafScalarCopy";

export type ScalarProposal = {
  ref: string;
  property: string;
  old: string;
  value: string;
};
export type DraftToken = { id: string; revision: number };
export type ScalarCheckpoint = DraftToken & {
  profile: string;
  caf_sha256: string;
  created_at: string;
  updated_at: string;
  changes: ScalarProposal[];
  checkpoint_sha256: string;
};
export type UnavailableCheckpoint = {
  state: "unavailable";
  id: string | null;
  revision: number | null;
  error: string;
};
export type RestoredScalarDraft = {
  checkpoint: ScalarCheckpoint;
  enumKeys: string[];
};
type Data = Record<string, any>;
export const scalarDraftScope =
  "Source-bound unfinished scalar text only. Saving does not validate proposed values or export a CAF. Restoration rechecks original field eligibility, but restores no successful export, review, connection or controller write authority.";
const unavailable =
  "Saved scalar draft evidence is unavailable or inconsistent; remove the checkpoint before saving new work.";
const hash = (v: unknown): v is string =>
  typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const identifier = (v: unknown): v is string =>
  typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const integer = (v: unknown, maximum: number) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= maximum;
const revision = (v: unknown): v is number =>
  integer(v, 2147483647) && (v as number) > 0;
const object = (v: any): v is Data =>
  !!v && typeof v === "object" && !Array.isArray(v);
const closed = (v: any, keys: string[]) =>
  object(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const text = (v: unknown, max = 8192): v is string =>
  typeof v === "string" &&
  [...v].length <= max &&
  !/(?:[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?:^|[^\uD800-\uDBFF])[\uDC00-\uDFFF])/.test(
    v,
  );
const timestamp = (v: unknown) =>
  text(v, 80) &&
  /(?:Z|[+-]\d\d:\d\d)$/.test(v) &&
  Number.isFinite(Date.parse(v));
const propertyId = (v: unknown) =>
  typeof v === "string" &&
  /^(0|[1-9][0-9]{0,4})$/.test(v) &&
  Number(v) <= 65535;
export const rawScalarKey = (changes: ScalarProposal[]) =>
  JSON.stringify(
    changes.map(({ ref, property, old, value }) => ({
      ref,
      property,
      old,
      value,
    })),
  );
export function scalarProposals(v: unknown): v is ScalarProposal[] {
  return (
    Array.isArray(v) &&
    v.length > 0 &&
    v.length <= 1000 &&
    v.every(
      (r) =>
        closed(r, ["ref", "property", "old", "value"]) &&
        text(r.ref, 512) &&
        r.ref.length > 0 &&
        propertyId(r.property) &&
        text(r.old) &&
        text(r.value),
    ) &&
    new Set(v.map((r) => JSON.stringify([r.ref, r.property]))).size === v.length
  );
}
// Checkpoints contain only safe integers and raw strings. Match Python's compact
// sorted ensure_ascii encoding without normalizing unfinished proposal text.
function sealedJSON(v: any): string {
  if (Array.isArray(v)) return "[" + v.map(sealedJSON).join(",") + "]";
  if (object(v))
    return (
      "{" +
      Object.keys(v)
        .sort()
        .map((k) => sealedJSON(k) + ":" + sealedJSON(v[k]))
        .join(",") +
      "}"
    );
  return JSON.stringify(v).replace(
    /[\u007f-\uffff]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
  );
}
export function savedScalarCheckpoint(v: any, caf: string): ScalarCheckpoint {
  if (
    !closed(v, [
      "profile",
      "id",
      "caf_sha256",
      "revision",
      "created_at",
      "updated_at",
      "changes",
      "checkpoint_sha256",
    ]) ||
    v.profile !== "caf-scalar-draft/1" ||
    !identifier(v.id) ||
    !revision(v.revision) ||
    !hash(caf) ||
    v.caf_sha256 !== caf ||
    !timestamp(v.created_at) ||
    !timestamp(v.updated_at) ||
    !scalarProposals(v.changes) ||
    !hash(v.checkpoint_sha256)
  )
    throw new Error(
      "Saved scalar draft does not match this original CAF or its raw proposal contract.",
    );
  const { checkpoint_sha256: digest, ...body } = v;
  const bytes = new TextEncoder().encode(sealedJSON(body));
  const seal = Array.from(sha256(bytes), (v) =>
    v.toString(16).padStart(2, "0"),
  ).join("");
  if (sealedJSON(v).length > 1048576 || digest !== seal)
    throw new Error(
      "Saved scalar draft integrity check failed. Refresh the checkpoint before continuing.",
    );
  return v;
}
function envelope(v: Data, caf: string, kind: string, revalidated: boolean) {
  if (
    !object(v) ||
    v.profile !== `caf-scalar-draft-${kind}/1` ||
    v.caf_sha256 !== caf ||
    !hash(caf) ||
    v.scope !== scalarDraftScope ||
    v.source_revalidated !== revalidated ||
    v.read_only !== true ||
    [
      "controller_queries",
      "controller_writes",
      "field_actions",
      "can_apply",
      "proposal_values_validated",
      "export_success_restored",
    ].some((k) => v[k] !== false)
  )
    throw new Error(
      "Scalar draft response differs from this original CAF and its local recovery scope.",
    );
}
export function scalarDraftToken(
  v: ScalarCheckpoint | UnavailableCheckpoint | null,
): DraftToken | null {
  return v && identifier(v.id) && revision(v.revision)
    ? { id: v.id, revision: v.revision }
    : null;
}
export function scalarDraftStatus(v: Data, caf: string) {
  envelope(v, caf, "status", false);
  const c = v.capacity;
  if (
    !closed(c, ["count", "limit", "bytes", "byte_limit"]) ||
    c.limit !== 32 ||
    c.byte_limit !== 8388608 ||
    !integer(c.count, 32) ||
    !integer(c.bytes, 8388608)
  )
    throw new Error("Unsupported scalar draft storage capacity.");
  let checkpoint: ScalarCheckpoint | UnavailableCheckpoint | null = null;
  if (v.checkpoint?.state === "unavailable") {
    const r = v.checkpoint;
    if (
      !closed(r, ["state", "id", "revision", "error"]) ||
      r.error !== unavailable ||
      (r.id !== null && !identifier(r.id)) ||
      (r.revision !== null && !revision(r.revision))
    )
      throw new Error("Unsupported unavailable scalar checkpoint.");
    checkpoint = r;
  } else if (v.checkpoint !== null)
    checkpoint = savedScalarCheckpoint(v.checkpoint, caf);
  return { checkpoint, capacity: c };
}
export function savedScalarResult(
  v: Data,
  caf: string,
  changes: ScalarProposal[],
  expected: DraftToken | null,
) {
  envelope(v, caf, "save", true);
  const checkpoint = savedScalarCheckpoint(v.checkpoint, caf);
  if (
    rawScalarKey(checkpoint.changes) !== rawScalarKey(changes) ||
    checkpoint.revision !== (expected ? expected.revision + 1 : 1) ||
    (expected && checkpoint.id !== expected.id)
  )
    throw new Error(
      "Saved scalar draft differs from the submitted raw proposals or checkpoint revision.",
    );
  return checkpoint;
}
export function restoredScalarResult(
  v: Data,
  caf: string,
  expected: ScalarCheckpoint,
): RestoredScalarDraft {
  envelope(v, caf, "restore", true);
  const checkpoint = savedScalarCheckpoint(v.checkpoint, caf);
  if (
    checkpoint.id !== expected.id ||
    checkpoint.revision !== expected.revision ||
    checkpoint.checkpoint_sha256 !== expected.checkpoint_sha256 ||
    !Array.isArray(v.fields) ||
    v.fields.length !== checkpoint.changes.length
  )
    throw new Error(
      "Restored scalar draft differs from the selected saved checkpoint.",
    );
  const enumKeys: string[] = [];
  for (const [index, row] of checkpoint.changes.entries()) {
    const f = v.fields[index],
      p = f?.property,
      s = p?.scalar,
      isEnum = s?.type === "enum";
    if (
      !closed(f, ["ref", "class_id", "property"]) ||
      f.ref !== row.ref ||
      (f.class_id !== null && typeof f.class_id !== "string") ||
      !closed(
        p,
        isEnum
          ? ["id", "kind", "editable", "scalar", "enum_code_copy"]
          : ["id", "kind", "editable", "scalar"],
      ) ||
      p.id !== row.property ||
      p.kind !== "property" ||
      p.editable !== true ||
      !["28", "2390", "3113"].includes(p.id) ||
      !closed(s, ["type", "text", "attributes"]) ||
      s.text !== row.old ||
      !object(s.attributes)
    )
      throw new Error(
        "Restored scalar field evidence does not match the original CAF proposal.",
      );
    if (isEnum) {
      if (!cafEnumMetadata(p, { ref: f.ref, class_id: f.class_id }, caf))
        throw new Error(
          "Restored Enum eligibility differs from the original CAF field.",
        );
      enumKeys.push(JSON.stringify([caf, row.ref, row.property]));
    } else if (
      ![
        "string",
        "float",
        "boolean",
        "short",
        "unsignedByte",
        "unsignedShort",
        "unsignedLong",
      ].includes(s.type) ||
      Object.keys(s.attributes).length
    )
      throw new Error(
        "Unsupported original scalar field in saved draft restoration.",
      );
  }
  return { checkpoint, enumKeys };
}
export function removedScalarResult(
  v: Data,
  caf: string,
  expected: DraftToken,
) {
  envelope(v, caf, "remove", false);
  if (
    v.id !== expected.id ||
    v.revision !== expected.revision ||
    v.removed !== true
  )
    throw new Error(
      "Scalar draft removal did not match the selected checkpoint. Refresh saved draft status.",
    );
}
