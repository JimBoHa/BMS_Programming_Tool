import { test, expect } from "@playwright/test";
import {
  cafRemovalSource,
  cafRemovalRequest,
  cafRemovalReview,
  cafRemovalExport,
  removedCafFile,
  type RemovedCafCopy,
} from "../src/cafConnectionRemovalContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import {
  cafRemovalKey,
  cafRemovalSignature,
  cafRemovalDirty,
  rememberCafRemoval,
  type CafRemovalDrafts,
} from "../src/cafRemovalDrafts";
import { removalFixture } from "./caf-connection-removal-fixture";
const original = removalFixture();
const sourceRequest = {
  source_sha256: original.hash,
  diagram_ref: original.diagram.ref,
  wire_index: 0,
};
const sourceValid = (v: any) =>
  cafRemovalSource(
    v,
    sourceRequest,
    original.diagram,
    original.diagram.connections[0],
  );
async function sealed(value: any, key: string) {
  const { [key]: _, ...body } = value;
  return { ...body, [key]: await connectionSeal(body) };
}

test("actual backend source, nested review, all five export headers and output bytes agree", async () => {
  expect(await sourceValid(original.source)).toBe(true);
  expect(cafRemovalRequest(original.source)).toEqual(original.request);
  expect(
    await cafRemovalReview(
      original.review,
      original.request,
      original.source,
      original.objects,
    ),
  ).toBe(true);
  expect(
    await cafRemovalExport(
      {
        blob: new Blob([Buffer.from(original.output, "base64")]),
        headers: new Headers(original.headers),
      },
      original.review,
    ),
  ).toBe(true);
});

const sourceChanges: Array<[string, (s: any) => void]> = [
  ["unknown source field", (s) => (s.compiler = "unearned")],
  ["missing source field", (s) => delete s.source_xml_sha256],
  ["wrong CAF", (s) => (s.source_sha256 = "a".repeat(64))],
  ["wrong diagram", (s) => (s.diagram_ref = "8-1/575_2")],
  ["wrong occurrence", (s) => (s.wire_index = 1)],
  ["wrong tuple", (s) => (s.old[0] = 1)],
  ["Boolean tuple", (s) => (s.old[0] = false)],
  ["wrong count", (s) => (s.connection_count = 3)],
  ["wrong source reference", (s) => (s.source_ref += "x")],
  ["wrong destination port", (s) => (s.target_port = 85)],
  ["wrong continuation text", (s) => (s.continuation.text += "x")],
  ["unknown continuation field", (s) => (s.continuation.extra = true)],
  ["wrong Boolean spelling type", (s) => (s.continuation.flag = "true")],
  ["unsupported class", (s) => (s.diagram_class_id = "999")],
  ["unsupported version", (s) => (s.diagram_class_version = "2.0")],
  ["unearned writer assertion", (s) => (s.target_remaining_writer_count = 1)],
  ["native execution authority", (s) => (s.native_execution_verified = true)],
  ["transfer authority", (s) => (s.field_transfer_enabled = true)],
  [
    "different profile",
    (s) => (s.profile = "native-archive-connection-copy/1"),
  ],
  ["different scope", (s) => (s.scope += "accepted")],
  [
    "malformed original row hash",
    (s) => (s.continuation_record_sha256 = "ABC"),
  ],
];
for (const [name, mutate] of sourceChanges)
  test(`source rejects ${name} even with a new seal`, async () => {
    const s = structuredClone(original.source);
    mutate(s);
    expect(await sourceValid(await sealed(s, "selection_sha256"))).toBe(false);
  });
test("source rejects a forged seal and mismatched actual graph endpoint", async () => {
  expect(
    await sourceValid({ ...original.source, selection_sha256: "0".repeat(64) }),
  ).toBe(false);
  const g = structuredClone(original.diagram);
  g.blocks[0].index = 1;
  expect(
    await cafRemovalSource(original.source, sourceRequest, g, g.connections[0]),
  ).toBe(false);
});
test("duplicate occurrences retain an actual remaining writer and exact selected occurrence", async () => {
  const f = removalFixture("duplicate", 1);
  expect(f.source.target_remaining_writer_count).toBe(1);
  expect(
    await cafRemovalSource(
      f.source,
      { source_sha256: f.hash, diagram_ref: f.diagram.ref, wire_index: 1 },
      f.diagram,
      f.diagram.connections[1],
    ),
  ).toBe(true);
  expect(
    await cafRemovalSource(
      f.source,
      { source_sha256: f.hash, diagram_ref: f.diagram.ref, wire_index: 0 },
      f.diagram,
      f.diagram.connections[0],
    ),
  ).toBe(false);
});

