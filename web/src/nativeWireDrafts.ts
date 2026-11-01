export type WireCopyDrafts = Map<string, string>;

// Refuse new slots at capacity rather than silently deleting another edit.
export function rememberWireDraft(
  drafts: WireCopyDrafts,
  key: string,
  value: string,
) {
  if (!drafts.has(key) && drafts.size >= 256) return false;
  drafts.set(key, value);
  return true;
}
