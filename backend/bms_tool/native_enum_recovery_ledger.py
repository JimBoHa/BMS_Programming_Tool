"""Recorded Enum lineage is local receipt evidence, never recovery admission."""

import re
from typing import Annotated, Literal

from pydantic import Field

from .application_store import PROFILE as TRANSFER_PROFILE
from .models import StrictModel
from .moi_identity import controller_name, seal, sha
from .native_enum_recovery import PROFILE as ORIGIN_PROFILE
from .native_enum_transfer import PROFILE as ENUM_TRANSFER_PROFILE
from .native_ledger_details import Digest, Identifier, RecordedProof

PROFILE = "native-enum-recovery-recorded/1"
SCOPE = (
    "Recorded Enum origin seal and child-receipt bindings only. This projection does not "
    "revalidate the parent receipt or backup files, authorize recovery or establish live state. "
    "Code meanings and allowed-state membership remain unverified."
)
UNAVAILABLE = (
    "Recorded Enum recovery metadata is incomplete or inconsistent; inspect original evidence."
)
Code = Annotated[int, Field(strict=True, ge=0, le=65535)]
Encoding = Annotated[str, Field(strict=True, pattern=r"^9[1-4](?:[a-f0-9]{2}){1,4}2f$")]


class RecordedEnumStorage(StrictModel):
    kind: Literal["captured-fixed-enum-slot"]
    datatype: int = Field(strict=True, ge=9, le=9)
    bytes: int = Field(strict=True, ge=2, le=2)
    maximum_code: int = Field(strict=True, ge=65535, le=65535)
    static_record_offset: int = Field(strict=True, ge=0, le=128 * 1024)
    dynamic_value_offset: int = Field(strict=True, ge=0, le=128 * 1024)


