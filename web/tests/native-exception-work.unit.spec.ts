import { test, expect } from "@playwright/test";
import {
  exceptionWork,
  rememberExceptions,
  exceptionBuffer,
  exceptionKey,
  blankException,
  blankExceptionTime,
  exceptionRequest,
} from "../src/nativeScheduleExceptions";
test("64 exception sources refuse eviction, preserve deep raw copies and allow an existing source to change", () => {
  const work = exceptionWork(),
    row = blankException();
  row.kind = "calendarReference";
  row.reference = "calendar,2";
  row.transitions = [blankExceptionTime("Real")];
  row.transitions[0].value_text = "1e-";
  for (let i = 0; i < 64; i++)
    rememberExceptions(work, exceptionKey(String(i), "schedule,1"), {
      rows: [row],
      imported: { filename: "source.json", review_id: "a".repeat(64) },
    });
  row.transitions[0].value_text = "mutated caller";
  const before = JSON.stringify([...work.drafts]);
  expect(() =>
    rememberExceptions(work, exceptionKey("65", "schedule,1"), {
      rows: [],
      imported: null,
    }),
  ).toThrow("64 retained drafts");
  expect(JSON.stringify([...work.drafts])).toBe(before);
  const key = exceptionKey("0", "schedule,1"),
    draft = exceptionBuffer(work, key)!;
  expect(draft.rows[0].transitions[0].value_text).toBe("1e-");
  draft.rows[0].priority = "-";
  expect(exceptionBuffer(work, key)!.rows[0].priority).toBe("8");
  rememberExceptions(work, key, draft);
  expect(work.drafts.size).toBe(64);
  work.drafts.delete(key);
  rememberExceptions(work, exceptionKey("65", "schedule,1"), {
    rows: [],
    imported: null,
  });
  expect(work.drafts.has(exceptionKey("63", "schedule,1"))).toBe(true);
});
test("a workspace byte overflow refuses replacement and keeps every prior exception field", () => {
  const work = exceptionWork(),
    time = blankExceptionTime("CharacterString");
  time.string_json = "x".repeat(1538);
  time.value_text = "x".repeat(256);
  const row = blankException();
  row.transitions = Array.from({ length: 32 }, () => structuredClone(time));
  const buffer = {
    rows: Array.from({ length: 32 }, () => structuredClone(row)),
    imported: null,
  };
  rememberExceptions(work, "first", buffer);
  const before = JSON.stringify([...work.drafts]);
  expect(() =>
    rememberExceptions(work, "second", {
      rows: [...buffer.rows, ...buffer.rows],
      imported: null,
    }),
  ).toThrow("editor limits");
  expect(JSON.stringify([...work.drafts])).toBe(before);
  let refused = false;
  for (let i = 0; i < 4; i++) {
    const prior = JSON.stringify([...work.drafts]);
    try {
      rememberExceptions(work, "bytes-" + i, buffer);
    } catch (error) {
      expect(String(error)).toContain("4 MiB");
      expect(JSON.stringify([...work.drafts])).toBe(prior);
      refused = true;
      break;
    }
  }
  expect(refused).toBe(true);
});
test("Null serialization leaves raw numeric or String work intact for a later type selection", () => {
  const row = blankException();
  row.kind = "calendarReference";
  row.reference = "calendar,2";
  const time = blankExceptionTime("Real");
  time.time = ["9", "0", "0", "0"];
  time.value_text = "1e-";
  row.transitions = [time];
  time.native_type = "Null";
  expect(
    exceptionRequest("a".repeat(64), "schedule,1", [row]).events[0]
      .transitions[0].value_text,
  ).toBe("null");
  expect(time.value_text).toBe("1e-");
  time.native_type = "Real";
  expect(
    exceptionRequest("a".repeat(64), "schedule,1", [row]).events[0]
      .transitions[0].value_text,
  ).toBe("1e-");
});

test("zero-padded exception clock and priority fields encode as native integers without changing raw text", () => {
  const row = blankException();
  row.kind = "calendarReference";
  row.reference = "calendar,2";
  row.priority = "08";
  const time = blankExceptionTime("Real");
  time.time = ["09", "05", "00", "09"];
  row.transitions = [time];
  const event = exceptionRequest("a".repeat(64), "schedule,1", [row]).events[0];
  expect(event.priority).toBe(8);
  expect(event.transitions[0].time).toEqual([9, 5, 0, 9]);
  expect(row.priority).toBe("08");
  expect(time.time).toEqual(["09", "05", "00", "09"]);
});
