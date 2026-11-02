import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { python } from "./native-effective-enum-fixture";
import { recordedEnumRecovery } from "../src/nativeEnumRecoveryLedger";
let data: any[];
test.beforeAll(() => {
  data = JSON.parse(
    python(
      `
import sys,json
from pathlib import Path
from bms_tool.app import create_app
from bms_tool.native_enum_recovery_ledger import enum_recovery_lineage
from tests.test_native_enum_recovery_ledger import recorded_child
result=[]
for cid,previous,after in ((528,0,65535),(529,513,0)):
 for later in (False,True):
  app=create_app(Path(sys.argv[1])/f'{cid}-{later}');body,_=recorded_child(app,cid=cid,previous=previous,after=after,later_proof=later)
  row=dict(source='native',native_change_kind='enum-default',id=body['id'],object=body['default_edit']['record_ref'],target=dict(device=body['identity']['device']))
  result.append(dict(row=row,value=enum_recovery_lineage(body,dict(object=row['object']))))
print(json.dumps(result))
`,
      mkdtempSync(path.join(tmpdir(), "bms-recorded-enum-contract-")),
    ),
  );
});
const clone = (v: any) => JSON.parse(JSON.stringify(v));
test("both recorded classes, actual zero encodings and immutable historical proof variants are accepted", () => {
  for (const d of data)
    expect(recordedEnumRecovery(d.value, d.row)).toBe(d.value);
  expect(data[0].value.previous_encoding_hex).toBe("91002f");
  expect(data[0].value.after_encoding_hex).toBe("9200002f");
  expect(data[2].value.before_value).toBe(0);
  const reordered = Object.fromEntries(Object.entries(data[0].value).reverse());
  expect(recordedEnumRecovery(reordered, data[0].row)).toBe(reordered);
});
test("typed codes, tags, state metadata and semantic claims cannot masquerade as recorded Enum lineage", () => {
  for (const patch of [
    { before_value: false },
    { after_value: "0" },
    { after_value: 65536 },
    { before_value: -1 },
    { before_value: 1.5 },
    { after_value: 65535 },
    { after_encoding_hex: "91002f" },
    { before_encoding_hex: "9200012f" },
    { previous_encoding_hex: "91ff2f" },
    { recorded_after_encoding_hex: "9200002f" },
    { states_text_encoded_sha256: false },
    { class_id: 531 },
    { property: 931 },
    { enum_semantics_verified: true },
    { enum_semantics_verified: 0 },
    { can_apply: true },
    { token: "not-authority" },
    { datatype: "Real" },
    { profile: "future/99" },
    { scope: "verified live controller state" },
  ]) {
    expect(
      recordedEnumRecovery({ ...data[0].value, ...patch }, data[0].row),
    ).toBeNull();
  }
});
test("parent, child, native family, record and Device bindings stay exact", () => {
  const d = data[0];
  for (const patch of [
    { source: "audit" },
    { native_change_kind: "boolean-default" },
    { object: "controller/other" },
    { id: d.value.parent_receipt_id },
    { target: null },
    { target: { device: "device,6001" } },
  ])
    expect(recordedEnumRecovery(d.value, { ...d.row, ...patch })).toBeNull();
  for (const patch of [
    { parent_receipt_id: "bad" },
    { original_backup_id: d.value.current_capture_id },
    { current_snapshot_sha256: "bad" },
    { origin_sha256: null },
    { instance: true },
    { instance: 4194303 },
  ])
    expect(recordedEnumRecovery({ ...d.value, ...patch }, d.row)).toBeNull();
});
test("historical proof requires a valid bounded timezone-aware timestamp and known record kind", () => {
  const d = data[0];
  for (const time of [
    "now",
    "2026-11-02T00:00:00",
    "2026-02-30T01:02:03Z",
    "2026-11-02T25:00:00Z",
    "2026-11-02T00:00:00+24:00",
  ])
    expect(
      recordedEnumRecovery(
        { ...d.value, verified_proof: { ...d.value.verified_proof, time } },
        d.row,
      ),
    ).toBeNull();
  for (const patch of [
    { kind: "live" },
    { sha256: "bad" },
    { can_apply: false },
  ])
    expect(
      recordedEnumRecovery(
        { ...d.value, verified_proof: { ...d.value.verified_proof, ...patch } },
        d.row,
      ),
    ).toBeNull();
});
test("recorded fixed storage retains exact type, capacity and bounded source offsets", () => {
  const d = data[0];
  for (const patch of [
    { bytes: 4 },
    { datatype: true },
    { maximum_code: 4294967295 },
    { static_record_offset: -1 },
    { dynamic_value_offset: 131072 },
    { dynamic_value_offset: false },
    { meanings: ["Off", "On"] },
  ])
    expect(
      recordedEnumRecovery(
        { ...d.value, saved_storage: { ...d.value.saved_storage, ...patch } },
        d.row,
      ),
    ).toBeNull();
});
test("explicit absent state evidence remains absent while unknown incomplete documents are unavailable", () => {
  const d = data[0];
  const absent = { ...d.value, states_text_encoded_sha256: null };
  expect(recordedEnumRecovery(absent, d.row)).toBe(absent);
  for (const v of [null, [], {}, { ...d.value, state: "verified" }])
    expect(recordedEnumRecovery(v, d.row)).toBeNull();
  const missing = clone(d.value);
  delete missing.states_text_encoded_sha256;
  expect(recordedEnumRecovery(missing, d.row)).toBeNull();
});
