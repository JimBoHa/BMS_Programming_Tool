import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { matchingConnectionTarget } from "./nativeMatchingConnectionContract";
import type { NativeArchiveSource } from "./NativeRecords";
import type { ControllerContext } from "./workflow";
type Data = Record<string, any>;
export type SnapshotRestoreArchive = NativeArchiveSource & { identity: Data };

export const snapshotRestoreBase =
  "/bacnet/controller/native-application/application-restore";
export const snapshotRestoreProfile = "native-retained-application-restore/1";
export const snapshotRestoreSourceProfile =
  "native-retained-application-restore-source/1";
export const snapshotRestoreCompilationProfile =
  "native-retained-application-restore-compilation/1";
export const snapshotRestoreScope =
  "Restore one retained native application and its supported historical saved application settings to the matching recorded route and complete Device/model/firmware identity. Read a separate current application for review and retain a fresh pre-write backup. Refuse changed current non-runtime settings; permit only qualified monotonic counters. One newly confirmed restore and complete native/effective readback are required. No automatic replay, new identity allocation, cross-controller/release migration, general logic compiler, whole-controller/runtime backup or CCT/physical acceptance.";
export const snapshotRestoreSourceScope =
  "Reconstruct this retained File3 application with supported saved application values from its original Files11/12. Preserve original object identities, graph and opaque configuration. Values are historical, not live. Non-application runtime slots remain original evidence and are not application defaults. No controller query, transfer review, current-device verification or field authority.";
export const snapshotRestoreTarget = matchingConnectionTarget;
export const restoreHash = (v: any) =>
  typeof v === "string" && v.length === 64 && /^[a-f0-9]{64}$/.test(v);
export const restoreID = (v: any) =>
  typeof v === "string" && v.length === 32 && /^[a-f0-9]{32}$/.test(v);
const count = (v: any, max = 2097152) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const object = (v: any): v is Data =>
  !!v && typeof v === "object" && !Array.isArray(v);
