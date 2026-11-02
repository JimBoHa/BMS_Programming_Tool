export type WeeklyRow = {
  key: number;
  time: string[];
  native_type: string;
  value_text: string;
  string_json?: string;
};
export type WeeklyDraft = {
  rows: WeeklyRow[];
  dirty: boolean;
  imported: { review_id: string; filename: string } | null;
  rawImported?: { filename: string; file_sha256: string };
};
export type WeeklyWork = {
  captureId: string;
  selected: Map<string, { object: string; day: number }>;
  drafts: Map<string, WeeklyDraft>;
};
export const WEEKLY_BUFFERS = 128;
export const WEEKLY_BYTES = 4 * 1024 * 1024;
export const weeklyWork = (): WeeklyWork => ({
  captureId: "",
  selected: new Map(),
  drafts: new Map(),
});
export const weeklyKey = (capture: string, object: string, day: number) =>
  JSON.stringify([capture, object, day]);
const copy = (draft: WeeklyDraft): WeeklyDraft => ({
  ...draft,
  rows: draft.rows.map((row) => ({ ...row, time: [...row.time] })),
  imported: draft.imported ? { ...draft.imported } : null,
  ...(draft.rawImported ? { rawImported: { ...draft.rawImported } } : {}),
});
export const weeklyDraft = (work: WeeklyWork, key: string) => {
  const value = work.drafts.get(key);
  return value ? copy(value) : null;
};
export function rememberWeekly(
  work: WeeklyWork,
  key: string,
  draft: WeeklyDraft,
) {
  if (!work.drafts.has(key) && work.drafts.size >= WEEKLY_BUFFERS)
    throw new Error(
      "Weekly workspace has 128 retained drafts. Export and explicitly discard a retained draft before editing another day.",
    );
  const retained = copy(draft);
  // Raw invalid input is intentional. Bound storage without parsing or normalizing it.
  if (
    retained.rows.length > 32 ||
    retained.rows.some(
      (row) =>
        row.time.length !== 4 ||
        row.time.some((value) => value.length > 2) ||
        row.value_text.length > 256 ||
        (row.string_json?.length || 0) > 1538,
    )
  )
    throw new Error("Weekly workspace draft exceeds its editor limits.");
  const encoder = new TextEncoder();
  let bytes = encoder.encode(JSON.stringify([key, retained])).length;
  for (const [other, value] of work.drafts)
    if (other !== key)
      bytes += encoder.encode(JSON.stringify([other, value])).length;
  if (bytes > WEEKLY_BYTES)
    throw new Error(
      "Weekly workspace exceeds 4 MiB. Export and explicitly discard retained drafts to make room; existing work was kept.",
    );
  work.drafts.set(key, retained);
}
