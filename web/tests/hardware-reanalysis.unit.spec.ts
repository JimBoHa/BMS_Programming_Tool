import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedReanalysis } from "./hardware-reanalysis-fixture";
import { admittedHardwareReanalysis } from "../src/hardwareReanalysis";
let fixture: any;
const data = () =>
  (fixture ??= seedReanalysis(
    mkdtempSync(path.join(tmpdir(), "hardware-reanalysis-")),
  ));
test("actual reanalysis binds separate ID and unchanged source without current controller authority", () => {
  const f = data();
  expect(admittedHardwareReanalysis(f.child, f.parent)).toBe(true);
  expect(admittedHardwareReanalysis(f.parent, f.parent)).toBe(false);
});
for (const [name, change] of Object.entries({
  same: (v: any) => (v.id = data().parent.id),
  id: (v: any) => (v.id = "bad"),
  profile: (v: any) => (v.profile = "future/1"),
  read: (v: any) => (v.read_only = false),
  source: (v: any) => (v.source.sha256 = "0".repeat(64)),
  bytes: (v: any) => (v.source.bytes = true),
  filename: (v: any) => (v.source.filename = "other.moi"),
  origin: (v: any) => (v.origin.profile = "future/1"),
  parent: (v: any) => (v.origin.parent_archive_id = "0".repeat(32)),
  parentSource: (v: any) => (v.origin.parent_source_sha256 = "0".repeat(64)),
  evidence: (v: any) => (v.origin.parent_evidence_sha256 = "bad"),
  query: (v: any) => (v.origin.controller_queries = true),
  write: (v: any) => (v.origin.controller_writes = true),
  identity: (v: any) => (v.origin.current_controller_identity_verified = true),
  extra: (v: any) => (v.origin.can_apply = true),
  missing: (v: any) => delete v.origin.parent_origin,
}))
  test(`reanalysis admission rejects ${name}`, () => {
    const f = data(),
      v = structuredClone(f.child);
    change(v);
    expect(admittedHardwareReanalysis(v, f.parent)).toBe(false);
  });
