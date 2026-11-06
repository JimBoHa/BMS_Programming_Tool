"""Recorded binary recovery lineage; no parent, source or field lookup."""

import re
from typing import Literal

from pydantic import Field

from .application_store import PROFILE as TRANSFER_PROFILE
from .models import StrictModel
from .moi_identity import seal
from .native_binary_terminal import PROFILE as TERMINAL_PROFILE
from .native_binary_terminal_ledger import binary_terminal_reference
from .native_binary_terminal_recovery import PROFILE as ORIGIN_PROFILE
from .native_binary_terminal_recovery_transfer import KEYS
from .native_binary_terminal_recovery_transfer import PROFILE as RECOVERY_PROFILE
from .native_encoded_analog_recovery_transfer import KEYS as ENCODED_ANALOG_KEYS
from .native_ledger_details import Digest, Identifier, RecordedProof
from .native_terminal_recovery_transfer import KEYS as LEGACY_KEYS

PROFILE = "native-binary-terminal-recovery-recorded/1"
SCOPE = (
    "Recorded binary terminal recovery origin seal and child-receipt bindings only. "
    "No parent/source lookup or current revalidation, controller query, current terminal/wiring "
    "verification or transfer authority."
)
UNAVAILABLE = (
    "Recorded binary terminal recovery metadata is incomplete or inconsistent; "
    "inspect original evidence."
)


class RecordedBinaryTerminalOrigin(StrictModel):
    profile: Literal[ORIGIN_PROFILE]
    parent_receipt_id: Identifier
    parent_intent_sha256: Digest
    original_dispatch: Literal["possible"]
    verified_proof: RecordedProof
    original_backup_id: Identifier
    original_snapshot_sha256: Digest
    current_capture_id: Identifier
    current_snapshot_sha256: Digest
    object_id: str = Field(strict=True, min_length=1, max_length=80)
    record_ref: str = Field(strict=True, min_length=1, max_length=512)
    previous_slot: int = Field(strict=True, ge=1, le=6)
    recorded_after_slot: int = Field(strict=True, ge=1, le=6)
    current_slot: int = Field(strict=True, ge=1, le=6)
    proposal_slot: int = Field(strict=True, ge=1, le=6)
    current_configuration_sha256: Digest


def binary_recovery_namespace(body):
    return {
        key for key in body if isinstance(key, str) and key.startswith("binary_terminal_recovery_")
    }


def binary_terminal_recovery_reference(body, terminal):
    present = binary_recovery_namespace(body)
    if not present:
        return {}
    unavailable = {
        "native_binary_terminal_recovery": {"state": "unavailable", "scope": UNAVAILABLE}
    }
    try:
        origin = RecordedBinaryTerminalOrigin.model_validate(
            body.get("binary_terminal_recovery_origin")
        )
        if (
            present != KEYS
            or LEGACY_KEYS.intersection(body)
            or ENCODED_ANALOG_KEYS.intersection(body)
            or type(terminal) is not dict
            or terminal.get("state") != "recorded"
            or seal(binary_terminal_reference(body).get("native_binary_terminal")) != seal(terminal)
            or body.get("profile") != TRANSFER_PROFILE
            or body.get("operation_profile") != TERMINAL_PROFILE
            or type(body.get("id")) is not str
            or not re.fullmatch(r"[a-f0-9]{32}", body["id"])
            or body.get("binary_terminal_recovery_profile") != RECOVERY_PROFILE
            or body.get("binary_terminal_recovery_lineage_enforced") is not True
            or body.get("binary_terminal_recovery_parent_receipt") != origin.parent_receipt_id
            or body.get("binary_terminal_recovery_origin_sha256")
            != seal(body["binary_terminal_recovery_origin"])
            or origin.parent_receipt_id == body["id"]
            or type(body.get("backup_id")) is not str
            or not re.fullmatch(r"[a-f0-9]{32}", body["backup_id"])
            or body["backup_id"] == origin.current_capture_id
            or origin.original_backup_id in (origin.current_capture_id, body.get("backup_id"))
            or origin.current_capture_id != body.get("review_capture_id")
            or origin.object_id != terminal["object_id"]
            or origin.record_ref != terminal["record_ref"]
            or origin.current_slot != terminal["old_slot"]
            or origin.proposal_slot != terminal["slot"]
            or origin.current_slot != origin.recorded_after_slot
            or origin.proposal_slot != origin.previous_slot
            or origin.previous_slot == origin.recorded_after_slot
            or origin.current_configuration_sha256 != terminal["configuration_sha256"]
            or type(body.get("target")) is not dict
            or type(body["target"].get("address")) is not str
            or not body["target"]["address"]
            or body["target"].get("device") not in (None, f"device,{body['old_instance']}")
        ):
            return unavailable
        return {
            "native_binary_terminal_recovery": {
                "state": "recorded",
                "profile": PROFILE,
                "origin": origin.model_dump(),
                "origin_sha256": body["binary_terminal_recovery_origin_sha256"],
                "instance": body["old_instance"],
                "lineage_enforced_recorded": True,
                "parent_and_source_revalidated": False,
                "transfer_authority": False,
                "scope": SCOPE,
            }
        }
    except (ValueError, TypeError, AttributeError, KeyError):
        return unavailable
