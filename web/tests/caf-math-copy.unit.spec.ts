import { test, expect } from "@playwright/test";
import { contract } from "./caf-math-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";

for (const kind of [
  "small",
  "extra",
  "output-second",
  "plain",
  "omitted",
  "unicode",
])
  test(`${kind} Math size and actual output mapping pass source and creation admission`, async () => {
    const f = contract(kind);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "math",
      ),
    ).toBe(true);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "comparison",
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
  class: (s: any) => (s.children[1].class_id = "526"),
  type: (s: any) => (s.children[0].bacnet_type = 5),
  identity: (s: any) => s.children[0].new_instance++,
  reference: (s: any) => (s.children[0].new_ref = "other"),
  exposure: (s: any) => (s.children[0].exposed = false),
  value: (s: any) => (s.children[2].recorded_default = "NaN"),
  metadata: (s: any) => (s.children[2].recorded_metadata_661 = "9"),
  extraName: (s: any) => (s.children[0].recorded_standard_name_code = 1),
  setup: (s: any) => (s.setup_code = 18),
  extraSetup: (s: any) => {
    s.setup_code = 12;
    s.standard_name_code = 42;
  },
  meaning: (s: any) => (s.operator_meaning_verified = true),
  field: (s: any) => (s.field_transfer_enabled = true),
  outputFirst: (s: any) => {
    const r = s.children[0];
    s.new_output_instance = r.new_instance;
    s.new_output_ref = r.new_ref;
    s.output_ref = r.ref;
    s.output_sha256 = r.sha256;
  },
  outputDefault: (s: any) => (s.children[1].recorded_default = "0.1"),
}))
  test(`Math source refuses resealed invalid ${name}`, async () => {
    const f = contract("output-second");
    change(f.source);
    const { selection_sha256, ...body } = f.source;
    void selection_sha256;
    f.source.selection_sha256 = await connectionSeal(body);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "math",
      ),
    ).toBe(false);
  });
for (const wrong of ["first-child", "missing-child"])
  test(`Math review refuses resealed ${wrong} artifact mapping`, async () => {
    const f = contract("output-second");
    if (wrong === "first-child")
      f.review.creation.new_output_sha256 =
        f.review.creation.new_child_sha256[0];
    else f.review.creation.new_child_sha256.pop();
    const { creation_sha256, ...creation } = f.review.creation;
    void creation_sha256;
    f.review.creation.creation_sha256 = await connectionSeal(creation);
    const { review_sha256, ...review } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
