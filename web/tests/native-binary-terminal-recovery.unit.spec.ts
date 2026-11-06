import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-binary-terminal-recovery-fixture";
import {
  binaryTerminalRecoveryDraft,
  binaryTerminalRecoveryReview,
  binaryTerminalRecoveryReceipt,
  sameBinaryTerminalRecoveryLineage,
} from "../src/nativeBinaryTerminalRecoveryContract";
let fixture: any;
const data = () =>
  (fixture ??= seed(mkdtempSync(path.join(tmpdir(), "bms-binary-recovery-"))));
test("actual typed binary recovery document admits its current source and verified parent", async () => {
  const f = data();
  expect(
    await binaryTerminalRecoveryDraft(
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
  kind: (r: any) => (r.origin.object_id = "analog-input,101"),
  current: (r: any) => (r.origin.current_slot = 1),
  proposal: (r: any) => (r.proposal.edit.slot = 2),
  action: (r: any) => (r.proposal.edit.action = "terminal"),
  guard: (r: any) => (r.proposal.edit.configuration_sha256 = "0".repeat(64)),
  config: (r: any) => (r.inverse_compilation.stored_configuration.polarity = 0),
  counterPresence: (r: any) =>
    delete r.inverse_compilation.captured_counter_values["15"],
  counterValue: (r: any) =>
    (r.inverse_compilation.captured_counter_values["15"] = 1),
  boolean: (r: any) =>
    (r.inverse_compilation.stored_configuration.states_text_index = true),
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
  test(`resealed binary recovery evidence refuses ${name}`, async () => {
    const f = data(),
      r = structuredClone(f.report);
    change(r);
    expect(
      await binaryTerminalRecoveryDraft(resealed(r), f.source, f.parent),
    ).toBe(false);
  });
test("admission binds displayed recovery data to original response bytes", async () => {
  const f = data(),
    r = structuredClone(f.report);
  r.scope = "Altered display";
  expect(
    await binaryTerminalRecoveryDraft(
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
    operation_profile: "native-local-universal-input-transfer/3",
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
  expect(binaryTerminalRecoveryReview(f.lineage, f.report)).toBe(true);
  expect(await binaryTerminalRecoveryReceipt(child)).toBe(true);
  expect(sameBinaryTerminalRecoveryLineage(child, f.lineage)).toBe(true);
  expect(binaryTerminalRecoveryReview({}, null)).toBe(true);
  expect(await binaryTerminalRecoveryReceipt({})).toBe(true);
  expect(binaryTerminalRecoveryReview(f.lineage, null)).toBe(false);
});
for (const key of [
  "binary_terminal_recovery_profile",
  "binary_terminal_recovery_parent_receipt",
  "binary_terminal_recovery_origin",
  "binary_terminal_recovery_origin_sha256",
  "binary_terminal_recovery_lineage_enforced",
])
  test(`missing ${key} cannot demote recovery review or receipt`, async () => {
    const child = childIntent();
    delete (child as any)[key];
    expect(binaryTerminalRecoveryReview(child, data().report)).toBe(false);
    expect(await binaryTerminalRecoveryReceipt(child)).toBe(false);
    expect(sameBinaryTerminalRecoveryLineage(child, data().lineage)).toBe(
      false,
    );
  });
for (const [fault, change] of Object.entries({
  profile: (r: any) =>
    (r.binary_terminal_recovery_profile =
      "native-analog-terminal-recovery-transfer/1"),
  lineage: (r: any) => (r.binary_terminal_recovery_lineage_enforced = false),
  parent: (r: any) =>
    (r.binary_terminal_recovery_parent_receipt = "0".repeat(32)),
  origin: (r: any) =>
    (r.binary_terminal_recovery_origin.current_configuration_sha256 =
      "0".repeat(64)),
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
    expect(await binaryTerminalRecoveryReceipt(child)).toBe(false);
  });

for (const variant of ["no-optional", "fresh-counters", "already"])
  test(`binary recovery admits actual ${variant} source without inferred values`, async () => {
    const f = seed(
      mkdtempSync(path.join(tmpdir(), "bms-binary-variant-")),
      variant,
    );
    expect(
      await binaryTerminalRecoveryDraft(
        { data: f.report, blob: new Blob([f.text]) },
        f.source,
        f.parent,
      ),
    ).toBe(true);
    if (variant === "no-optional") {
      expect(f.report.inverse_compilation.captured_counter_values).toEqual({});
      expect(f.report.inverse_compilation.stored_configuration.polarity).toBe(
        null,
      );
    }
    if (variant === "fresh-counters")
      expect(f.report.inverse_compilation.captured_counter_values).toEqual({
        "15": 4294967295,
        "33": 0,
      });
    if (variant === "already") expect(f.report.proposal).toBe(null);
  });

test("confirmed child may retain newer typed counters without changing its original recovery lineage", async () => {
  const child = structuredClone(childIntent());
  child.compilation.captured_counter_values = { "15": 4294967295, "33": 0 };
  expect(await binaryTerminalRecoveryReceipt(child)).toBe(true);
});
for (const counter of [true, -1, 4294967296, 1.25, "77", null])
  test(`child refuses malformed current counter ${JSON.stringify(counter)}`, async () => {
    const child = structuredClone(childIntent());
    child.compilation.captured_counter_values["15"] = counter;
    expect(await binaryTerminalRecoveryReceipt(child)).toBe(false);
  });
for (const key of [
  "recovery_parent_receipt",
  "encoded_analog_recovery_parent_receipt",
  "terminal_recovery_profile",
  "terminal_recovery_lineage_enforced",
])
  test(`child refuses mixed recovery namespace ${key}`, async () => {
    const child = structuredClone(childIntent());
    (child as any)[key] = "a".repeat(32);
    expect(binaryTerminalRecoveryReview(child, data().report)).toBe(false);
    expect(await binaryTerminalRecoveryReceipt(child)).toBe(false);
  });

test("a resealed already-recorded origin cannot serve as a dispatched recovery child", async () => {
  const child = structuredClone(childIntent());
  child.binary_terminal_recovery_origin.current_slot =
    child.binary_terminal_recovery_origin.previous_slot;
  child.compilation.terminal_compilation.old_slot =
    child.binary_terminal_recovery_origin.previous_slot;
  child.binary_terminal_recovery_origin_sha256 = python(
    "import json,sys;from bms_tool.moi_identity import seal;print(seal(json.loads(sys.argv[1])))",
    JSON.stringify(child.binary_terminal_recovery_origin),
  );
  expect(await binaryTerminalRecoveryReceipt(child)).toBe(false);
});

test("child counter values may advance while expected counter presence remains exact", async () => {
  const expected = structuredClone(childIntent()),
    child = structuredClone(expected);
  child.compilation.captured_counter_values = { "15": 4294967295, "33": 0 };
  expect(await binaryTerminalRecoveryReceipt(child, expected)).toBe(true);
  delete child.compilation.captured_counter_values["15"];
  expect(await binaryTerminalRecoveryReceipt(child, expected)).toBe(false);
});

for (const [fault, change] of Object.entries({
  route: (p: any) => (p.target.address = "127.0.0.2:47819"),
  oldName: (p: any) => (p.old_name = "Other controller"),
  newName: (p: any) => (p.new_name = "Other controller"),
  kind: (p: any) => (p.change_kind = "signal-default"),
  wiring: (p: any) => (p.physical_wiring_confirmed = false),
  input: (p: any) => (p.input_change_confirmed = false),
  transfer: (p: any) => (p.application_transfer_confirmed = false),
}))
  test(`independently fetched parent substitution refuses ${fault}`, async () => {
    const f = data(),
      parent = structuredClone(f.parent);
    change(parent);
    expect(
      await binaryTerminalRecoveryDraft(
        { data: f.report, blob: new Blob([f.text]) },
        f.source,
        parent,
      ),
    ).toBe(false);
  });
