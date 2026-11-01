"""Project typed recorded instance-recovery metadata without loading source files."""

from typing import Literal

from pydantic import Field

from .models import StrictModel
from .moi_identity import seal
from .native_instance_recovery import PROFILE
from .native_ledger_details import Digest, Identifier, RecordedProof


class RecordedInstanceOrigin(StrictModel):
    profile: Literal[PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    original_after_native_sha256: Digest
    verified_after_capture_id: Identifier
    verified_after_snapshot_sha256: Digest
    verified_after_static_sha256: Digest
    verified_after_preservation_sha256: Digest
    proposal_preservation_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    current_archive_sha256: Digest
    current_static_sha256: Digest
    normalized_static_sha256: Digest
    normalized_root_selectors: int = Field(strict=True, ge=0, le=10000)
    root_ref: str = Field(strict=True, min_length=1, max_length=512)
    root_class: int = Field(strict=True, ge=0, le=1023)
    property: int = Field(strict=True, ge=75, le=75)
    previous_instance: int = Field(strict=True, ge=0, le=4194302)
    recorded_after_instance: int = Field(strict=True, ge=0, le=4194302)
    current_instance: int = Field(strict=True, ge=0, le=4194302)
    proposal_instance: int = Field(strict=True, ge=0, le=4194302)
    unchanged_name: str = Field(strict=True, min_length=1, max_length=512)


def instance_recovery_lineage(body):
    unavailable = {
        "state": "unavailable",
        "scope": "Recorded recovery metadata is incomplete or inconsistent; inspect original evidence.",
    }
    try:
        origin = RecordedInstanceOrigin.model_validate(body.get("recovery_origin"))
    except ValueError:
        return unavailable
    compilation = body.get("compilation")
    selected = compilation.get("identity_edit") if isinstance(compilation, dict) else None
    parameters = compilation.get("parameters") if isinstance(compilation, dict) else None
    if (
        not isinstance(selected, dict)
        or not isinstance(parameters, dict)
        or body.get("profile") != "native-application-transfer/1"
        or body.get("change_kind") != "instance"
        or "operation_profile" in body
        or body.get("allocation_confirmed") is not True
        or body.get("application_transfer_confirmed") is not True
        or body.get("name_change_confirmed", False) is not False
        or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
        or body.get("review_capture_id") != origin.current_capture_id
        or origin.parent_receipt_id == body.get("id")
        or origin.original_backup_id == body.get("backup_id")
        or origin.previous_instance == origin.recorded_after_instance
        or origin.current_instance != origin.recorded_after_instance
        or origin.proposal_instance != origin.previous_instance
        or origin.normalized_root_selectors != 0
        or origin.current_static_sha256 != origin.verified_after_static_sha256
        or origin.normalized_static_sha256 != origin.verified_after_static_sha256
        or parameters.get("source_sha256") != origin.current_archive_sha256
        or parameters.get("static_sha256") != origin.current_static_sha256
        or type(body.get("old_instance")) is not int
        or type(body.get("new_instance")) is not int
        or body["old_instance"] != origin.current_instance
        or body["new_instance"] != origin.previous_instance
        or body.get("old_name") != origin.unchanged_name
        or body.get("new_name") != origin.unchanged_name
        or selected.get("profile") != "tagged-moi-device-identity/1"
        or selected.get("change_kind") is not None
        or selected.get("root_ref") != origin.root_ref
        or type(selected.get("root_class")) is not int
        or selected["root_class"] != origin.root_class
        or selected.get("name") != origin.unchanged_name
        or type(selected.get("old_instance")) is not int
        or type(selected.get("new_instance")) is not int
        or selected["old_instance"] != origin.current_instance
        or selected["new_instance"] != origin.previous_instance
    ):
        return unavailable
    edits = selected.get("edits")
    if not isinstance(edits, list) or len(edits) != 2:
        return unavailable
    offsets = []
    for edit, (location, kind) in zip(
        edits,
        (("root-object-header", origin.root_class), ("Device.Object_Identifier", 8)),
        strict=True,
    ):
        if (
            not isinstance(edit, dict)
            or edit.get("location") != location
            or type(edit.get("native_byte_offset")) is not int
            or edit["native_byte_offset"] < 0
            or edit.get("before")
            != ((kind << 22) | origin.current_instance).to_bytes(4, "big").hex()
            or edit.get("after")
            != ((kind << 22) | origin.previous_instance).to_bytes(4, "big").hex()
        ):
            return unavailable
        offsets.append(edit["native_byte_offset"])
    if offsets[0] == offsets[1]:
        return unavailable
    return {
        "state": "recorded",
        "profile": PROFILE,
        "datatype": "ObjectIdentifier",
        "parent_receipt_id": origin.parent_receipt_id,
        "record_ref": origin.root_ref,
        "before_instance": origin.current_instance,
        "after_instance": origin.previous_instance,
        "unchanged_name": origin.unchanged_name,
        "verified_proof": origin.verified_proof.model_dump(),
        "original_backup_id": origin.original_backup_id,
        "verified_after_capture_id": origin.verified_after_capture_id,
        "current_capture_id": origin.current_capture_id,
        "origin_sha256": body["recovery_origin_sha256"],
        "scope": "Recorded origin seal and child-receipt bindings only. This projection does not revalidate the parent or backup files, allocate a number, authorize recovery or establish live state.",
    }
