import { test, expect } from "@playwright/test";
import {
  createdCafFile,
  creationHintFor,
  type CreatedCafCopy,
} from "../src/cafCreatedCopy";
import { sha256Blob } from "../src/activityContracts";
async function copy(): Promise<CreatedCafCopy> {
  const blob = new Blob(["authored opaque copy bytes"]);
  return {
    blob,
    name: "authored-copy.caf",
    sha256: await sha256Blob(blob),
    sourceArchive: "a".repeat(64),
    diagram: "source/536_4",
    prototype: "source/536_4.551_31",
    kind: "float",
  };
}
test("exact immutable bytes and typed location become a File without a field action", async () => {
  const c = await copy(),
    file = await createdCafFile(c, () => true);
  expect(file?.name).toBe(c.name);
  expect(await sha256Blob(file!)).toBe(c.sha256);
  expect(await file!.text()).toBe(await c.blob.text());
});
for (const [name, change] of Object.entries({
  digest: (c: any) => (c.sha256 = "0".repeat(64)),
  source: (c: any) => (c.sourceArchive = "not-a-hash"),
  name: (c: any) => (c.name = "unsafe/name.caf"),
  extension: (c: any) => (c.name = "program.exe"),
  prototype: (c: any) => (c.prototype = "source/536_4.562_31"),
  instance: (c: any) => (c.prototype = "source/536_4.551_4194303"),
  kind: (c: any) => (c.kind = "constructor"),
  bytes: (c: any) => (c.blob = new Blob(["changed"])),
}))
  test(`handoff rejects changed ${name}`, async () => {
    const c = await copy();
    change(c);
    await expect(createdCafFile(c, () => true)).rejects.toThrow(/CAF copy/);
  });
test("retired ownership before or during hashing cannot produce a File", async () => {
  const c = await copy();
  expect(await createdCafFile(c, () => false)).toBeNull();
  let checks = 0;
  expect(await createdCafFile(c, () => ++checks === 1)).toBeNull();
  expect(checks).toBe(2);
});
test("Unicode references retain codepoint bounds at handoff", async () => {
  const c = await copy();
  c.diagram = "source/" + "😀".repeat(400) + "/536_4";
  c.prototype = c.diagram + ".551_31";
  expect(c.prototype.length).toBeGreaterThan(512);
  expect(await createdCafFile(c, () => true)).not.toBeNull();
});
test("a hint is preferred only when its actual source, diagram, class and version match", async () => {
  const hint = {
    archive: "b".repeat(64),
    diagram: "source/536_4",
    prototype: "source/536_4.551_31",
    kind: "float" as const,
  };
  const diagram = {
    ref: hint.diagram,
    blocks: [{ ref: hint.prototype, class_id: "551", class_version: "1.0" }],
  };
  expect(creationHintFor(hint, hint.archive, diagram)).toEqual(hint);
  for (const changed of [
    { ...hint, archive: "c".repeat(64) },
    { ...hint, diagram: "other" },
    { ...hint, prototype: "missing" },
    { ...hint, kind: "boolean" as const },
  ])
    expect(creationHintFor(changed, hint.archive, diagram)).toBeNull();
  expect(
    creationHintFor(hint, hint.archive, {
      ...diagram,
      blocks: [{ ...diagram.blocks[0], class_version: "2.0" }],
    }),
  ).toBeNull();
  expect(creationHintFor(null, hint.archive, diagram)).toBeNull();
});
