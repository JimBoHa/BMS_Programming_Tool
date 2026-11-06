/** Navigation-only proposals. Reviewed evidence is never restored from this map. */
export type CafRemovalDraft = {
  archive: string;
  diagram: string;
  index: number;
  old: number[];
  count: number;
  saved?: string;
};
export type CafRemovalDrafts = Map<string, CafRemovalDraft>;
export const cafRemovalKey = (archive: string, diagram: string) =>
  JSON.stringify([archive, diagram]);
export const cafRemovalSignature = (draft: CafRemovalDraft) =>
  JSON.stringify([
    draft.archive,
    draft.diagram,
    draft.index,
    draft.old,
    draft.count,
  ]);
export const cafRemovalDirty = (draft: CafRemovalDraft) =>
  draft.saved !== cafRemovalSignature(draft);
export function rememberCafRemoval(
  drafts: CafRemovalDrafts,
  draft: CafRemovalDraft,
) {
  const key = cafRemovalKey(draft.archive, draft.diagram);
  if (!drafts.has(key) && drafts.size >= 32) return false;
  drafts.set(key, { ...draft, old: [...draft.old] });
  return true;
}
