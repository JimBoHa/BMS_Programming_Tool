import { test, expect } from "@playwright/test";
import { CanvasMeasurements } from "../src/canvasMeasurements";
function element(id = "a", canvas = "canvas", width = 220, height = 108) {
  return {
    isConnected: true,
    classList: { contains: (name: string) => name === "react-flow__node" },
    offsetWidth: width,
    offsetHeight: height,
    getAttribute: (key: string) => (key === "data-id" ? id : null),
    closest: () => ({ getAttribute: () => canvas }),
  } as unknown as HTMLElement;
}
test("measured geometry survives same-node parent updates without modifying source descriptors", () => {
  const cache = new CanvasMeasurements("canvas"),
    source = [{ id: "a", shape: "Constant" }];
  const owners = cache.prepare("project", source),
    owner = owners.get("a")!,
    dom = element();
  expect(cache.measure(owner, dom)).toBe(true);
  expect(cache.measure(owner, dom)).toBe(false);
  expect(cache.prepare("project", [...source]).get("a")).toBe(owner);
  expect(cache.get(owner)).toEqual({ width: 220, height: 108 });
  expect(source).toEqual([{ id: "a", shape: "Constant" }]);
});
test("scope, removed/reinserted IDs and changed port shapes retire old measurement owners", () => {
  const cache = new CanvasMeasurements("canvas"),
    nodes = [{ id: "a", shape: "input" }];
  const first = cache.prepare("one", nodes).get("a")!,
    dom = element();
  cache.measure(first, dom);
  cache.prepare("one", []);
  expect(cache.measure(first, dom)).toBe(false);
  expect(cache.get(first)).toBeUndefined();
  const second = cache.prepare("one", nodes).get("a")!;
  expect(second).not.toBe(first);
  expect(cache.get(second)).toBeUndefined();
  cache.measure(second, dom);
  const third = cache
    .prepare("one", [{ id: "a", shape: "different ports" }])
    .get("a")!;
  expect(cache.measure(second, dom)).toBe(false);
  expect(cache.get(third)).toBeUndefined();
  const replacement = cache.prepare("two", nodes).get("a")!;
  expect(cache.measure(third, dom)).toBe(false);
  expect(cache.get(replacement)).toBeUndefined();
});
test("disconnected, foreign, wrong-node, zero/nonfinite and stale duplicate DOM are refused", () => {
  const cache = new CanvasMeasurements("canvas"),
    owner = cache.prepare("p", [{ id: "a", shape: "constant" }]).get("a")!;
  for (const bad of [
    element("b"),
    element("a", "other"),
    element("a", "canvas", 0),
    element("a", "canvas", NaN),
    element("a", "canvas", 1_000_001),
    { ...element(), isConnected: false },
    { ...element(), classList: { contains: () => false } },
  ])
    expect(cache.measure(owner, bad as HTMLElement)).toBe(false);
  const first = element();
  expect(cache.measure(owner, first)).toBe(true);
  expect(cache.measure(owner, element())).toBe(false);
  (first as any).isConnected = false;
  expect(cache.get(owner)).toBeUndefined();
  const current = element("a", "canvas", 230, 150);
  expect(cache.measure(owner, current)).toBe(true);
  expect(cache.get(owner)).toEqual({ width: 230, height: 150 });
});
