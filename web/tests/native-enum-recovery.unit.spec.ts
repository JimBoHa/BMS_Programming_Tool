import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { python } from "./native-effective-enum-fixture";
import {
  previousEnumDefaultMatches,
  enumRecoveryTransferMatches,
  enumRecoveryEncodingMatches,
} from "../src/nativeEnumRecoveryContract";
import {
  enumTransferReviewMatches,
  enumTransferReceiptMatches,
} from "../src/nativeEnumTransferContract";

let data: any;
test.beforeAll(() => {
  data = JSON.parse(
    python(
      `
import asyncio,json,sys,struct,pytest
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_enum_recovery_transfer import recovery_review
from tests.test_native_default_transfer import apply_request,real_slot
from bms_tool.native_enum_compiler import EffectiveEnumService
from bms_tool.native_backup_records import NativeBackupRecords
async def main():
 patch=pytest.MonkeyPatch();generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator)
 try:
  peer,_,_,service,_=link
  parent,capture,prepared,proposal,review=await recovery_review(link,previous=0)
  source=EffectiveEnumService(NativeBackupRecords(service.storage)).source({'capture_id':capture['id'],'snapshot_sha256':capture['snapshot_evidence_sha256']})
  real_slot(peer.files,4,struct.pack('>f',9.25))
  receipt=await service.apply_enum_default(**apply_request(review));assert receipt['result']['status']=='verified',receipt
  print(json.dumps(dict(parent=parent,prepared=prepared,proposal=proposal,review=review,receipt=receipt,source=source,field=source['fields'][0])))
 finally:await generator.aclose();patch.undo()
asyncio.run(main())
`,
      mkdtempSync(path.join(tmpdir(), "bms-enum-recovery-contract-")),
    ),
  );
});
const clone = (v: any) => JSON.parse(JSON.stringify(v));
const matches = (v: any) =>
  previousEnumDefaultMatches(v, data.source, data.parent, data.field);
