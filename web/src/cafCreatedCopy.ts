import { sha256Blob } from "./activityContracts";
import { constantKinds, type ConstantKind } from "./cafConstantContract";

export type CafCreationHint = {
  archive: string;
  diagram: string;
  prototype: string;
  kind: ConstantKind;
};
export type CreatedCafCopy = {
  blob: Blob;
  name: string;
  sha256: string;
  sourceArchive: string;
  diagram: string;
  prototype: string;
  kind: ConstantKind;
};
export type OpenCafCopy = (
  copy: CreatedCafCopy,
  current: () => boolean,
) => Promise<boolean>;

/** Recheck immutable bytes at the document handoff, before replacing a file. */
export async function createdCafFile(
  copy: CreatedCafCopy,
  current: () => boolean,
) {
  if (!current()) return null;
  const hash = (value: unknown) =>
    typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  if (
    !copy ||
    !(copy.blob instanceof Blob) ||
    !hash(copy.sha256) ||
    !hash(copy.sourceArchive) ||
    typeof copy.name !== "string" ||
    !copy.name ||
    !/\.caf$/i.test(copy.name) ||
    /[\\/\r\n\x00]/.test(copy.name) ||
    !Object.prototype.hasOwnProperty.call(constantKinds, copy.kind) ||
    typeof copy.diagram !== "string" ||
    !copy.diagram ||
    [...copy.diagram].length > 512 ||
    typeof copy.prototype !== "string" ||
    [...copy.prototype].length > 512
  )
    throw new Error(
      "CAF copy identity or location is invalid. Save a fresh reviewed copy.",
    );
  const prefix = `${copy.diagram}.${constantKinds[copy.kind].classId}_`;
  const instance = copy.prototype.slice(prefix.length);
  if (
    !copy.prototype.startsWith(prefix) ||
    !/^[1-9][0-9]{0,6}$/.test(instance) ||
    Number(instance) > 4194302 ||
    (await sha256Blob(copy.blob)) !== copy.sha256
  )
    throw new Error(
      "CAF copy bytes or location changed. Save a fresh reviewed copy.",
    );
  if (!current()) return null;
  return new File([copy.blob], copy.name, { type: "application/octet-stream" });
}

/** Prefer only a location actually present in the newly loaded file graph. */
export function creationHintFor(
  hint: CafCreationHint | null | undefined,
  archive: string,
  diagram: { ref: string; blocks: Array<Record<string, any>> },
) {
  if (
    !hint ||
    !diagram ||
    typeof diagram.ref !== "string" ||
    !Array.isArray(diagram.blocks) ||
    hint.archive !== archive ||
    hint.diagram !== diagram.ref ||
    !Object.prototype.hasOwnProperty.call(constantKinds, hint.kind)
  )
    return null;
  return diagram.blocks.some(
    (block) =>
      block.ref === hint.prototype &&
      block.class_id === constantKinds[hint.kind].classId &&
      block.class_version === "1.0",
  )
    ? hint
    : null;
}
