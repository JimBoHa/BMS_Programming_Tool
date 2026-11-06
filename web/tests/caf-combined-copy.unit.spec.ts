import { test, expect } from "@playwright/test";
import {
  combinedSource,
  combinedReview,
  combinedExport,
  combinedCafFile,
} from "../src/cafCombinedCopyContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import { combinedFixture } from "./caf-combined-copy-fixture";
async function reseal(v: any, key: string) {
  const { [key]: _, ...body } = v;
  return { ...body, [key]: await connectionSeal(body) };
}
for (const kind of ["rewire", "connect"])
  for (const enumValue of [false, true])
    test(`combined ${kind} ${enumValue ? "Enum" : "Float"} actual backend evidence and artifact agree`, async () => {
      const f = combinedFixture(kind, enumValue);
      expect(await combinedSource(f.source, f.request, f.diagram)).toBe(true);
      expect(
        await combinedReview(f.review, f.previewRequest, f.source, f.diagram),
      ).toBe(true);
      expect(
        await combinedExport(
          {
            blob: new Blob([Buffer.from(f.output, "base64")]),
            headers: new Headers(f.headers),
          },
          f.review,
        ),
      ).toBe(true);
    });
test("unchanged combined copy admits the exact original hash through a separate handoff", async () => {
  const f = combinedFixture("rewire", false, true);
  expect(
    await combinedReview(f.review, f.previewRequest, f.source, f.diagram),
  ).toBe(true);
  const copy = {
    blob: new Blob([Buffer.from(f.output, "base64")]),
    name: "unchanged.caf",
    sha256: f.hash,
    sourceArchive: f.hash,
    diagram: f.diagram.ref,
    selectionSha256: f.source.selection_sha256,
    reviewSha256: f.review.review_sha256,
    unchanged: true,
  };
  expect((await combinedCafFile(copy, () => true))?.name).toBe("unchanged.caf");
  await expect(
    combinedCafFile({ ...copy, unchanged: false }, () => true),
  ).rejects.toThrow("identity");
  expect(await combinedCafFile(copy, () => false)).toBeNull();
});
for (const name of [
  "raw-order",
  "raw-spelling",
  "wire-tuple",
  "authority",
  "unknown",
])
  test(`source refuses resealed ${name} substitution`, async () => {
    const f = combinedFixture(),
      s = structuredClone(f.source);
    if (name === "raw-order") s.request.changes.reverse();
    if (name === "raw-spelling") s.request.changes[0].value = "12.5";
    if (name === "wire-tuple") s.wiring_report[0].new[0] = 0;
    if (name === "authority") s.can_apply = true;
    if (name === "unknown") s.compiler = true;
    expect(
      await combinedSource(
        await reseal(s, "selection_sha256"),
        f.request,
        f.diagram,
      ),
    ).toBe(false);
  });
for (const name of [
  "count",
  "scalar-raw",
  "intermediate",
  "field-authority",
  "unknown",
  "wiring-chain",
])
  test(`review refuses internally resealed ${name} mismatch`, async () => {
    const f = combinedFixture(),
      v = structuredClone(f.review),
      r = v.result;
    if (name === "count") r.actual_scalar_change_count = 0;
    if (name === "scalar-raw") r.scalar_changes[0].value = "12.5";
    if (name === "intermediate")
      r.orders.scalar_then_wiring.intermediate_sha256 = "a".repeat(64);
    if (name === "field-authority") r.can_apply = true;
    if (name === "unknown") r.writer = true;
    if (name === "wiring-chain")
      r.orders.wiring_then_scalar.intermediate_sha256 = "a".repeat(64);
    v.result = await reseal(r, "combined_sha256");
    expect(
      await combinedReview(
        await reseal(v, "review_sha256"),
        f.previewRequest,
        f.source,
        f.diagram,
      ),
    ).toBe(false);
  });
test("artifact hash, every proof header and immutable handoff bytes are required", async () => {
  const f = combinedFixture(),
    blob = new Blob([Buffer.from(f.output, "base64")]);
  for (const key of Object.keys(f.headers)) {
    const headers = new Headers(f.headers);
    headers.set(key, "a".repeat(64));
    expect(await combinedExport({ blob, headers }, f.review)).toBe(false);
  }
  expect(
    await combinedExport(
      { blob: new Blob(["altered"]), headers: new Headers(f.headers) },
      f.review,
    ),
  ).toBe(false);
  const copy = {
    blob: new Blob(["altered"]),
    name: "copy.caf",
    sha256: f.review.result.output_sha256,
    sourceArchive: f.hash,
    diagram: f.diagram.ref,
    selectionSha256: f.source.selection_sha256,
    reviewSha256: f.review.review_sha256,
    unchanged: false,
  };
  await expect(combinedCafFile(copy, () => true)).rejects.toThrow(
    "bytes changed",
  );
});
