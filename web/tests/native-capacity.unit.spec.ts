import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedCapacity } from "./native-capacity-fixture";
import {
  capacitySource,
  capacityObservation,
} from "../src/nativeCapacityContract";
import { connectionSeal } from "../src/nativeConnectionContract";
let fixture: any;
function data(kind = "direct") {
  fixture ??= seedCapacity(
    mkdtempSync(path.join(tmpdir(), "bms-capacity-contract-")),
  );
  return structuredClone(fixture[kind]);
}
for (const kind of ["direct", "routed", "over"])
  test(`actual ${kind} capacity evidence retains historical source and fresh read`, async () => {
    const f = data(kind);
    expect(await capacitySource(f.source, f.archive)).toBe(true);
    expect(
      await capacityObservation(
        f.report,
        f.archive,
        f.controller,
        f.query.operation_id,
      ),
    ).toBe(true);
  });
const mutations: Record<string, (v: any) => void> = {
  profile: (v) => (v.profile = "future/2"),
  capture: (v) => (v.source.capture_id = "0".repeat(32)),
  snapshot: (v) => (v.source.snapshot_sha256 = "f".repeat(64)),
  source: (v) => (v.source.sha256 = "f".repeat(64)),
  size: (v) => v.source.archive_bytes++,
  expanded: (v) => (v.source.expanded_bytes = 0),
  records: (v) => v.source.native_record_count++,
  classes: (v) => v.source.record_classes[0].count++,
  diagrams: (v) => v.source.diagram_count++,
  merged: (v) => (v.source.saved_settings_merged = true),
  target: (v) => (v.target.address = "3001:99"),
  device: (v) => (v.identity.device = "device,99"),
  iface: (v) => (v.connector_config.local_address = "127.0.0.1:1"),
  operation: (v) => (v.operation_id = "other-capacity-query"),
  capacity: (v) => v.capacity.bytes++,
  object: (v) => (v.capacity.object = "file,4"),
  property: (v) => (v.capacity.property = 3381),
  datatype: (v) => (v.capacity.datatype = "Real"),
  tag: (v) => (v.capacity.encoded_hex = "2400000000"),
  frame: (v) => (v.capacity.wire.response_apdu_hex = "30010c"),
  invocation: (v) => v.capacity.wire.invoke_id++,
  service: (v) => (v.capacity.wire.service = 15),
  peer: (v) => (v.capacity.wire.source = "127.0.0.1:1"),
  nextHop: (v) => (v.capacity.wire.next_hop = "127.0.0.1:1"),
  wireHash: (v) => (v.capacity.wire.udp_payload_sha256 = "invalid"),
  headroom: (v) => v.comparison.headroom_for_retained_archive_bytes++,
  fits: (v) => (v.comparison.archive_fits = false),
  readOnly: (v) => (v.read_only = false),
  authority: (v) => (v.can_apply = true),
  currentProgram: (v) => (v.current_application_verified = true),
  restore: (v) => (v.restore_payload_prepared = true),
  backup: (v) => (v.backup_state_commands = true),
  seal: (v) => (v.observation_sha256 = "f".repeat(64)),
};
for (const [name, mutate] of Object.entries(mutations))
  test(`capacity evidence rejects changed ${name}`, async () => {
    const f = data();
    mutate(f.report);
    expect(
      await capacityObservation(
        f.report,
        f.archive,
        f.controller,
        f.query.operation_id,
      ),
    ).toBe(false);
  });
test("resealing a different native reply cannot manufacture the reported capacity", async () => {
  const f = data();
  f.report.capacity.encoded_hex = "2101";
  const { observation_sha256: _, ...body } = f.report;
  f.report.observation_sha256 = await connectionSeal(body);
  expect(
    await capacityObservation(
      f.report,
      f.archive,
      f.controller,
      f.query.operation_id,
    ),
  ).toBe(false);
});

test("a resealed wrong native property still fails independent APDU validation", async () => {
  const f = data();
  f.report.capacity.wire.response_apdu_hex =
    f.report.capacity.wire.response_apdu_hex.replace("1a0d34", "1a0d35");
  const { observation_sha256: _, ...body } = f.report;
  f.report.observation_sha256 = await connectionSeal(body);
  expect(
    await capacityObservation(
      f.report,
      f.archive,
      f.controller,
      f.query.operation_id,
    ),
  ).toBe(false);
});

test("a valid nonminimal native property tag preserves the observed value", async () => {
  const f = data();
  f.report.capacity.wire.response_apdu_hex =
    f.report.capacity.wire.response_apdu_hex.replace("1a0d34", "1b000d34");
  const { observation_sha256: _, ...body } = f.report;
  f.report.observation_sha256 = await connectionSeal(body);
  expect(
    await capacityObservation(
      f.report,
      f.archive,
      f.controller,
      f.query.operation_id,
    ),
  ).toBe(true);
});
