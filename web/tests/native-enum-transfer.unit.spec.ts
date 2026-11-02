import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { python } from "./native-effective-enum-fixture";
import {
  enumTransferReviewMatches,
  enumTransferReceiptMatches,
} from "../src/nativeEnumTransferContract";

let data: any;
test.beforeAll(() => {
  const directory = mkdtempSync(
    path.join(tmpdir(), "bms-enum-transfer-contract-"),
  );
  data = JSON.parse(
    python(
      `
import asyncio,json,sys,struct,pytest
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_enum_transfer import enum_review
from tests.test_native_default_transfer import apply_request,real_slot
async def main():
 # Reuse the authored async fixture's actual setup/cleanup without a pytest runner.
 patch=pytest.MonkeyPatch()
 generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator)
 try:
  peer,_,_,service,_=link
  _,source,proposal,review=await enum_review(link)
  real_slot(peer.files,4,struct.pack('>f',9.25))
  receipt=await service.apply_enum_default(**apply_request(review))
  assert receipt['result']['status']=='verified',receipt
  print(json.dumps({'source':source,'field':source['fields'][0],'proposal':proposal,'review':review,'receipt':receipt}))
 finally:
  await generator.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
    ),
  );
});
const reviewMatches = (review: any) =>
  enumTransferReviewMatches(review, data.source, data.proposal, data.field);
const clone = (v: any) => JSON.parse(JSON.stringify(v));
test("real UDP Enum review and fresh-other-setting receipt independently match numeric storage and source", () => {
  expect(reviewMatches(data.review)).toBe(true);
  expect(enumTransferReceiptMatches(data.receipt, data.review)).toBe(true);
  expect(data.receipt.intent.payload_sha256).not.toBe(
    data.review.payload_sha256,
  );
  const reordered = clone(data.receipt);
  reordered.intent.default_edit = Object.fromEntries(
    Object.entries(reordered.intent.default_edit).reverse(),
  );
  reordered.intent.compilation.saved_storage = Object.fromEntries(
    Object.entries(reordered.intent.compilation.saved_storage).reverse(),
  );
  expect(enumTransferReceiptMatches(reordered, data.review)).toBe(true);
});
test("changed Enum code, type, capacity, source and semantic declarations cannot match a field review", () => {
  for (const change of [
    (x: any) => (x.default_edit.value = true),
    (x: any) => (x.default_edit.value = 65536),
    (x: any) => (x.compilation.selected_edit.before_value = 1),
    (x: any) => (x.compilation.selected_edit.after_encoding_hex = "91ff2f"),
    (x: any) => (x.compilation.selected_edit.class_id = 530),
    (x: any) => (x.compilation.saved_storage = null),
    (x: any) => (x.compilation.saved_storage.bytes = 4),
    (x: any) => (x.compilation.parameter_merge.dynamic_sha256 = "0".repeat(64)),
    (x: any) => (x.compilation.files["11"].bytes += 1),
    (x: any) => (x.enum_semantics_verified = true),
    (x: any) => (x.identity["vendor-identifier"] = 99),
    (x: any) => (x.compilation.states_text_encoded_sha256 = "0".repeat(64)),
    (x: any) =>
      (x.compilation.parameter_transfer_qualification.model_inventory_used = true),
  ]) {
    const changed = clone(data.review);
    change(changed);
    expect(reviewMatches(changed)).toBe(false);
  }
});
test("altered verified Enum receipt cannot claim the selected code or full preservation", () => {
  for (const change of [
    (x: any) => (x.intent.default_edit.value = 0),
    (x: any) => (x.intent.default_change_confirmed = false),
    (x: any) => (x.intent.operation_profile = "future/99"),
    (x: any) => (x.intent.new_instance = 5336),
    (x: any) => (x.intent.review_sha256 = "0".repeat(64)),
    (x: any) => (x.intent.compilation.selected_edit.datatype = "Unsigned"),
    (x: any) => (x.intent.compilation.saved_storage.maximum_code = 4294967295),
    (x: any) => (x.result.preservation.enum_semantics_verified = true),
    (x: any) =>
      (x.result.preservation.selected_default.states_text_encoded_sha256 =
        "0".repeat(64)),
    (x: any) => (x.result.preservation.selected_default.effective_value = 0),
    (x: any) =>
      (x.result.preservation.selected_default.equal_typed_code = false),
    (x: any) => (x.result.preservation.identity_unchanged = false),
    (x: any) => (x.pending = true),
  ]) {
    const changed = clone(data.receipt);
    change(changed);
    expect(enumTransferReceiptMatches(changed, data.review)).toBe(false);
  }
});
test("not-sent and unresolved Enum outcomes remain distinct from verified controller acceptance", () => {
  expect(
    enumTransferReceiptMatches({
      pending: false,
      result: {
        status: "not_sent",
        may_have_applied: false,
        protocol_accepted: false,
      },
    }),
  ).toBe(true);
  expect(
    enumTransferReceiptMatches({
      pending: false,
      result: {
        status: "not_sent",
        may_have_applied: true,
        protocol_accepted: false,
      },
    }),
  ).toBe(false);
  const unknown = clone(data.receipt);
  unknown.pending = true;
  unknown.result = { status: "unknown", may_have_applied: true };
  expect(enumTransferReceiptMatches(unknown, data.review)).toBe(true);
  unknown.result = { status: "verified" };
  unknown.pending = false;
  expect(enumTransferReceiptMatches(unknown, data.review)).toBe(false);
});
