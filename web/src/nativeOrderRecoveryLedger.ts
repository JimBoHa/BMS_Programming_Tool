import { orderRecoveryOrigin } from "./nativeOrderRecoveryTransferContract";
type Data = Record<string, any>;
export const orderRecoveryRecordedProfile =
  "native-execution-order-recovery-recorded/1";
export const orderRecoveryRecordedScope =
  "Recorded previous-order origin seal and child-receipt bindings only. Parent receipts, backup files and current controller state are not revalidated. This projection grants no recovery or transfer authority.";
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((key) => Object.hasOwn(v, key));
const id = (v: any) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const permutation = (v: any) =>
  Array.isArray(v) &&
  v.length >= 1 &&
  v.length <= 512 &&
  v.every((n) => Number.isSafeInteger(n) && n >= 0 && n < v.length) &&
  new Set(v).size === v.length;
export function recordedOrderRecovery(row: Data): Data | null {
  try {
    const value = row.native_order_recovery;
    if (
      row.source !== "native" ||
      row.native_change_kind !== "execution-order" ||
      !exact(value, [
        "state",
        "profile",
        "scope",
        "child_receipt_id",
        "instance",
        "diagram_ref",
        "before",
        "after",
        "payload_widths",
        "review_capture_id",
        "review_snapshot_sha256",
        "origin",
        "origin_sha256",
        "compiled_native_sha256",
        "field_authority",
        "parent_revalidated",
        "source_revalidated",
        "current_device_verified",
      ]) ||
      value.state !== "recorded" ||
      value.profile !== orderRecoveryRecordedProfile ||
      value.scope !== orderRecoveryRecordedScope ||
      value.child_receipt_id !== row.id ||
      !id(row.id) ||
      !Number.isSafeInteger(value.instance) ||
      value.instance < 0 ||
      value.instance > 4194302 ||
      row.target?.device !== `device,${value.instance}` ||
      typeof value.diagram_ref !== "string" ||
      value.diagram_ref.length < 1 ||
      value.diagram_ref.length > 512 ||
      value.diagram_ref !== row.object ||
      !id(value.review_capture_id) ||
      !hash(value.review_snapshot_sha256) ||
      !hash(value.compiled_native_sha256) ||
      !orderRecoveryOrigin(value.origin, value.origin_sha256) ||
      value.origin.parent_receipt_id === row.id ||
      !permutation(value.before) ||
      !permutation(value.after) ||
      value.before.length !== value.after.length ||
      value.before.every((n: number, i: number) => n === value.after[i]) ||
      !Array.isArray(value.payload_widths) ||
      value.payload_widths.length !== value.before.length ||
      value.payload_widths.some(
        (width: any, index: number) =>
          !Number.isSafeInteger(width) ||
          width < 1 ||
          width > 4 ||
          value.before[index] >= 2 ** (8 * width) ||
          value.after[index] >= 2 ** (8 * width),
      ) ||
      [
        "field_authority",
        "parent_revalidated",
        "source_revalidated",
        "current_device_verified",
      ].some((key) => value[key] !== false)
    )
      return null;
    return value;
  } catch {
    return null;
  }
}
