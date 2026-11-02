import { test, expect } from "@playwright/test";
import {
  unfinishedWeeklyDocument,
  unfinishedWeeklyImport,
  UNFINISHED_WEEKLY_DOCUMENT,
  UNFINISHED_WEEKLY_IMPORT,
} from "../src/unfinishedWeekly";
import {
  weeklyWork,
  weeklyDraft,
  rememberWeekly,
  type WeeklyDraft,
} from "../src/nativeWeeklyWork";
import { parseSourceJSON } from "../src/programSource";
const draft = (): WeeklyDraft => ({
  rows: [
    {
      key: 99,
      time: ["1e", "", "-", "00"],
      native_type: "Real",
      value_text: "2e-",
      string_json: '"\\u',
    },
  ],
  dirty: true,
  imported: { filename: "old.json", review_id: "a".repeat(64) },
});
const capture = "b".repeat(64),
  sha = "c".repeat(64);
async function response() {
  const blob = unfinishedWeeklyDocument(
      capture,
      "schedule,1",
      1,
      draft(),
      "Real",
    ),
    original = parseSourceJSON(await blob.text());
  return {
    original,
    data: {
      profile: UNFINISHED_WEEKLY_IMPORT,
      document_profile: UNFINISHED_WEEKLY_DOCUMENT,
      field_authority: false,
      controller_queries: false,
      capture_mutations: false,
      native_review_created: false,
      file_sha256: sha,
      source: [capture, "schedule,1", "1"],
      native_type: "Real",
      buffer: JSON.parse(await blob.text()).buffer,
      provenance_policy: "Unverified metadata",
    },
  };
}
test("raw export keeps invalid fields, omits internal keys/dirty state and has no field authority", async () => {
  const { original, data } = await response();
  const restored = unfinishedWeeklyImport(
    data,
    capture,
    "schedule,1",
    1,
    "Real",
    sha,
    original,
  );
  expect(restored.rows[0]).toEqual({
    time: ["1e", "", "-", "00"],
    native_type: "Real",
    value_text: "2e-",
    string_json: '"\\u',
  });
  expect(Object.keys(restored).sort()).toEqual(["imported", "rows"]);
  restored.rows[0].time[0] = "12";
  expect(data.buffer.rows[0].time[0]).toBe("1e");
});
test("new raw provenance is cloned and counted by the unchanged no-eviction workspace", () => {
  const work = weeklyWork(),
    raw = {
      ...draft(),
      rawImported: { filename: "raw.json", file_sha256: sha },
    };
  rememberWeekly(work, "first", raw);
  raw.rawImported.filename = "changed";
  expect(weeklyDraft(work, "first")!.rawImported!.filename).toBe("raw.json");
  const copy = weeklyDraft(work, "first")!;
  copy.rawImported!.filename = "again";
  expect(weeklyDraft(work, "first")!.rawImported!.filename).toBe("raw.json");
  for (let i = 1; i < 128; i++) rememberWeekly(work, String(i), draft());
  const before = JSON.stringify([...work.drafts]);
  expect(() =>
    rememberWeekly(work, "import", {
      ...draft(),
      rawImported: { filename: "import.json", file_sha256: sha },
    }),
  ).toThrow("128 retained drafts");
  expect(JSON.stringify([...work.drafts])).toBe(before);
});
test("raw export refuses unpaired Unicode and oversized fields instead of emitting unrecoverable files", () => {
  const bad = draft();
  bad.rows[0].value_text = "\ud800";
  expect(() =>
    unfinishedWeeklyDocument(capture, "schedule,1", 1, bad, "Real"),
  ).toThrow("editor limits");
  bad.rows[0].value_text = "x".repeat(257);
  expect(() =>
    unfinishedWeeklyDocument(capture, "schedule,1", 1, bad, "Real"),
  ).toThrow("editor limits");
});
