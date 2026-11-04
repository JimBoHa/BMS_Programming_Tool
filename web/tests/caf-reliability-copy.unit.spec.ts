import { test, expect } from "@playwright/test";
import { contract } from "./caf-reliability-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";
for (const kind of ["float", "one", "enum", "unicode"])
  test(`${kind} Reliability Check source and three-object proof pass admission`, async () => {
    const f = contract(kind);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "reliability",
      ),
    ).toBe(true);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "timer",
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
  missing: (s: any) => s.children.pop(),
  order: (s: any) => s.children.reverse(),
  direction: (s: any) => (s.children[0].direction = "input"),
  exposure: (s: any) => (s.children[1].exposed = false),
  class: (s: any) => (s.children[1].class_id = "526"),
  type: (s: any) => (s.children[1].bacnet_type = 2),
  identity: (s: any) => s.children[1].new_instance++,
  reference: (s: any) => (s.children[1].new_ref = "other"),
  outputDefault: (s: any) => (s.children[0].recorded_default = "true"),
  inputDefault: (s: any) => (s.children[1].recorded_default = "0"),
  namespace: (s: any) => (s.children[1].states_text_encoding_set = 647),
  states: (s: any) => (s.children[1].number_of_states = 3),
  statesText: (s: any) => (s.children[1].states_text_code = 350),
  units: (s: any) => (s.children[1].units_code = 73),
  metadata: (s: any) => (s.children[0].recorded_metadata_661 = "9"),
  meaning: (s: any) => (s.reliability_semantics_verified = true),
  enumMeaning: (s: any) => (s.enum_semantics_verified = true),
  operatorMeaning: (s: any) => (s.operator_meaning_verified = true),
  field: (s: any) => (s.controller_write = true),
}))
  test(`Reliability Check refuses resealed invalid ${name}`, async () => {
    const f = contract("enum");
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
        "reliability",
      ),
    ).toBe(false);
  });
for (const value of ["false", "0", true, null])
  test(`Float Reliability Check refuses substituted output default ${value}`, async () => {
    const f = contract();
    f.source.children[0].recorded_default = value;
    const { selection_sha256, ...body } = f.source;
    void selection_sha256;
    f.source.selection_sha256 = await connectionSeal(body);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "reliability",
      ),
    ).toBe(false);
  });
for (const wrong of ["input-hash", "missing-input"])
  test(`Reliability Check review refuses resealed ${wrong} mapping`, async () => {
    const f = contract("enum");
    if (wrong === "input-hash")
      f.review.creation.new_output_sha256 =
        f.review.creation.new_child_sha256[1];
    else f.review.creation.new_child_sha256.pop();
    const { creation_sha256, ...creation } = f.review.creation;
    void creation_sha256;
    f.review.creation.creation_sha256 = await connectionSeal(creation);
    const { review_sha256, ...review } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
