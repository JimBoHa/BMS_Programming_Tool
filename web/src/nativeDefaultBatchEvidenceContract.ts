import { sha256Blob } from "./activityContracts";
import { connectionSame as same } from "./nativeConnectionContract";
import { batchRecoveryOriginJSON } from "./nativeDefaultBatchRecoveryContract";
import {
  batchResultMatchProfile,
  batchResultMatchScope,
} from "./nativeDefaultBatchResultMatchContract";
type Data = Record<string, any>;
export const batchEvidenceProfile = "native-default-batch-evidence-bundle/1";
export const batchEvidenceHeader = "X-Native-Batch-Evidence";
export const batchEvidenceBase =
  "/bacnet/controller/native-application/default-batch/result/evidence";
export const batchEvidenceScope =
  "Local export of retained Files3/11/12, original typed-batch intent, selected immutable verification proof and comparison. Not a complete journal or controller backup, import, executable application, recovery or field authority.";
export const batchEvidenceLimit = 20 * 1024 * 1024;
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const falseFlags = [
  "field_actions",
  "can_apply",
  "current_device_verified",
  "credentials_restored",
  "reviews_restored",
  "complete_controller_backup",
  "complete_journal",
];
const crcTable = Uint32Array.from({ length: 256 }, (_, n) => {
  for (let i = 0; i < 8; i++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
  return n >>> 0;
});
const crc = (bytes: Uint8Array) => {
  let c = 0xffffffff;
  for (const b of bytes) c = crcTable[(c ^ b) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};

async function storedMembers(blob: Blob, count: number) {
  const bytes = new Uint8Array(await blob.arrayBuffer()),
    view = new DataView(bytes.buffer),
    entries = new Map<string, Data>();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let offset = 0;
  while (
    offset + 30 <= bytes.length &&
    view.getUint32(offset, true) === 0x04034b50
  ) {
    if (
      entries.size >= count ||
      view.getUint16(offset + 6, true) !== 0 ||
      view.getUint16(offset + 8, true) !== 0
    )
      throw Error("Unsupported evidence ZIP member.");
    const size = view.getUint32(offset + 18, true),
      nameSize = view.getUint16(offset + 26, true),
      extra = view.getUint16(offset + 28, true);
    if (
      size !== view.getUint32(offset + 22, true) ||
      extra !== 0 ||
      !nameSize ||
      nameSize > 128 ||
      offset + 30 + nameSize + size > bytes.length
    )
      throw Error("Invalid evidence ZIP member bounds.");
    if (
      bytes
        .subarray(offset + 30, offset + 30 + nameSize)
        .some((b) => b < 32 || b > 126)
    )
      throw Error("Evidence ZIP names must use the documented ASCII paths.");
    const name = decoder.decode(
        bytes.subarray(offset + 30, offset + 30 + nameSize),
      ),
      start = offset + 30 + nameSize,
      content = bytes.subarray(start, start + size),
      checksum = view.getUint32(offset + 14, true);
    if (entries.has(name) || crc(content) !== checksum)
      throw Error("Duplicate or damaged evidence ZIP member.");
    entries.set(name, { content, offset, size, checksum });
    offset = start + size;
  }
  const directory = offset;
  for (const [name, entry] of entries) {
    if (
      offset + 46 > bytes.length ||
      view.getUint32(offset, true) !== 0x02014b50
    )
      throw Error("Missing evidence ZIP directory.");
    const nameSize = view.getUint16(offset + 28, true),
      extra = view.getUint16(offset + 30, true),
      comment = view.getUint16(offset + 32, true),
      attributes = view.getUint32(offset + 38, true),
      type = (attributes >>> 16) & 0o170000;
    if (
      offset + 46 + nameSize > bytes.length ||
      extra ||
      comment ||
      view.getUint16(offset + 8, true) !== 0 ||
      view.getUint16(offset + 10, true) !== 0 ||
      view.getUint16(offset + 34, true) !== 0 ||
      view.getUint32(offset + 16, true) !== entry.checksum ||
      view.getUint32(offset + 20, true) !== entry.size ||
      view.getUint32(offset + 24, true) !== entry.size ||
      view.getUint32(offset + 42, true) !== entry.offset ||
      (attributes & 16) !== 0 ||
      ![0, 0o100000].includes(type) ||
      decoder.decode(bytes.subarray(offset + 46, offset + 46 + nameSize)) !==
        name
    )
      throw Error("Inconsistent evidence ZIP directory.");
    offset += 46 + nameSize;
  }
  if (
    entries.size !== count ||
    offset + 22 !== bytes.length ||
    view.getUint32(offset, true) !== 0x06054b50 ||
    view.getUint16(offset + 4, true) !== 0 ||
    view.getUint16(offset + 6, true) !== 0 ||
    view.getUint16(offset + 8, true) !== count ||
    view.getUint16(offset + 10, true) !== count ||
    view.getUint32(offset + 12, true) !== offset - directory ||
    view.getUint32(offset + 16, true) !== directory ||
    view.getUint16(offset + 20, true) !== 0
  )
    throw Error("Invalid evidence ZIP boundary.");
  return entries;
}

async function checkedProofBytes(bytes: Uint8Array, expected: string) {
  const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    value = JSON.parse(raw);
  if (
    !raw.startsWith("{") ||
    !raw.endsWith("}") ||
    value.evidence_sha256 !== expected
  )
    return false;
  const parts: [string, string][] = [];
  let depth = 0,
    quoted = false,
    escaped = false,
    start = 1;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') quoted = false;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === "{" || ch === "[") depth++;
    else if (ch === "}" || ch === "]") depth--;
    if ((ch === "," && depth === 1) || (ch === "}" && depth === 0)) {
      const part = raw.slice(start, i),
        match = part.match(/^("(?:[^"\\]|\\.)*"):/);
      if (!match) return false;
      parts.push([JSON.parse(match[1]), part]);
      start = i + 1;
      if (depth === 0 && i !== raw.length - 1) return false;
    }
  }
  if (
    new Set(parts.map(([key]) => key)).size !== parts.length ||
    parts.filter(([key]) => key === "evidence_sha256").length !== 1
  )
    return false;
  // Stored intent/proof JSON is canonical Python JSON. Keep numeric atoms intact,
  // including float32 renderings and signed zero, when removing the outer seal.
  const body =
    "{" +
    parts
      .filter(([key]) => key !== "evidence_sha256")
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([, part]) => part)
      .join(",") +
    "}";
  return (await sha256Blob(new Blob([body]))) === expected;
}

