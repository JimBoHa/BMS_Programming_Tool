import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-encoded-analog-recovery-fixture";
import {
  encodedAnalogRecoveryDraft,
  encodedAnalogRecoveryReview,
  encodedAnalogRecoveryReceipt,
  sameEncodedAnalogRecoveryLineage,
} from "../src/nativeEncodedAnalogRecoveryContract";
let fixture: any;
const data = () =>
  (fixture ??= seed(mkdtempSync(path.join(tmpdir(), "bms-analog-recovery-"))));
test("actual typed analog recovery document admits its current source and verified parent", async () => {
  const f = data();
  expect(
    await encodedAnalogRecoveryDraft(
      { data: f.report, blob: new Blob([f.text]) },
      f.source,
      f.parent,
    ),
  ).toBe(true);
});

import { python } from "./native-connection-fixture";
function resealed(v: any) {
  const text = python(
    `import json,sys\nfrom bms_tool.moi_identity import seal\nr=json.loads(sys.argv[1]);c=r.get('inverse_compilation');p=c.get('terminal_compilation') if c else None\nif p:p['compilation_sha256']=seal({k:v for k,v in p.items() if k!='compilation_sha256'})\nr['origin_sha256']=seal(r['origin']);r['evidence_sha256']=seal({k:v for k,v in r.items() if k!='evidence_sha256'})\nprint(json.dumps(r,ensure_ascii=False))`,
    JSON.stringify(v),
  );
  return { data: JSON.parse(text), blob: new Blob([text]) };
}
for (const [name, change] of Object.entries({
  profile: (r: any) => (r.profile = "unknown/1"),
  authority: (r: any) => (r.can_apply = true),
  query: (r: any) => (r.controller_queries = true),
  extra: (r: any) => (r.token = "A".repeat(32)),
  source: (r: any) => (r.source.capture_id = "0".repeat(32)),
  snapshot: (r: any) => (r.source.snapshot_sha256 = "0".repeat(64)),
  effective: (r: any) => (r.current_effective_sha256 = "0".repeat(64)),
  parent: (r: any) => (r.origin.parent_receipt_id = "0".repeat(32)),
  parentHash: (r: any) => (r.origin.parent_intent_sha256 = "0".repeat(64)),
  ref: (r: any) => (r.origin.record_ref = "other/0_101"),
  kind: (r: any) => (r.origin.object_id = "binary-input,101"),
  current: (r: any) => (r.origin.current_slot = 1),
  proposal: (r: any) => (r.proposal.edit.slot = 2),
  action: (r: any) => (r.proposal.edit.action = "terminal"),
  guard: (r: any) => (r.proposal.edit.configuration_sha256 = "0".repeat(64)),
  config: (r: any) =>
    (r.inverse_compilation.stored_configuration.output_low = 0),
  storage: (r: any) =>
    (r.inverse_compilation.configuration_storage.linear_output_endpoints_present = true),
  boolean: (r: any) =>
    (r.inverse_compilation.stored_configuration.setup = true),
  compiler: (r: any) =>
    (r.inverse_compilation.terminal_compilation.profile =
      "tagged-moi-local-terminal-copy/2"),
  charset: (r: any) =>
    (r.inverse_compilation.terminal_compilation.device_type_character_encoding = 5),
  bytes: (r: any) =>
    (r.inverse_compilation.terminal_compilation.payloads[0].after = "02"),
  overlap: (r: any) =>
    (r.inverse_compilation.terminal_compilation.payloads[1].offset =
      r.inverse_compilation.terminal_compilation.payloads[0].offset),
  static: (r: any) =>
    (r.inverse_compilation.parameter_merge.static_sha256 = "0".repeat(64)),
  output: (r: any) => (r.inverse_output_sha256 = "0".repeat(64)),
  originExtra: (r: any) => (r.origin.can_apply = true),
  already: (r: any) => {
    r.already_recorded = true;
    r.new_review_required = false;
  },
}))
  test(`resealed analog recovery evidence refuses ${name}`, async () => {
    const f = data(),
      r = structuredClone(f.report);
    change(r);
    expect(
      await encodedAnalogRecoveryDraft(resealed(r), f.source, f.parent),
    ).toBe(false);
  });
test("admission binds displayed recovery data to original response bytes", async () => {
  const f = data(),
    r = structuredClone(f.report);
  r.scope = "Altered display";
  expect(
    await encodedAnalogRecoveryDraft(
      { data: r, blob: new Blob([f.text]) },
      f.source,
      f.parent,
    ),
  ).toBe(false);
});

function childIntent() {
  const f = data();
  return {
    ...f.lineage,
    review_capture_id: f.source.capture_id,
    input_edit: f.report.proposal.edit,
    compilation: f.report.inverse_compilation,
    physical_wiring_confirmed: true,
    input_change_confirmed: true,
    application_transfer_confirmed: true,
  };
}
test("backend-derived origin admits a fresh review and confirmed child while ordinary work stays separate", async () => {
  const f = data(),
    child = childIntent();
  expect(encodedAnalogRecoveryReview(f.lineage, f.report)).toBe(true);
  expect(await encodedAnalogRecoveryReceipt(child)).toBe(true);
  expect(sameEncodedAnalogRecoveryLineage(child, f.lineage)).toBe(true);
  expect(encodedAnalogRecoveryReview({}, null)).toBe(true);
  expect(await encodedAnalogRecoveryReceipt({})).toBe(true);
  expect(encodedAnalogRecoveryReview(f.lineage, null)).toBe(false);
});
for (const key of [
  "encoded_analog_recovery_profile",
  "encoded_analog_recovery_parent_receipt",
  "encoded_analog_recovery_origin",
  "encoded_analog_recovery_origin_sha256",
  "encoded_analog_recovery_lineage_enforced",
])
  test(`missing ${key} cannot demote recovery review or receipt`, async () => {
    const child = childIntent();
    delete (child as any)[key];
    expect(encodedAnalogRecoveryReview(child, data().report)).toBe(false);
    expect(await encodedAnalogRecoveryReceipt(child)).toBe(false);
    expect(sameEncodedAnalogRecoveryLineage(child, data().lineage)).toBe(false);
  });
for (const [fault, change] of Object.entries({
  profile: (r: any) =>
    (r.encoded_analog_recovery_profile =
      "native-analog-terminal-recovery-transfer/1"),
  lineage: (r: any) => (r.encoded_analog_recovery_lineage_enforced = false),
  parent: (r: any) =>
    (r.encoded_analog_recovery_parent_receipt = "0".repeat(32)),
  origin: (r: any) =>
    (r.encoded_analog_recovery_origin.current_configuration_sha256 = "0".repeat(
      64,
    )),
  capture: (r: any) => (r.review_capture_id = "0".repeat(32)),
  slot: (r: any) => (r.input_edit.slot = 2),
  guard: (r: any) => (r.input_edit.configuration_sha256 = "0".repeat(64)),
  ref: (r: any) => (r.compilation.record_ref = "other/0_101"),
  pair: (r: any) => (r.compilation.terminal_compilation.old_slot = 2),
  physical: (r: any) => (r.physical_wiring_confirmed = false),
  input: (r: any) => (r.input_change_confirmed = false),
  transfer: (r: any) => (r.application_transfer_confirmed = false),
}))
  test(`child receipt independently refuses ${fault}`, async () => {
    const child = structuredClone(childIntent());
    change(child);
    expect(await encodedAnalogRecoveryReceipt(child)).toBe(false);
  });
