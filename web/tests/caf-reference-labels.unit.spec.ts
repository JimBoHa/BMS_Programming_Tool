import { test, expect } from "@playwright/test";
import { contract } from "./caf-reference-fixture";
import { admitReferenceLabels } from "../src/cafReferenceLabels";
import { connectionSeal } from "../src/nativeConnectionContract";
test("versioned reference names bind the original source and diagram without authority", async () => {
  const f = contract();
  expect(await admitReferenceLabels(f.labels, f.archive, f.diagram)).toBe(true);
  expect(f.labels.rows[0].standard_name.reference_name).toBe("MAX");
  expect(f.labels.rows[0].setup.reference_name).toBe("MAX");
});
for (const [name, change] of Object.entries({
  archive: (v: any) => (v.source_sha256 = "0".repeat(64)),
  diagram: (v: any) => (v.diagram_ref = "other"),
  profile: (v: any) => (v.profile = "future"),
  catalog: (v: any) => (v.catalog.sha256 = "0".repeat(64)),
  release: (v: any) => (v.catalog.source.database = "current firmware"),
  compatibility: (v: any) => (v.catalog.archive_compatibility_verified = true),
  runtime: (v: any) => (v.runtime_meaning_verified = true),
  write: (v: any) => (v.controller_write = true),
  field: (v: any) => (v.field_requests = 1),
  row: (v: any) => v.rows.reverse(),
  missing: (v: any) => v.rows.pop(),
  identity: (v: any) => v.rows[0].instance++,
  reference: (v: any) => (v.rows[0].ref = "other"),
  code: (v: any) => (v.rows[0].setup.code = 15),
  namespace: (v: any) => (v.rows[0].setup.enum_set = 287),
  name: (v: any) => (v.rows[0].setup.reference_name = ""),
  absent: (v: any) =>
    (v.rows[1].setup.observed = {
      type: "enum",
      text: "0",
      attributes: { set: "288" },
    }),
}))
  test(`reference annotations refuse resealed invalid ${name}`, async () => {
    const f = contract();
    change(f.labels);
    const { annotation_sha256, ...body } = f.labels;
    void annotation_sha256;
    f.labels.annotation_sha256 = await connectionSeal(body);
    expect(await admitReferenceLabels(f.labels, f.archive, f.diagram)).toBe(
      false,
    );
  });
