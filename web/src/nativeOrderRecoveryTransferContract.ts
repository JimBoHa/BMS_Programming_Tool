import { sha256 } from "@noble/hashes/sha2.js";
import { connectionSame as same } from "./nativeConnectionContract";
type Data = Record<string, any>;
export const orderRecoveryTransferProfile =
  "native-execution-order-recovery-transfer/1";
export const orderRecoveryTransferScope =
  "Transfer only the previous permutation derived from a resolved historically verified original execution-order receipt and matching retained after application/order/static directory. Revalidate the original proof, proposal and lineage before review and durable intent; retain fresh other saved settings. Require a new confirmed one-use restore and complete native/effective readback. No old-token replay, automatic inverse, recursive recovery, new identities, general restore/compiler or CCT/physical acceptance.";
export const orderRecoveryMetadataKeys = [
  "recovery_profile",
  "recovery_scope",
  "recovery_origin",
  "recovery_origin_sha256",
];
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const id = (v: any) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);

/** This closed origin contains only validated ASCII strings and one proof. */
export function orderRecoveryOriginJSON(o: Data) {
  return JSON.stringify({
    comparison_sha256: o.comparison_sha256,
    original_backup_id: o.original_backup_id,
    original_snapshot_sha256: o.original_snapshot_sha256,
    parent_intent_sha256: o.parent_intent_sha256,
    parent_receipt_id: o.parent_receipt_id,
    verified_proof: {
      kind: o.verified_proof.kind,
      sha256: o.verified_proof.sha256,
      time: o.verified_proof.time,
    },
  });
}

export function orderRecoveryOrigin(o: any, digest: any) {
  if (
    !exact(o, [
      "parent_receipt_id",
      "parent_intent_sha256",
      "verified_proof",
      "original_backup_id",
      "original_snapshot_sha256",
      "comparison_sha256",
    ]) ||
    !id(o.parent_receipt_id) ||
    !id(o.original_backup_id) ||
    ![
      o.parent_intent_sha256,
      o.original_snapshot_sha256,
      o.comparison_sha256,
      digest,
    ].every(hash) ||
    !exact(o.verified_proof, ["kind", "sha256", "time"]) ||
    !["result", "readback-event"].includes(o.verified_proof.kind) ||
    !hash(o.verified_proof.sha256) ||
    typeof o.verified_proof.time !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      o.verified_proof.time,
    ) ||
    !Number.isFinite(Date.parse(o.verified_proof.time))
  )
    return false;
  return (
    Array.from(
      sha256(new TextEncoder().encode(orderRecoveryOriginJSON(o))),
      (v) => v.toString(16).padStart(2, "0"),
    ).join("") === digest
  );
}

/** null expects an ordinary review; undefined admits independently recorded lineage. */
export function orderRecoveryMetadata(
  value: Data,
  expected?: Data | null,
  reference?: Data,
) {
  try {
    const present = Object.keys(value).filter((key) =>
      key.startsWith("recovery_"),
    );
    const fromReference =
      reference &&
      Object.keys(reference).some((key) => key.startsWith("recovery_"));
    if (!present.length) return !expected && !fromReference;
    if (
      expected === null ||
      present.length !== orderRecoveryMetadataKeys.length ||
      !orderRecoveryMetadataKeys.every((key) => present.includes(key)) ||
      value.recovery_profile !== orderRecoveryTransferProfile ||
      value.recovery_scope !== orderRecoveryTransferScope ||
      !orderRecoveryOrigin(
        value.recovery_origin,
        value.recovery_origin_sha256,
      ) ||
      value.id === value.recovery_origin.parent_receipt_id
    )
      return false;
    if (
      expected &&
      (!same(value.recovery_origin, expected.origin) ||
        value.recovery_origin_sha256 !== expected.origin_sha256 ||
        !same(value.order_edit, expected.proposal))
    )
      return false;
    return (
      !reference ||
      (!!fromReference &&
        orderRecoveryMetadataKeys.every((key) =>
          same(value[key], reference[key]),
        ))
    );
  } catch {
    return false;
  }
}
