import { test, expect } from "@playwright/test";
import { contract } from "./caf-float-multiplexer-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";
for (const kind of ["float", "last", "unicode"])
  test(`${kind} Float Multiplexer source and five-object proof pass admission`, async () => {
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
  count: (s: any) => (s.object_count = 4),
  setup: (s: any) => (s.setup_code = 0),
  standard: (s: any) => (s.standard_name_code = 15),
  modes: (s: any) => (s.recorded_property_2381 = ["0", "1"]),
  modeTypes: (s: any) => (s.recorded_property_2381 = [0, 2]),
  bookkeeping: (s: any) => (s.recorded_property_3122 = "0"),
  missing: (s: any) => s.children.pop(),
  order: (s: any) => s.children.reverse(),
  direction: (s: any) => (s.children[1].direction = "output"),
  exposure: (s: any) => (s.children[1].exposed = false),
  class: (s: any) => (s.children[1].class_id = "526"),
  type: (s: any) => (s.children[1].bacnet_type = 2),
  identity: (s: any) => s.children[1].new_instance++,
  reference: (s: any) => (s.children[1].new_ref = "other"),
  selectorDefault: (s: any) => (s.children[1].recorded_default = "false"),
  floatDefault: (s: any) => (s.children[2].recorded_default = "0.0"),
  metadata: (s: any) => (s.children[2].recorded_metadata_661 = "9"),
  meaning: (s: any) => (s.multiplexer_semantics_verified = true),
  operatorMeaning: (s: any) => (s.operator_meaning_verified = true),
  field: (s: any) => (s.field_transfer_enabled = true),
  output: (s: any) => {
    const r = s.children[1];
    s.output_ref = r.ref;
    s.new_output_ref = r.new_ref;
    s.new_output_instance = r.new_instance;
    s.output_sha256 = r.sha256;
  },
}))
  test(`Float Multiplexer refuses resealed invalid ${name}`, async () => {
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
for (const wrong of ["selector-hash", "missing-input", "invalid-hash"])
  test(`Float Multiplexer review refuses resealed ${wrong} mapping`, async () => {
    const f = contract();
    if (wrong === "selector-hash")
      f.review.creation.new_output_sha256 =
        f.review.creation.new_child_sha256[1];
    else if (wrong === "missing-input")
      f.review.creation.new_child_sha256.pop();
    else f.review.creation.new_child_sha256[3] = "not-a-hash";
    const { creation_sha256, ...creation } = f.review.creation;
    void creation_sha256;
    f.review.creation.creation_sha256 = await connectionSeal(creation);
    const { review_sha256, ...review } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
