import { test, expect } from "@playwright/test";
import { persistDraftRecovery } from "../src/draftRecovery";
import { blankProgram } from "../src/types";
import { parseSourceDocument, sourceEqual } from "../src/programSource";

test("normal draft is written before stale macro recovery is removed", () => {
  const program = blankProgram(),
    calls: string[] = [],
    data = new Map([
      ["bms-studio-draft-v1", "previous"],
      ["bms-studio-macro-edit-v1", "macro"],
    ]);
  persistDraftRecovery(
    {
      setItem: (key, value) => {
        calls.push("write:" + key);
        data.set(key, value);
      },
      removeItem: (key) => {
        calls.push("remove:" + key);
        data.delete(key);
      },
    },
    program,
    null,
  );
  expect(calls).toEqual([
    "write:bms-studio-draft-v1",
    "remove:bms-studio-macro-edit-v1",
  ]);
  expect(
    sourceEqual(parseSourceDocument(data.get("bms-studio-draft-v1")!), program),
  ).toBe(true);
  expect(data.has("bms-studio-macro-edit-v1")).toBe(false);
});
test("macro snapshot includes exact parent, definition and current draft without replacing parent recovery", () => {
  const parent = blankProgram(),
    draft = {
      ...parent,
      name: "latest definition",
      metadata: { unknown: { preserve: [1, 2.5] } },
    },
    calls: string[] = [];
  persistDraftRecovery(
    {
      setItem: (key, value) => {
        calls.push(key);
        expect(
          sourceEqual(parseSourceDocument(value), {
            parent,
            definition: "limiter",
            draft,
          }),
        ).toBe(true);
      },
      removeItem: () => {
        throw new Error("must not remove parent");
      },
    },
    draft,
    { parent, definition: "limiter" },
  );
  expect(calls).toEqual(["bms-studio-macro-edit-v1"]);
});
test("failed primary write preserves previous copies and never clears macro", () => {
  const data = new Map([
    ["bms-studio-draft-v1", "good"],
    ["bms-studio-macro-edit-v1", "macro"],
  ]);
  expect(() =>
    persistDraftRecovery(
      {
        setItem: () => {
          throw new Error("quota");
        },
        removeItem: (key) => data.delete(key),
      },
      blankProgram(),
      null,
    ),
  ).toThrow("quota");
  expect([...data]).toEqual([
    ["bms-studio-draft-v1", "good"],
    ["bms-studio-macro-edit-v1", "macro"],
  ]);
});
test("serialization failure performs no storage mutation", () => {
  const p = blankProgram();
  p.metadata.circular = p;
  let calls = 0;
  expect(() =>
    persistDraftRecovery(
      {
        setItem: () => {
          calls++;
        },
        removeItem: () => {
          calls++;
        },
      },
      p,
      null,
    ),
  ).toThrow();
  expect(calls).toBe(0);
});
test("removal failure retains both independently recoverable copies and is reported", () => {
  const program = blankProgram(),
    data = new Map([["bms-studio-macro-edit-v1", "good macro"]]);
  expect(() =>
    persistDraftRecovery(
      {
        setItem: (k, v) => data.set(k, v),
        removeItem: () => {
          throw new Error("remove denied");
        },
      },
      program,
      null,
    ),
  ).toThrow("remove denied");
  expect(
    sourceEqual(parseSourceDocument(data.get("bms-studio-draft-v1")!), program),
  ).toBe(true);
  expect(data.get("bms-studio-macro-edit-v1")).toBe("good macro");
});
