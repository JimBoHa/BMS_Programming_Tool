import { saveBlob } from "./api";
import { restoreID, restoreHash } from "./nativeSnapshotRestoreContract";
type Data = Record<string, any>;
export const snapshotRestoreRecordedProfile =
  "native-retained-application-restore-recorded/1";
export const snapshotRestoreRecordedScope =
  "Recorded restore-source, review and pre-write backup bindings only. Original files and current controller state are not revalidated; no field or restore authority.";
export function recordedSnapshotRestore(row?: Data | null): Data | null {
  try {
    const v = row?.native_application_restore;
    if (
      row?.source !== "native" ||
      row.native_change_kind !== "application-restore" ||
      !v ||
      v.state !== "recorded" ||
      v.profile !== snapshotRestoreRecordedProfile ||
      v.scope !== snapshotRestoreRecordedScope ||
      Object.keys(v).length !== 15 ||
      v.child_receipt_id !== row.id ||
      ![
        v.child_receipt_id,
        v.restore_capture_id,
        v.review_capture_id,
        v.prewrite_backup_id,
      ].every(restoreID) ||
      [v.restore_capture_id, v.review_capture_id].includes(
        v.prewrite_backup_id,
      ) ||
      v.restore_capture_id === v.review_capture_id ||
      ![
        v.restore_snapshot_sha256,
        v.review_snapshot_sha256,
        v.compiled_native_sha256,
      ].every(restoreHash) ||
      !Number.isSafeInteger(v.instance) ||
      v.instance < 0 ||
      v.instance > 4194302 ||
      row.target?.device !== `device,${v.instance}` ||
      ["field_authority", "source_revalidated", "current_device_verified"].some(
        (k) => v[k] !== false,
      )
    )
      return null;
    const d = v.difference;
    if (
      !d ||
      Object.keys(d).length !== 8 ||
      d.scope !==
        "Complete native record-byte comparison, including opaque records; not runtime behavior or physical I/O compatibility." ||
      ![
        "before_records",
        "restored_records",
        "added_records",
        "removed_records",
        "changed_existing_records",
      ].every(
        (k) => Number.isSafeInteger(d[k]) && d[k] >= 0 && d[k] <= 2097152,
      ) ||
      d.before_records < 1 ||
      d.restored_records < 1 ||
      d.before_records + d.added_records - d.removed_records !==
        d.restored_records ||
      d.changed_existing_records > d.before_records - d.removed_records ||
      !restoreHash(d.before_native_sha256) ||
      d.restored_native_sha256 !== v.compiled_native_sha256 ||
      d.before_native_sha256 === d.restored_native_sha256
    )
      return null;
    return v;
  } catch {
    return null;
  }
}
export function SnapshotRestoreSummary({ row }: { row: Data }) {
  if (row.native_application_restore === undefined) return null;
  const data = recordedSnapshotRestore(row);
  return (
    <span>
      {data
        ? `Retained source ${data.restore_capture_id}`
        : "Retained restore metadata unavailable"}
    </span>
  );
}
export function NativeSnapshotRestoreLedgerView({ row }: { row: Data }) {
  const v = recordedSnapshotRestore(row);
  return (
    <section aria-label="Recorded retained application restore provenance">
      <h4>
        {v
          ? "Recorded retained application restore"
          : "Retained restore metadata unavailable"}
      </h4>
      {v ? (
        <>
          <dl>
            <dt>Historical restore source</dt>
            <dd>{v.restore_capture_id}</dd>
            <dt>Current review backup</dt>
            <dd>{v.review_capture_id}</dd>
            <dt>Fresh pre-write backup</dt>
            <dd>{v.prewrite_backup_id}</dd>
            <dt>Recorded restored native hash</dt>
            <dd>{v.compiled_native_sha256}</dd>
          </dl>
          <p>
            {v.difference.before_records} current records;{" "}
            {v.difference.restored_records} restored records;{" "}
            {v.difference.added_records} added, {v.difference.removed_records}{" "}
            removed and {v.difference.changed_existing_records} changed existing
            records.
          </p>
          <p>{v.scope}</p>
          <button
            onClick={() =>
              saveBlob(
                new Blob([JSON.stringify(v, null, 2)], {
                  type: "application/json",
                }),
                "recorded-retained-application-restore.json",
              )
            }
          >
            Save recorded application-restore provenance
          </button>
        </>
      ) : (
        <p>
          Inspect the original receipt. This projection grants no controller or
          restore authority.
        </p>
      )}
    </section>
  );
}
