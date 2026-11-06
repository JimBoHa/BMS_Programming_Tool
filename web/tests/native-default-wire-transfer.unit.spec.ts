import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { python } from "./caf-native-fixture";
import {
  defaultWireTransferReviewMatches,
  defaultWireTransferReceiptMatches,
} from "../src/nativeDefaultWireTransferContract";
import { recordedDefaultWire } from "../src/NativeDefaultWireLedgerView";
let data: any;
test.beforeAll(() => {
  const directory = mkdtempSync(
    path.join(tmpdir(), "bms-combined-transfer-contract-"),
  );
  data = JSON.parse(
    python(
      `
import asyncio,json,sys,struct,pytest
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_default_wire_transfer import review,applying,saved
from tests.test_native_default_transfer import real_slot
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.native_default_wire import NativeDefaultWire
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_wire_ledger import combined_reference
async def main():
 patch=pytest.MonkeyPatch();generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator)
 try:
  peer,_,_,native,_=link
  proposal,plan=await review(link)
  source=SignalCompilerService(native.storage).source(proposal['capture_id'])
  service=NativeDefaultWire(NativeBackupRecords(native.storage))
  opened=service.source({k:proposal[k] for k in ['capture_id','snapshot_sha256']})
  selected=service.selection({k:proposal[k] for k in ['capture_id','snapshot_sha256','source_sha256','effective_sha256','diagram_ref','record_sha256','wire_index']})
  field=next(f for f in source['fields'] if f['ref']==proposal['record_ref'])
  real_slot(peer.files,0,struct.pack('>f',45));saved(peer.files,10,b'\\0')
  receipt=await native.apply_default_wire(**applying(plan));assert receipt['result']['status']=='verified',receipt
  recorded=combined_reference(receipt['intent'])['native_default_wire']
  print(json.dumps(dict(source=source,proposal=proposal,review=plan,receipt=receipt,field=field,opened=opened,selected=selected,recorded=recorded)))
 finally:await generator.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
    ),
  );
});
const matches = (value: any) =>
  defaultWireTransferReviewMatches(
    value,
    data.source,
    data.proposal,
    data.field,
    data.opened,
    data.selected,
  );
test("actual UDP combined review and fresh-setting receipt retain both selected changes", () => {
  expect(matches(data.review)).toBe(true);
  expect(defaultWireTransferReceiptMatches(data.receipt, data.review)).toBe(
    true,
  );
  expect(data.receipt.intent.payload_sha256).not.toBe(
    data.review.payload_sha256,
  );
});
for (const [name, change] of Object.entries({
  kind: (v: any) => (v.change_kind = "wire-source"),
  profile: (v: any) =>
    (v.operation_profile = "native-effective-default-transfer/1"),
  source: (v: any) => (v.combined_edit.encoded_sha256 = "0".repeat(64)),
  text: (v: any) => (v.combined_edit.value_text = "9"),
  identity: (v: any) => (v.identity["vendor-identifier"] = 99),
  application: (v: any) => (v.application_sha256 = "0".repeat(64)),
  directory: (v: any) => (v.static_parameters_sha256 = "0".repeat(64)),
  before: (v: any) => (v.combined_guard.prior_bits = "00000000"),
  configuration: (v: any) =>
    (v.combined_guard.wire_guard.configuration_sha256 = "0".repeat(64)),
  real: (v: any) => (v.compilation.selected_default.after_bits = "00000000"),
  wire: (v: any) => (v.compilation.selected_wire.new[0] = 0),
  order: (v: any) => (v.compilation.both_orders_identical = false),
  intermediate: (v: any) =>
    (v.compilation.default_then_wire.intermediate_sha256 = "0".repeat(64)),
  saved: (v: any) =>
    (v.compilation.parameter_merge.dynamic_sha256 = "0".repeat(64)),
  qualification: (v: any) =>
    (v.compilation.parameter_transfer_qualification.model_inventory_used = true),
}))
  test(`changed combined ${name} review is refused`, () => {
    const value = structuredClone(data.review);
    change(value);
    expect(matches(value)).toBe(false);
  });
for (const [name, change] of Object.entries({
  kind: (v: any) => (v.intent.change_kind = "signal-default"),
  profile: (v: any) => (v.intent.operation_profile = "other/1"),
  allocation: (v: any) => (v.intent.new_instance += 1),
  rename: (v: any) => (v.intent.new_name = "Other name"),
  vendor: (v: any) => (v.intent.identity["vendor-identifier"] = 99),
  extra: (v: any) => (v.intent.combined_edit.router = "127.0.0.1:47999"),
  tupleType: (v: any) => (v.intent.combined_edit.old = null),
  realConfirmation: (v: any) => (v.intent.default_change_confirmed = false),
  wireConfirmation: (v: any) => (v.intent.wire_change_confirmed = false),
  interruption: (v: any) => (v.intent.application_transfer_confirmed = false),
  proposal: (v: any) => (v.intent.combined_edit.value_text = "9"),
  reviewed: (v: any) => (v.intent.review_sha256 = "0".repeat(64)),
  source: (v: any) => (v.intent.combined_guard.encoded_sha256 = "0".repeat(64)),
  identity: (v: any) => (v.result.preservation.identity_unchanged = false),
  real: (v: any) =>
    (v.result.preservation.selected_default.effective_bits = "00000000"),
  wire: (v: any) => (v.result.preservation.selected_wire.new[0] = 0),
  bytes: (v: any) => (v.result.native_sha256 = "0".repeat(64)),
  pending: (v: any) => (v.pending = true),
}))
  test(`altered verified combined ${name} receipt cannot claim acceptance`, () => {
    const value = structuredClone(data.receipt);
    change(value);
    expect(defaultWireTransferReceiptMatches(value, data.review)).toBe(false);
  });
test("unknown and not-sent outcomes remain distinct from verified readback", () => {
  expect(
    defaultWireTransferReceiptMatches({
      pending: false,
      result: {
        status: "not_sent",
        may_have_applied: false,
        protocol_accepted: false,
      },
    }),
  ).toBe(true);
  const value = structuredClone(data.receipt);
  value.result.status = "unknown";
  value.pending = true;
  expect(defaultWireTransferReceiptMatches(value, data.review)).toBe(true);
  value.pending = false;
  expect(defaultWireTransferReceiptMatches(value, data.review)).toBe(false);
});

test("recorded combined projection remains reference only", () => {
  const recorded = recordedDefaultWire(data.recorded);
  expect(recorded).not.toBeNull();
  expect(recorded?.field_authority).toBe(false);
  expect(recorded?.source_ref).toBe(data.proposal.source_ref);
});
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "future/2"),
  state: (v: any) => (v.state = "verified"),
  authority: (v: any) => (v.field_authority = true),
  confirmation: (v: any) => (v.transfer_confirmation_recorded = 1),
  bits: (v: any) => (v.before_bits = "7fc00000"),
  tuple: (v: any) => (v.new[3] += 1),
  boolean: (v: any) => (v.old[0] = true),
  reference: (v: any) => (v.source_ref = "bad\nreference"),
  hash: (v: any) => (v.compiled_native_sha256 = "bad"),
}))
  test(`inconsistent recorded combined ${name} is unavailable`, () => {
    const recorded = structuredClone(data.recorded);
    change(recorded);
    expect(recordedDefaultWire(recorded)).toBeNull();
  });