const exact = (v: any, keys: string[]) =>
  object(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const identity = (v: any) =>
  exact(v, [
    "device",
    "object-name",
    "vendor-identifier",
    "model-name",
    "firmware-revision",
    "application-software-version",
  ]) &&
  v["vendor-identifier"] === 5 &&
  [
    "device",
    "object-name",
    "model-name",
    "firmware-revision",
    "application-software-version",
  ].every(
    (k) =>
      typeof v[k] === "string" && v[k].length > 0 && [...v[k]].length <= 512,
  );
export async function restoreSealed(v: any, key: string) {
  if (!object(v) || !restoreHash(v[key])) return false;
  const { [key]: digest, ...body } = v;
  return (await connectionSeal(body)) === digest;
}
function guard(v: any) {
  return (
    exact(v, [
      "profile",
      "application_sha256",
      "static_parameters_sha256",
      "saved_configuration_sha256",
      "counter_values_sha256",
      "saved_parameter_count",
      "counter_count",
    ]) &&
    v.profile === "native-restore-current-configuration/1" &&
    [
      "application_sha256",
      "static_parameters_sha256",
      "saved_configuration_sha256",
      "counter_values_sha256",
    ].every((k) => restoreHash(v[k])) &&
    count(v.saved_parameter_count, 131072) &&
    count(v.counter_count, 131072) &&
    v.counter_count <= v.saved_parameter_count
  );
}
export async function snapshotRestoreSource(
  v: any,
  source?: SnapshotRestoreArchive,
) {
  try {
    if (
      !exact(v, [
        "profile",
        "scope",
        "request",
        "captured_at",
        "target",
        "identity",
        "compilation",
        "saved_settings_merged",
        "read_only",
        "controller_queries",
        "field_actions",
        "field_transfer_enabled",
        "current_device_verified",
        "can_apply",
        "evidence_sha256",
      ]) ||
      v.profile !== snapshotRestoreSourceProfile ||
      v.scope !== snapshotRestoreSourceScope ||
      !exact(v.request, ["restore_capture_id", "restore_snapshot_sha256"]) ||
      !restoreID(v.request.restore_capture_id) ||
      !restoreHash(v.request.restore_snapshot_sha256) ||
      !identity(v.identity) ||
      v.identity.device !== v.target?.device ||
      !snapshotRestoreTarget(v.target, v.target) ||
      !Number.isFinite(Date.parse(v.captured_at)) ||
      v.saved_settings_merged !== true ||
      v.read_only !== true ||
      [
        "controller_queries",
        "field_actions",
        "field_transfer_enabled",
        "current_device_verified",
        "can_apply",
      ].some((k) => v[k] !== false) ||
      !(await restoreSealed(v, "evidence_sha256"))
    )
      return false;
    const c = v.compilation;
    if (
      !exact(c, [
        "files",
        "archive_native_sha256",
        "compiled_sha256",
        "compiled_native_sha256",
        "compiled_bytes",
        "native_record_count",
        "format_versions",
        "encoding",
        "saved_application_parameters",
        "changed_saved_parameters",
        "retained_runtime_slots",
        "omitted_field_qualification",
        "non_application_runtime_restored",
      ]) ||
      !exact(c.files, ["3", "11", "12"]) ||
      !["3", "11", "12"].every(
        (k) =>
          exact(c.files[k], ["bytes", "sha256"]) &&
          count(c.files[k].bytes) &&
          c.files[k].bytes > 0 &&
          restoreHash(c.files[k].sha256),
      ) ||
      ![
        "archive_native_sha256",
        "compiled_sha256",
        "compiled_native_sha256",
      ].every((k) => restoreHash(c[k])) ||
      !count(c.compiled_bytes) ||
      c.compiled_bytes < 1 ||
      !count(c.native_record_count) ||
      c.native_record_count < 1 ||
      !exact(c.format_versions, ["acs", "dmcs"]) ||
      !["acs", "dmcs"].every(
        (k) => count(c.format_versions[k], 65535) && c.format_versions[k] > 0,
      ) ||
      !["moi-v2", "gzip-moi-v2"].includes(c.encoding) ||
      ![
        "saved_application_parameters",
        "changed_saved_parameters",
        "retained_runtime_slots",
      ].every((k) => count(c[k], 131072)) ||
      c.changed_saved_parameters > c.saved_application_parameters ||
      c.non_application_runtime_restored !== false ||
      !exact(c.omitted_field_qualification, [
        "profile",
        "qualified_fields",
        "model_inventory_used",
      ]) ||
      c.omitted_field_qualification.profile !==
        "native-omitted-application-field-types/1" ||
      !count(c.omitted_field_qualification.qualified_fields, 131072) ||
      c.omitted_field_qualification.model_inventory_used !== false
    )
      return false;
    return (
      !source ||
      (v.request.restore_capture_id === source.capture_id &&
        v.request.restore_snapshot_sha256 === source.snapshot_sha256 &&
        snapshotRestoreTarget(v.target, source.target) &&
        same(v.identity, source.identity) &&
        same(c.files, source.files))
    );
  } catch {
    return false;
  }
}
export async function snapshotRestoreCompilation(c: any, source: Data) {
  try {
    if (
      !exact(c, [
        "profile",
        "scope",
        "restore_source_evidence_sha256",
        "reviewed_current",
        "reviewed_current_guard",
        "prewrite_guard",
        "difference",
        "compiled_sha256",
        "compiled_native_sha256",
        "historical_saved_settings_restored",
        "non_application_runtime_restored",
        "compilation_sha256",
      ]) ||
      c.profile !== snapshotRestoreCompilationProfile ||
      c.scope !== snapshotRestoreScope ||
      c.restore_source_evidence_sha256 !== source.evidence_sha256 ||
      !exact(c.reviewed_current, ["capture_id", "snapshot_sha256"]) ||
      !restoreID(c.reviewed_current.capture_id) ||
      !restoreHash(c.reviewed_current.snapshot_sha256) ||
      c.reviewed_current.capture_id === source.request.restore_capture_id ||
      !guard(c.reviewed_current_guard) ||
      !guard(c.prewrite_guard) ||
      c.compiled_sha256 !== source.compilation.compiled_sha256 ||
      c.compiled_native_sha256 !== source.compilation.compiled_native_sha256 ||
      c.historical_saved_settings_restored !== true ||
      c.non_application_runtime_restored !== false ||
      !(await restoreSealed(c, "compilation_sha256"))
    )
      return false;
    if (
      [
        "profile",
        "application_sha256",
        "static_parameters_sha256",
        "saved_configuration_sha256",
        "saved_parameter_count",
        "counter_count",
      ].some((k) => !same(c.reviewed_current_guard[k], c.prewrite_guard[k]))
    )
      return false;
    const d = c.difference;
    return (
      exact(d, [
        "before_records",
        "restored_records",
        "added_records",
        "removed_records",
        "changed_existing_records",
        "before_native_sha256",
        "restored_native_sha256",
        "scope",
      ]) &&
      [
        "before_records",
        "restored_records",
        "added_records",
        "removed_records",
        "changed_existing_records",
      ].every((k) => count(d[k])) &&
      d.before_records > 0 &&
      d.restored_records === source.compilation.native_record_count &&
      d.before_records + d.added_records - d.removed_records ===
        d.restored_records &&
      d.changed_existing_records <= d.before_records - d.removed_records &&
      restoreHash(d.before_native_sha256) &&
      d.before_native_sha256 !== d.restored_native_sha256 &&
      d.restored_native_sha256 === c.compiled_native_sha256 &&
      d.scope ===
        "Complete native record-byte comparison, including opaque records; not runtime behavior or physical I/O compatibility."
    );
  } catch {
    return false;
  }
}
export async function snapshotRestoreReview(
  v: any,
  selected: SnapshotRestoreArchive,
  inspected: Data,
  controller: ControllerContext,
) {
  try {
    const { token, review_sha256, ...body } = v;
    return (
      typeof token === "string" &&
      /^[A-Za-z0-9_-]{32}$/.test(token) &&
      (await restoreSealed({ ...body, review_sha256 }, "review_sha256")) &&
      v.profile === "native-application-transfer/1" &&
      v.operation_profile === snapshotRestoreProfile &&
      v.change_kind === "application-restore" &&
      v.scope === snapshotRestoreScope &&
      v.can_apply === true &&
      v.vendor_runtime_required === false &&
      snapshotRestoreTarget(
        { ...v.target, device: v.identity?.device },
        controller,
      ) &&
      same(v.identity, inspected.identity) &&
      same(v.restore_source, inspected) &&
      (await snapshotRestoreSource(v.restore_source, selected)) &&
      (await snapshotRestoreCompilation(v.compilation, v.restore_source)) &&
      v.capture_id === v.compilation.reviewed_current.capture_id &&
      v.snapshot_sha256 === v.compilation.reviewed_current.snapshot_sha256 &&
      v.application_sha256 ===
        v.compilation.reviewed_current_guard.application_sha256 &&
      v.static_parameters_sha256 ===
        v.compilation.reviewed_current_guard.static_parameters_sha256 &&
      same(
        v.compilation.reviewed_current_guard,
        v.compilation.prewrite_guard,
      ) &&
      v.payload_sha256 === inspected.compilation.compiled_sha256 &&
      v.old_instance === Number(controller.device.split(",")[1]) &&
      v.new_instance === v.old_instance &&
      v.old_name === inspected.identity["object-name"] &&
      v.new_name === v.old_name &&
      same(v.connector_config, JSON.parse(controller.interfaceKey)) &&
      Number.isFinite(Date.parse(v.created_at)) &&
      Date.parse(v.expires_at) > Date.parse(v.created_at) &&
      Date.parse(v.expires_at) <= Date.parse(v.created_at) + 901000 &&
      Date.parse(v.expires_at) > Date.now() &&
      !Object.keys(v).some((k) => k.startsWith("recovery_"))
    );
  } catch {
    return false;
  }
}

export async function snapshotRestoreReceipt(
  data: any,
  reference?: Data,
): Promise<boolean> {
  try {
    if (!object(data) || typeof data.pending !== "boolean") return false;
    const i = data.intent;
    if (!i)
      return (
        reference?.id === undefined &&
        data.pending === false &&
        data.result?.status === "not_sent" &&
        data.result.may_have_applied === false &&
        data.result.protocol_accepted === false
      );
    const c = i.compilation;
    if (
      !restoreID(i.id) ||
      i.profile !== "native-application-transfer/1" ||
      i.operation_profile !== snapshotRestoreProfile ||
      i.change_kind !== "application-restore" ||
      !(await restoreSealed(i, "evidence_sha256")) ||
      !(await snapshotRestoreSource(i.restore_source)) ||
      !(await snapshotRestoreCompilation(c, i.restore_source)) ||
      !snapshotRestoreTarget(
        { ...i.target, device: i.identity?.device },
        i.restore_source.target,
      ) ||
      !same(i.identity, i.restore_source.identity) ||
      !restoreID(i.backup_id) ||
      [
        i.review_capture_id,
        i.restore_source.request.restore_capture_id,
      ].includes(i.backup_id) ||
      i.review_capture_id !== c.reviewed_current.capture_id ||
      i.review_snapshot_sha256 !== c.reviewed_current.snapshot_sha256 ||
      i.payload_sha256 !== c.compiled_sha256 ||
      i.native_payload_sha256 !== c.compiled_native_sha256 ||
      !count(i.old_instance, 4194302) ||
      i.new_instance !== i.old_instance ||
      i.identity.device !== `device,${i.old_instance}` ||
      i.old_name !== i.identity["object-name"] ||
      i.new_name !== i.old_name ||
      i.historical_application_confirmed !== true ||
      i.application_transfer_confirmed !== true ||
      !restoreHash(i.review_sha256) ||
      !object(i.connector_config) ||
      Object.keys(i).some((k) => k.startsWith("recovery_")) ||
      [
        "order_edit",
        "default_edit",
        "wire_edit",
        "input_edit",
        "batch_edit",
        "combined_edit",
        "point_name_edit",
        "connection_edit",
      ].some((k) => i[k] !== undefined)
    )
      return false;
    if (
      reference &&
      ((reference.id !== undefined &&
        (i.id !== reference.id || i.operation_id !== reference.operation_id)) ||
        i.review_sha256 !== reference.review_sha256 ||
        !same(i.target, reference.target) ||
        !same(i.identity, reference.identity) ||
        !same(i.connector_config, reference.connector_config) ||
        !same(i.restore_source, reference.restore_source) ||
        i.review_capture_id !==
          (reference.review_capture_id ?? reference.capture_id) ||
        i.review_snapshot_sha256 !==
          (reference.review_snapshot_sha256 ?? reference.snapshot_sha256) ||
        !same(
          c.reviewed_current_guard,
          reference.compilation.reviewed_current_guard,
        ) ||
        !same(c.difference, reference.compilation.difference))
    )
      return false;
    const observed = data.latest_readback || data.result;
    if (
      object(data.result) &&
      data.result.evidence_sha256 !== undefined &&
      (data.result.profile !== "native-application-transfer/1" ||
        data.result.receipt_id !== i.id ||
        data.result.intent_sha256 !== i.evidence_sha256 ||
        !(await restoreSealed(data.result, "evidence_sha256")))
    )
      return false;
    if (data.latest_readback) {
      const last = Array.isArray(data.events) ? data.events.at(-1) : null;
      if (
        !object(last) ||
        last.profile !== "native-application-transfer/1" ||
        last.receipt_id !== i.id ||
        last.stage !== "readback" ||
        !same(last.detail, data.latest_readback) ||
        !(await restoreSealed(last, "evidence_sha256"))
      )
        return false;
    }
    if (!object(observed))
      return (
        data.pending === true && data.result === null && !data.latest_readback
      );
    if (observed.status === "unknown")
      return (
        data.pending === true ||
        (!!data.latest_readback &&
          (await snapshotRestoreReceipt(
            { ...data, latest_readback: null },
            reference,
          )))
      );
    if (observed.status === "not_sent")
      return (
        data.pending === false &&
        observed.may_have_applied === false &&
        observed.protocol_accepted === false
      );
    if (
      !["verified", "recovered_original"].includes(observed.status) ||
      data.pending !== false ||
      observed.operational !== true ||
      observed.system_status !== 0 ||
      !restoreID(observed.verification_capture_id) ||
      !restoreHash(observed.native_sha256) ||
      observed.native_sha256 !== observed.expected_native_sha256 ||
      !same(observed.readback?.identity, i.identity)
    )
      return false;
    const p = observed.preservation;
    if (
      !object(p) ||
      p.controller_writes !== false ||
      !count(p.saved_application_parameters_verified, 131072) ||
      !count(p.post_saved_parameters, 131072) ||
      !Array.isArray(p.runtime_counter_changes) ||
      !Array.isArray(p.device_calculated_changes) ||
      p.preserved_native_sha256 !== observed.native_sha256 ||
      !restoreHash(p.verified_application_sha256)
    )
      return false;
    if (observed.status === "recovered_original")
      return (
        observed.proposed_change_verified === false &&
        observed.native_sha256 !== i.native_payload_sha256 &&
        observed.recovery?.profile ===
          "native-original-application-readback/1" &&
        observed.recovery.original_backup_id === i.backup_id &&
        observed.recovery.original_reviewed_native_sha256 ===
          i.native_payload_sha256 &&
        p.profile === "native-application-preservation/1" &&
        p.application_identical_except_instance === true &&
        p.application_identical_except_name === false &&
        same(p.allowed_identity_changes, ["instance"])
      );
    return (
      observed.native_sha256 === i.native_payload_sha256 &&
      p.profile === "native-retained-application-restore-preservation/1" &&
      p.restored_application_matches_retained_source === true &&
      p.effective_saved_application_values_verified === true &&
      p.identity_unchanged === true &&
      p.restore_source_capture_id ===
        i.restore_source.request.restore_capture_id &&
      p.prewrite_backup_id === i.backup_id &&
      p.saved_application_parameters_verified ===
        i.restore_source.compilation.saved_application_parameters &&
      p.non_application_runtime_restored === false
    );
  } catch {
    return false;
  }
}
