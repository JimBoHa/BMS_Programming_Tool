import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedPointRecovery } from "./nativePointNameRecoveryFixture";
import {
  activePointNameRecovery,
  previousPointNameMatches,
  pointNameRecoveryTransferMatches,
} from "../src/nativePointNameRecovery";
const fixture = () =>
  seedPointRecovery(
    mkdtempSync(path.join(tmpdir(), "point-recovery-contract-")),
  );

test("exact previous point-name evidence binds historical proof and current captured source", () => {
  const f = fixture();
  expect(
    previousPointNameMatches(f.report, f.capture, f.field, f.receipt),
  ).toBe(true);
  expect(
    previousPointNameMatches(
      f.report,
      { ...f.capture, id: "f".repeat(32) },
      f.field,
      f.receipt,
    ),
  ).toBe(false);
  expect(
    previousPointNameMatches(
      f.report,
      f.capture,
      { ...f.field, object_id: "analog-input,102" },
      f.receipt,
    ),
  ).toBe(false);
});
test("substituted source, parent, point, outcome or authority remains unavailable", () => {
  const f = fixture();
  for (const patch of [
    { profile: "future/2" },
    { field_actions: true },
    { can_apply: true },
    { controller_queries: true },
    { origin_sha256: "bad" },
    { current_name: "other" },
    {
      source: {
        ...f.report.source,
        target: { ...f.report.source.target, router: "127.0.0.2" },
      },
    },
    { origin: { ...f.report.origin, parent_receipt_id: "f".repeat(32) } },
    { origin: { ...f.report.origin, current_name_sha256: "f".repeat(64) } },
    { origin: { ...f.report.origin, character_encoding: 5 } },
    {
      origin: {
        ...f.report.origin,
        verified_proof: {
          ...f.report.origin.verified_proof,
          sha256: "f".repeat(64),
        },
      },
    },
    { proposal: { ...f.report.proposal, new_name: "other" } },
  ])
    expect(
      previousPointNameMatches(
        { ...f.report, ...patch },
        f.capture,
        f.field,
        f.receipt,
      ),
    ).toBe(false);
  expect(
    previousPointNameMatches(f.report, f.capture, f.field, {
      ...f.receipt,
      pending: true,
    }),
  ).toBe(false);
});
test("only the exact explicitly active proposal adds recovery bindings", () => {
  const f = fixture(),
    work = {
      name: f.report.previous_name,
      capture: f.capture,
      field: f.field,
      recovery: { data: f.report, active: true, ordinaryName: "keep my draft" },
    };
  expect(activePointNameRecovery(work)).toBe(f.report);
  for (const patch of [
    { name: "other" },
    { capture: { ...f.capture, id: "f".repeat(32) } },
    { recovery: { ...work.recovery, active: false } },
  ])
    expect(activePointNameRecovery({ ...work, ...patch })).toBeNull();
  expect(work.recovery.ordinaryName).toBe("keep my draft");
});
test("review and receipt origin bindings must agree while ordinary point changes remain ordinary", () => {
  const f = fixture(),
    expected = {
      recovery_origin: f.report.origin,
      recovery_origin_sha256: f.report.origin_sha256,
    };
  expect(pointNameRecoveryTransferMatches({ ...expected }, expected)).toBe(
    true,
  );
  expect(
    pointNameRecoveryTransferMatches(
      {
        ...expected,
        recovery_origin: { ...f.report.origin, object_id: "analog-input,102" },
      },
      expected,
    ),
  ).toBe(false);
  expect(pointNameRecoveryTransferMatches({}, expected)).toBe(false);
  expect(pointNameRecoveryTransferMatches(expected, {})).toBe(false);
  expect(pointNameRecoveryTransferMatches({}, {})).toBe(true);
});
