import { test, expect } from "@playwright/test";
import { contract } from "./caf-boolean-fixture";
import { constantSource, constantReview } from "../src/cafConstantContract";
test("actual Boolean class552/output531 profile has separate source and review admission", async () => {
  const f = contract();
  expect(
    await constantSource(
      f.source,
      f.request,
      f.diagram,
      f.diagram.blocks[0],
      "boolean",
    ),
  ).toBe(true);
  expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
  expect(
    await constantSource(
      f.source,
      f.request,
      f.diagram,
      f.diagram.blocks[0],
      "float",
    ),
  ).toBe(false);
});
for (const [name, change] of Object.entries({
  profile: (s: any) => (s.profile = "caf-recorded-float-constant-copy/1"),
  value: (s: any) => (s.recorded_value = "1.0"),
  coercion: (s: any) => (s.recorded_value = true),
  omission: (s: any) => (s.recorded_value = null),
  standard: (s: any) => (s.standard_name_code = 11),
  type: (s: any) => (s.new_ref = s.new_ref.replace(".552_", ".551_")),
  outputType: (s: any) =>
    (s.new_output_ref = s.new_output_ref.replace(".5_", ".2_")),
  field: (s: any) => (s.field_transfer_enabled = true),
}))
  test(`Boolean source refuses substituted ${name}`, async () => {
    const f = contract();
    change(f.source);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        "boolean",
      ),
    ).toBe(false);
  });
for (const kind of ["unicode-float", "unicode-boolean"])
  test(`${kind} matches the API512-codepoint bound and exact source/review seals`, async () => {
    const f = contract(kind);
    expect(f.source.new_output_ref.length).toBeGreaterThan(512);
    expect([...f.source.new_output_ref].length).toBeLessThanOrEqual(512);
    expect(
      await constantSource(
        f.source,
        f.request,
        f.diagram,
        f.diagram.blocks[0],
        kind.endsWith("boolean") ? "boolean" : "float",
      ),
    ).toBe(true);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
  });
