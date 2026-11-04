import { sha256Blob } from "./activityContracts";
import { connectionSame, connectionSeal } from "./nativeConnectionContract";

type Data = Record<string, any>;
export const constantProfile = "caf-recorded-float-constant-copy/1";
export type ConstantKind = "float" | "boolean" | "enumeration";
export const constantKinds = {
  float: {
    label: "Float Constant",
    profile: constantProfile,
    classId: "551",
    outputType: 2,
    codes: [11, 796],
    path: "constant-copy",
  },
  boolean: {
    label: "Boolean Constant",
    profile: "caf-recorded-boolean-constant-copy/1",
    classId: "552",
    outputType: 5,
    codes: [13],
    path: "boolean-constant-copy",
  },
  enumeration: {
    label: "Enumeration Constant",
    profile: "caf-recorded-enumeration-constant-copy/1",
    classId: "568",
    outputType: 19,
    codes: [12],
    path: "enum-constant-copy",
  },
} as const;
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, min: number, max: number) =>
  Number.isInteger(v) && (v as number) >= min && (v as number) <= max;
export function constantCoordinate(value: string) {
  return (
    value.length <= 80 &&
    /^[ \t\r\n]*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[ \t\r\n]*$/.test(
      value,
    ) &&
    Number.isFinite(Math.fround(Number(value)))
  );
}
const local = (v: Data) =>
  !!v &&
  v.controller_write === false &&
  v.field_transfer_enabled === false &&
  v.vendor_acceptance_verified === false;
export async function constantSource(
  s: Data,
  request: Data,
  diagram: Data,
  block: Data,
  kind: ConstantKind = "float",
) {
  const spec = constantKinds[kind];
  if (!spec) return false;
  const outputPrefix = request.prototype_ref + `.${spec.outputType}_`;
  const value = s?.recorded_value;
  const valueValid =
    kind === "boolean"
      ? typeof value === "string" && ["true", "false", "0", "1"].includes(value)
      : kind === "enumeration"
        ? value === null ||
          (typeof value === "string" &&
            /^(0|[1-9][0-9]{0,9})$/.test(value) &&
            Number(value) <= 4294967295)
        : value === null ||
          (typeof value === "string" && constantCoordinate(value));
  const enumValid =
    kind !== "enumeration" ||
    (!!s &&
      s.enum_semantics_verified === false &&
      integer(s.number_of_states, 0, 65535) &&
      s.states_text_encoding_set === 802 &&
      [351, 886, 405].includes(s.states_text_code) &&
      (value === null
        ? s.default_encoding_set === null
        : [647, 351, 886, 405].includes(s.default_encoding_set)));
  if (
    !local(s) ||
    block.bacnet_type !== Number(spec.classId) ||
    block.class_id !== spec.classId ||
    block.class_version !== "1.0" ||
    s.profile !== spec.profile ||
    typeof s.scope !== "string" ||
    ["source_sha256", "diagram_ref", "prototype_ref"].some(
      (k) => s[k] !== request[k],
    ) ||
    s.prototype_index !== block.index ||
    s.execution_after !== block.execution_index ||
    s.member_count !== diagram.blocks.length ||
    s.new_index !== s.member_count ||
    !connectionSame(s.execution_order, diagram.execution_order) ||
    s.opaque_layout_code !== block.layout.opaque_code ||
    !integer(s.member_count, 1, 65534) ||
    !integer(s.new_instance, 1, 4194301) ||
    s.new_output_instance !== s.new_instance + 1 ||
    diagram.blocks.some((b: Data) => s.new_instance <= b.instance) ||
    s.new_ref !== `${request.diagram_ref}.${spec.classId}_${s.new_instance}` ||
    s.new_output_ref !==
      `${s.new_ref}.${spec.outputType}_${s.new_output_instance}` ||
    [...s.new_output_ref].length > 512 ||
    typeof s.output_ref !== "string" ||
    !s.output_ref.startsWith(outputPrefix) ||
    !/^(0|[1-9][0-9]{0,9})$/.test(s.output_ref.slice(outputPrefix.length)) ||
    !valueValid ||
    !enumValid ||
    !spec.codes.some((code) => code === s.standard_name_code) ||
    s.exposed_port !== 85 ||
    [
      "diagram_sha256",
      "prototype_sha256",
      "output_sha256",
      "selection_sha256",
    ].some((k) => !hash(s[k])) ||
    !s.suggested_position ||
    ["x", "y"].some(
      (k) =>
        typeof s.suggested_position[k] !== "string" ||
        !constantCoordinate(s.suggested_position[k]),
    )
  )
    return false;
  const { selection_sha256, ...body } = s;
  return (await connectionSeal(body)) === selection_sha256;
}
export async function constantReview(v: Data, request: Data, source: Data) {
  const c = v?.creation;
  if (
    !v ||
    v.controller_write !== false ||
    v.field_transfer_enabled !== false ||
    !local(c) ||
    !connectionSame(v.request, request) ||
    !connectionSame(c.selection, source) ||
    !connectionSame(c.position, { x: request.x, y: request.y }) ||
    [
      "output_sha256",
      "output_xml_sha256",
      "new_object_sha256",
      "new_output_sha256",
      "creation_sha256",
    ].some((k) => !hash(c[k])) ||
    !hash(v.review_sha256)
  )
    return false;
  const { creation_sha256, ...creation } = c;
  const { review_sha256, ...review } = v;
  return (
    (await connectionSeal(creation)) === creation_sha256 &&
    (await connectionSeal(review)) === review_sha256
  );
}
export async function constantExport(
  result: { blob: Blob; headers: Headers },
  review: Data,
) {
  return (
    result.headers.get("X-Studio-Source-Sha256") ===
      review.request.source_sha256 &&
    result.headers.get("X-Studio-Review-Sha256") === review.review_sha256 &&
    result.headers.get("X-Studio-Creation-Sha256") ===
      review.creation.creation_sha256 &&
    result.headers.get("X-Studio-Artifact-Sha256") ===
      review.creation.output_sha256 &&
    (await sha256Blob(result.blob)) === review.creation.output_sha256
  );
}
export type ConstantDraft = {
  archive: string;
  diagram: string;
  prototype: string;
  x?: string;
  y?: string;
  saved?: string;
};
export type ConstantDrafts = Map<string, ConstantDraft>;
export const constantDraftKey = (
  archive: string,
  diagram: string,
  prototype: string,
) => JSON.stringify([archive, diagram, prototype]);
export const constantDraftSignature = (draft: ConstantDraft) =>
  JSON.stringify([draft.x ?? null, draft.y ?? null]);
export const constantDraftDirty = (draft: ConstantDraft) =>
  draft.saved !== constantDraftSignature(draft);
export function rememberConstant(drafts: ConstantDrafts, draft: ConstantDraft) {
  const key = constantDraftKey(draft.archive, draft.diagram, draft.prototype);
  if (!drafts.has(key) && drafts.size >= 32) return false;
  drafts.delete(key);
  drafts.set(key, draft);
  return true;
}
