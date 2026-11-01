"""Bounded native receipt metadata, without loading backup files or parent journals."""

import math
import struct
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .models import StrictModel
from .moi_identity import seal
from .native_default_recovery import PROFILE as RECOVERY_PROFILE
from .native_default_transfer import PROFILE as DEFAULT_PROFILE

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


def native_reference(kind, selection):
    """Read canonical native keys; retain a legacy alias only when unambiguous."""
    if kind not in {"signal-default", "boolean-default", "wire-source"}:
        return {}
    if not isinstance(selection, dict):
        return {"object": "", "native_reference_issue": "Native edit reference was not recorded."}
    key = "diagram_ref" if kind == "wire-source" else "record_ref"
    value = selection.get(key)
    if kind != "wire-source" and key not in selection:
        value = selection.get("ref")
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or kind != "wire-source"
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
