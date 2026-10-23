/** A separately versioned wire-text domain; legacy numeric draft rules stay unchanged. */
export const STRING_DRAFT = "native-schedule-utf8-weekly-day-draft/1";
export const STRING_DRAFT_RULES =
  "efcaabf953a4bc6c6d647494fdc11bce9cf7c692103dd4a3d0e3d8579434b1d3";
export const STRING_WRITE = "native-schedule-reviewed-utf8-weekly-day-write/1";
export const STRING_WRITE_RULES =
  "a448c5c8eea93bd61f241fdccd6338da773caa5c96f7f4f015ae0390c32a1374";
export const STRING_BYTES = 256;
// Every admitted byte may need a six-character JSON escape, plus the quotes.
export const STRING_EDITOR_LENGTH = STRING_BYTES * 6 + 2;

export function wellFormedString(value: unknown): value is string {
  if (typeof value !== "string") return false;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(++index);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}
export function nativeString(value: unknown): value is string {
  // TextEncoder replaces unpaired surrogates. Check them before encoding.
  return (
    wellFormedString(value) &&
    new TextEncoder().encode(value).length <= STRING_BYTES
  );
}
export function parseStringEditor(text: string): string {
  if (text.length > STRING_EDITOR_LENGTH)
    throw new Error("CharacterString editor literal exceeds its bound.");
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(
      "CharacterString requires a quoted JSON string literal; escapes preserve controls and newlines.",
    );
  }
  if (!nativeString(value))
    throw new Error(
      "CharacterString must be well-formed Unicode within 256 UTF-8 wire bytes.",
    );
  return value;
}
export function stringDraftCapability(value: any): boolean {
  return (
    value?.profile === STRING_DRAFT &&
    value.rules_sha256 === STRING_DRAFT_RULES &&
    value.utf8_bytes === STRING_BYTES &&
    value.rules?.id === STRING_DRAFT &&
    value.rules.stack === "bacpypes3/0.0.110"
  );
}
export function stringWriteCapability(value: any): boolean {
  return (
    value?.profile === STRING_WRITE &&
    value.rules_sha256 === STRING_WRITE_RULES &&
    value.draft_profile === STRING_DRAFT &&
    value.draft_rules_sha256 === STRING_DRAFT_RULES &&
    value.rules?.profile === STRING_WRITE &&
    value.rules.draft_rules_sha256 === STRING_DRAFT_RULES
  );
}
/** Independent canonical application-tag7 encoding for the admitted UTF-8 domain. */
export function stringTagHex(value: string): string {
  if (!nativeString(value)) throw new Error("Unsupported native String value.");
  const bytes = [0, ...new TextEncoder().encode(value)];
  const size = bytes.length;
  const header =
    size <= 4
      ? [0x70 + size]
      : size <= 253
        ? [0x75, size]
        : [0x75, 254, size >> 8, size & 255];
  return [...header, ...bytes]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
export function stringDraftReview(value: any): boolean {
  if (
    value?.profile !== STRING_DRAFT ||
    value.format !== STRING_DRAFT ||
    value.rules_sha256 !== STRING_DRAFT_RULES ||
    value.source?.observed_native_type !== "CharacterString" ||
    value.request?.draft_profile !== STRING_DRAFT ||
    !Array.isArray(value.request.transitions) ||
    !Array.isArray(value.new?.transitions) ||
    value.request.transitions.length !== value.new.transitions.length ||
    value.request.transitions.length > 32
  )
    return false;
  let day = "0e";
  const valid = value.request.transitions.every(
    (requested: any, index: number) => {
      const row = value.new.transitions[index];
      if (
        !row ||
        row.native_type !== requested.native_type ||
        row.value_text !== requested.value_text ||
        !Array.isArray(requested.time) ||
        requested.time.length !== 4 ||
        requested.time.some(
          (part: any, field: number) =>
            !Number.isInteger(part) ||
            part < 0 ||
            part > [23, 59, 59, 99][field],
        ) ||
        !Array.isArray(row.time) ||
        row.time.length !== 4 ||
        row.time.some(
          (part: any, field: number) => part !== requested.time[field],
        )
      )
        return false;
      day +=
        "b4" +
        requested.time
          .map((part: number) => part.toString(16).padStart(2, "0"))
          .join("");
      if (requested.native_type === "CharacterString") {
        if (!nativeString(requested.value_text)) return false;
        day += stringTagHex(requested.value_text);
        return (
          nativeString(requested.value_text) &&
          row.wire_value_text === requested.value_text &&
          row.wire === requested.value_text &&
          row.wire_encoded_hex === stringTagHex(requested.value_text)
        );
      }
      day += "00";
      return (
        requested.native_type === "Null" &&
        requested.value_text === "null" &&
        row.wire_value_text === "null" &&
        row.wire === null &&
        row.wire_encoded_hex === "00"
      );
    },
  );
  return valid && value.new.encoded_hex === day + "0f";
}
