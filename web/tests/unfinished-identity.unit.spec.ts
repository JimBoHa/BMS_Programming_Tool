import { test, expect } from "@playwright/test";
import {
  emptyIdentityWork,
  identityDraftDocument,
  rememberIdentityWork,
} from "../src/nativeIdentityWork";
import {
  identityDraftBlob,
  identityTextSha,
  importedIdentityText,
  parseIdentityText,
  sameIdentityTextContext,
  IDENTITY_TEXT_IMPORT,
  IDENTITY_TEXT_PROFILE,
} from "../src/unfinishedIdentity";

const iface = (epoch = 7, local_address = "192.0.2.1:47808") =>
  JSON.stringify({
    connected: false,
    config: { transport: "ip", local_address },
    epoch,
  });
const key = (kind = "name", epoch = 7) =>
  JSON.stringify([
    false,
    iface(epoch),
    "3001:7",
    "device,42",
    "192.0.2.5",
    3001,
    kind,
  ]);
async function fixture(kind = "name") {
  const source = {
    profile: "native-application-transfer/1",
    id: "a".repeat(32),
    captured_at: "2026-11-02T00:00:00+00:00",
    target: { address: "3001:7", router: "192.0.2.5", dnet: 3001 },
    device: "device,42",
    identity: {
      "object-name": "Authored source",
      "model-name": "Authored model",
    },
    files: Object.fromEntries(
      [3, 11, 12].map((id) => [
        String(id),
        { bytes: 5, sha256: "b".repeat(64) },
      ]),
    ),
  };
  const evidence = JSON.stringify(source),
    snapshot = await identityTextSha(new Blob([evidence]));
  const work = {
    ...emptyIdentityWork(),
    capture: {
      id: source.id,
      target: { ...source.target, device: source.device },
      snapshot_evidence_sha256: snapshot,
    },
    newName: "  unfinished 🌡  ",
    number: " 1e- ",
    receipt: { intent: { id: "c".repeat(32) } },
    recovery: {
      data: { origin_sha256: "d".repeat(64) },
      token: "must-not-export",
    },
  };
  const document = identityDraftDocument(key(kind), work),
    sha = "e".repeat(64);
  const response = {
    profile: IDENTITY_TEXT_IMPORT,
    document_profile: IDENTITY_TEXT_PROFILE,
    field_authority: false,
    controller_queries: false,
    capture_mutations: false,
    native_review_created: false,
    recovery_prepared: false,
    file_sha256: sha,
    document,
    source_evidence_text: evidence,
    local_source_verified: true,
  };
  return { source, work, document, sha, response };
}

