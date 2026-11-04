import { test, expect } from "@playwright/test";
import { contract } from "./caf-enum-comparison-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";
for (const kind of ["enum", "four", "matching", "omitted", "max", "unicode"])
  test(`${kind} Enum comparison metadata and source namespace pass source/review admission`, async () => {
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
        "enumeration",
      ),
    ).toBe(false);
    if (kind === "unicode") {
      expect(f.source.new_output_ref.length).toBeGreaterThan(512);
      expect([...f.source.new_output_ref].length).toBeLessThanOrEqual(512);
    }
  });
for (const [name, change] of Object.entries({
  profile: (s: any) => (s.profile = "caf-recorded-float-comparison-copy/1"),
  count: (s: any) => (s.object_count = 2),
  missing: (s: any) => s.children.pop(),
  order: (s: any) => s.children.reverse(),
  exposure: (s: any) => (s.children[1].exposed = true),
  class: (s: any) => (s.children[2].class_id = "529"),
  type: (s: any) => (s.children[2].bacnet_type = 2),
  identity: (s: any) => s.children[2].new_instance++,
  reference: (s: any) => (s.children[2].new_ref = "other"),
  value: (s: any) => (s.children[2].recorded_default = "-1"),
  overflow: (s: any) => (s.children[2].recorded_default = "4294967296"),
  coercion: (s: any) => (s.children[2].recorded_default = 3),
  namespace: (s: any) => (s.children[2].default_encoding_set = 351),
  pair: (s: any) => (s.children[2].number_of_states = 4),
  textSet: (s: any) => (s.children[2].states_text_encoding_set = 803),
  omission: (s: any) => (s.children[2].recorded_default = null),
  meaning: (s: any) => (s.enum_semantics_verified = true),
  operator: (s: any) => (s.operator_meaning_verified = true),
  setup: (s: any) => (s.setup_code = 1),
  hiddenValue: (s: any) => (s.children[1].recorded_default = "0.1"),
  field: (s: any) => (s.field_transfer_enabled = true),
}))
  test(`Enum comparison refuses resealed invalid ${name}`, async () => {
    const f = contract();
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
        "comparison",
      ),
    ).toBe(false);
  });
for (const wrong of ["hidden-input-output", "missing-child"])
  test(`Enum comparison refuses resealed ${wrong} artifact proof`, async () => {
    const f = contract();
    if (wrong === "missing-child") f.review.creation.new_child_sha256.pop();
    else
      f.review.creation.new_output_sha256 =
        f.review.creation.new_child_sha256[1];
    const { creation_sha256, ...creation } = f.review.creation;
    void creation_sha256;
    f.review.creation.creation_sha256 = await connectionSeal(creation);
    const { review_sha256, ...review } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
