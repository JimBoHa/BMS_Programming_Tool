import { test, expect } from "@playwright/test";
import { python } from "./caf-native-fixture";
import {
  defaultWireSource,
  defaultWireSelection,
  defaultWireReview,
  rememberDefaultWireChoice,
} from "../src/nativeDefaultWireContract";

const fixtures = JSON.parse(
  python(`
import json,tempfile
from pathlib import Path
from tests.test_native_default_wire import setup,source_request,proposal
from bms_tool.native_signal_compiler import SignalCompilerService
out=[]
with tempfile.TemporaryDirectory() as directory:
 storage,service,snapshot=setup(Path(directory))
 parent=SignalCompilerService(storage).source(snapshot['id'])
 opened=service.source(source_request(snapshot))
 for text in ['-0','0.1','3','3.4028234663852886e38']:
  body=proposal(service,snapshot,value=text)
  query={k:body[k] for k in ['capture_id','snapshot_sha256','source_sha256','effective_sha256','diagram_ref','record_sha256','wire_index']}
  selection=service.selection(query)
  _,review=service.preview(body)
  field=next(f for f in parent['fields'] if f['ref']==body['record_ref'])
  out.append(dict(parent=parent,opened=opened,query=query,selection=selection,body=body,review=review,field=field))
print(json.dumps(out))
`),
);
for (const f of fixtures)
  test(`backend combined source and both literal orders validate for ${f.body.value_text}`, () => {
    expect(defaultWireSource(f.opened, f.parent)).toBe(true);
    expect(defaultWireSelection(f.selection, f.parent, f.opened, f.query)).toBe(
      true,
    );
    expect(
      defaultWireReview(
        f.review,
        f.parent,
        f.opened,
        f.selection,
        f.body,
        f.field,
      ),
    ).toBe(true);
  });

const first = fixtures[1];
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "native-effective-wire-source-compiler/1"),
  source: (v: any) => (v.source_sha256 = "0".repeat(64)),
  route: (v: any) => (v.target.address = "127.0.0.1:47999"),
  snapshot: (v: any) => (v.snapshot_sha256 = "0".repeat(64)),
  identity: (v: any) => (v.identity["object-name"] = "Other controller"),
  files: (v: any) => (v.files["12"].sha256 = "0".repeat(64)),
  saved: (v: any) => (v.parameter_merge.dynamic_sha256 = "0".repeat(64)),
  authority: (v: any) => (v.can_apply = true),
  physical: (v: any) => (v.current_identity_verified = true),
  preservation: (v: any) =>
    (v.compilation.other_merged_bytes_preserved = false),
  orders: (v: any) => (v.compilation.both_orders_identical = false),
  disjoint: (v: any) => (v.compilation.disjoint_fields = false),
  realBefore: (v: any) =>
    (v.compilation.selected_default.before_bits = "00000000"),
  realAfter: (v: any) =>
    (v.compilation.selected_default.after_bits = "00000000"),
  realValue: (v: any) => (v.compilation.selected_default.stored_value = 10),
  realField: (v: any) => (v.compilation.selected_default.record_ref = "other"),
  realText: (v: any) => (v.compilation.selected_default.value_text = "0.10"),
  oldWire: (v: any) => (v.compilation.selected_wire.old[0] = 1),
  newWire: (v: any) => (v.compilation.selected_wire.new[0] = 0),
  pin: (v: any) => (v.compilation.selected_wire.target_ref = "other"),
  width: (v: any) => (v.compilation.selected_wire.source_index_bytes = 4),
  defaultIntermediate: (v: any) =>
    (v.compilation.default_then_wire.intermediate_sha256 = "0".repeat(64)),
  wireIntermediate: (v: any) =>
    (v.compilation.wire_then_default.intermediate_sha256 = "0".repeat(64)),
  forwardInput: (v: any) =>
    (v.compilation.default_then_wire.wire_edit.source_sha256 = "0".repeat(64)),
  reverseInput: (v: any) =>
    (v.compilation.wire_then_default.default_edit.source_sha256 = "0".repeat(
      64,
    )),
  forwardOutput: (v: any) =>
    (v.compilation.default_then_wire.wire_edit.output_sha256 = "0".repeat(64)),
  reverseOutput: (v: any) =>
    (v.compilation.wire_then_default.default_edit.output_sha256 = "0".repeat(
      64,
    )),
  independentDefault: (v: any) =>
    (v.compilation.independent_default.files["11"].sha256 = "0".repeat(64)),
  independentWire: (v: any) =>
    (v.compilation.independent_wire.wire_edit.new[0] = 0),
  output: (v: any) => (v.output_sha256 = "0".repeat(64)),
}))
  test(`substituted combined ${name} review cannot authorize a local download`, () => {
    const value = structuredClone(first.review);
    change(value);
    expect(
      defaultWireReview(
        value,
        first.parent,
        first.opened,
        first.selection,
        first.body,
        first.field,
      ),
    ).toBe(false);
  });

for (const [name, change] of Object.entries({
  diagramHash: (v: any) => (v.selection.record_sha256 = "0".repeat(64)),
  tuple: (v: any) => (v.selection.selected_wire.old[0] = 1),
  pin: (v: any) => (v.selection.wires[0].source_port = 99),
  width: (v: any) => (v.selection.wires[0].source_index_bytes = 0),
  candidates: (v: any) =>
    v.selection.candidates.push(v.selection.candidates[0]),
  request: (v: any) => (v.request.wire_index = 1),
}))
  test(`altered combined ${name} selection fails its exact retained context`, () => {
    const value = structuredClone(first.selection);
    change(value);
    expect(
      defaultWireSelection(value, first.parent, first.opened, first.query),
    ).toBe(false);
  });

test("negative zero output retains its float32 sign", () => {
  const f = fixtures[0];
  expect(
    Object.is(f.review.compilation.selected_default.stored_value, -0),
  ).toBe(true);
  const value = structuredClone(f.review);
  value.compilation.selected_default.stored_value = 0;
  expect(
    defaultWireReview(value, f.parent, f.opened, f.selection, f.body, f.field),
  ).toBe(false);
});

for (const [kind, fallback, changed] of [
  ["diagram", "original diagram", "another diagram"],
  ["wire", "0", "1"],
  ["source", "recorded source", "replacement source"],
]) {
  test(`full combined ${kind} storage admits defaults and frees only its original slot`, () => {
    const drafts = new Map(
      Array.from({ length: 256 }, (_, i) => [String(i), "retained draft " + i]),
    );
    const before = new Map(drafts);
    expect(rememberDefaultWireChoice(drafts, "new", changed, fallback)).toBe(
      false,
    );
    expect(drafts).toEqual(before);
    expect(rememberDefaultWireChoice(drafts, "new", fallback, fallback)).toBe(
      true,
    );
    expect(drafts).toEqual(before);
    expect(rememberDefaultWireChoice(drafts, "8", fallback, fallback)).toBe(
      true,
    );
    before.delete("8");
    expect(drafts).toEqual(before);
    expect(rememberDefaultWireChoice(drafts, "new", changed, fallback)).toBe(
      true,
    );
    before.set("new", changed);
    expect(drafts).toEqual(before);
  });
}
