import { test, expect } from "@playwright/test";
import { contract } from "./caf-enum-creation-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
for (const kind of ["enumeration", "omitted", "unicode"])
  test(`${kind} source retains enum metadata without semantic authority`, async () => {
    const f = contract(kind);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "enumeration",
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
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "float",
      ),
    ).toBe(false);
    if (kind === "unicode") {
      expect(f.source.new_output_ref.length).toBeGreaterThan(512);
      expect([...f.source.new_output_ref].length).toBeLessThanOrEqual(512);
    }
  });
for (const [name, change] of Object.entries({
  profile: (s: any) => (s.profile = "caf-recorded-boolean-constant-copy/1"),
  value: (s: any) => (s.recorded_value = "1.0"),
  coercion: (s: any) => (s.recorded_value = 10),
  overflow: (s: any) => (s.recorded_value = "4294967296"),
  negative: (s: any) => (s.recorded_value = "-1"),
  defaultSet: (s: any) => (s.default_encoding_set = 999),
  statesText: (s: any) => (s.states_text_code = 999),
  metadataSet: (s: any) => (s.states_text_encoding_set = 647),
  count: (s: any) => (s.number_of_states = 65536),
  semantics: (s: any) => (s.enum_semantics_verified = true),
  omittedSet: (s: any) => (s.default_encoding_set = null),
  field: (s: any) => (s.field_transfer_enabled = true),
}))
  test(`enum source refuses substituted ${name}`, async () => {
    const f = contract();
    change(f.source);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "enumeration",
      ),
    ).toBe(false);
  });
test("omitted value cannot carry a manufactured encoding set", async () => {
  const f = contract("omitted");
  f.source.default_encoding_set = 647;
  expect(
    await constantSource(
      f.source,
      f.request,
      f.diagram,
      f.diagram.blocks[0],
      "enumeration",
    ),
  ).toBe(false);
});
