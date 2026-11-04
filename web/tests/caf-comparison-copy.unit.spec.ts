import { test, expect } from "@playwright/test";
import { contract } from "./caf-comparison-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
for (const kind of ["comparison", "hidden", "unicode"])
  test(`${kind} five-object source and creation seals pass independent admission`, async () => {
    const f = contract(kind);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "comparison",
      ),
    ).toBe(true);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "boolean",
      ),
    ).toBe(false);
    if (kind === "unicode") {
      expect(f.source.new_output_ref.length).toBeGreaterThan(512);
      expect([...f.source.new_output_ref].length).toBeLessThanOrEqual(512);
    }
  });
for (const [name, change] of Object.entries({
  count: (s: any) => (s.object_count = 2),
  missing: (s: any) => s.children.pop(),
  order: (s: any) => s.children.reverse(),
  port: (s: any) => (s.children[1].port = 50084),
  type: (s: any) => (s.children[1].bacnet_type = 19),
  identity: (s: any) => s.children[1].new_instance++,
  reference: (s: any) => (s.children[1].new_ref = "other"),
  shape: (s: any) => (s.children[1].sha256 = "0".repeat(64)),
  exposure: (s: any) => (s.children[3].exposed = !s.children[3].exposed),
  value: (s: any) => (s.children[2].recorded_default = "NaN"),
  metadata: (s: any) => (s.children[2].recorded_metadata_661 = null),
  setup: (s: any) => (s.setup_code = 5),
  meaning: (s: any) => (s.operator_meaning_verified = true),
  field: (s: any) => (s.field_transfer_enabled = true),
}))
  test(`comparison source refuses substituted ${name}`, async () => {
    const f = contract();
    change(f.source);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "comparison",
      ),
    ).toBe(false);
  });
test("comparison review requires all four child artifact hashes", async () => {
  const f = contract();
  f.review.creation.new_child_sha256.pop();
  expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
});