class RecordedEnumOrigin(StrictModel):
    profile: Literal[ORIGIN_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    class_id: int = Field(strict=True, ge=528, le=529)
    property: int = Field(strict=True, ge=3113, le=3113)
    previous_effective_value: Code
    recorded_after_value: Code
    current_effective_value: Code
    proposal_value: Code
    previous_encoding_hex: Encoding
    recorded_after_encoding_hex: Encoding
    current_encoding_hex: Encoding
    proposal_encoding_hex: Encoding
    states_text_encoded_sha256: Digest | None
    saved_storage: RecordedEnumStorage
    enum_semantics_verified: bool = Field(strict=True)


def tagged(value, code):
    if not isinstance(value, str) or not re.fullmatch(r"9[1-4](?:[a-f0-9]{2}){1,4}2f", value):
        return False
    return len(value) == (int(value[1]) + 2) * 2 and int(value[2:-2], 16) == code


def enum_recovery_lineage(body, reference):
    unavailable = {"state": "unavailable", "scope": UNAVAILABLE}
    try:
        origin = RecordedEnumOrigin.model_validate(body.get("recovery_origin"))
        compiled, edit = body.get("compilation"), body.get("default_edit")
        selected = compiled.get("selected_edit") if type(compiled) is dict else None
        identity, target = body.get("identity"), body.get("target")
        instance = body.get("old_instance")
        if (
            type(compiled) is not dict
            or type(edit) is not dict
            or type(selected) is not dict
            or body.get("profile") != TRANSFER_PROFILE
            or body.get("change_kind") != "enum-default"
            or body.get("operation_profile") != ENUM_TRANSFER_PROFILE
            or body.get("default_change_confirmed") is not True
            or body.get("application_transfer_confirmed") is not True
            or body.get("enum_semantics_verified") is not False
            or origin.enum_semantics_verified is not False
            or body.get("recovery_origin_sha256") != seal(body["recovery_origin"])
            or origin.parent_receipt_id == body.get("id")
            or origin.original_backup_id in (body.get("backup_id"), origin.current_capture_id)
            or origin.current_capture_id != body.get("review_capture_id")
            or origin.current_snapshot_sha256 != body.get("review_snapshot_sha256")
            or reference.get("object") != origin.record_ref
            or "native_reference_issue" in reference
            or type(instance) is not int
            or not 0 <= instance <= 4194302
            or type(body.get("new_instance")) is not int
            or body["new_instance"] != instance
            or type(identity) is not dict
            or identity.get("device") != f"device,{instance}"
            or type(identity.get("vendor-identifier")) is not int
            or identity["vendor-identifier"] != 5
            or controller_name(body.get("old_name")) != body.get("new_name")
            or identity.get("object-name") != body["old_name"]
            or type(target) is not dict
            or not isinstance(target.get("address"), str)
            or not target["address"]
            or target.get("device") not in (None, f"device,{instance}")
            or compiled.get("profile") != "native-effective-enum-default-compiler/1"
            or compiled.get("enum_semantics_verified") is not False
            or "states_text_encoded_sha256" not in compiled
            or compiled["states_text_encoded_sha256"] != origin.states_text_encoded_sha256
            or seal(compiled.get("saved_storage")) != seal(origin.saved_storage.model_dump())
            or compiled.get("compiled_sha256") != body.get("payload_sha256")
            or compiled.get("compiled_native_sha256") != body.get("native_payload_sha256")
            or not all(
                isinstance(body.get(k), str) and re.fullmatch(r"[0-9a-f]{64}", body[k])
                for k in ("payload_sha256", "native_payload_sha256", "review_sha256")
            )
            or selected.get("profile") != "tagged-moi-enum-default-copy/1"
            or selected.get("record_ref") != origin.record_ref
            or edit.get("record_ref") != origin.record_ref
            or type(selected.get("class_id")) is not int
            or selected["class_id"] != origin.class_id
            or type(selected.get("property")) is not int
            or selected["property"] != 3113
            or selected.get("datatype") != "Enumerated"
            or selected.get("changed") is not True
            or selected.get("enum_semantics_verified") is not False
            or type(edit.get("value")) is not int
            or edit["value"] != origin.previous_effective_value
            or type(selected.get("before_value")) is not int
            or selected["before_value"] != origin.current_effective_value
            or type(selected.get("after_value")) is not int
            or selected["after_value"] != origin.previous_effective_value
            or origin.current_effective_value != origin.recorded_after_value
            or origin.proposal_value != origin.previous_effective_value
            or origin.previous_effective_value == origin.recorded_after_value
            or selected.get("before_encoding_hex") != origin.current_encoding_hex
            or selected.get("after_encoding_hex") != origin.proposal_encoding_hex
            or edit.get("encoded_sha256") != sha(bytes.fromhex(origin.current_encoding_hex))
            or selected.get("encoded_sha256") != edit["encoded_sha256"]
            or not all(
                tagged(getattr(origin, a), getattr(origin, b))
                for a, b in (
                    ("previous_encoding_hex", "previous_effective_value"),
                    ("recorded_after_encoding_hex", "recorded_after_value"),
                    ("current_encoding_hex", "current_effective_value"),
                    ("proposal_encoding_hex", "proposal_value"),
                )
            )
        ):
            return unavailable
        storage = origin.saved_storage
        for number, minimum in (
            ("11", storage.static_record_offset + 16),
            ("12", storage.dynamic_value_offset + 3),
        ):
            size = compiled.get("files", {}).get(number, {}).get("bytes")
            if type(size) is not int or not minimum <= size <= 128 * 1024:
                return unavailable
        width = max(
            int(origin.current_encoding_hex[1]),
            max(1, (origin.proposal_value.bit_length() + 7) // 8),
        )
        if (
            origin.proposal_encoding_hex
            != f"9{width}" + origin.proposal_value.to_bytes(width, "big").hex() + "2f"
        ):
            return unavailable
        return {
            "state": "recorded",
            "profile": PROFILE,
            "datatype": "Enumerated",
            "parent_receipt_id": origin.parent_receipt_id,
            "parent_intent_sha256": origin.parent_intent_sha256,
            "record_ref": origin.record_ref,
            "class_id": origin.class_id,
            "property": 3113,
            "instance": instance,
            "before_value": origin.current_effective_value,
            "after_value": origin.previous_effective_value,
            "before_encoding_hex": origin.current_encoding_hex,
            "after_encoding_hex": origin.proposal_encoding_hex,
            "previous_encoding_hex": origin.previous_encoding_hex,
            "recorded_after_encoding_hex": origin.recorded_after_encoding_hex,
            "states_text_encoded_sha256": origin.states_text_encoded_sha256,
            "saved_storage": storage.model_dump(),
            "enum_semantics_verified": False,
            "verified_proof": origin.verified_proof.model_dump(),
            "original_backup_id": origin.original_backup_id,
            "original_snapshot_sha256": origin.original_snapshot_sha256,
            "current_capture_id": origin.current_capture_id,
            "current_snapshot_sha256": origin.current_snapshot_sha256,
            "origin_sha256": body["recovery_origin_sha256"],
            "scope": SCOPE,
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        return unavailable
