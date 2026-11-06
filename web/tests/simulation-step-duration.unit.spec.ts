import { test, expect } from "@playwright/test";
import { inspectStepDuration } from "../src/simulationStepDuration";

test("nominal timing ignores retained custom text and preserves the project interval", () => {
  expect(
    inspectStepDuration({ enabled: false, text: "invalid" }, 0.25),
  ).toEqual({ seconds: 0.25, error: "" });
});
for (const [text, seconds] of [
  [".25", 0.25],
  ["+0.25", 0.25],
  [" 1e-2 ", 0.01],
  ["60", 60],
  ["1e-20", 1e-20],
] as const)
  test(`declared ${text} seconds has its finite effective value`, () => {
    expect(inspectStepDuration({ enabled: true, text }, 1)).toEqual({
      seconds,
      error: "",
    });
  });
for (const text of [
  "",
  " ",
  "0",
  "-0",
  "-1",
  "60.01",
  "Infinity",
  "NaN",
  "true",
  "0x10",
  "1e-",
  "1e999",
  "1e-999",
])
  test(`unfinished or out-of-range ${JSON.stringify(text)} cannot select an effective duration`, () => {
    expect(inspectStepDuration({ enabled: true, text }, 1)).toEqual({
      seconds: null,
      error: expect.stringContaining("greater than 0"),
    });
  });
