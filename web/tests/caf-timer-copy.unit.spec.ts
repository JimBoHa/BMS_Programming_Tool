import { test, expect } from "@playwright/test";
import { contract } from "./caf-timer-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";
for (const kind of ["timer", "matching", "off", "maxmode", "unicode"])
  test(`${kind} Timer seven-port source and eight-object proof pass admission`, async () => {
    const f = contract(kind);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "timer",
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
  count: (s: any) => (s.object_count = 5),
  setup: (s: any) => (s.setup_code = 0),
  missing: (s: any) => s.children.pop(),
  order: (s: any) => s.children.reverse(),
  direction: (s: any) => (s.children[6].direction = "input"),
  exposure: (s: any) => (s.children[6].exposed = true),
  class: (s: any) => (s.children[1].class_id = "531"),
  type: (s: any) => (s.children[3].bacnet_type = 5),
  identity: (s: any) => s.children[3].new_instance++,
  reference: (s: any) => (s.children[3].new_ref = "other"),
  boolDefault: (s: any) => (s.children[1].recorded_default = "false"),
  modeNamespace: (s: any) => (s.children[3].default_encoding_set = 22),
  modeStates: (s: any) => (s.children[3].number_of_states = 8),
  modeOverflow: (s: any) => (s.children[3].recorded_default = "4294967296"),
  resetDefault: (s: any) => (s.children[5].recorded_default = "1"),
  duration: (s: any) => (s.children[4].recorded_default = "NaN"),
  units: (s: any) => (s.children[4].units_code = 72),
  floatMetadata: (s: any) => (s.children[6].recorded_metadata_661 = "5"),
  outputDefault: (s: any) => (s.children[6].recorded_default = "0"),
  timerMeaning: (s: any) => (s.timer_semantics_verified = true),
  enumMeaning: (s: any) => (s.enum_semantics_verified = true),
  field: (s: any) => (s.field_transfer_enabled = true),
}))
  test(`Timer refuses resealed invalid ${name}`, async () => {
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
        "timer",
      ),
    ).toBe(false);
  });
for (const wrong of ["second-output", "missing-hidden-child"])
  test(`Timer review refuses resealed ${wrong} artifact mapping`, async () => {
    const f = contract();
    if (wrong === "second-output")
      f.review.creation.new_output_sha256 =
        f.review.creation.new_child_sha256[6];
    else f.review.creation.new_child_sha256.pop();
    const { creation_sha256, ...creation } = f.review.creation;
    void creation_sha256;
    f.review.creation.creation_sha256 = await connectionSeal(creation);
    const { review_sha256, ...review } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
