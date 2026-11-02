import { test, expect } from "@playwright/test";
import { cafEnumMetadata, cafScalarRequestSha } from "../src/cafScalarCopy";

const source = "a".repeat(64),
  selected = { ref: "controller/enum", class_id: "528" };
function property() {
  return {
    id: "3113",
    kind: "property",
    editable: true,
    scalar: { type: "enum", text: "1", attributes: { set: "state&set" } },
    enum_code_copy: {
      profile: "caf-enum-default-code-copy/1",
      source_sha256: source,
      record_ref: selected.ref,
      class_id: "528",
      property: "3113",
      original_code: 1,
      set_reference: "state&set",
      enum_semantics_verified: false,
      controller_write: false,
    },
  };
}
test("CAF Enum eligibility binds the actual source, class, field, code and retained set", () => {
  const p = property();
  expect(cafEnumMetadata(p, selected, source)).toEqual(p.enum_code_copy);
  p.enum_code_copy.class_id = "529";
  expect(cafEnumMetadata(p, { ...selected, class_id: "529" }, source)).toEqual(
    p.enum_code_copy,
  );
  p.scalar.text = "4294967295";
  p.enum_code_copy.original_code = 4294967295;
  expect(
    cafEnumMetadata(p, { ...selected, class_id: "529" }, source),
  ).not.toBeNull();
});

test("altered or semantic/field-authority metadata cannot enable the Enum input", () => {
  for (const [key, value] of [
    ["source_sha256", "b".repeat(64)],
    ["record_ref", "controller/other"],
    ["class_id", "530"],
    ["property", "931"],
    ["original_code", 2],
    ["profile", "caf-enum-default-code-copy/2"],
    ["set_reference", "other"],
    ["enum_semantics_verified", true],
    ["controller_write", true],
    ["can_apply", true],
  ] as const) {
    const p = property();
    (p.enum_code_copy as any)[key] = value;
    expect(cafEnumMetadata(p, selected, source)).toBeNull();
  }
  expect(cafEnumMetadata(property(), selected, "invalid-source")).toBeNull();
});

test("wrong scalar tags, simulation fields, noncanonical codes and unknown attributes stay readonly", () => {
  for (const text of ["-1", "01", "4294967296", "1e2", ""]) {
    const p = property();
    p.scalar.text = text;
    expect(cafEnumMetadata(p, selected, source)).toBeNull();
  }
  const type = property();
  type.scalar.type = "unsignedLong";
  expect(cafEnumMetadata(type, selected, source)).toBeNull();
  const simulation = property();
  simulation.kind = "simulationProperty";
  expect(cafEnumMetadata(simulation, selected, source)).toBeNull();
  const attributes = property();
  (attributes.scalar.attributes as any).unknown = "preserve";
  expect(cafEnumMetadata(attributes, selected, source)).toBeNull();
});

test("CAF copy request hashing matches independent Python compact UTF8 JSON including Unicode", async () => {
  expect(
    await cafScalarRequestSha([
      { ref: "controller/enum", property: "3113", old: "1", value: "256" },
      { ref: "controller/real", property: "28", old: "blue", value: "é🙂" },
    ]),
  ).toBe("76ecb3156e26dae9a3151103abf8f691c093c110bf7cc199ce9e1792d438a014");
});

test("browser scalar request hashes reject coercions and unexpected fields", async () => {
  const original = {
    ref: "controller/enum",
    property: "3113",
    old: "1",
    value: "2",
  };
  for (const update of [
    { property: 3113 },
    { value: 2 },
    { old: null },
    { grant: true },
  ])
    await expect(
      cafScalarRequestSha([{ ...original, ...update }]),
    ).rejects.toThrow("Unsupported CAF scalar request");
});
