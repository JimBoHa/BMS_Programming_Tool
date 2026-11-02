"""Recorded point-name lineage is a projection, never recovery admission."""

from typing import Literal

from pydantic import Field, field_validator

from .application_store import PROFILE as TRANSFER_PROFILE
from .models import StrictModel
from .moi_identity import controller_name, seal
from .native_ledger_details import Digest, Identifier, RecordedProof
from .native_point_name_ledger import point_name_reference
from .native_point_name_recovery import PROFILE as ORIGIN_PROFILE

PROFILE = "native-point-name-recovery-recorded/1"
SCOPE = (
    "Recorded point-name origin seal and child-receipt bindings only. Parent receipt and "
    "original-source availability, current point names and transfer authority are not established."
)
UNAVAILABLE = "Recorded point-name recovery metadata is incomplete or inconsistent; inspect original evidence."


class RecordedPointNameOrigin(StrictModel):
    profile: Literal[ORIGIN_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    original_after_native_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    current_archive_sha256: Digest
    object_id: str = Field(strict=True, min_length=1, max_length=80)
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    current_name_sha256: Digest
    native_class: int = Field(strict=True, ge=0, le=65535)
    property: int = Field(strict=True, ge=2390, le=2390)
    character_encoding: int = Field(strict=True, ge=0, le=5)
    previous_name: str = Field(strict=True)
    recorded_after_name: str = Field(strict=True)
    current_name: str = Field(strict=True)
    proposal_name: str = Field(strict=True)

    @field_validator("previous_name", "recorded_after_name", "current_name", "proposal_name")
    @classmethod
    def name(cls, value):
        return controller_name(value)

    @field_validator("character_encoding")
    @classmethod
    def encoding(cls, value):
        if value not in (0, 3, 4, 5):
            raise ValueError("Unknown recorded point-name character encoding.")
        return value


def point_name_recovery_reference(body, point):
    if "recovery_origin" not in body and "recovery_origin_sha256" not in body:
        return {}
    unavailable = {"native_point_name_recovery": {"state": "unavailable", "scope": UNAVAILABLE}}
    try:
        origin = RecordedPointNameOrigin.model_validate(body.get("recovery_origin"))
        if (
            type(point) is not dict
            or point.get("state") != "recorded"
            or point_name_reference(body).get("native_point_name") != point
            or body.get("profile") != TRANSFER_PROFILE
            or body.get("change_kind") != "point-name"
            or body.get("point_name_confirmed") is not True
            or body.get("application_transfer_confirmed") is not True
            or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
            or origin.parent_receipt_id == body.get("id")
            or origin.original_backup_id == body.get("backup_id")
            or origin.original_backup_id == origin.current_capture_id
            or origin.current_capture_id != body.get("review_capture_id")
            or origin.object_id != point["object_id"]
            or origin.record_ref != point["record_ref"]
            or origin.current_name_sha256 != point["before_record_sha256"]
            or origin.character_encoding != point["character_encoding"]
            or origin.current_name != origin.recorded_after_name
            or origin.proposal_name != origin.previous_name
            or origin.previous_name == origin.recorded_after_name
            or point["before"] != origin.current_name
            or point["after"] != origin.previous_name
            or body.get("old_name") != body.get("new_name")
            or type(body.get("old_name")) is not str
            or type(body.get("identity")) is not dict
            or body["identity"].get("object-name") != body["old_name"]
            or body["identity"].get("device") != f"device,{body['old_instance']}"
            or type(body.get("target")) is not dict
            or type(body["target"].get("address")) is not str
            or not body["target"]["address"]
            or body["target"].get("device") not in (None, f"device,{body['old_instance']}")
        ):
            return unavailable
        return {
            "native_point_name_recovery": {
                "state": "recorded",
                "profile": PROFILE,
                "object_id": origin.object_id,
                "record_ref": origin.record_ref,
                "instance": body["old_instance"],
                "before": origin.current_name,
                "after": origin.previous_name,
                "character_encoding": origin.character_encoding,
                "parent_receipt_id": origin.parent_receipt_id,
                "parent_intent_sha256": origin.parent_intent_sha256,
                "verified_proof": origin.verified_proof.model_dump(),
                "original_backup_id": origin.original_backup_id,
                "original_snapshot_sha256": origin.original_snapshot_sha256,
                "current_capture_id": origin.current_capture_id,
                "current_snapshot_sha256": origin.current_snapshot_sha256,
                "origin_sha256": body["recovery_origin_sha256"],
                "scope": SCOPE,
            }
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        return unavailable
