import { sha256Text } from "./activityContracts";

/** The browser scalar editor sends only these four source-bound string fields. */
export async function cafScalarRequestSha(changes: any[]) {
  const rows = changes.map((change) => {
    if (
      !change ||
      Object.keys(change).sort().join(",") !== "old,property,ref,value" ||
      ![change.old, change.property, change.ref, change.value].every(
        (value) => typeof value === "string",
      )
    )
      throw new Error(
        "Unsupported CAF scalar request. Reopen the original file.",
      );
    return {
      old: change.old,
      property: change.property,
      ref: change.ref,
      value: change.value,
    };
  });
  return sha256Text(JSON.stringify({ changes: rows }));
}

/** Enum eligibility stays tied to this file, actual block and stored scalar. */
export function cafEnumMetadata(property: any, selected: any, source: string) {
  const metadata = property?.enum_code_copy,
    scalar = property?.scalar;
  if (
    !metadata ||
    !/^[a-f0-9]{64}$/.test(source) ||
    Object.keys(metadata).sort().join(",") !==
      "class_id,controller_write,enum_semantics_verified,original_code,profile,property,record_ref,set_reference,source_sha256" ||
    metadata.profile !== "caf-enum-default-code-copy/1" ||
    metadata.source_sha256 !== source ||
    metadata.record_ref !== selected?.ref ||
    metadata.class_id !== selected?.class_id ||
    !["528", "529"].includes(metadata.class_id) ||
    metadata.property !== "3113" ||
    property.id !== "3113" ||
    property.kind !== "property" ||
    property.editable !== true ||
    scalar?.type !== "enum" ||
    typeof scalar.text !== "string" ||
    !/^(0|[1-9][0-9]{0,9})$/.test(scalar.text) ||
    Number(scalar.text) > 4294967295 ||
    metadata.original_code !== Number(scalar.text) ||
    !scalar.attributes ||
    typeof scalar.attributes !== "object" ||
    Array.isArray(scalar.attributes) ||
    !Object.keys(scalar.attributes).every((key) => key === "set") ||
    (Object.hasOwn(scalar.attributes, "set") &&
      typeof scalar.attributes.set !== "string") ||
    metadata.set_reference !== (scalar.attributes.set ?? null) ||
    metadata.enum_semantics_verified !== false ||
    metadata.controller_write !== false
  )
    return null;
  return metadata;
}
