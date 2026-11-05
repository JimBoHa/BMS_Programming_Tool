import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seed } from "./native-connection-removal-fixture";
import {
  removalSource,
  removalReview,
  removalSelection,
  type RemovalBasis,
} from "../src/nativeConnectionRemovalContract";
import {
  connectionExport,
  connectionSeal,
  connectionDraftKey,
} from "../src/nativeConnectionContract";
import { rememberWireDraft } from "../src/nativeWireDrafts";

let fixture: any;
function data(basis: RemovalBasis) {
  fixture ??= seed(mkdtempSync(path.join(tmpdir(), "bms-removal-contract-")));
  return structuredClone(fixture[basis]);
}
for (const basis of ["archive", "effective"] as const) {
  test(`${basis} actual source, nested proofs and full review seal pass client admission`, async () => {
    const f = data(basis);
    expect(removalSource(f.source, f.archive, f.request, basis)).toBe(true);
    expect(
      await removalReview(f.review, f.archive, f.proposal, f.source, basis),
    ).toBe(true);
    expect(
      removalSource(
        f.source,
        f.archive,
        f.request,
        basis === "archive" ? "effective" : "archive",
      ),
    ).toBe(false);
  });
  for (const [name, change] of Object.entries({
    snapshot: (v: any) => (v.snapshot_sha256 = "0".repeat(64)),
    source: (v: any) => (v.source_sha256 = "0".repeat(64)),
    target: (v: any) => (v.target.router = "different-route"),
    file: (v: any) => v.files["12"].bytes++,
    identity: (v: any) => (v.current_identity_verified = true),
    queries: (v: any) => (v.controller_queries = true),
    writes: (v: any) => (v.controller_write = true),
    apply: (v: any) => (v.can_apply = true),
    transfer: (v: any) => (v.field_transfer_enabled = true),
    immutable: (v: any) => (v.source_immutable = false),
    settings: (v: any) => (v.saved_settings_merged = basis === "archive"),
    diagram: (v: any) => (v.selection.diagram_ref = "another-diagram"),
    property: (v: any) => (v.selection.property_sha256 = "bad-hash"),
    continuation: (v: any) =>
      (v.selection.continuation_metadata = "not-recorded"),
    index: (v: any) => v.selection.wire_index++,
    tuple: (v: any) => v.selection.selected_wire.old[2]++,
    BooleanIndex: (v: any) => (v.selection.wires[0].old[0] = false),
    port: (v: any) => v.selection.wires[1].target_port++,
    member: (v: any) =>
      (v.selection.wires[2].source_ref = "substituted-member"),
    owner: (v: any) => {
      v.selection.wires[2].old[3] = 7000;
      v.selection.wires[2].target_port = 7000;
    },
    width: (v: any) => (v.selection.wires[1].source_index_bytes = 5),
    count: (v: any) => v.selection.connection_count++,
    unavailable: (v: any) => (v.selection.available = false),
  }))
    test(`${basis} source refuses substituted ${name}`, () => {
      const f = data(basis);
      change(f.source);
      expect(removalSource(f.source, f.archive, f.request, basis)).toBe(false);
    });
  for (const [name, change] of Object.entries({
    request: (v: any) => v.request.wire_index++,
    output: (v: any) => (v.output_sha256 = "0".repeat(64)),
    topSeal: (v: any) => (v.review_sha256 = "0".repeat(64)),
    unknownField: (v: any) => (v.substituted = "unreviewed"),
    source: (v: any) => (v.source_sha256 = "0".repeat(64)),
    field: (v: any) => (v.field_transfer_enabled = true),
    old: (_v: any, c: any) => c.old[0]++,
    sourceRef: (_v: any, c: any) => (c.source_ref = "another-source"),
    targetRef: (_v: any, c: any) => (c.target_ref = "another-target"),
    count: (_v: any, c: any) => c.connection_count_after++,
    property: (_v: any, c: any) => (c.property_sha256 = "0".repeat(64)),
    continuation: (_v: any, c: any) => (c.metadata_property_sha256 = null),
    preservation: (_v: any, c: any) =>
      (c.other_expanded_bytes_preserved = false),
    destination: (_v: any, c: any) =>
      (c.destination_configuration_preserved = false),
    semantics: (_v: any, c: any) =>
      (c.native_fallback_or_retention_verified = true),
    readback: (_v: any, c: any) =>
      (c.native_structure_readback_verified = false),
    framing: (_v: any, c: any) => (c.record_prefix_growth = 4),
    prefix: (_v: any, c: any) => (c.record_prefix_bytes = 4),
    growth: (_v: any, c: any) => c.native_bytes_growth++,
    encoding: (_v: any, c: any) => (c.removed_encoding_hex = ""),
    metadataBytes: (_v: any, c: any) => c.removed_continuation_bytes++,
    metadataHash: (_v: any, c: any) => (c.removed_continuation_sha256 = null),
    innerSeal: (_v: any, c: any) => (c.compilation_sha256 = "0".repeat(64)),
  }))
    test(`${basis} review refuses substituted ${name}`, async () => {
      const f = data(basis),
        c =
          basis === "effective"
            ? f.review.compilation.connection_removal
            : f.review.compilation;
      change(f.review, c);
      expect(
        await removalReview(f.review, f.archive, f.proposal, f.source, basis),
      ).toBe(false);
    });
  test(`${basis} export checks actual bytes and all five source/review/compiler headers`, async () => {
    const f = data(basis),
      blob = new Blob([Buffer.from(f.output, "base64")]);
    const headers = new Headers({
      "X-Studio-Artifact-Sha256": f.review.output_sha256,
      "X-Studio-Review-Sha256": f.review.review_sha256,
      "X-Studio-Snapshot-Sha256": f.review.snapshot_sha256,
      "X-Studio-Source-Sha256": f.review.source_sha256,
      "X-Studio-Compilation-Sha256": f.review.compilation.compilation_sha256,
    });
    expect(await connectionExport({ blob, headers }, f.review)).toBe(true);
    for (const key of headers.keys()) {
      const copy = new Headers(headers);
      copy.delete(key);
      expect(await connectionExport({ blob, headers: copy }, f.review)).toBe(
        false,
      );
    }
    expect(
      await connectionExport(
        { blob: new Blob(["different output"]), headers },
        f.review,
      ),
    ).toBe(false);
  });
  test(`${basis} independently resealed runtime authority claim is still refused`, async () => {
    const f = data(basis),
      c =
        basis === "effective"
          ? f.review.compilation.connection_removal
          : f.review.compilation;
    c.native_fallback_or_retention_verified = true;
    const { compilation_sha256, ...inner } = c;
    void compilation_sha256;
    c.compilation_sha256 = await connectionSeal(inner);
    if (basis === "effective") {
      const { compilation_sha256, ...outer } = f.review.compilation;
      void compilation_sha256;
      f.review.compilation.compilation_sha256 = await connectionSeal(outer);
    }
    const { review_sha256, ...body } = f.review;
    void review_sha256;
    f.review.review_sha256 = await connectionSeal(body);
    expect(
      await removalReview(f.review, f.archive, f.proposal, f.source, basis),
    ).toBe(false);
  });
}
for (const [name, change] of Object.entries({
  original: (v: any) => (v.compilation.archive_sha256 = "0".repeat(64)),
  effective: (v: any) => (v.compilation.effective_sha256 = "0".repeat(64)),
  request: (v: any) => (v.request.effective_record_sha256 = "0".repeat(64)),
  files: (v: any) => v.compilation.files["11"].bytes++,
  saved: (v: any) => v.compilation.parameter_merge.matched_parameters++,
  native: (v: any) => (v.compilation.compiled_native_sha256 = "0".repeat(64)),
  outerSeal: (v: any) => (v.compilation.compilation_sha256 = "0".repeat(64)),
}))
  test(`effective wrapper refuses substituted ${name}`, async () => {
    const f = data("effective");
    change(f.review);
    expect(
      await removalReview(
        f.review,
        f.archive,
        f.proposal,
        f.source,
        "effective",
      ),
    ).toBe(false);
  });
