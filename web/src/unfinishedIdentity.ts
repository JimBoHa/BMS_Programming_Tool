import { parseSourceJSON, isSourceNumber, sourceEqual } from "./programSource";
import { ordered } from "./nativeCalendar";
import {
  emptyIdentityWork,
  identityDraftDocument,
  type NativeIdentityWork,
} from "./nativeIdentityWork";

export const IDENTITY_TEXT_BYTES = 128 * 1024;
export const IDENTITY_TEXT_RESPONSE_BYTES = 512 * 1024;
export const IDENTITY_TEXT_PROFILE = "native-identity-local-draft/1";
export const IDENTITY_TEXT_IMPORT = "native-identity-local-draft-import/1";
const object = (v: any, required: string[], optional: string[] = []) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  required.every((k) => Object.hasOwn(v, k)) &&
  Object.keys(v).every((k) => required.includes(k) || optional.includes(k));
const text = (v: any, maximum: number, nonempty = false) =>
  typeof v === "string" &&
  v.length <= maximum &&
  (!nonempty || !!v) &&
  !/[\uD800-\uDFFF]/u.test(v);
const ref = (v: any, length: number) =>
  v === null ||
  (typeof v === "string" && new RegExp(`^[a-f0-9]{${length}}$`).test(v));
const network = (v: any) =>
  v === null || (Number.isInteger(v) && v >= 0 && v <= 65535);
const target = (v: any) =>
  object(v, ["address", "router", "dnet"], ["device"]) &&
  text(v.address, 1024, true) &&
  (v.router === null || text(v.router, 1024, true)) &&
  network(v.dnet) &&
  (v.device === undefined || text(v.device, 256, true));

export function identityTextDocument(value: any) {
  if (
    !object(
      value,
      [
        "profile",
        "field_authority",
        "selection",
        "new_name",
        "new_instance_text",
        "capture_id",
        "captured_target",
        "snapshot_sha256",
        "receipt_id",
        "recovery_origin_sha256",
      ],
      ["raw_imported"],
    ) ||
    value.profile !== IDENTITY_TEXT_PROFILE ||
    value.field_authority !== false ||
    !object(value.selection, [
      "connected_context",
      "interface_identity",
      "address",
      "device",
      "router",
      "dnet",
      "change_kind",
    ]) ||
    typeof value.selection.connected_context !== "boolean" ||
    !["name", "instance"].includes(value.selection.change_kind) ||
    !text(value.selection.interface_identity, 16384) ||
    !text(value.selection.address, 1024) ||
    !text(value.selection.device, 256) ||
    !(
      value.selection.router === null ||
      text(value.selection.router, 1024, true)
    ) ||
    !network(value.selection.dnet) ||
    !text(value.new_name, 128) ||
    !text(value.new_instance_text, 65536) ||
    !ref(value.capture_id, 32) ||
    !ref(value.snapshot_sha256, 64) ||
    !ref(value.receipt_id, 32) ||
    !ref(value.recovery_origin_sha256, 64) ||
    (value.capture_id === null
      ? value.captured_target !== null || value.snapshot_sha256 !== null
      : value.snapshot_sha256 === null || !target(value.captured_target)) ||
    (value.raw_imported !== undefined &&
      (!object(value.raw_imported, ["filename", "file_sha256"]) ||
        !text(value.raw_imported.filename, 1024, true) ||
        value.raw_imported.file_sha256 === null ||
        !ref(value.raw_imported.file_sha256, 64)))
  )
    throw new Error(
      "Local identity draft has unknown fields or exceeds its raw file limits.",
    );
  return structuredClone(value);
}

