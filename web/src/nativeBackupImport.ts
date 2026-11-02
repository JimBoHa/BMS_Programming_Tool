/** Portable original files are historical evidence, never renewed field authority. */
export const nativeBackupImportProfile = "native-backup-import/1";
export const nativeBackupImportLimit = 8 * 1024 * 1024;
export const nativeBackupImportScope =
  "Local original-file import only. Imported metadata describes historical evidence, " +
  "not a responding controller, current settings, compatible compilation or transfer authority. " +
  "No receipt, review, confirmation, credential or prepared recovery is restored.";
const hash = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const id = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{32}$/.test(value);

export function validNativeImportOrigin(value: any, capture: any) {
  return (
    value?.profile === nativeBackupImportProfile &&
    value.scope === nativeBackupImportScope &&
    id(value.capture_id) &&
    value.capture_id === capture?.id &&
    hash(value.snapshot_sha256) &&
    value.snapshot_sha256 === capture?.evidence_sha256 &&
    hash(value.incoming_archive_sha256) &&
    hash(value.manifest_file_sha256) &&
    hash(value.evidence_sha256) &&
    typeof value.filename === "string" &&
    value.filename.length > 0 &&
    value.filename.length <= 1024 &&
    typeof value.imported_at === "string" &&
    value.imported_at.length > 0 &&
    value.imported_at.length <= 64
  );
}

export function checkedNativeImport(result: any, incoming: string) {
  const manifest = result?.manifest;
  if (
    result?.profile !== nativeBackupImportProfile ||
    result.controller_queries !== false ||
    result.field_actions !== false ||
    result.authority_restored !== false ||
    result.scope !== nativeBackupImportScope ||
    !hash(incoming) ||
    result.incoming_archive_sha256 !== incoming ||
    !hash(result.manifest_file_sha256) ||
    ![result.created, result.resumed, result.already_present].every(
      (v) => typeof v === "boolean",
    ) ||
    [result.created, result.resumed, result.already_present].filter(Boolean)
      .length !== 1 ||
    !id(result.capture_id) ||
    !hash(result.snapshot_sha256) ||
    manifest?.id !== result.capture_id ||
    manifest.evidence_sha256 !== result.snapshot_sha256 ||
    manifest.profile !== "native-application-transfer/1" ||
    typeof manifest.target?.address !== "string" ||
    !manifest.target.address ||
    typeof manifest.device !== "string" ||
    !/^device,(0|[1-9][0-9]*)$/.test(manifest.device) ||
    Number(manifest.device.split(",")[1]) > 4194302 ||
    typeof manifest.captured_at !== "string" ||
    !manifest.files ||
    Object.keys(manifest.files).sort().join(",") !== "11,12,3" ||
    !["3", "11", "12"].every(
      (k) =>
        hash(manifest.files[k]?.sha256) &&
        Number.isInteger(manifest.files[k]?.bytes) &&
        manifest.files[k].bytes > 0 &&
        manifest.files[k].bytes <= 2097152,
    ) ||
    (result.local_import !== null &&
      !validNativeImportOrigin(result.local_import, manifest)) ||
    ((result.created || result.resumed) &&
      (result.local_import?.incoming_archive_sha256 !== incoming ||
        result.local_import?.manifest_file_sha256 !==
          result.manifest_file_sha256))
  )
    throw new Error(
      "Import response does not match this ZIP. Refresh the catalog and inspect original evidence before retrying.",
    );
  return result;
}

export async function nativeArchiveHash(file: File) {
  if (
    !file.size ||
    file.size > nativeBackupImportLimit ||
    !file.name ||
    file.name.length > 1024
  )
    throw new Error(
      "Choose an original native backup ZIP between 1 byte and 8 MiB with a bounded filename.",
    );
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
    ),
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}