const reviewChanges: Array<[string, (r: any) => void]> = [
  ["extra envelope", (r) => (r.other = 1)],
  ["envelope write authority", (r) => (r.controller_write = true)],
  [
    "request guard omission",
    (r) => delete r.request.continuation_record_sha256,
  ],
  ["source substitution", (r) => (r.removal.selection.old[0] = 1)],
  ["extra result field", (r) => (r.removal.other = 1)],
  ["result authority", (r) => (r.removal.can_apply = true)],
  ["two removed records", (r) => (r.removal.removed_connection_count = 2)],
  ["wrong remaining count", (r) => (r.removal.remaining_connection_count = 2)],
  ["unchanged artifact", (r) => (r.removal.output_sha256 = original.hash)],
  [
    "unchanged XML",
    (r) => (r.removal.output_xml_sha256 = original.source.source_xml_sha256),
  ],
  [
    "wrong object count",
    (r) => (r.removal.preserved.original_object_count += 1),
  ],
  [
    "destination changed",
    (r) => (r.removal.preserved.destination_configuration = false),
  ],
  ["extra preservation claim", (r) => (r.removal.preserved.runtime = true)],
];
for (const [name, mutate] of reviewChanges)
  test(`review rejects ${name} even when resealed`, async () => {
    const r = structuredClone(original.review);
    mutate(r);
    r.removal = await sealed(r.removal, "removal_sha256");
    const v = await sealed(r, "review_sha256");
    expect(
      await cafRemovalReview(
        v,
        original.request,
        original.source,
        original.objects,
      ),
    ).toBe(false);
  });
test("both review seals independently protect otherwise valid evidence", async () => {
  for (const level of ["outer", "inner"]) {
    const r = structuredClone(original.review);
    if (level === "outer") r.review_sha256 = "f".repeat(64);
    else {
      r.removal.removal_sha256 = "f".repeat(64);
      Object.assign(r, await sealed(r, "review_sha256"));
    }
    expect(
      await cafRemovalReview(
        r,
        original.request,
        original.source,
        original.objects,
      ),
    ).toBe(false);
  }
});
for (const header of Object.keys(original.headers))
  test(`export refuses missing or substituted ${header}`, async () => {
    for (const altered of [null, "f".repeat(64)]) {
      const headers = new Headers(original.headers);
      if (altered) headers.set(header, altered);
      else headers.delete(header);
      expect(
        await cafRemovalExport(
          { blob: new Blob([Buffer.from(original.output, "base64")]), headers },
          original.review,
        ),
      ).toBe(false);
    }
  });
test("substituted artifact bytes do not become an exported proposal", async () => {
  expect(
    await cafRemovalExport(
      {
        blob: new Blob([Buffer.from(original.caf, "base64")]),
        headers: new Headers(original.headers),
      },
      original.review,
    ),
  ).toBe(false);
});

function copy(): RemovedCafCopy {
  return {
    blob: new Blob([Buffer.from(original.output, "base64")]),
    name: "removed.caf",
    sha256: original.review.removal.output_sha256,
    sourceArchive: original.hash,
    diagram: original.diagram.ref,
    selectionSha256: original.source.selection_sha256,
    reviewSha256: original.review.review_sha256,
  };
}
test("independent removal handoff accepts exact bytes without a constant creation identity", async () => {
  const file = await removedCafFile(copy(), () => true);
  expect(file?.name).toBe("removed.caf");
  expect(Buffer.from(await file!.arrayBuffer())).toEqual(
    Buffer.from(original.output, "base64"),
  );
});
test("copy handoff refuses unsafe identity, location or bytes", async () => {
  for (const changes of [
    { name: "../removed.caf" },
    { name: "removed.txt" },
    { diagram: "" },
    { sourceArchive: "x" },
    { selectionSha256: "x" },
    { reviewSha256: "x" },
    { sha256: original.hash },
    { blob: new Blob(["changed"]) },
  ]) {
    await expect(
      removedCafFile({ ...copy(), ...changes }, () => true),
    ).rejects.toThrow(/identity or bytes changed/);
  }
});
test("handoff rechecks ownership before and after asynchronous hashing", async () => {
  expect(await removedCafFile(copy(), () => false)).toBeNull();
  let calls = 0;
  expect(await removedCafFile(copy(), () => ++calls === 1)).toBeNull();
  expect(calls).toBe(2);
});
test("bounded draft map clones occurrence bytes and never evicts original contexts", () => {
  const drafts: CafRemovalDrafts = new Map();
  const d = {
    archive: original.hash,
    diagram: "d0",
    index: 0,
    old: [0, 663, 2, 513],
    count: 2,
  };
  expect(rememberCafRemoval(drafts, d)).toBe(true);
  d.old[0] = 99;
  expect(drafts.get(cafRemovalKey(d.archive, "d0"))!.old[0]).toBe(0);
  for (let i = 1; i < 32; i++)
    expect(rememberCafRemoval(drafts, { ...d, diagram: `d${i}` })).toBe(true);
  expect(rememberCafRemoval(drafts, { ...d, diagram: "over" })).toBe(false);
  expect(drafts.size).toBe(32);
  expect(drafts.has(cafRemovalKey(d.archive, "d0"))).toBe(true);
  expect(rememberCafRemoval(drafts, { ...d, diagram: "d0", index: 1 })).toBe(
    true,
  );
});
test("export status belongs only to the exact CAF, diagram, index, tuple and count", () => {
  const d = {
    archive: original.hash,
    diagram: original.diagram.ref,
    index: 0,
    old: [0, 663, 2, 513],
    count: 2,
  };
  expect(cafRemovalDirty(d)).toBe(true);
  const saved = { ...d, saved: cafRemovalSignature(d) };
  expect(cafRemovalDirty(saved)).toBe(false);
  for (const changes of [
    { archive: "a".repeat(64) },
    { diagram: "other" },
    { index: 1 },
    { old: [1, 663, 2, 513] },
    { count: 3 },
  ])
    expect(cafRemovalDirty({ ...saved, ...changes })).toBe(true);
});
