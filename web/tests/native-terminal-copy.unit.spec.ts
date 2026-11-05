import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedTerminals } from "./native-terminal-fixture";
import {
  terminalSource,
  terminalReview,
  terminalProposal,
  type TerminalBasis,
} from "../src/nativeTerminalCopyContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import {
  rememberTerminalDraft,
  terminalDraft,
  discardTerminalDraft,
  blankTerminalDraft,
} from "../src/nativeTerminalDrafts";

let fixture: any;
const data = (basis: TerminalBasis) => {
  fixture ??= seedTerminals(
    mkdtempSync(path.join(tmpdir(), "bms-terminal-contract-")),
  );
  return structuredClone(fixture[basis]);
};
for (const basis of ["archive", "effective"] as const) {
  test(`${basis} authored source and nested whole-image proofs pass`, async () => {
    const f = data(basis);
    expect(terminalSource(f.source, f.archive, basis)).toBe(true);
    expect(
      await terminalReview(f.review, f.archive, f.proposal, f.source, basis),
    ).toBe(true);
    expect(
      terminalSource(
        f.source,
        f.archive,
        basis === "archive" ? "effective" : "archive",
      ),
    ).toBe(false);
    const row = f.source.inventory.inputs.find((p: any) => p.movable);
    expect(terminalProposal(f.source, f.query, row, 3, basis)).toEqual(
      f.proposal,
    );
  });
  for (const [name, change] of Object.entries({
    source: (v: any) => (v.source_sha256 = "0".repeat(64)),
    snapshot: (v: any) => (v.snapshot_sha256 = "0".repeat(64)),
    target: (v: any) => (v.target.address = "127.0.0.2:47819"),
    live: (v: any) => (v.current_identity_verified = true),
    apply: (v: any) => (v.can_apply = true),
    write: (v: any) => (v.controller_write = true),
    query: (v: any) => (v.controller_queries = true),
    identity: (v: any) => (v.inventory.inputs[1].object = "analog-input,102"),
    name: (v: any) => (v.inventory.inputs[1].name = { untrusted: true }),
    host: (v: any) => (v.inventory.inputs[1].ref = "controller/module/0_101"),
    slot: (v: any) => (v.inventory.inputs[1].slot = true),
    label: (v: any) => (v.inventory.inputs[1].device_type = "BI IN1"),
    dpt: (v: any) => (v.inventory.inputs[0].movable = true),
    duplicate: (v: any) => v.inventory.inputs.push(v.inventory.inputs[1]),
    capacity: (v: any) =>
      (v.inventory.hardware.capacity.universal_inputs = [1, 2, 3, 16]),
    occupied: (v: any) => (v.inventory.unassigned_slots = [1, 2, 3]),
    record: (v: any) => (v.inventory.inputs[1].record_sha256 = "bad"),
    version: (v: any) => (v.inventory.controller.format_versions.acs = 99),
    basis: (v: any) => (v.saved_settings_merged = !v.saved_settings_merged),
  }))
    test(`${basis} source rejects ${name}`, () => {
      const f = data(basis);
      change(f.source);
      expect(terminalSource(f.source, f.archive, basis)).toBe(false);
    });
  for (const [name, change] of Object.entries({
    request: (v: any) => (v.request.destination_slot = 2),
    output: (v: any) => (v.output_sha256 = "0".repeat(64)),
    identity: (v: any) => (v.compilation.object = "analog-input,102"),
    mode: (v: any) =>
      (v.compilation.identities_modes_graph_and_record_framing_preserved = false),
    wiring: (v: any) =>
      (v.compilation.physical_terminal_or_wiring_verified = true),
    write: (v: any) => (v.compilation.controller_write = true),
    oldSlot: (v: any) => (v.compilation.old_slot = 2),
    newSlot: (v: any) => (v.compilation.destination_slot = 2),
    payload: (v: any) => (v.compilation.payloads[0].after = "02"),
    overlap: (v: any) =>
      (v.compilation.payloads[1].offset = v.compilation.payloads[0].offset),
    label: (v: any) => (v.compilation.payloads[1].after = "00"),
    record: (v: any) => (v.compilation.record_sha256 = "0".repeat(64)),
    seal: (v: any) => (v.compilation.compilation_sha256 = "0".repeat(64)),
    review: (v: any) => (v.review_sha256 = "0".repeat(64)),
  }))
    test(`${basis} review rejects ${name} even with outer seal recomputed`, async () => {
      const f = data(basis);
      if (basis === "effective") {
        const outer = f.review.compilation;
        f.review.compilation = outer.terminal_edit;
        change(f.review);
        outer.terminal_edit = f.review.compilation;
        f.review.compilation = outer;
      } else change(f.review);
      if (name !== "review") {
        const { review_sha256, ...body } = f.review;
        f.review.review_sha256 = await connectionSeal(body);
      }
      expect(
        await terminalReview(f.review, f.archive, f.proposal, f.source, basis),
      ).toBe(false);
    });
}
test("bounded drafts retain exact earlier edits and refuse a new workspace at capacity", () => {
  const keys = Array.from({ length: 32 }, (_, i) => `terminal-test-${i}`);
  for (const key of keys)
    expect(
      rememberTerminalDraft(key, {
        capture: key,
        basis: "archive",
        ref: "controller/0_101",
        destination: "3",
      }),
    ).toBe(true);
  expect(
    rememberTerminalDraft("overflow", {
      ...blankTerminalDraft(),
      capture: "new",
    }),
  ).toBe(false);
  const copy = terminalDraft(keys[0]);
  copy.destination = "2";
  expect(terminalDraft(keys[0]).destination).toBe("3");
  for (const key of keys) discardTerminalDraft(key);
});
