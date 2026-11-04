import { test, expect } from "@playwright/test";
import { contract, sourceForms } from "./caf-boolean-multiplexer-fixture";
import {
  constantSource,
  constantReview,
  hasBooleanMultiplexerOutput,
  hasEnumMultiplexerOutput,
} from "../src/cafConstantContract";
import { connectionSeal } from "../src/nativeConnectionContract";
for (const kind of [...sourceForms, "last", "unicode"])
  test(`${kind} Boolean-output Multiplexer preserves typed selector and Boolean storage`, async () => {
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
    expect(hasBooleanMultiplexerOutput(f.source.profile)).toBe(true);
    expect(hasEnumMultiplexerOutput(f.source.profile)).toBe(false);
    expect(f.source.children.map((r: any) => r.bacnet_type)).toEqual([
      5,
      kind === "boolean" ? 5 : 19,
      5,
      5,
    ]);
    expect(f.source.children[3].recorded_default).toBe(
      kind === "boolean" ? null : kind.split(":")[1] || "1",
    );
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
const changes: Record<string, (s: any) => void> = {
  count: (s) => (s.object_count = 4),
  setup: (s) => (s.setup_code = 0),
  standard: (s) => (s.standard_name_code = 17),
  profile: (s) =>
    (s.profile = "caf-recorded-enum-enum-selector-multiplexer-copy/1"),
  modes: (s) => (s.recorded_property_2381 = ["0", "1"]),
  modeTypes: (s) => (s.recorded_property_2381 = [1, 2]),
  bookkeeping: (s) => (s.recorded_property_3122 = "9"),
  stateCount: (s) => (s.children[1].number_of_states = 3),
  stateCode: (s) => (s.children[1].states_text_code = 359),
  stateNamespace: (s) => (s.children[1].states_text_encoding_set = 803),
  dataStateMetadata: (s) => (s.children[2].number_of_states = 2),
  outputDefault: (s) => (s.children[0].recorded_default = "1"),
  defaultNamespace: (s) => (s.children[3].default_encoding_set = 647),
  defaultSpelling: (s) => (s.children[3].recorded_default = "01"),
  defaultFloat: (s) => (s.children[3].recorded_default = "1.0"),
  defaultCase: (s) => (s.children[3].recorded_default = "True"),
  defaultBoolean: (s) => (s.children[3].recorded_default = true),
  defaultOmitted: (s) => (s.children[3].recorded_default = null),
  selectorName: (s) => (s.children[1].recorded_standard_name_code = 1),
  missingEncoding: (s) => {
    delete s.children[3].default_encoding_set;
  },
  missing: (s) => {
    s.children.pop();
  },
  order: (s) => {
    s.children.reverse();
  },
  direction: (s) => (s.children[1].direction = "output"),
  exposure: (s) => (s.children[1].exposed = false),
  class: (s) => (s.children[1].class_id = "526"),
  outputType: (s) => (s.children[0].bacnet_type = 19),
  selectorType: (s) => (s.children[1].bacnet_type = 2),
  identity: (s) => s.children[1].new_instance++,
  reference: (s) => (s.children[1].new_ref = "other"),
  selectorDefault: (s) => (s.children[1].recorded_default = "false"),
  firstInputDefault: (s) => (s.children[2].recorded_default = "0"),
  metadata: (s) => (s.children[2].recorded_metadata_661 = "9"),
  meaning: (s) => (s.multiplexer_semantics_verified = true),
  operatorMeaning: (s) => (s.operator_meaning_verified = true),
  field: (s) => (s.field_transfer_enabled = true),
  allocation: (s) => (s.new_instance = 4194299),
  output: (s) => {
    const r = s.children[1];
    s.output_ref = r.ref;
    s.new_output_ref = r.new_ref;
    s.new_output_instance = r.new_instance;
    s.output_sha256 = r.sha256;
  },
};
for (const [name, change] of Object.entries(changes))
  test(`Boolean-output Enum-selector refuses resealed invalid ${name}`, async () => {
    const f = contract("enum-two:1");
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
for (const name of [
  "stateCount",
  "stateCode",
  "stateNamespace",
  "dataStateMetadata",
  "outputDefault",
  "defaultSpelling",
  "selectorName",
  "selectorDefault",
  "outputType",
  "selectorType",
])
  test(`Boolean selector refuses resealed ${name}`, async () => {
    const f = contract();
    changes[name](f.source);
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
  test(`Boolean-output Multiplexer review refuses resealed ${wrong} mapping`, async () => {
    const f = contract("enum-two:1");
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
