import { test, expect } from "@playwright/test";
import {
  weeklyWork,
  weeklyKey,
  weeklyDraft,
  rememberWeekly,
  WEEKLY_BUFFERS,
  WEEKLY_BYTES,
  type WeeklyDraft,
} from "../src/nativeWeeklyWork";
const draft = (): WeeklyDraft => ({
  rows: [
    {
      key: 1,
      time: ["1e", "", "0", "0"],
      native_type: "Real",
      value_text: "-8e",
    },
  ],
  dirty: true,
  imported: null,
});
test("weekly capacity refuses a 129th draft without evicting any source and permits explicit discard", () => {
  const work = weeklyWork();
  for (let i = 0; i < WEEKLY_BUFFERS; i++)
    rememberWeekly(work, weeklyKey(String(i), "schedule,1", 1), draft());
  const before = JSON.stringify([...work.drafts]);
  expect(() => rememberWeekly(work, "another", draft())).toThrow(
    "128 retained drafts",
  );
  expect(JSON.stringify([...work.drafts])).toBe(before);
  const key = weeklyKey("0", "schedule,1", 1);
  rememberWeekly(work, key, { ...draft(), dirty: false });
  expect(work.drafts.size).toBe(128);
  work.drafts.delete(key);
  rememberWeekly(work, "another", draft());
  expect(work.drafts.size).toBe(128);
  expect(work.drafts.has(weeklyKey("127", "schedule,1", 1))).toBe(true);
});
test("raw rows, invalid String literals and imported provenance are isolated copies without authority", () => {
  const work = weeklyWork(),
    original = {
      ...draft(),
      imported: { review_id: "f".repeat(64), filename: "original.json" },
    };
  original.rows[0].string_json = '  "unfinished';
  rememberWeekly(work, "source", original);
  original.rows[0].time[0] = "20";
  original.imported.filename = "changed";
  const restored = weeklyDraft(work, "source")!;
  expect(restored.rows[0].time[0]).toBe("1e");
  expect(restored.rows[0].string_json).toBe('  "unfinished');
  expect(restored.imported?.filename).toBe("original.json");
  restored.rows[0].time[0] = "10";
  expect(weeklyDraft(work, "source")!.rows[0].time[0]).toBe("1e");
  expect(Object.keys(restored).sort()).toEqual(["dirty", "imported", "rows"]);
});
test("UTF8 byte quota refuses oversized replacement atomically and retains earlier source text", () => {
  const work = weeklyWork(),
    large: WeeklyDraft = {
      ...draft(),
      rows: Array.from({ length: 32 }, (_, key) => ({
        key,
        time: ["1e", "", "0", "0"],
        native_type: "CharacterString",
        value_text: "€".repeat(256),
        string_json: "€".repeat(1538),
      })),
    };
  let refused = false;
  for (let i = 0; i < WEEKLY_BUFFERS; i++) {
    const before = JSON.stringify([...work.drafts]);
    try {
      rememberWeekly(work, String(i), large);
    } catch (e) {
      expect(String(e)).toContain("4 MiB");
      expect(JSON.stringify([...work.drafts])).toBe(before);
      refused = true;
      break;
    }
  }
  expect(refused).toBe(true);
  expect(work.drafts.size).toBeLessThan(WEEKLY_BUFFERS);
  expect(
    new TextEncoder().encode(JSON.stringify([...work.drafts])).length,
  ).toBeLessThanOrEqual(WEEKLY_BYTES + 300);
  const count = work.drafts.size;
  work.drafts.delete("0");
  rememberWeekly(work, "new", large);
  expect(work.drafts.size).toBe(count);
  expect(weeklyDraft(work, "1")!.rows[0].string_json).toBe("€".repeat(1538));
});
