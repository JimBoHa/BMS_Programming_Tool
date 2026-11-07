import { test, expect } from "@playwright/test";
import {
  orderSource,
  orderReview,
  orderRequest,
  orderExport,
  orderAllowed,
  orderKey,
  orderDirty,
  rememberOrder,
  type OrderDrafts,
} from "../src/cafExecutionOrderContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import { orderFixture } from "./caf-execution-order-fixture";
const original = orderFixture();
async function reseal(x: any, key: string) {
  const { [key]: _, ...body } = x;
  return { ...body, [key]: await connectionSeal(body) };
}
for (const kind of ["normal", "activity", "empty", "backward"])
  test(`actual ${kind} source/review/artifact proofs bind exact bytes`, async () => {
    const f = orderFixture(kind);
    expect(await orderSource(f.source, f.hash, f.diagram)).toBe(true);
    expect(orderRequest(f.source, [1, 0, 2, 3])).toEqual(f.request);
    expect(
      await orderReview(f.review, f.source, f.request, f.objects, f.diagram),
    ).toBe(true);
    expect(
      await orderExport(
        {
          blob: new Blob([Buffer.from(f.output, "base64")]),
          headers: new Headers(f.headers),
        },
        f.review,
      ),
    ).toBe(true);
  });
const changes: Record<string, (s: any) => void> = {
  extra: (s) => (s.authority = true),
  missing: (s) => delete s.source_xml_sha256,
  source: (s) => (s.source_sha256 = "a".repeat(64)),
  diagram: (s) => (s.diagram_ref += "x"),
  version: (s) => (s.diagram_class_version = "2.0"),
  class: (s) => (s.diagram_class_id = "999"),
  members: (s) => (s.members[0].ref += "x"),
  order: (s) => (s.original_order = [1, 0, 2, 3]),
  duplicate: (s) => (s.original_order = [0, 0, 2, 3]),
  wire: (s) => (s.edge_relationships[0].source_index = 1),
  phase: (s) => (s.edge_relationships[0].relationship = "after"),
  write: (s) => (s.controller_write = true),
  scope: (s) => (s.scope += "executed"),
  hash: (s) => (s.diagram_sha256 = "not a hash"),
};
for (const [name, change] of Object.entries(changes))
  test(`resealed ${name} source is refused`, async () => {
    const s = structuredClone(original.source);
    change(s);
    expect(
      await orderSource(
        await reseal(s, "selection_sha256"),
        original.hash,
        original.diagram,
      ),
    ).toBe(false);
  });
const reviews: Record<string, (r: any) => void> = {
  extra: (r) => (r.plan_token = "unearned"),
  request: (r) => (r.request.proposed_order = [0, 1, 2, 3]),
  selection: (r) => (r.result.selection.members[0].ref += "x"),
  proposed: (r) => (r.result.proposed_order = [0, 1, 2, 3]),
  changed: (r) => r.result.changed_positions++,
  objects: (r) => r.result.preserved.original_object_count++,
  preserve: (r) => (r.result.preserved.wire_relationships = false),
  authority: (r) => (r.can_apply = true),
  output: (r) => (r.result.output_sha256 = original.hash),
  profile: (r) => (r.result.profile = "future/2"),
};
for (const [name, change] of Object.entries(reviews))
  test(`resealed ${name} review is refused`, async () => {
    const r = structuredClone(original.review);
    change(r);
    r.result = await reseal(r.result, "order_sha256");
    expect(
      await orderReview(
        await reseal(r, "review_sha256"),
        original.source,
        original.request,
        original.objects,
        original.diagram,
      ),
    ).toBe(false);
  });
for (const name of Object.keys(original.headers))
  test(`wrong ${name} export header refuses download`, async () => {
    const h = new Headers(original.headers);
    h.set(name, "incorrect");
    expect(
      await orderExport(
        {
          blob: new Blob([Buffer.from(original.output, "base64")]),
          headers: h,
        },
        original.review,
      ),
    ).toBe(false);
  });
test("changed artifact bytes refuse even with untouched original headers", async () => {
  expect(
    await orderExport(
      {
        blob: new Blob([Buffer.from(original.caf, "base64")]),
        headers: new Headers(original.headers),
      },
      original.review,
    ),
  ).toBe(false);
});
test("existing wire phases and strict permutations constrain moves independently", () => {
  expect(orderAllowed(original.diagram, [1, 0, 2, 3])).toBe(true);
  for (const proposed of [
    [2, 1, 0, 3],
    [0, 3, 2, 1],
    [0, 0, 2, 3],
    [true, 1, 2, 3],
    [],
    [0, 1, 2],
  ])
    expect(orderAllowed(original.diagram, proposed)).toBe(false);
});
test("bounded drafts retain originals, refuse a33rd and free only an explicitly discarded slot", () => {
  const drafts: OrderDrafts = new Map();
  for (let i = 0; i < 32; i++)
    rememberOrder(drafts, String(i), original.diagram, [1, 0, 2, 3]);
  const before = JSON.stringify([...drafts]);
  expect(() =>
    rememberOrder(drafts, "overflow", original.diagram, [1, 0, 2, 3]),
  ).toThrow("32 execution-order drafts");
  expect(JSON.stringify([...drafts])).toBe(before);
  const first = drafts.get(orderKey("0", original.diagram.ref))!;
  expect(orderDirty(first)).toBe(true);
  first.saved = JSON.stringify(first.proposed);
  expect(orderDirty(first)).toBe(false);
  rememberOrder(drafts, "0", original.diagram, [0, 1, 2, 3]);
  expect(drafts.size).toBe(31);
  rememberOrder(drafts, "overflow", original.diagram, [1, 0, 2, 3]);
  expect(drafts.size).toBe(32);
  const stable = JSON.stringify([...drafts]);
  expect(() =>
    rememberOrder(drafts, "overflow", original.diagram, [2, 1, 0, 3]),
  ).toThrow("execution relationship");
  expect(JSON.stringify([...drafts])).toBe(stable);
});
