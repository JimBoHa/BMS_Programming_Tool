import { test, expect } from "@playwright/test";
import { calendarMatchingWeekday } from "../src/calendarWeekday";

test("civil weekdays cover native year bounds and Gregorian century leap rules without changing raw fields", () => {
  // Independent civil-date expectations, also checked with Python datetime.date.
  for (const [year, month, day, weekday] of [
    ["1900", "3", "1", "4"],
    ["2000", "2", "29", "2"],
    ["2026", "11", "2", "1"],
    ["2026", "11", "4", "3"],
    ["2100", "3", "1", "1"],
    ["2154", "12", "31", "2"],
  ]) {
    const raw = [year, month, day, "*"];
    expect(calendarMatchingWeekday(raw)).toBe(weekday);
    expect(raw).toEqual([year, month, day, "*"]);
  }
  for (const raw of [
    ["1900", "2", "29", "*"],
    ["2100", "2", "29", "*"],
    ["2026", "2", "30", "*"],
    ["2026", "13", "1", "*"],
    ["2026", "11", "32", "*"],
    ["*", "11", "2", "*"],
    ["20", "11", "2", "*"],
    ["2155", "1", "1", "*"],
    ["1899", "12", "31", "*"],
    ["2026", "01", "2", "*"],
    ["2026", "1", "02", "*"],
    ["2026", "1", "1"],
  ])
    expect(calendarMatchingWeekday(raw)).toBeNull();
});
