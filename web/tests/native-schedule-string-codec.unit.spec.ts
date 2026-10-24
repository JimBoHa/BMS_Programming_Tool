import { test, expect } from "@playwright/test";
import {
  parseStringEditor,
  STRING_EDITOR_LENGTH,
} from "../src/nativeScheduleStrings";

test("String editor enforces its literal bound even when padding decodes to an empty value", () => {
  const boundary = JSON.stringify("\0".repeat(256));
  expect(boundary.length).toBe(STRING_EDITOR_LENGTH);
  expect(parseStringEditor(boundary)).toBe("\0".repeat(256));
  expect(() =>
    parseStringEditor(" ".repeat(STRING_EDITOR_LENGTH) + '""'),
  ).toThrow(/editor.*bound/);
});
