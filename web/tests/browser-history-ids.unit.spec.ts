import { test, expect } from "@playwright/test";
import {
  parseHistoryId,
  requireHistoryId,
  showHistoryId,
} from "../src/browserHistoryIds";

test("plain whole-ID tokens are checked before Number coercion", () => {
  for (const token of [
    "9007199254740993",
    "9007199254740992",
    "-1",
    "+1",
    "1.0",
    "1e0",
    ".5",
    "01",
    "0x10",
    "Infinity",
    "NaN",
    "",
    "1".repeat(5000),
  ])
    expect(() => parseHistoryId(token, "Selected ID")).toThrow();
});
test("positive boundary and explicit zero cursor have separate bounds", () => {
  expect(parseHistoryId(" 42 ", "ID")).toBe(42);
  expect(parseHistoryId("9007199254740991", "ID")).toBe(
    Number.MAX_SAFE_INTEGER,
  );
  expect(parseHistoryId("0", "Cursor", true)).toBe(0);
  expect(() => parseHistoryId("0", "ID")).toThrow();
});
test("received IDs reject unsafe, nonnumeric, nonpositive and fractional values", () => {
  for (const value of [
    2 ** 53,
    2 ** 53 + 1,
    2 ** 60,
    -1,
    0,
    0.5,
    NaN,
    Infinity,
    true,
    "1",
    null,
    undefined,
  ])
    expect(() => requireHistoryId(value, "Received ID")).toThrow();
  expect(requireHistoryId(Number.MAX_SAFE_INTEGER, "ID")).toBe(
    Number.MAX_SAFE_INTEGER,
  );
  expect(requireHistoryId(0, "Cursor", true)).toBe(0);
});
test("unsupported display identities never print rounded digits", () => {
  expect(showHistoryId(9007199254740993)).toBe("unsupported browser ID");
  expect(showHistoryId(42)).toBe("42");
  expect(showHistoryId(0, true)).toBe("0");
});
