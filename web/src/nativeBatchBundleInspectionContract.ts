import { sha256Blob } from "./activityContracts";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import {
  batchEvidenceDocument,
  batchEvidenceLimit,
  batchEvidenceProfile,
  batchEvidenceScope,
  batchEvidenceStoredMembers,
} from "./nativeDefaultBatchEvidenceContract";
import { batchRecoveryOriginJSON } from "./nativeDefaultBatchRecoveryContract";

type Data = Record<string, any>;
export const bundleInspectionProfile =
  "native-default-batch-bundle-inspection/1";
export const bundleInspectionBase =
  "/bacnet/controller/native-application/default-batch/result/inspect-evidence";
export const bundleInspectionScope =
  "In-memory inspection of one portable typed-batch evidence bundle. Internal byte, proof and reconstructed-comparison consistency only; hashes are not signatures or vendor provenance. Historical bundled evidence is not a current controller, complete backup or journal, imported receipt, review, recovery or transfer authority.";
const falseFlags = [
  "controller_queries",
  "field_actions",
  "can_apply",
  "field_transfer_enabled",
  "current_device_verified",
  "credentials_restored",
  "reviews_restored",
  "complete_controller_backup",
  "complete_journal",
];
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export type CheckedBatchBundle = {
  data: Data;
  members: Map<string, Data>;
};

/** Bind server reconstruction to this exact local file and its original contents. */
export async function checkedBatchBundle(
  value: Data,
  file: Blob,
): Promise<CheckedBatchBundle | null> {
  try {
    if (
      !exact(value, [
        "profile",
        "scope",
        "bundle_sha256",
        "bundle_bytes",
        "manifest_sha256",
        "manifest",
        "comparison",
        "members",
        "capture_count",
        "internal_consistency_verified",
        "native_result_reconstructed",
        "read_only",
        "storage_imported",
        "receipt_restored",
        "vendor_provenance_verified",
        ...falseFlags,
        "inspection_sha256",
      ]) ||
      value.profile !== bundleInspectionProfile ||
      value.scope !== bundleInspectionScope ||
      value.read_only !== true ||
      value.internal_consistency_verified !== true ||
      value.native_result_reconstructed !== true ||
      [
        ...falseFlags,
        "storage_imported",
        "receipt_restored",
        "vendor_provenance_verified",
      ].some((k) => value[k] !== false) ||
      file.size < 66 ||
      file.size > batchEvidenceLimit ||
      value.bundle_bytes !== file.size ||
      !Number.isSafeInteger(value.bundle_bytes) ||
      ![
        value.bundle_sha256,
        value.manifest_sha256,
        value.inspection_sha256,
      ].every(hash) ||
      ![1, 2].includes(value.capture_count) ||
      !Array.isArray(value.members) ||
      value.members.length !== value.capture_count + 4 ||
      (await sha256Blob(file)) !== value.bundle_sha256
    )
      return null;
    const { inspection_sha256: _, ...body } = value;
    if ((await connectionSeal(body)) !== value.inspection_sha256) return null;
    const manifest = value.manifest,
      report = value.comparison;
    if (
      !manifest ||
      !report ||
      manifest.profile !== batchEvidenceProfile ||
      manifest.scope !== batchEvidenceScope ||
      !hash(report.evidence_sha256)
    )
      return null;
    const { evidence_sha256: comparisonHash, ...comparisonBody } = report;
    if (
      (await sha256Blob(
        new Blob([batchRecoveryOriginJSON(comparisonBody)]),
      )) !== comparisonHash
    )
      return null;
    // File MIME is operating-system supplied. Normalize only the Blob descriptor;
    // every original byte and its digest remain unchanged.
    const archive = new Blob([file], { type: "application/zip" });
    const metadata = {
      profile: batchEvidenceProfile,
      scope: batchEvidenceScope,
      receipt_id: manifest.receipt_id,
      comparison_sha256: manifest.comparison_sha256,
      comparison_state: manifest.comparison_state,
      original_backup_id: manifest.original_backup_id,
      current_capture_id: manifest.current_capture_id,
      proof_sha256: manifest.verified_proof?.sha256,
      manifest_sha256: value.manifest_sha256,
      bundle_sha256: value.bundle_sha256,
      bytes: file.size,
      capture_count: value.capture_count,
      member_count: value.members.length,
      read_only: true,
      ...Object.fromEntries(
        falseFlags
          .filter(
            (k) =>
              !["controller_queries", "field_transfer_enabled"].includes(k),
          )
          .map((k) => [k, false]),
      ),
    };
    if (
      !(await batchEvidenceDocument(archive, JSON.stringify(metadata), report))
    )
      return null;
    const members = await batchEvidenceStoredMembers(
      archive,
      value.members.length,
    );
    const actualManifest = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(
        members.get("manifest.json")!.content,
      ),
    );
    if (!same(actualManifest, manifest)) return null;
    const expected = [];
    for (const [name, entry] of [...members].sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    ))
      expected.push({
        name,
        bytes: entry.size,
        sha256: await sha256Blob(new Blob([Uint8Array.from(entry.content)])),
      });
    if (!same(value.members, expected)) return null;
    return { data: value, members };
  } catch {
    return null;
  }
}
