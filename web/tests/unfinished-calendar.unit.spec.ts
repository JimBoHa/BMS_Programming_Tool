import { test, expect } from "@playwright/test";
import {
  calendarWork,
  rememberCalendar,
  blankCalendarRow,
  CALENDAR_BUFFERS,
  type CalendarDraftBuffer,
} from "../src/nativeCalendar";
import {
  unfinishedCalendarDocument,
  unfinishedCalendarImport,
  UNFINISHED_CALENDAR_DOCUMENT,
  UNFINISHED_CALENDAR_IMPORT,
} from "../src/unfinishedCalendar";
import { parseSourceJSON } from "../src/programSource";
const draft = (): CalendarDraftBuffer => ({
  rows: [
    {
      ...blankCalendarRow(),
      date: ["20", "?", "32", ""],
      fields: ["*", "9", "?"],
    },
  ],
  imported: "a".repeat(64),
  rawImported: { filename: "prior.json", file_sha256: "b".repeat(64) },
});
const capture = "c".repeat(64),
  sha = "d".repeat(64);
test("the existing512-context limit refuses without eviction and deep copies raw provenance", () => {
  const work = calendarWork(),
    buffer = draft();
  rememberCalendar(work, "first", buffer);
  buffer.rows[0].date[0] = "2026";
  buffer.rawImported!.filename = "changed";
  expect(work.drafts.get("first")!.rows[0].date[0]).toBe("20");
  expect(work.drafts.get("first")!.rawImported!.filename).toBe("prior.json");
  for (let i = 1; i < CALENDAR_BUFFERS; i++)
    rememberCalendar(work, String(i), draft());
  const before = JSON.stringify([...work.drafts]);
  expect(() => rememberCalendar(work, "import", draft())).toThrow(
    "Calendar workspace is full",
  );
  expect(JSON.stringify([...work.drafts])).toBe(before);
  work.drafts.delete("first");
  rememberCalendar(work, "import", draft());
  expect(work.drafts.size).toBe(512);
});
test("raw export and exact response binding preserve inactive fields without internal keys", async () => {
  const blob = unfinishedCalendarDocument(capture, "calendar,1", draft()),
    original = parseSourceJSON(await blob.text()),
    doc = JSON.parse(await blob.text());
  expect(doc.profile).toBe(UNFINISHED_CALENDAR_DOCUMENT);
  expect(doc.buffer.rows[0].key).toBeUndefined();
  const response = {
    profile: UNFINISHED_CALENDAR_IMPORT,
    document_profile: UNFINISHED_CALENDAR_DOCUMENT,
    field_authority: false,
    controller_queries: false,
    capture_mutations: false,
    native_review_created: false,
    file_sha256: sha,
    source: [capture, "calendar,1"],
    buffer: doc.buffer,
    provenance_policy: "Unverified references",
  };
  const restored = unfinishedCalendarImport(
    response,
    capture,
    "calendar,1",
    sha,
    original,
  );
  expect(restored.rows).toEqual(doc.buffer.rows);
  restored.rows[0].date[0] = "2026";
  expect(doc.buffer.rows[0].date[0]).toBe("20");
  expect(() =>
    unfinishedCalendarImport(
      { ...response, source: [capture, "calendar,2"] },
      capture,
      "calendar,1",
      sha,
      original,
    ),
  ).toThrow("differs from this file");
});
test("unpaired Unicode and oversized fields never export an unrecoverable raw copy", () => {
  const buffer = draft();
  buffer.rows[0].date[0] = "\ud800";
  expect(() =>
    unfinishedCalendarDocument(capture, "calendar,1", buffer),
  ).toThrow("editor limits");
  buffer.rows[0].date[0] = "12345";
  expect(() =>
    unfinishedCalendarDocument(capture, "calendar,1", buffer),
  ).toThrow("editor limits");
});