test("empty diagram has no removal and exact zero selector", () => {
  const f = data("archive"),
    s = {
      ...f.source.selection,
      wire_index: 0,
      wires: [],
      connection_count: 0,
      selected_wire: null,
      available: false,
    };
  expect(removalSelection(s, f.request, "archive")).toBe(true);
  expect(
    removalSelection({ ...s, available: true }, f.request, "archive"),
  ).toBe(false);
  expect(
    removalSelection(
      { ...s, wire_index: 1 },
      { ...f.request, wire_index: 1 },
      "archive",
    ),
  ).toBe(false);
});
test("source-bound removal drafts share the existing non-evicting 256-slot budget", () => {
  const f = data("archive"),
    record = {
      ref: f.request.diagram_ref,
      record_sha256: f.request.record_sha256,
    };
  const root = connectionDraftKey(f.archive, record) + "/removal";
  const drafts = new Map(
    Array.from({ length: 255 }, (_, i) => ["old-" + i, "unchanged"]),
  );
  expect(rememberWireDraft(drafts, root + "/archive/index", "2")).toBe(true);
  const before = [...drafts];
  expect(rememberWireDraft(drafts, root + "/basis", "effective")).toBe(false);
  expect([...drafts]).toEqual(before);
  expect(rememberWireDraft(drafts, root + "/archive/index", "1")).toBe(true);
  expect(drafts.size).toBe(256);
  expect(
    connectionDraftKey(
      { ...f.archive, snapshot_sha256: "0".repeat(64) },
      record,
    ) + "/removal",
  ).not.toBe(root);
});
