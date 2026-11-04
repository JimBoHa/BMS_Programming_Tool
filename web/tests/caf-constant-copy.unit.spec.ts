import { test, expect } from "@playwright/test";
import { python } from "./caf-constant-fixture";
import {
  constantSource,
  constantReview,
  constantExport,
  constantCoordinate,
  rememberConstant,
  constantDraftDirty,
  constantDraftSignature,
  type ConstantDrafts,
} from "../src/cafConstantContract";
let fixture: any;
function data() {
  fixture ??= JSON.parse(
    python(`
import json
from tests.test_caf_constant_copy import example,REF,PROTOTYPE
from bms_tool.caf_constant_copy import CafConstantCopies
from bms_tool.moi_identity import seal
c=CafConstantCopies(example());s=c.inspect(REF,PROTOTYPE)
request={'source_sha256':c.archive.hash,'diagram_ref':REF,'prototype_ref':PROTOTYPE}
proposal={**request,'selection_sha256':s['selection_sha256'],'x':'81.000','y':'42.000'}
output,creation=c.compile(**{k:v for k,v in proposal.items() if k!='source_sha256'})
review={'request':proposal,'creation':creation,'controller_write':False,'field_transfer_enabled':False}
print(json.dumps({'source':s,'request':request,'proposal':proposal,'diagram':c.graph.diagram(REF),'review':{**review,'review_sha256':seal(review)}}))
`).toString(),
  );
  return structuredClone(fixture);
}
test("actual constant/output source and review seals pass independent browser admission", async () => {
  const f = data();
  expect(
    await constantSource(f.source, f.request, f.diagram, f.diagram.blocks[0]),
  ).toBe(true);
  expect(await constantReview(f.review, f.proposal, f.source)).toBe(true);
});
for (const [name, change] of Object.entries({
  source: (v: any) => (v.source_sha256 = "0".repeat(64)),
  prototype: (v: any) => v.prototype_index++,
  identity: (v: any) => v.new_instance++,
  child: (v: any) => v.new_output_instance++,
  reference: (v: any) => (v.new_output_ref = "other"),
  membership: (v: any) => v.member_count++,
  order: (v: any) => v.execution_order.reverse(),
  opaque: (v: any) => v.opaque_layout_code++,
  field: (v: any) => (v.field_transfer_enabled = true),
  vendor: (v: any) => (v.vendor_acceptance_verified = true),
  schema: (v: any) => (v.standard_name_code = 12),
  value: (v: any) => (v.recorded_value = "NaN"),
  coordinate: (v: any) => (v.suggested_position.x = "1e100"),
  seal: (v: any) => (v.selection_sha256 = "0".repeat(64)),
}))
  test(`constant source refuses substituted ${name}`, async () => {
    const f = data();
    change(f.source);
    expect(
      await constantSource(f.source, f.request, f.diagram, f.diagram.blocks[0]),
    ).toBe(false);
  });
for (const [name, change] of Object.entries({
  request: (v: any) => (v.request.x = "82"),
  source: (v: any) => (v.creation.selection.output_sha256 = "0".repeat(64)),
  output: (v: any) => (v.creation.new_output_sha256 = "0".repeat(64)),
  position: (v: any) => (v.creation.position.x = "82"),
  authority: (v: any) => (v.creation.controller_write = true),
  field: (v: any) => (v.field_transfer_enabled = true),
  vendor: (v: any) => (v.creation.vendor_acceptance_verified = true),
  seal: (v: any) => (v.review_sha256 = "0".repeat(64)),
}))
  test(`constant review refuses substituted ${name}`, async () => {
    const f = data();
    change(f.review);
    expect(await constantReview(f.review, f.proposal, f.source)).toBe(false);
  });
test("all artifact bytes and four proof headers are required", async () => {
  const f = data(),
    blob = new Blob(["authored bytes"]),
    digest = Buffer.from(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ).toString("hex");
  f.review.creation.output_sha256 = digest;
  const headers = new Headers({
    "X-Studio-Artifact-Sha256": digest,
    "X-Studio-Review-Sha256": f.review.review_sha256,
    "X-Studio-Source-Sha256": f.proposal.source_sha256,
    "X-Studio-Creation-Sha256": f.review.creation.creation_sha256,
  });
  expect(await constantExport({ blob, headers }, f.review)).toBe(true);
  for (const key of headers.keys()) {
    const missing = new Headers(headers);
    missing.delete(key);
    expect(await constantExport({ blob, headers: missing }, f.review)).toBe(
      false,
    );
  }
  expect(
    await constantExport(
      { blob: new Blob(["substituted"]), headers },
      f.review,
    ),
  ).toBe(false);
});
test("passive inspection allocates nothing and a full cache never evicts unfinished contexts", () => {
  const drafts: ConstantDrafts = new Map();
  expect(drafts.size).toBe(0);
  for (let i = 0; i < 32; i++)
    expect(
      rememberConstant(drafts, {
        archive: "source" + i,
        diagram: "diagram",
        prototype: "prototype",
        x: "-",
        y: " ",
      }),
    ).toBe(true);
  const before = [...drafts];
  expect(
    rememberConstant(drafts, {
      archive: "source33",
      diagram: "diagram",
      prototype: "prototype",
    }),
  ).toBe(false);
  expect([...drafts]).toEqual(before);
  const [key, old] = before[0];
  expect(constantDraftDirty(old)).toBe(true);
  expect(
    rememberConstant(drafts, {
      ...old,
      x: "1",
      y: "2",
      saved: constantDraftSignature({ ...old, x: "1", y: "2" }),
    }),
  ).toBe(true);
  expect(constantDraftDirty(drafts.get(key)!)).toBe(false);
  expect(drafts.size).toBe(32);
  drafts.delete(key);
  expect(
    rememberConstant(drafts, {
      archive: "source33",
      diagram: "diagram",
      prototype: "prototype",
    }),
  ).toBe(true);
  for (const [k, v] of before.slice(1)) expect(drafts.get(k)).toEqual(v);
});
for (const value of [
  "",
  "-",
  " ",
  "NaN",
  "Infinity",
  "1e100",
  "3.5e38",
  "١",
  "1_000",
  "\u00a01",
  "1".repeat(81),
])
  test(`unfinished or invalid coordinate ${JSON.stringify(value)} cannot review`, () =>
    expect(constantCoordinate(value)).toBe(false));
