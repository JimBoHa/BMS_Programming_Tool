import { test, expect } from "@playwright/test";
import {
  SIMULATION_CLEANUP_KEY,
  pendingSimulationCleanup,
  rememberSimulationCleanup,
  finishSimulationCleanup,
} from "../src/simulationSessions";

const handle = (n: number) => ({
  session: "session-" + String(n).padStart(20, "0"),
  retirement_token: "t".repeat(32),
  creation_operation_id: n.toString(16).padStart(32, "0"),
});
function storage() {
  const values = new Map<string, string>([["unrelated", "keep"]]);
  return {
    values,
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    },
  };
}
test("cleanup acknowledgements remove only their exact retained ownership", () => {
  const store = storage(),
    first = handle(1),
    second = handle(2);
  rememberSimulationCleanup(first, store);
  rememberSimulationCleanup(second, store);
  rememberSimulationCleanup(first, store);
  expect(pendingSimulationCleanup(store)).toEqual([first, second]);
  finishSimulationCleanup(first, store);
  expect(pendingSimulationCleanup(store)).toEqual([second]);
  finishSimulationCleanup(first, store);
  expect(pendingSimulationCleanup(store)).toEqual([second]);
  finishSimulationCleanup(second, store);
  expect(store.getItem(SIMULATION_CLEANUP_KEY)).toBeNull();
  expect(store.values.get("unrelated")).toBe("keep");
});
test("a reused session identity cannot replace or acknowledge another capability", () => {
  const store = storage(),
    first = handle(1);
  rememberSimulationCleanup(first, store);
  const original = store.getItem(SIMULATION_CLEANUP_KEY);
  const forged = { ...first, retirement_token: "f".repeat(32) };
  expect(() => rememberSimulationCleanup(forged, store)).toThrow("collision");
  expect(() => finishSimulationCleanup(forged, store)).toThrow(
    "another ownership",
  );
  expect(store.getItem(SIMULATION_CLEANUP_KEY)).toBe(original);
});
for (const [name, raw] of [
  ["invalid JSON", "{"],
  [
    "duplicate handles",
    `{"format":"${SIMULATION_CLEANUP_KEY}","handles":[${JSON.stringify(handle(1))}],"handles":[${JSON.stringify(handle(2))}]}`,
  ],
  [
    "duplicate capability",
    `{"format":"${SIMULATION_CLEANUP_KEY}","handles":[{"session":"${handle(1).session}","retirement_token":"${"a".repeat(32)}","retirement_token":"${"b".repeat(32)}","creation_operation_id":"${handle(1).creation_operation_id}"}]}`,
  ],
  ["wrong profile", JSON.stringify({ format: "other", handles: [] })],
  [
    "extra authority",
    JSON.stringify({
      format: SIMULATION_CLEANUP_KEY,
      handles: [],
      guessed: true,
    }),
  ],
  [
    "invalid operation",
    JSON.stringify({
      format: SIMULATION_CLEANUP_KEY,
      handles: [{ ...handle(1), creation_operation_id: true }],
    }),
  ],
  [
    "duplicate session",
    JSON.stringify({
      format: SIMULATION_CLEANUP_KEY,
      handles: [handle(1), handle(1)],
    }),
  ],
  ["oversized record", " ".repeat(16385)],
] as const)
  test(`malformed ${name} is retained without automatic cleanup or overwrite`, () => {
    const store = storage();
    store.setItem(SIMULATION_CLEANUP_KEY, raw);
    expect(() => pendingSimulationCleanup(store)).toThrow();
    expect(() => rememberSimulationCleanup(handle(2), store)).toThrow();
    expect(() => finishSimulationCleanup(handle(1), store)).toThrow();
    expect(store.getItem(SIMULATION_CLEANUP_KEY)).toBe(raw);
    expect(store.values.get("unrelated")).toBe("keep");
  });
test("bounded cleanup storage refuses excess ownership without evicting records", () => {
  const store = storage();
  for (let i = 0; i < 32; i++) rememberSimulationCleanup(handle(i), store);
  const original = store.getItem(SIMULATION_CLEANUP_KEY);
  expect(() => rememberSimulationCleanup(handle(32), store)).toThrow(
    "capacity",
  );
  expect(store.getItem(SIMULATION_CLEANUP_KEY)).toBe(original);
  expect(pendingSimulationCleanup(store)).toHaveLength(32);
});

test("unavailable storage propagates without fabricating or deleting retained ownership", () => {
  const store = storage();
  const blocked = {
    ...store,
    setItem: () => {
      throw new Error("Deliberate storage denial");
    },
  };
  expect(() => rememberSimulationCleanup(handle(1), blocked)).toThrow(
    "storage denial",
  );
  expect(pendingSimulationCleanup(store)).toEqual([]);
  expect(store.values.get("unrelated")).toBe("keep");
});
