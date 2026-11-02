import { test, expect } from "@playwright/test";
import {
  checkedNativeImport,
  nativeBackupImportProfile,
  nativeBackupImportScope,
  validNativeImportOrigin,
} from "../src/nativeBackupImport";

function fixture() {
  const origin = {
    profile: nativeBackupImportProfile,
    scope: nativeBackupImportScope,
    capture_id: "a".repeat(32),
    snapshot_sha256: "b".repeat(64),
    incoming_archive_sha256: "c".repeat(64),
    manifest_file_sha256: "d".repeat(64),
    evidence_sha256: "e".repeat(64),
    filename: "original.zip",
    imported_at: "2026-11-02",
  };
  const manifest = {
    profile: "native-application-transfer/1",
    id: origin.capture_id,
    evidence_sha256: origin.snapshot_sha256,
    target: { address: "3001:7", router: "192.0.2.5", dnet: 3001 },
    device: "device,42",
    captured_at: "2026-11-02",
    files: Object.fromEntries(
      [3, 11, 12].map((k) => [String(k), { bytes: 5, sha256: "f".repeat(64) }]),
    ),
  };
  return {
    profile: nativeBackupImportProfile,
    scope: nativeBackupImportScope,
    controller_queries: false,
    field_actions: false,
    authority_restored: false,
    created: true,
    resumed: false,
    already_present: false,
    incoming_archive_sha256: origin.incoming_archive_sha256,
    manifest_file_sha256: origin.manifest_file_sha256,
    capture_id: origin.capture_id,
    snapshot_sha256: origin.snapshot_sha256,
    manifest,
    local_import: origin,
  };
}

test("new, resumed and previously imported copies keep exact origin bindings", () => {
  for (const outcome of ["created", "resumed", "already_present"]) {
    const f = fixture(),
      value = {
        ...f,
        created: false,
        resumed: false,
        already_present: false,
        [outcome]: true,
      };
    expect(checkedNativeImport(value, f.incoming_archive_sha256)).toBe(value);
  }
});
test("identical preexisting local originals need no invented import provenance", () => {
  const f = fixture(),
    result = {
      ...f,
      created: false,
      already_present: true,
      local_import: null,
    };
  expect(checkedNativeImport(result, f.incoming_archive_sha256)).toBe(result);
  expect(() =>
    checkedNativeImport(
      { ...result, created: true, already_present: false },
      f.incoming_archive_sha256,
    ),
  ).toThrow();
});
test("changed response identity, archive, status and authority cannot announce a verified import", () => {
  const f = fixture();
  for (const patch of [
    { controller_queries: true },
    { field_actions: true },
    { authority_restored: true },
    { incoming_archive_sha256: "f".repeat(64) },
    { capture_id: "0".repeat(32) },
    { snapshot_sha256: "0".repeat(64) },
    { created: false },
    { resumed: true },
    { already_present: true },
    { scope: "other" },
    { local_import: undefined },
    { manifest: { ...f.manifest, device: "device,4194303" } },
    { manifest: { ...f.manifest, files: {} } },
    { local_import: { ...f.local_import, capture_id: "0".repeat(32) } },
  ])
    expect(() =>
      checkedNativeImport({ ...f, ...patch }, f.incoming_archive_sha256),
    ).toThrow("does not match");
});
test("catalog provenance belongs to its original ID and snapshot; importing an existing repacked ZIP keeps first provenance", () => {
  const f = fixture();
  expect(validNativeImportOrigin(f.local_import, f.manifest)).toBe(true);
  expect(
    validNativeImportOrigin(f.local_import, {
      ...f.manifest,
      evidence_sha256: "0".repeat(64),
    }),
  ).toBe(false);
  const repeated = {
    ...f,
    created: false,
    already_present: true,
    incoming_archive_sha256: "0".repeat(64),
    manifest_file_sha256: "1".repeat(64),
  };
  expect(checkedNativeImport(repeated, repeated.incoming_archive_sha256)).toBe(
    repeated,
  );
});
