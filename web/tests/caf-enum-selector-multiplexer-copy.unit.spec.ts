import { test, expect } from "@playwright/test";
import { contract } from "./caf-enum-selector-multiplexer-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";
for (const kind of ["float", "short", "finite", "last", "unicode"])
  test(`${kind} Enum-selector Multiplexer source and seven-object proof pass admission`, async () => {
    const f = contract(kind);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "multiplexer",
      ),
    ).toBe(true);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "math",
      ),
    ).toBe(false);
    if (kind === "unicode") {
      expect(f.source.new_output_ref.length).toBeGreaterThan(512);
      expect([...f.source.new_output_ref].length).toBeLessThanOrEqual(512);
    }
  });
for (const [name, change] of Object.entries({
  count: (s: any) => (s.object_count = 5),
  setup: (s: any) => (s.setup_code = 0),
  standard: (s: any) => (s.standard_name_code = 14),
  modes: (s: any) => (s.recorded_property_2381 = ["0", "2"]),
  bookkeeping: (s: any) => (s.recorded_property_3122 = "0"),
  missing: (s: any) => s.children.pop(),
  order: (s: any) => s.children.reverse(),
  direction: (s: any) => (s.children[5].direction = "output"),
  exposure: (s: any) => (s.children[1].exposed = false),
  class: (s: any) => (s.children[5].class_id = "530"),
  type: (s: any) => (s.children[5].bacnet_type = 5),
  identity: (s: any) => s.children[1].new_instance++,
  reference: (s: any) => (s.children[1].new_ref = "other"),
  selectorDefault: (s: any) => (s.children[5].recorded_default = "1"),
  missingDefault: (s: any) => (s.children[4].recorded_default = null),
  floatDefault: (s: any) => (s.children[4].recorded_default = "NaN"),
  unrecordedDefault: (s: any) => (s.children[3].recorded_default = "0"),
  extraName: (s: any) => (s.children[1].recorded_standard_name_code = 1),
  states: (s: any) => (s.children[5].number_of_states = 5),
  statesText: (s: any) => (s.children[5].states_text_code = 901),
  namespace: (s: any) => (s.children[5].states_text_encoding_set = 647),
  metadata: (s: any) => (s.children[4].recorded_metadata_661 = "9"),
  enumMeaning: (s: any) => (s.enum_semantics_verified = true),
  meaning: (s: any) => (s.multiplexer_semantics_verified = true),
  operatorMeaning: (s: any) => (s.operator_meaning_verified = true),
  field: (s: any) => (s.field_transfer_enabled = true),
}))
  test(`Enum-selector Multiplexer refuses resealed invalid ${name}`, async () => {
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
        "multiplexer",
      ),
    ).toBe(false);
  });
for (const wrong of ["input-hash", "missing-selector", "invalid-hash"])
  test(`Enum-selector Multiplexer review refuses resealed ${wrong} mapping`, async () => {
    const f = contract();
    if (wrong === "input-hash")
      f.review.creation.new_output_sha256 =
        f.review.creation.new_child_sha256[1];
    else if (wrong === "missing-selector")
      f.review.creation.new_child_sha256.pop();
    else f.review.creation.new_child_sha256[5] = "not-a-hash";
    const { creation_sha256, ...creation } = f.review.creation;
    void creation_sha256;
    f.review.creation.creation_sha256 = await connectionSeal(creation);
    const { review_sha256, ...review } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