// Only this application's declared transient connection epoch is excluded from
// cross-session text matching. Every interface configuration field remains bound.
function interfaceConfiguration(value: string): unknown {
  try {
    const data = parseSourceJSON(value);
    if (
      !object(data, ["connected", "config", "epoch"]) ||
      typeof data.connected !== "boolean" ||
      !isSourceNumber(data.epoch) ||
      !/^(0|[1-9][0-9]*)$/.test(data.epoch.token) ||
      !Number.isSafeInteger(Number(data.epoch.token)) ||
      !(
        data.config === null ||
        (typeof data.config === "object" &&
          !Array.isArray(data.config) &&
          !isSourceNumber(data.config))
      )
    )
      return value;
    return { connected: data.connected, config: data.config };
  } catch {
    return value;
  }
}
export function sameIdentityTextContext(value: any, key: string) {
  const current = identityDraftDocument(key, emptyIdentityWork()).selection;
  return sourceEqual(
    {
      ...value,
      interface_identity: interfaceConfiguration(value.interface_identity),
    },
    {
      ...current,
      interface_identity: interfaceConfiguration(current.interface_identity),
    },
  );
}
export function parseIdentityText(source: string, key: string) {
  parseSourceJSON(source);
  const document = identityTextDocument(JSON.parse(source));
  if (!sameIdentityTextContext(document.selection, key))
    throw new Error(
      "Select the same interface configuration, route, Device and name/instance context before importing this local draft.",
    );
  return document;
}
export function identityDraftBlob(key: string, work: NativeIdentityWork) {
  const value = identityTextDocument(identityDraftDocument(key, work));
  const blob = new Blob([JSON.stringify(value, null, 2) + "\n"], {
    type: "application/json",
  });
  if (blob.size > IDENTITY_TEXT_BYTES)
    throw new Error(
      "Local identity draft exceeds 128 KiB. Existing work was kept.",
    );
  return blob;
}
export async function identityTextSha(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
  )
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
}
export async function importedIdentityText(
  data: any,
  original: any,
  key: string,
  sha: string,
): Promise<NativeIdentityWork> {
  original = identityTextDocument(original);
  if (
    !object(data, [
      "profile",
      "document_profile",
      "field_authority",
      "controller_queries",
      "capture_mutations",
      "native_review_created",
      "recovery_prepared",
      "file_sha256",
      "document",
      "source_evidence_text",
      "local_source_verified",
    ]) ||
    data.profile !== IDENTITY_TEXT_IMPORT ||
    data.document_profile !== IDENTITY_TEXT_PROFILE ||
    data.field_authority !== false ||
    data.controller_queries !== false ||
    data.capture_mutations !== false ||
    data.native_review_created !== false ||
    data.recovery_prepared !== false ||
    sha === null ||
    !ref(sha, 64) ||
    data.file_sha256 !== sha ||
    ordered(data.document) !== ordered(original) ||
    !sameIdentityTextContext(original.selection, key)
  )
    throw new Error(
      "Local identity import response differs from this exact file and context.",
    );
  let capture = null;
  if (original.capture_id === null) {
    if (
      data.source_evidence_text !== null ||
      data.local_source_verified !== false
    )
      throw new Error("Local identity import unexpectedly supplied a source.");
  } else {
    if (
      data.local_source_verified !== true ||
      !text(data.source_evidence_text, IDENTITY_TEXT_BYTES, true)
    )
      throw new Error("Local identity import lacks its original source proof.");
    const blob = new Blob([data.source_evidence_text]);
    if (
      blob.size > IDENTITY_TEXT_BYTES ||
      (await identityTextSha(blob)) !== original.snapshot_sha256
    )
      throw new Error(
        "Local identity source proof differs from its original snapshot.",
      );
    parseSourceJSON(data.source_evidence_text);
    const source = JSON.parse(data.source_evidence_text);
    if (
      !source ||
      source.profile !== "native-application-transfer/1" ||
      source.id !== original.capture_id ||
      !/^device,(0|[1-9][0-9]*)$/.test(source.device || "") ||
      Number(source.device.split(",")[1]) > 4194302 ||
      !text(source.captured_at, 128, true) ||
      !target(source.target) ||
      !(
        ordered(source.target) === ordered(original.captured_target) ||
        ordered({ ...source.target, device: source.device }) ===
          ordered(original.captured_target)
      ) ||
      !source.identity ||
      typeof source.identity !== "object" ||
      Array.isArray(source.identity) ||
      !object(source.files, ["3", "11", "12"]) ||
      Object.values(source.files).some(
        (v: any) =>
          !object(v, ["bytes", "sha256"]) ||
          !Number.isInteger(v.bytes) ||
          v.bytes < 1 ||
          v.bytes > 2 * 1024 * 1024 ||
          v.sha256 === null ||
          !ref(v.sha256, 64),
      )
    )
      throw new Error(
        "Local identity source proof has a different capture or target.",
      );
    capture = {
      id: source.id,
      captured_at: source.captured_at,
      target: structuredClone(original.captured_target),
      identity: { ...source.identity, device: source.device },
      application:
        source.application &&
        typeof source.application === "object" &&
        !Array.isArray(source.application)
          ? source.application
          : {},
      files: source.files,
      snapshot_evidence_sha256: original.snapshot_sha256,
      read_only: true,
      controller_queries: false,
      field_actions: false,
    };
  }
  return {
    ...emptyIdentityWork(),
    capture,
    newName: original.new_name,
    number: original.new_instance_text,
  };
}
