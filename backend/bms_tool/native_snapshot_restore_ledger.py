"""Recorded restore-source/backup bindings without original-file or field access."""

import copy

from pydantic import TypeAdapter

from .native_backup_records import BackupInspectionSource
from .native_snapshot_restore import Identifier, validate_evidence

PROFILE = "native-retained-application-restore-recorded/1"
SCOPE = (
    "Recorded restore-source, review and pre-write backup bindings only. Original files "
    "and current controller state are not revalidated; no field or restore authority."
)


def restore_reference(body):
    unavailable = {
        "native_application_restore": {
            "state": "unavailable",
            "scope": "Recorded retained-application restore metadata is incomplete or inconsistent; inspect the original receipt.",
        }
    }
    try:
        validate_evidence(body)
        for key in ("id", "backup_id", "review_capture_id"):
            TypeAdapter(Identifier).validate_python(body[key])
        c = body["compilation"]
        BackupInspectionSource.model_validate(c["reviewed_current"])
        request = body["restore_source"]["request"]
        if body["backup_id"] in (request["restore_capture_id"], body["review_capture_id"]):
            return unavailable
        d = c["difference"]
        counts = (
            "before_records",
            "restored_records",
            "added_records",
            "removed_records",
            "changed_existing_records",
        )
        if (
            any(type(d[k]) is not int or not 0 <= d[k] <= 2097152 for k in counts)
            or d["before_records"] <= 0
            or d["restored_records"] != body["restore_source"]["compilation"]["native_record_count"]
            or d["before_records"] + d["added_records"] - d["removed_records"]
            != d["restored_records"]
            or d["changed_existing_records"] > d["before_records"] - d["removed_records"]
            or d["restored_native_sha256"] != body["native_payload_sha256"]
            or d["before_native_sha256"] == d["restored_native_sha256"]
        ):
            return unavailable
        return {
            "native_application_restore": {
                "state": "recorded",
                "profile": PROFILE,
                "scope": SCOPE,
                "child_receipt_id": body["id"],
                "instance": body["old_instance"],
                "restore_capture_id": request["restore_capture_id"],
                "restore_snapshot_sha256": request["restore_snapshot_sha256"],
                "review_capture_id": body["review_capture_id"],
                "review_snapshot_sha256": body["review_snapshot_sha256"],
                "prewrite_backup_id": body["backup_id"],
                "compiled_native_sha256": body["native_payload_sha256"],
                "difference": copy.deepcopy(d),
                "field_authority": False,
                "source_revalidated": False,
                "current_device_verified": False,
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return unavailable
