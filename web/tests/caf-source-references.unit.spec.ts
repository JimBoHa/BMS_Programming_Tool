import { test, expect } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import {
  referenceList,
  referenceReport,
  referenceRequest,
  referenceSave,
  savedReference,
} from "../src/cafSourceReferenceContract";
import type { ComparisonSource } from "../src/cafNativeCorrelationSources";
import { seedReferences } from "./caf-source-references-fixture";
let fixture: any, directory: string;
test.beforeAll(() => {
  directory = mkdtempSync(path.join(tmpdir(), "caf-reference-unit-"));
  fixture = seedReferences(directory);
});
test.afterAll(() => {
  rmSync(directory, { recursive: true, force: true });
});
const source = (kind: "backup" | "file"): ComparisonSource => {
  const r = fixture.samples[kind].row,
    report = JSON.parse(fixture.samples[kind].raw);
  return {
    kind,
    id: r.source.capture_id,
    signature:
      kind === "backup" ? r.source.snapshot_sha256 : r.source.receipt_sha256,
    target: r.source.target,
    captured_at: r.source.captured_at,
    identity: {},
    raw: report[kind === "backup" ? "native_backup" : "native_file"],
  };
};
const document = (raw: string, digest?: string) => ({
  data: JSON.parse(raw),
  blob: new Blob([raw]),
  headers: new Headers({
    "X-Studio-Artifact-Sha256":
      digest || createHash("sha256").update(raw).digest("hex"),
  }),
});
for (const kind of ["backup", "file"] as const) {
  test(`${kind} original report and discriminated unfiltered save request bind independently`, async () => {
    const f = fixture.samples[kind];
    expect(referenceRequest(source(kind), fixture.hash)).toEqual(
      fixture.bodies[kind],
    );
    expect(referenceSave(f.save, source(kind), fixture.hash)).toEqual(f.row);
    expect(referenceList(f.list, fixture.hash)).toEqual([f.row]);
    expect(
      (await referenceReport(document(f.raw), f.row, fixture.hash)).data,
    ).toEqual(JSON.parse(f.raw));
  });
}
for (const fault of [
  "CAF",
  "scope",
  "availability",
  "authority",
  "source-kind",
  "route",
  "counts",
  "page",
  "next-page",
  "count-type",
  "mixed-source",
] as const) {
  test(`saved metadata refuses altered ${fault}`, () => {
    const row = structuredClone(fixture.samples.backup.row);
    if (fault === "CAF") row.caf_sha256 = "0".repeat(64);
    if (fault === "scope") row.scope = "A live match";
    if (fault === "availability") row.source_availability_revalidated = true;
    if (fault === "authority") row.application_association_granted = true;
    if (fault === "source-kind") row.source_kind = "live";
    if (fault === "route") row.source.target.dnet = "3001";
    if (fault === "counts")
      row.coverage.record_status_counts["same-record-identity"]++;
    if (fault === "page") row.pagination.query = "signal";
    if (fault === "next-page") row.pagination.next_offset = 128;
    if (fault === "count-type") row.coverage.caf_objects = true;
    if (fault === "mixed-source") row.source.receipt_sha256 = "a".repeat(64);
    expect(savedReference(row, fixture.hash)).toBeNull();
  });
}
test("unavailable rows remain CAF-bound and supply no recorded source", () => {
  const row = {
    id: "1".repeat(32),
    caf_sha256: fixture.hash,
    state: "unavailable",
    error: "Unavailable",
  };
  expect(savedReference(row, fixture.hash)).toEqual(row);
  expect(
    savedReference({ ...row, caf_sha256: "0".repeat(64) }, fixture.hash),
  ).toBeNull();
  expect(
    savedReference(
      { ...row, source: fixture.samples.backup.row.source },
      fixture.hash,
    ),
  ).toBeNull();
});
for (const fault of [
  "wrong-CAF",
  "availability",
  "authority",
  "duplicates",
  "capacity",
] as const) {
  test(`saved list rejects ${fault}`, () => {
    const v = structuredClone(fixture.samples.backup.list);
    if (fault === "wrong-CAF") v.caf_sha256 = "0".repeat(64);
    if (fault === "availability") v.source_availability_revalidated = true;
    if (fault === "authority") v.controller_writes = true;
    if (fault === "duplicates") v.references.push(v.references[0]);
    if (fault === "capacity") v.capacity.count = 257;
    expect(() => referenceList(v, fixture.hash)).toThrow();
  });
}
for (const fault of [
  "digest",
  "CAF",
  "source",
  "route",
  "authority",
  "inner-seal",
  "coverage",
  "records",
  "request",
  "classification",
  "profile",
] as const) {
  test(`saved report rejects altered ${fault} even with refreshed artifact header`, async () => {
    const f = fixture.samples.file,
      data = JSON.parse(f.raw);
    if (fault === "CAF") data.caf.sha256 = "0".repeat(64);
    if (fault === "source") data.native_file.capture_id = "0".repeat(32);
    if (fault === "route") data.native_file.target.address = "3001:8";
    if (fault === "authority") data.can_apply = true;
    if (fault === "inner-seal") data.report_sha256 = "0".repeat(64);
    if (fault === "coverage") data.coverage.union_references++;
    if (fault === "records") data.records[0].ref = data.records[1].ref;
    if (fault === "request") data.request.query = "signal";
    if (fault === "classification")
      data.classification = "recorded-differences";
    if (fault === "profile") data.profile = "caf-native-source-correlation/1";
    const raw = fault === "digest" ? f.raw : JSON.stringify(data);
    await expect(
      referenceReport(
        document(raw, fault === "digest" ? "0".repeat(64) : undefined),
        f.row,
        fixture.hash,
      ),
    ).rejects.toThrow();
  });
}
test("save result cannot adopt another source or promote local association", () => {
  const f = fixture.samples.backup;
  expect(() =>
    referenceSave(
      { ...f.save, application_association_granted: true },
      source("backup"),
      fixture.hash,
    ),
  ).toThrow();
  expect(() =>
    referenceSave(
      f.save,
      { ...source("backup"), id: "0".repeat(32) },
      fixture.hash,
    ),
  ).toThrow();
});
