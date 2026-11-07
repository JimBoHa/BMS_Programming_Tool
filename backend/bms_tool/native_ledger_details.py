"""Bounded native receipt metadata, without loading backup files or parent journals."""

import math
import struct
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .application_store import PROFILE as TRANSFER_PROFILE
from .models import StrictModel
from .moi_identity import controller_name, seal
from .native_boolean_recovery import PROFILE as BOOLEAN_RECOVERY_PROFILE
from .native_boolean_recovery import tag as boolean_tag
from .native_boolean_transfer import PROFILE as BOOLEAN_TRANSFER_PROFILE
from .native_default_recovery import PROFILE as RECOVERY_PROFILE
from .native_default_transfer import PROFILE as DEFAULT_PROFILE
from .native_historical_pin import RecordedWirePin, recorded_pin_matches
from .native_historical_wire_recovery import PROFILE as HISTORICAL_WIRE_PROFILE
from .native_name_recovery import PROFILE as NAME_RECOVERY_PROFILE
from .native_wire_copies import UInt
from .native_wire_recovery import PROFILE as WIRE_RECOVERY_PROFILE
from .native_wire_transfer import PROFILE as WIRE_TRANSFER_PROFILE

Identifier = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{32}$")]
Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Bits = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{8}$")]


class RecordedProof(StrictModel):
    kind: Literal["result", "readback-event"]
    sha256: Digest
    time: str = Field(strict=True, min_length=1, max_length=80)

    @field_validator("time")
    @classmethod
    def recorded_time(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("The recorded proof needs an explicit time zone.")
        return value


class RecordedOrigin(StrictModel):
    profile: Literal[RECOVERY_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    class_id: int = Field(strict=True, ge=526, le=527)
    property: int = Field(strict=True, ge=3113, le=3113)
    previous_effective_bits: Bits
    recorded_after_bits: Bits
    current_effective_bits: Bits
    proposal_bits: Bits

    @field_validator(
        "previous_effective_bits", "recorded_after_bits", "current_effective_bits", "proposal_bits"
    )
    @classmethod
    def finite_bits(cls, value):
        if not math.isfinite(struct.unpack(">f", bytes.fromhex(value))[0]):
            raise ValueError("The recorded recovery profile requires finite float32 values.")
        return value


class RecordedBooleanOrigin(StrictModel):
    profile: Literal[BOOLEAN_RECOVERY_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    class_id: int = Field(strict=True, ge=530, le=531)
    property: int = Field(strict=True, ge=3113, le=3113)
    previous_effective_value: bool = Field(strict=True)
    recorded_after_value: bool = Field(strict=True)
    current_effective_value: bool = Field(strict=True)
    proposal_value: bool = Field(strict=True)
    previous_tag: Literal["10", "11"]
    recorded_after_tag: Literal["10", "11"]
    current_tag: Literal["10", "11"]
    proposal_tag: Literal["10", "11"]


class RecordedWireOrigin(StrictModel):
    profile: Literal[WIRE_RECOVERY_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    diagram_ref: str = Field(strict=True, min_length=1, max_length=512)
    class_id: int = Field(strict=True)
    property: int = Field(strict=True, ge=3118, le=3118)
    wire_index: int = Field(strict=True, ge=0, le=4095)
    previous_tuple: list[UInt] = Field(min_length=4, max_length=4)
    recorded_after_tuple: list[UInt] = Field(min_length=4, max_length=4)
    current_tuple: list[UInt] = Field(min_length=4, max_length=4)
    proposal_tuple: list[UInt] = Field(min_length=4, max_length=4)
    previous_source_ref: str = Field(strict=True, min_length=1, max_length=512)
    recorded_after_source_ref: str = Field(strict=True, min_length=1, max_length=512)
    current_source_ref: str = Field(strict=True, min_length=1, max_length=512)
    proposal_source_ref: str = Field(strict=True, min_length=1, max_length=512)
    target_ref: str = Field(strict=True, min_length=1, max_length=512)
    source_index_bytes: int = Field(strict=True, ge=1, le=4)

    @field_validator("class_id")
    @classmethod
    def diagram_class(cls, value):
        if value not in (536, 575):
            raise ValueError("A recorded wire recovery requires an actual native diagram class.")
        return value


class RecordedHistoricalWireOrigin(RecordedWireOrigin):
    profile: Literal[HISTORICAL_WIRE_PROFILE]
    historical_pin: RecordedWirePin
    historical_pin_sha256: Digest


class RecordedNameOrigin(StrictModel):
    profile: Literal[NAME_RECOVERY_PROFILE]
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
    root_ref: str = Field(strict=True, min_length=1, max_length=512)
    root_class: int = Field(strict=True, ge=0, le=65535)
    instance: int = Field(strict=True, ge=0, le=4194302)
    property: int = Field(strict=True, ge=2390, le=2390)
    previous_name: str = Field(strict=True)
    recorded_after_name: str = Field(strict=True)
    current_name: str = Field(strict=True)
    proposal_name: str = Field(strict=True)

    @field_validator("previous_name", "recorded_after_name", "current_name", "proposal_name")
    @classmethod
    def qualified_name(cls, value):
        return controller_name(value)


def native_reference(kind, selection):
    """Read canonical native keys; retain a legacy alias only when unambiguous."""
    if kind not in {
        "signal-default",
        "boolean-default",
        "enum-default",
        "wire-source",
        "execution-order",
    }:
        return {}
    if not isinstance(selection, dict):
        return {"object": "", "native_reference_issue": "Native edit reference was not recorded."}
    key = "diagram_ref" if kind in {"wire-source", "execution-order"} else "record_ref"
    value = selection.get(key)
    if kind not in {"wire-source", "execution-order"} and key not in selection:
        value = selection.get("ref")
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or kind not in {"wire-source", "execution-order"}
        and key in selection
        and "ref" in selection
        and selection["ref"] != value
    ):
        return {
            "object": "",
            "native_reference_issue": "Native edit reference is missing, invalid or conflicting.",
        }
    result = {"object": value}
    if kind == "wire-source" and "wire_index" in selection:
        index = selection["wire_index"]
        if type(index) is int and 0 <= index <= 4095:
            result["native_wire_index"] = index
        else:
            result["native_reference_issue"] = "The recorded wire index is invalid."
    return result


def recovery_lineage(body, kind, reference):
    """Project recorded lineage, never assert present parent/source availability."""
    if "recovery_origin" not in body and "recovery_origin_sha256" not in body:
        return None
    if kind == "boolean-default":
        return boolean_recovery_lineage(body, reference)
    if kind == "enum-default":
        from .native_enum_recovery_ledger import enum_recovery_lineage

        return enum_recovery_lineage(body, reference)
    if kind == "wire-source":
        return wire_recovery_lineage(body, reference)
    if kind == "name":
        return name_recovery_lineage(body)
    if kind == "instance":
        from .native_instance_ledger import instance_recovery_lineage

        return instance_recovery_lineage(body)
    unavailable = {
        "state": "unavailable",
        "scope": "Recorded recovery metadata is incomplete or inconsistent; inspect original evidence.",
    }
    if kind != "signal-default" or body.get("operation_profile") != DEFAULT_PROFILE:
        return unavailable
    try:
        origin = RecordedOrigin.model_validate(body.get("recovery_origin"))
    except ValueError:
        return unavailable
    compilation = body.get("compilation")
    selected = compilation.get("selected_edit") if isinstance(compilation, dict) else None
    edit = body.get("default_edit")
    if (
        not isinstance(selected, dict)
        or not isinstance(edit, dict)
        or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
        or origin.parent_receipt_id == body.get("id")
        or origin.current_capture_id != body.get("review_capture_id")
        or origin.record_ref != reference.get("object")
        or origin.record_ref != edit.get("record_ref")
        or origin.record_ref != selected.get("record_ref")
        or type(selected.get("class_id")) is not int
        or origin.class_id != selected["class_id"]
        or origin.current_effective_bits != origin.recorded_after_bits
        or origin.proposal_bits != origin.previous_effective_bits
        or origin.previous_effective_bits == origin.recorded_after_bits
        or selected.get("before_bits") != origin.current_effective_bits
        or selected.get("after_bits") != origin.previous_effective_bits
        or "native_reference_issue" in reference
    ):
        return unavailable
    return {
        "state": "recorded",
        "parent_receipt_id": origin.parent_receipt_id,
        "parent_intent_sha256": origin.parent_intent_sha256,
        "record_ref": origin.record_ref,
        "before_bits": origin.current_effective_bits,
        "after_bits": origin.previous_effective_bits,
        "before_value": struct.unpack(">f", bytes.fromhex(origin.current_effective_bits))[0],
        "after_value": struct.unpack(">f", bytes.fromhex(origin.previous_effective_bits))[0],
        "verified_proof": origin.verified_proof.model_dump(),
        "original_backup_id": origin.original_backup_id,
        "current_capture_id": origin.current_capture_id,
        "origin_sha256": body["recovery_origin_sha256"],
        "scope": (
            "Recorded origin seal and child-receipt bindings only. This projection does not "
            "revalidate the parent receipt or backup files, authorize recovery or establish live state."
        ),
    }


def name_recovery_lineage(body):
    unavailable = {
        "state": "unavailable",
        "scope": "Recorded recovery metadata is incomplete or inconsistent; inspect original evidence.",
    }
    try:
        origin = RecordedNameOrigin.model_validate(body.get("recovery_origin"))
    except ValueError:
        return unavailable
    compilation = body.get("compilation")
    selected = compilation.get("identity_edit") if isinstance(compilation, dict) else None
    if (
        not isinstance(selected, dict)
        or body.get("profile") != TRANSFER_PROFILE
        or body.get("change_kind") != "name"
        or body.get("name_change_confirmed") is not True
        or body.get("application_transfer_confirmed") is not True
        or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
        or body.get("review_capture_id") != origin.current_capture_id
        or origin.parent_receipt_id == body.get("id")
        or origin.original_backup_id == body.get("backup_id")
        or origin.previous_name == origin.recorded_after_name
        or origin.current_name != origin.recorded_after_name
        or origin.proposal_name != origin.previous_name
        or body.get("old_name") != origin.current_name
        or body.get("new_name") != origin.previous_name
        or type(body.get("old_instance")) is not int
        or type(body.get("new_instance")) is not int
        or body["old_instance"] != origin.instance
        or body["new_instance"] != origin.instance
        or selected.get("change_kind") != "name"
        or selected.get("root_ref") != origin.root_ref
        or type(selected.get("root_class")) is not int
        or selected["root_class"] != origin.root_class
        or selected.get("old_name") != origin.current_name
        or selected.get("new_name") != origin.previous_name
        or type(selected.get("old_instance")) is not int
        or type(selected.get("new_instance")) is not int
        or selected["old_instance"] != origin.instance
        or selected["new_instance"] != origin.instance
    ):
        return unavailable
    return {
        "state": "recorded",
        "profile": NAME_RECOVERY_PROFILE,
        "datatype": "CharacterString",
        "parent_receipt_id": origin.parent_receipt_id,
        "record_ref": origin.root_ref,
        "instance": origin.instance,
        "before_value": origin.current_name,
        "after_value": origin.previous_name,
        "verified_proof": origin.verified_proof.model_dump(),
        "original_backup_id": origin.original_backup_id,
        "current_capture_id": origin.current_capture_id,
        "origin_sha256": body["recovery_origin_sha256"],
        "scope": "Recorded origin seal and child-receipt bindings only. This projection does not revalidate the parent receipt or backup files, authorize recovery or establish live state.",
    }


def boolean_recovery_lineage(body, reference):
    unavailable = {
        "state": "unavailable",
        "scope": "Recorded recovery metadata is incomplete or inconsistent; inspect original evidence.",
    }
    if body.get("operation_profile") != BOOLEAN_TRANSFER_PROFILE:
        return unavailable
    try:
        origin = RecordedBooleanOrigin.model_validate(body.get("recovery_origin"))
    except ValueError:
        return unavailable
    compilation = body.get("compilation")
    selected = compilation.get("selected_edit") if isinstance(compilation, dict) else None
    edit = body.get("default_edit")
    if (
        not isinstance(selected, dict)
        or not isinstance(edit, dict)
        or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
        or origin.parent_receipt_id == body.get("id")
        or origin.current_capture_id != body.get("review_capture_id")
        or origin.record_ref != reference.get("object")
        or origin.record_ref != edit.get("record_ref")
        or type(edit.get("value")) is not bool
        or edit["value"] is not origin.previous_effective_value
        or origin.record_ref != selected.get("record_ref")
        or type(selected.get("class_id")) is not int
        or origin.class_id != selected["class_id"]
        or selected.get("datatype") != "Boolean"
        or selected.get("property") != 3113
        or type(selected.get("before_value")) is not bool
        or type(selected.get("after_value")) is not bool
        or origin.current_effective_value is not origin.recorded_after_value
        or origin.proposal_value is not origin.previous_effective_value
        or origin.previous_effective_value is origin.recorded_after_value
        or selected["before_value"] is not origin.current_effective_value
        or selected["after_value"] is not origin.previous_effective_value
        or origin.previous_tag != boolean_tag(origin.previous_effective_value)
        or origin.recorded_after_tag != boolean_tag(origin.recorded_after_value)
        or origin.current_tag != boolean_tag(origin.current_effective_value)
        or origin.proposal_tag != boolean_tag(origin.proposal_value)
        or selected.get("before_tag") != origin.current_tag
        or selected.get("after_tag") != origin.previous_tag
        or "native_reference_issue" in reference
    ):
        return unavailable
    return {
        "state": "recorded",
        "datatype": "Boolean",
        "parent_receipt_id": origin.parent_receipt_id,
        "parent_intent_sha256": origin.parent_intent_sha256,
        "record_ref": origin.record_ref,
        "before_value": origin.current_effective_value,
        "after_value": origin.previous_effective_value,
        "before_tag": origin.current_tag,
        "after_tag": origin.previous_tag,
        "verified_proof": origin.verified_proof.model_dump(),
        "original_backup_id": origin.original_backup_id,
        "current_capture_id": origin.current_capture_id,
        "origin_sha256": body["recovery_origin_sha256"],
        "scope": (
            "Recorded origin seal and child-receipt bindings only. This projection does not "
            "revalidate the parent receipt or backup files, authorize recovery or establish live state."
        ),
    }


def wire_recovery_lineage(body, reference):
    unavailable = {
        "state": "unavailable",
        "scope": "Recorded recovery metadata is incomplete or inconsistent; inspect original evidence.",
    }
    if body.get("operation_profile") != WIRE_TRANSFER_PROFILE:
        return unavailable
    try:
        historical = (
            isinstance(body.get("recovery_origin"), dict)
            and body["recovery_origin"].get("profile") == HISTORICAL_WIRE_PROFILE
        )
        origin = (
            RecordedHistoricalWireOrigin if historical else RecordedWireOrigin
        ).model_validate(body.get("recovery_origin"))
    except ValueError:
        return unavailable
    compilation = body.get("compilation")
    selected = compilation.get("wire_edit") if isinstance(compilation, dict) else None
    edit = body.get("wire_edit")
    if (
        not isinstance(selected, dict)
        or not isinstance(edit, dict)
        or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
        or origin.parent_receipt_id == body.get("id")
        or origin.current_capture_id != body.get("review_capture_id")
        or origin.diagram_ref != reference.get("object")
        or origin.wire_index != reference.get("native_wire_index")
        or origin.diagram_ref != edit.get("diagram_ref")
        or origin.diagram_ref != selected.get("diagram_ref")
        or type(selected.get("wire_index")) is not int
        or selected["wire_index"] != origin.wire_index
        or type(edit.get("wire_index")) is not int
        or edit["wire_index"] != origin.wire_index
        or seal(selected.get("old")) != seal(origin.current_tuple)
        or seal(edit.get("old")) != seal(origin.current_tuple)
        or seal(selected.get("new")) != seal(origin.previous_tuple)
        or origin.current_tuple != origin.recorded_after_tuple
        or origin.proposal_tuple != origin.previous_tuple
        or origin.previous_tuple[1:] != origin.recorded_after_tuple[1:]
        or origin.previous_tuple[0] == origin.recorded_after_tuple[0]
        or origin.previous_source_ref == origin.recorded_after_source_ref
        or origin.current_source_ref != origin.recorded_after_source_ref
        or origin.proposal_source_ref != origin.previous_source_ref
        or selected.get("old_source_ref") != origin.current_source_ref
        or selected.get("source_ref") != origin.previous_source_ref
        or edit.get("source_ref") != origin.previous_source_ref
        or selected.get("target_ref") != origin.target_ref
        or type(selected.get("source_index_bytes")) is not int
        or selected["source_index_bytes"] != origin.source_index_bytes
        or max(origin.previous_tuple[0], origin.current_tuple[0])
        >= 1 << (8 * origin.source_index_bytes)
        or "native_reference_issue" in reference
        or historical
        and not recorded_pin_matches(origin, body)
    ):
        return unavailable
    return {
        "state": "recorded",
        "datatype": "Wire",
        **(
            {
                "historical_pin": {
                    "source_ref": origin.historical_pin.source_ref,
                    "source_port": origin.historical_pin.old[1],
                    "source_class": origin.historical_pin.source_class,
                    "original_capture_id": origin.historical_pin.original_capture_id,
                    "evidence_sha256": origin.historical_pin_sha256,
                    "scope": "Recorded verified-original pin evidence; no current outgoing connection is inferred.",
                }
            }
            if historical
            else {}
        ),
        "parent_receipt_id": origin.parent_receipt_id,
        "parent_intent_sha256": origin.parent_intent_sha256,
        "record_ref": origin.diagram_ref,
        "wire_index": origin.wire_index,
        "before_source_ref": origin.current_source_ref,
        "after_source_ref": origin.previous_source_ref,
        "before_tuple": origin.current_tuple,
        "after_tuple": origin.previous_tuple,
        "target_ref": origin.target_ref,
        "verified_proof": origin.verified_proof.model_dump(),
        "original_backup_id": origin.original_backup_id,
        "current_capture_id": origin.current_capture_id,
        "origin_sha256": body["recovery_origin_sha256"],
        "scope": (
            "Recorded origin seal and child-receipt bindings only. This projection does not "
            "revalidate the parent receipt or backup files, authorize recovery or establish live state."
        ),
    }
