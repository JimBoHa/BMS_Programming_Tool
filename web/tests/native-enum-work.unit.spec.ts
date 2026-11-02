import { test, expect } from "@playwright/test";
import {
  enumCode,
  rememberEnumText,
  ENUM_DRAFT_LIMIT,
} from "../src/nativeEnumCopyWork";

test("Enum codes accept exact decimal UInt32 values while raw unfinished text remains untouched", () => {
  for (const [text, value] of [
    ["0", 0],
    [" 000256 ", 256],
    ["4294967295", 4294967295],
  ] as const)
    expect(enumCode(text)).toBe(value);
  for (const text of [
    "",
    " ",
    "-1",
    "+1",
    "1.0",
    "1e2",
    "0x10",
    "4294967296",
    "∞",
    "9".repeat(129),
  ])
    expect(() => enumCode(text)).toThrow("decimal Enum code");
  const drafts = new Map<string, string>();
  for (const text of ["1e", "", " 000256 "]) {
    expect(rememberEnumText(drafts, "source/record", text, 1)).toBe(true);
    expect(drafts.get("source/record")).toBe(text);
  }
});

test("128 Enum fields refuse new work without eviction; editing or explicit discard frees only its own field", () => {
  const drafts = new Map<string, string>();
  for (let i = 0; i < ENUM_DRAFT_LIMIT; i++)
    expect(rememberEnumText(drafts, `capture/${i}`, "1e", 1)).toBe(true);
  const before = [...drafts];
  expect(rememberEnumText(drafts, "another", "", 1)).toBe(false);
  expect([...drafts]).toEqual(before);
  expect(rememberEnumText(drafts, "capture/0", "", 1)).toBe(true);
  expect(drafts.get("capture/1")).toBe("1e");
  expect(rememberEnumText(drafts, "capture/0", "1", 1)).toBe(true);
  expect(drafts.has("capture/0")).toBe(false);
  expect(rememberEnumText(drafts, "another", "2", 1)).toBe(true);
  expect(drafts.size).toBe(ENUM_DRAFT_LIMIT);
});