export async function batchEvidenceDocument(
  blob: Blob,
  header: string | null,
  report: Data,
): Promise<Data | null> {
  try {
    if (
      !header ||
      header.length > 4096 ||
      blob.type !== "application/zip" ||
      blob.size < 66 ||
      blob.size > batchEvidenceLimit ||
      report.profile !== batchResultMatchProfile ||
      report.scope !== batchResultMatchScope ||
      report.read_only !== true ||
      [
        "controller_queries",
        "field_actions",
        "can_apply",
        "field_transfer_enabled",
        "current_device_verified",
        "parent_revalidated",
        "enum_semantics_verified",
      ].some((k) => report[k] !== false)
    )
      return null;
    const v = JSON.parse(header),
      captureIds = [
        ...new Set([report.original_backup_id, report.source.capture_id]),
      ];
    if (
      !exact(v, [
        "profile",
        "scope",
        "receipt_id",
        "comparison_sha256",
        "comparison_state",
        "original_backup_id",
        "current_capture_id",
        "proof_sha256",
        "manifest_sha256",
        "bundle_sha256",
        "bytes",
        "capture_count",
        "member_count",
        "read_only",
        ...falseFlags,
      ]) ||
      v.profile !== batchEvidenceProfile ||
      v.scope !== batchEvidenceScope ||
      v.read_only !== true ||
      falseFlags.some((k) => v[k] !== false) ||
      !id(v.receipt_id) ||
      v.receipt_id !== report.receipt_id ||
      !hash(v.comparison_sha256) ||
      v.comparison_sha256 !== report.evidence_sha256 ||
      !["application-and-values-match", "different"].includes(
        v.comparison_state,
      ) ||
      v.comparison_state !== report.state ||
      !captureIds.every(id) ||
      v.original_backup_id !== report.original_backup_id ||
      v.current_capture_id !== report.source.capture_id ||
      v.proof_sha256 !== report.verified_proof.sha256 ||
      ![v.proof_sha256, v.manifest_sha256, v.bundle_sha256].every(hash) ||
      v.bytes !== blob.size ||
      !Number.isSafeInteger(v.bytes) ||
      v.capture_count !== captureIds.length ||
      v.member_count !== captureIds.length + 4 ||
      (report.original_backup_id === report.source.capture_id &&
        report.original_snapshot_sha256 !== report.source.snapshot_sha256) ||
      (await sha256Blob(blob)) !== v.bundle_sha256
    )
      return null;
    const entries = await storedMembers(blob, v.member_count),
      names = [
        "manifest.json",
        "intent.json",
        "proof.json",
        "comparison.json",
        ...captureIds.map((id) => `captures/${id}.zip`),
      ];
    if (entries.size !== names.length || names.some((n) => !entries.has(n)))
      return null;
    const manifestBytes = entries.get("manifest.json")!.content as Uint8Array;
    if (
      manifestBytes.length > 64 * 1024 ||
      (await sha256Blob(new Blob([Uint8Array.from(manifestBytes)]))) !==
        v.manifest_sha256
    )
      return null;
    const manifest = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(manifestBytes),
    );
    if (
      !exact(manifest, [
        "profile",
        "scope",
        "receipt_id",
        "intent_sha256",
        "verified_proof",
        "comparison_sha256",
        "comparison_state",
        "original_backup_id",
        "current_capture_id",
        "captures",
        "members",
        "read_only",
        "controller_queries",
        "field_transfer_enabled",
        ...falseFlags,
        "evidence_sha256",
      ]) ||
      manifest.profile !== batchEvidenceProfile ||
      manifest.scope !== batchEvidenceScope ||
      manifest.read_only !== true ||
      falseFlags.some((k) => manifest[k] !== false) ||
      manifest.controller_queries !== false ||
      manifest.field_transfer_enabled !== false ||
      manifest.receipt_id !== report.receipt_id ||
      manifest.intent_sha256 !== report.intent_sha256 ||
      !same(manifest.verified_proof, report.verified_proof) ||
      manifest.comparison_sha256 !== report.evidence_sha256 ||
      manifest.comparison_state !== report.state ||
      manifest.original_backup_id !== report.original_backup_id ||
      manifest.current_capture_id !== report.source.capture_id ||
      !same(manifest.captures, {
        [report.original_backup_id]: report.original_snapshot_sha256,
        [report.source.capture_id]: report.source.snapshot_sha256,
      }) ||
      !exact(
        manifest.members,
        names.filter((n) => n !== "manifest.json"),
      ) ||
      !hash(manifest.evidence_sha256)
    )
      return null;
    const body = { ...manifest };
    delete body.evidence_sha256;
    if (
      (await sha256Blob(new Blob([batchRecoveryOriginJSON(body)]))) !==
      manifest.evidence_sha256
    )
      return null;
    for (const [name, detail] of Object.entries(manifest.members) as [
      string,
      Data,
    ][]) {
      const entry = entries.get(name)!,
        limit = name.startsWith("captures/")
          ? 8 * 1024 * 1024
          : name === "comparison.json"
            ? 512 * 1024
            : 128 * 1024;
      if (
        !exact(detail, ["bytes", "sha256"]) ||
        detail.bytes !== entry.size ||
        !Number.isSafeInteger(detail.bytes) ||
        detail.bytes < 1 ||
        detail.bytes > limit ||
        !hash(detail.sha256) ||
        (await sha256Blob(new Blob([Uint8Array.from(entry.content)]))) !==
          detail.sha256
      )
        return null;
    }
    const parse = (name: string) =>
      JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(
          entries.get(name)!.content,
        ),
      );
    const intent = parse("intent.json"),
      proof = parse("proof.json"),
      comparison = parse("comparison.json");
    if (
      intent.id !== report.receipt_id ||
      intent.evidence_sha256 !== report.intent_sha256 ||
      intent.backup_id !== report.original_backup_id ||
      intent.native_payload_sha256 !== report.expected_native_sha256 ||
      !same(intent.identity, report.recorded_identity) ||
      !same(intent.target, report.recorded_target) ||
      proof.evidence_sha256 !== report.verified_proof.sha256 ||
      !same(comparison, report)
    )
      return null;
    if (
      !(await checkedProofBytes(
        entries.get("intent.json")!.content,
        report.intent_sha256,
      )) ||
      !(await checkedProofBytes(
        entries.get("proof.json")!.content,
        report.verified_proof.sha256,
      ))
    )
      return null;
    return v;
  } catch {
    return null;
  }
}
