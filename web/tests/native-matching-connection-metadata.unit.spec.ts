import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { matchingConnectionSeed } from "./native-matching-connection-fixture";
import { recordedConnection } from "../src/nativeConnectionLedger";
import {
  connectionCapabilityEvidence,
  matchingConnectionTransferCapability,
} from "../src/nativeConnectionCapabilityContract";

let fixture: any;
function data() {
  fixture ??= matchingConnectionSeed(
    mkdtempSync(path.join(tmpdir(), "bms-matching-metadata-")),
  );
  return structuredClone(fixture.verified);
}

test("recorded connection fields stay separate from current source or transfer authority", () => {
  const f = data(),
    original = structuredClone(f.recorded);
  const v = recordedConnection(f.recorded)!;
  expect(v).not.toBeNull();
  expect(v.new).toEqual([0, 85, 3, 7000]);
  expect(v.index).toBe(1);
  v.new[0] = 99;
  v.prototype_old[0] = 99;
  expect(f.recorded).toEqual(original);
});
for (const [name, change] of Object.entries({
  profile: (v: any) => (v.profile = "future/2"),
  state: (v: any) => (v.state = "verified"),
  scope: (v: any) => (v.scope = "Current graph verified"),
  extra: (v: any) => (v.can_apply = true),
  source: (v: any) => (v.source_ref = v.target_ref),
  control: (v: any) => (v.diagram_ref += "\n"),
  tuple: (v: any) => v.new[3]++,
  occupied: (v: any) => (v.new[2] = v.prototype_old[2]),
  before: (v: any) => (v.connection_count_before = true),
  after: (v: any) => v.connection_count_after++,
  index: (v: any) => v.index++,
  prototype: (v: any) => (v.prototype_index = v.connection_count_before),
  hash: (v: any) => (v.compiled_native_sha256 = "not-a-hash"),
  confirmation: (v: any) => (v.connection_confirmation_recorded = "true"),
}))
  test(`recorded connection refuses changed ${name}`, () => {
    const f = data();
    change(f.recorded);
    expect(recordedConnection(f.recorded)).toBeNull();
  });

test("explicit13 transfer evidence preserves the old matching-copy evidence reader", () => {
  const f = data();
  expect(matchingConnectionTransferCapability(f.capabilities, f.source)).toBe(
    true,
  );
  expect(connectionCapabilityEvidence(f.capabilities, f.source)).toBe(true);
  const legacy = structuredClone(f.capabilities);
  legacy.capability_profile = "native-backup-operation-capabilities/12";
  legacy.operations = legacy.operations.filter(
    (r: any) => r.id !== "matching-connection-transfer",
  );
  expect(connectionCapabilityEvidence(legacy, f.source)).toBe(true);
  expect(matchingConnectionTransferCapability(legacy, f.source)).toBe(false);
});
for (const [name, change] of Object.entries({
  missing: (v: any) =>
    (v.operations = v.operations.filter(
      (r: any) => r.id !== "matching-connection-transfer",
    )),
  duplicate: (v: any) =>
    v.operations.push(
      v.operations.find((r: any) => r.id === "matching-connection-transfer"),
    ),
  malformed: (v: any) => v.operations.push(null),
  status: (v: any) =>
    (v.operations.find(
      (r: any) => r.id === "matching-connection-transfer",
    ).status = "source-qualified"),
  interface: (v: any) => (v.qualification.captured_plain_ipv4 = false),
  typedInterface: (v: any) => (v.qualification.captured_plain_ipv4 = "true"),
  witness: (v: any) =>
    (v.qualification.effective_matching_connection.target_index =
      v.qualification.effective_matching_connection.source_index),
}))
  test(`explicit13 transfer evidence refuses changed ${name}`, () => {
    const f = data();
    change(f.capabilities);
    expect(matchingConnectionTransferCapability(f.capabilities, f.source)).toBe(
      false,
    );
  });