test("name and instance raw text export preserves references without plans or credentials", async () => {
  for (const kind of ["name", "instance"]) {
    const f = await fixture(kind),
      before = JSON.stringify(f.work);
    const blob = identityDraftBlob(key(kind), f.work),
      parsed = parseIdentityText(await blob.text(), key(kind));
    expect(parsed.new_name).toBe(f.work.newName);
    expect(parsed.new_instance_text).toBe(f.work.number);
    expect(parsed.receipt_id).toBe("c".repeat(32));
    expect(JSON.stringify(parsed)).not.toContain("must-not-export");
    expect(JSON.stringify(f.work)).toBe(before);
  }
});
test("only a declared connection epoch is excluded from configuration matching", async () => {
  const { document } = await fixture();
  expect(sameIdentityTextContext(document.selection, key("name", 0))).toBe(
    true,
  );
  for (const [index, value] of [
    [0, true],
    [1, iface(0, "192.0.2.2:47808")],
    [2, "3001:8"],
    [3, "device,43"],
    [4, "192.0.2.6"],
    [5, 3002],
    [6, "instance"],
  ] as const) {
    const different = JSON.parse(key());
    different[index] = value;
    expect(
      sameIdentityTextContext(document.selection, JSON.stringify(different)),
    ).toBe(false);
  }
  for (const pair of [
    [
      '{"connected":false,"config":1,"epoch":7}',
      '{"connected":false,"config":1,"epoch":0}',
    ],
    [
      '{"connected":false,"config":{"x":9007199254740992},"epoch":7}',
      '{"connected":false,"config":{"x":9007199254740993},"epoch":0}',
    ],
    [
      '{"connected":false,"config":{"x":0},"epoch":7}',
      '{"connected":false,"config":{"x":1e-999},"epoch":0}',
    ],
    [
      '{"connected":false,"config":null,"epoch":7,"extra":1}',
      '{"connected":false,"config":null,"epoch":0,"extra":1}',
    ],
  ]) {
    const d = { ...document.selection, interface_identity: pair[0] },
      current = JSON.parse(key());
    current[1] = pair[1];
    expect(sameIdentityTextContext(d, JSON.stringify(current))).toBe(false);
  }
});
test("original source proof restores a capture reference and raw text without receipt or recovery authority", async () => {
  const f = await fixture(),
    restored = await importedIdentityText(
      f.response,
      f.document,
      key("name", 0),
      f.sha,
    );
  expect(restored.newName).toBe(f.work.newName);
  expect(restored.number).toBe(f.work.number);
  expect(restored.receipt).toBeNull();
  expect(restored.recovery).toBeNull();
  expect(restored.capture.id).toBe(f.document.capture_id);
  expect(restored.capture.snapshot_evidence_sha256).toBe(
    f.document.snapshot_sha256,
  );
  expect(restored.capture.controller_queries).toBe(false);
  restored.capture.target.address = "changed";
  expect(f.document.captured_target.address).toBe("3001:7");
});
test("substituted file, proposal, authority, source proof or context never restores a draft", async () => {
  const f = await fixture();
  for (const changed of [
    { ...f.response, file_sha256: "f".repeat(64) },
    { ...f.response, document: { ...f.document, new_name: "changed" } },
    { ...f.response, field_authority: true },
    { ...f.response, recovery_prepared: true },
    {
      ...f.response,
      source_evidence_text: f.response.source_evidence_text + " ",
    },
    { ...f.response, source_evidence_text: null },
  ])
    await expect(
      importedIdentityText(changed, f.document, key(), f.sha),
    ).rejects.toThrow();
  await expect(
    importedIdentityText(f.response, f.document, key("instance"), f.sha),
  ).rejects.toThrow("exact file and context");
});
test("provenance survives export and copy isolation under the existing32-context capacity", async () => {
  const f = await fixture(),
    drafts = new Map(),
    work = {
      ...f.work,
      rawImported: {
        filename: "old.json",
        file_sha256: "f".repeat(64),
        receipt_id: "c".repeat(32),
        recovery_origin_sha256: "d".repeat(64),
      },
    };
  rememberIdentityWork(drafts, key(), work);
  work.rawImported.filename = "changed";
  expect(drafts.get(key()).rawImported.filename).toBe("old.json");
  const doc = JSON.parse(
    await identityDraftBlob(key(), drafts.get(key())).text(),
  );
  expect(doc.raw_imported.filename).toBe("old.json");
  for (let i = 1; i < 32; i++)
    rememberIdentityWork(drafts, String(i), {
      ...emptyIdentityWork(),
      number: "1e-",
    });
  const before = JSON.stringify([...drafts]);
  expect(
    rememberIdentityWork(drafts, "33", {
      ...emptyIdentityWork(),
      newName: "new",
    }),
  ).toBe(false);
  expect(JSON.stringify([...drafts])).toBe(before);
});
test("source-less text has no fabricated capture and strict file bounds preserve existing work", async () => {
  const f = await fixture(),
    doc = {
      ...f.document,
      capture_id: null,
      captured_target: null,
      snapshot_sha256: null,
    };
  const response = {
    ...f.response,
    document: doc,
    source_evidence_text: null,
    local_source_verified: false,
  };
  expect(
    (await importedIdentityText(response, doc, key(), f.sha)).capture,
  ).toBeNull();
  expect(() => parseIdentityText('{"profile":1,"profile":2}', key())).toThrow(
    "Duplicate",
  );
  const work = { ...f.work, newName: "🌡".repeat(65) };
  expect(() => identityDraftBlob(key(), work)).toThrow("raw file limits");
  expect(() =>
    identityDraftBlob(key(), { ...f.work, number: "\x00".repeat(65536) }),
  ).toThrow("128 KiB");
});
