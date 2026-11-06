import { test, expect } from "@playwright/test";
import {
  wiringSelection,
  wiringCheckpoint,
  wiringDraftStatus,
  wiringDraftResult,
  wiringDraftRemoved,
} from "../src/cafWiringDraftContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import { wiringFixture } from "./caf-wiring-draft-fixture";
for (const kind of ["partial", "rewire"])
  test(`actual ${kind} checkpoint preserves exact unfinished fields and source proofs`, async () => {
    const f = wiringFixture(kind);
    expect(wiringSelection(f.selection, f.graph)).toBe(true);
    expect(await wiringCheckpoint(f.checkpoint, f.hash, f.graph)).toBe(true);
    expect(await wiringDraftStatus(f.status, f.hash, f.graph)).toBe(true);
    expect(
      await wiringDraftResult(
        f.saved,
        "save",
        f.hash,
        f.graph,
        null,
        f.selection,
      ),
    ).toBe(true);
    expect(
      await wiringDraftResult(f.restored, "restore", f.hash, f.graph, f.token),
    ).toBe(true);
  });
for (const fault of [
  "tuple",
  "count",
  "member",
  "block-proof",
  "continuation",
  "authority",
  "extra",
])
  test(`restore refuses internally resealed ${fault} checkpoint mismatch`, async () => {
    const f = wiringFixture(),
      v = structuredClone(f.restored),
      c = v.checkpoint;
    if (fault === "tuple") c.selection.old[0] = 1;
    if (fault === "count") c.selection.connection_count = 1;
    if (fault === "member") c.selection.rewire_source_ref = "unknown";
    if (fault === "block-proof")
      c.source_evidence.blocks_sha256 = "a".repeat(64);
    if (fault === "continuation") c.source_evidence.continuation_flag = false;
    if (fault === "authority") v.export_success_restored = true;
    if (fault === "extra") c.exported = true;
    const { checkpoint_sha256, ...body } = c;
    c.checkpoint_sha256 = await connectionSeal(body);
    expect(
      await wiringDraftResult(v, "restore", f.hash, f.graph, f.token),
    ).toBe(false);
  });
test("historical status grants no source revalidation and corrupt rows can be explicitly removed", async () => {
  const f = wiringFixture(),
    v = structuredClone(f.status);
  v.capacity.bytes = 10 * 1024 * 1024;
  v.checkpoint = {
    state: "unavailable",
    id: f.token.id,
    revision: f.token.revision,
    error: "Saved checkpoint unavailable",
  };
  expect(await wiringDraftStatus(v, f.hash, f.graph)).toBe(true);
  const removed = {
    profile: "caf-wiring-draft-remove/1",
    caf_sha256: f.hash,
    diagram_ref: f.graph.ref,
    scope: v.scope,
    controller_queries: false,
    controller_writes: false,
    can_apply: false,
    graph_compatibility_validated: false,
    export_success_restored: false,
    source_revalidated: false,
    ...f.token,
    removed: true,
  };
  expect(wiringDraftRemoved(removed, f.hash, f.graph.ref, f.token)).toBe(true);
  expect(
    wiringDraftRemoved(
      { ...removed, revision: f.token.revision + 1 },
      f.hash,
      f.graph.ref,
      f.token,
    ),
  ).toBe(false);
  expect(
    await wiringDraftStatus(
      { ...v, source_revalidated: true },
      f.hash,
      f.graph,
    ),
  ).toBe(false);
});
