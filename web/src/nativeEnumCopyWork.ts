/** Retain unfinished source-specific code text without evicting older work. */
export const ENUM_DRAFT_LIMIT = 128;
export function enumCode(text: string) {
  if (
    !/^[0-9]+$/.test(text.trim()) ||
    text.length > 128 ||
    Number(text.trim()) > 4294967295
  )
    throw new Error("Use a decimal Enum code from 0 through 4294967295.");
  return Number(text.trim());
}
export function rememberEnumText(
  drafts: Map<string, string>,
  key: string,
  text: string,
  original: number,
) {
  if (text === String(original)) {
    drafts.delete(key);
    return true;
  }
  if (!drafts.has(key) && drafts.size >= ENUM_DRAFT_LIMIT) return false;
  drafts.set(key, text);
  return true;
}
