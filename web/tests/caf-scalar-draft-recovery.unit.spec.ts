import { test, expect } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  savedScalarCheckpoint,
  savedScalarResult,
  restoredScalarResult,
  scalarDraftStatus,
  scalarProposals,
  scalarDraftToken,
  removedScalarResult,
  rawScalarKey,
} from "../src/cafScalarDraftContract";
import { seedDraft, pythonDraft } from "./caf-scalar-draft-recovery-fixture";
let f: any, directory: string;
test.beforeAll(() => {
  directory = mkdtempSync(path.join(tmpdir(), "caf-scalar-ui-"));
  f = seedDraft(directory);
});
test.afterAll(() => rmSync(directory, { recursive: true, force: true }));
function sealed(checkpoint: any) {
  return JSON.parse(
    pythonDraft(
      "import json,sys;from bms_tool.moi_identity import seal;v=json.loads(sys.argv[1]);v.pop('checkpoint_sha256',None);print(json.dumps(v|{'checkpoint_sha256':seal(v)}))",
      JSON.stringify(checkpoint),
    ),
  );
}
test("actual checkpoint raw order, Unicode and unfinished values survive independent admission", () => {
  expect(savedScalarCheckpoint(f.checkpoint, f.hash)).toEqual(f.checkpoint);
  expect(scalarDraftStatus(f.status, f.hash).checkpoint).toEqual(f.checkpoint);
  expect(savedScalarResult(f.save, f.hash, f.changes, null)).toEqual(
    f.checkpoint,
  );
  const restored = restoredScalarResult(f.restored, f.hash, f.checkpoint);
  expect(restored.checkpoint.changes).toEqual(f.changes);
  expect(restored.enumKeys).toEqual([
    JSON.stringify([f.hash, "controller/enum", "3113"]),
  ]);
  expect(rawScalarKey(f.changes)).toEqual(
    rawScalarKey(
      f.changes.map((r: any) => ({
        value: r.value,
        old: r.old,
        property: r.property,
        ref: r.ref,
      })),
    ),
  );
  expect(rawScalarKey(f.changes)).not.toEqual(
    rawScalarKey([...f.changes].reverse()),
  );
});
for (const raw of ["-", "1e", "", " ", "\t\n", "NaN", "0003", "🙂\u0000"])
  test(`raw ${JSON.stringify(raw)} stays text, without value parsing`, () => {
    const row = structuredClone(f.checkpoint);
    row.changes[0].value = raw;
    expect(savedScalarCheckpoint(sealed(row), f.hash).changes[0].value).toBe(
      raw,
    );
  });
for (const fault of [
  "CAF",
  "profile",
  "generation",
  "revision",
  "timestamp",
  "seal",
  "extra",
  "numeric-value",
  "duplicate",
  "extra-row-field",
  "noncanonical-property",
  "oversize-value",
  "surrogate",
] as const)
  test(`checkpoint rejects ${fault}`, () => {
    const row = structuredClone(f.checkpoint);
    if (fault === "CAF") row.caf_sha256 = "0".repeat(64);
    if (fault === "profile") row.profile = "caf-scalar-draft/2";
    if (fault === "generation") row.id = "bad";
    if (fault === "revision") row.revision = true;
    if (fault === "timestamp") row.created_at = "yesterday";
    if (fault === "seal") row.checkpoint_sha256 = "0".repeat(64);
    if (fault === "extra") row.can_apply = true;
    if (fault === "numeric-value") row.changes[0].value = 1;
    if (fault === "duplicate") row.changes.push(row.changes[0]);
    if (fault === "extra-row-field") row.changes[0].editable = true;
    if (fault === "noncanonical-property") row.changes[0].property = "03113";
    if (fault === "oversize-value") row.changes[0].value = "x".repeat(8193);
    if (fault === "surrogate") row.changes[0].value = "\ud800";
    expect(() =>
      savedScalarCheckpoint(fault === "seal" ? row : sealed(row), f.hash),
    ).toThrow();
  });
for (const fault of [
  "fields-count",
  "field-order",
  "old-text",
  "ref",
  "property",
  "editable",
  "enum-source",
  "enum-class",
  "enum-meaning",
  "ordinary-attributes",
  "ordinary-type",
  "mixed-eligibility",
  "revision",
  "generation",
  "authority",
  "validation",
  "scope",
] as const)
  test(`restore rejects ${fault} without returning replacement work`, () => {
    const v = structuredClone(f.restored);
    if (fault === "fields-count") v.fields.pop();
    if (fault === "field-order") v.fields.reverse();
    if (fault === "old-text") v.fields[0].property.scalar.text = "23.50";
    if (fault === "ref") v.fields[0].ref = "controller/elsewhere";
    if (fault === "property") v.fields[0].property.id = "75";
    if (fault === "editable") v.fields[0].property.editable = false;
    if (fault === "enum-source")
      v.fields[1].property.enum_code_copy.source_sha256 = "0".repeat(64);
    if (fault === "enum-class") v.fields[1].class_id = "530";
    if (fault === "enum-meaning")
      v.fields[1].property.enum_code_copy.enum_semantics_verified = true;
    if (fault === "ordinary-attributes")
      v.fields[0].property.scalar.attributes = { unsafe: "extra" };
    if (fault === "ordinary-type") v.fields[0].property.scalar.type = "BACoid";
    if (fault === "mixed-eligibility")
      v.fields[0].property.enum_code_copy = v.fields[1].property.enum_code_copy;
    if (fault === "revision")
      v.checkpoint = sealed({ ...v.checkpoint, revision: 2 });
    if (fault === "generation")
      v.checkpoint = sealed({ ...v.checkpoint, id: "0".repeat(32) });
    if (fault === "authority") v.controller_writes = true;
    if (fault === "validation") v.proposal_values_validated = true;
    if (fault === "scope") v.scope = "Restored export success";
    expect(() => restoredScalarResult(v, f.hash, f.checkpoint)).toThrow();
  });
test("actual ordinary field with omitted class identity remains eligible", () => {
  const data = seedDraft(directory, false, true);
  expect(data.restored.fields[0].class_id).toBeNull();
  expect(
    restoredScalarResult(data.restored, data.hash, data.checkpoint).checkpoint
      .changes,
  ).toEqual(data.changes);
});
test("unavailable checkpoint exposes only a valid generation token for removal", () => {
  const v = structuredClone(f.status);
  v.checkpoint = {
    state: "unavailable",
    id: f.checkpoint.id,
    revision: 1,
    error:
      "Saved scalar draft evidence is unavailable or inconsistent; remove the checkpoint before saving new work.",
  };
  expect(scalarDraftToken(scalarDraftStatus(v, f.hash).checkpoint)).toEqual(
    f.token,
  );
  v.checkpoint.id = null;
  expect(scalarDraftToken(scalarDraftStatus(v, f.hash).checkpoint)).toBeNull();
  v.checkpoint.changes = f.changes;
  expect(() => scalarDraftStatus(v, f.hash)).toThrow();
});
test("CAS save and remove results cannot substitute another generation or revision", () => {
  expect(() => savedScalarResult(f.save, f.hash, f.changes, f.token)).toThrow();
  expect(() =>
    savedScalarResult(f.save, f.hash, [...f.changes].reverse(), null),
  ).toThrow();
  expect(() =>
    removedScalarResult(
      {
        ...f.status,
        profile: "caf-scalar-draft-remove/1",
        id: "0".repeat(32),
        revision: 1,
        removed: true,
      },
      f.hash,
      f.token,
    ),
  ).toThrow();
  expect(scalarProposals([])).toBe(false);
});