test("actual direct UDP lineage binds previous zero despite different retained encoding widths", () => {
  expect(matches(data.prepared)).toBe(true);
  expect(data.prepared.origin.previous_encoding_hex).toBe("91002f");
  expect(data.prepared.origin.proposal_encoding_hex).toBe("9200002f");
  expect(
    enumTransferReviewMatches(
      data.review,
      data.source,
      data.proposal,
      data.field,
    ),
  ).toBe(true);
  expect(enumTransferReceiptMatches(data.receipt, data.review)).toBe(true);
  expect(data.receipt.intent.payload_sha256).not.toBe(
    data.review.payload_sha256,
  );
});
test("all code aliases, meanings, encodings, storage and state mutations refuse local recovery", () => {
  const changes = [
    (x: any) => (x.profile = "future/99"),
    (x: any) => (x.origin_sha256 = "bad"),
    (x: any) => (x.enum_semantics_verified = true),
    (x: any) => (x.can_apply = true),
    (x: any) => (x.controller_queries = true),
    (x: any) => (x.field_actions = true),
    (x: any) => (x.previous_effective_value = false),
    (x: any) => (x.recorded_after_value = "65535"),
    (x: any) => (x.current_effective_value = 42),
    (x: any) => (x.proposal.value = 1),
    (x: any) => (x.proposal.source_sha256 = "0".repeat(64)),
    (x: any) => (x.proposal.encoded_sha256 = "0".repeat(64)),
    (x: any) => (x.proposal.recovery_parent_receipt = "0".repeat(32)),
    (x: any) => (x.source.source_identity_matches = false),
    (x: any) => (x.source.target.router = "127.0.0.1:1"),
    ...[
      "parent_receipt_id",
      "parent_intent_sha256",
      "original_backup_id",
      "current_capture_id",
      "current_snapshot_sha256",
      "record_ref",
      "class_id",
      "property",
      "previous_effective_value",
      "recorded_after_value",
      "current_effective_value",
      "proposal_value",
      "previous_encoding_hex",
      "recorded_after_encoding_hex",
      "current_encoding_hex",
      "proposal_encoding_hex",
      "states_text_encoded_sha256",
    ].map((key) => (x: any) => (x.origin[key] = null)),
    (x: any) => (x.origin.saved_storage.bytes = 4),
    (x: any) => (x.origin.enum_semantics_verified = true),
    (x: any) => (x.origin.verified_proof.sha256 = "0".repeat(64)),
    (x: any) => (x.origin.original_dispatch = "not-sent"),
  ];
  for (const change of changes) {
    const changed = clone(data.prepared);
    change(changed);
    expect(matches(changed)).toBe(false);
  }
});
test("changed parent, source and selected field cannot confer recovery authority", () => {
  for (const key of ["pending", "profile", "value", "states", "proof"]) {
    const parent = clone(data.parent);
    if (key === "pending") parent.pending = true;
    else if (key === "profile") parent.intent.operation_profile = "future/99";
    else if (key === "value")
      parent.intent.compilation.selected_edit.before_value = 1;
    else if (key === "states")
      parent.intent.compilation.states_text_encoded_sha256 = "0".repeat(64);
    else parent.result.status = "unknown";
    expect(
      previousEnumDefaultMatches(
        data.prepared,
        data.source,
        parent,
        data.field,
      ),
    ).toBe(false);
  }
  for (const change of [
    (x: any) => (x.snapshot_sha256 = "0".repeat(64)),
    (x: any) => (x.target.address = "other"),
    (x: any) => (x.fields[0].effective_value = 42),
    (x: any) => (x.identity["vendor-identifier"] = 99),
  ]) {
    const source = clone(data.source);
    change(source);
    expect(
      previousEnumDefaultMatches(
        data.prepared,
        source,
        data.parent,
        data.field,
      ),
    ).toBe(false);
  }
});
test("verified readback-event proof remains distinct from an unresolved or forged result", () => {
  const parent = clone(data.parent),
    prepared = clone(data.prepared);
  parent.result.status = "unknown";
  const proof = prepared.origin.verified_proof;
  proof.kind = "readback-event";
  parent.events = [
    {
      stage: "readback",
      detail: { status: "verified" },
      evidence_sha256: proof.sha256,
      created_at: proof.time,
    },
  ];
  expect(
    previousEnumDefaultMatches(prepared, data.source, parent, data.field),
  ).toBe(true);
  parent.events[0].detail.status = "unknown";
  expect(
    previousEnumDefaultMatches(prepared, data.source, parent, data.field),
  ).toBe(false);
});
test("recovery field review requires its exact source, typed code and encoding lineage", () => {
  for (const change of [
    (x: any) => delete x.recovery_origin_sha256,
    (x: any) => (x.recovery_origin.current_capture_id = "0".repeat(32)),
    (x: any) => (x.recovery_origin.current_snapshot_sha256 = "0".repeat(64)),
    (x: any) => (x.recovery_origin.proposal_encoding_hex = "91002f"),
    (x: any) => (x.recovery_origin.current_encoding_hex = "91002f"),
    (x: any) => (x.recovery_origin.states_text_encoded_sha256 = "0".repeat(64)),
    (x: any) => (x.recovery_origin.saved_storage.bytes = 4),
    (x: any) => (x.recovery_origin.profile = "future/99"),
  ]) {
    const changed = clone(data.review);
    change(changed);
    expect(enumRecoveryTransferMatches(changed)).toBe(false);
    expect(
      enumTransferReviewMatches(
        changed,
        data.source,
        data.proposal,
        data.field,
      ),
    ).toBe(false);
  }
});
test("receipt lineage and review snapshot cannot silently change during Apply or readback", () => {
  for (const change of [
    (x: any) => delete x.intent.recovery_origin_sha256,
    (x: any) => (x.intent.review_snapshot_sha256 = "0".repeat(64)),
    (x: any) => (x.intent.recovery_origin.parent_receipt_id = "0".repeat(32)),
    (x: any) => (x.intent.recovery_origin.previous_encoding_hex = "9200002f"),
    (x: any) => (x.intent.recovery_origin.proposal_value = false),
    (x: any) => (x.intent.recovery_origin.enum_semantics_verified = true),
  ]) {
    const changed = clone(data.receipt);
    change(changed);
    expect(enumTransferReceiptMatches(changed, data.review)).toBe(false);
  }
});
test("actual current encoding hash and retained proposal width reject equal-code byte substitutions", async () => {
  expect(await enumRecoveryEncodingMatches(data.prepared, data.field)).toBe(
    true,
  );
  for (const [key, value] of [
    ["current_encoding_hex", "9300ffff2f"],
    ["proposal_encoding_hex", "91002f"],
  ]) {
    const changed = clone(data.prepared);
    changed.origin[key] = value;
    expect(await enumRecoveryEncodingMatches(changed, data.field)).toBe(false);
  }
});
