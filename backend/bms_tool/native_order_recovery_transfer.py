"""Fresh previous-order transfers rederive immutable lineage before dispatch."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .models import StrictModel
from .moi_identity import seal
from .native_backup_records import NativeBackupRecords
from .native_execution_order import Hash, OrderPreview

PROFILE = "native-execution-order-recovery-transfer/1"
SCOPE = (
    "Transfer only the previous permutation derived from a resolved historically verified "
    "original execution-order receipt and matching retained after application/order/static "
    "directory. Revalidate the original proof, proposal and lineage before review and durable "
    "intent; retain fresh other saved settings. Require a new confirmed one-use restore and "
    "complete native/effective readback. No old-token replay, automatic inverse, recursive "
    "recovery, new identities, general restore/compiler or CCT/physical acceptance."
)
METADATA = {"recovery_profile", "recovery_scope", "recovery_origin", "recovery_origin_sha256"}
Identifier = str


class OrderRecoveryProof(StrictModel):
    kind: Literal["result", "readback-event"]
    sha256: Hash
    time: str = Field(strict=True, min_length=1, max_length=80)

    @field_validator("time")
    @classmethod
    def explicit_time(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("The original order proof requires an explicit time zone.")
        return value


class OrderRecoveryOrigin(StrictModel):
    parent_receipt_id: Identifier = Field(strict=True, pattern=r"^[0-9a-f]{32}$")
    parent_intent_sha256: Hash
    verified_proof: OrderRecoveryProof
    original_backup_id: Identifier = Field(strict=True, pattern=r"^[0-9a-f]{32}$")
    original_snapshot_sha256: Hash
    comparison_sha256: Hash


def validate_recorded_lineage(body):
    """Check the recorded namespace only; no parent/file access or field authority."""
    present = {key for key in body if key.startswith("recovery_")}
    if not present:
        return None
    if (
        present != METADATA
        or body.get("recovery_profile") != PROFILE
        or body.get("recovery_scope") != SCOPE
    ):
        raise ValueError("The recorded previous-order recovery profile is incomplete.")
    origin = OrderRecoveryOrigin.model_validate(body.get("recovery_origin")).model_dump()
    if (
        origin != body["recovery_origin"]
        or body.get("recovery_origin_sha256") != seal(origin)
        or body.get("id") == origin["parent_receipt_id"]
    ):
        raise ValueError("The previous-order origin and recorded child receipt disagree.")
    return origin


def recovery_origin(service, options, compilation):
    if options.recovery_parent_receipt is None:
        return {}
    # Deferred import avoids coupling original order compilation to its receipt
    # comparison while those format/transfer modules are being initialized.
    from .native_order_recovery_proposal import NativeOrderRecoveryProposal

    prepared = NativeOrderRecoveryProposal(NativeBackupRecords(service.storage)).prepare(
        {
            "receipt_id": options.recovery_parent_receipt,
            "capture_id": options.capture_id,
            "snapshot_sha256": options.snapshot_sha256,
        }
    )
    proposal = options.model_dump(include=set(OrderPreview.model_fields))
    selection = prepared["comparison"]["source"]["selection"]
    guard = compilation["order_guard"]
    if (
        prepared["proposal"] != proposal
        or prepared["origin_sha256"] != options.recovery_origin_sha256
        or compilation["order_edit"]["proposed_order"] != proposal["proposed_order"]
        or guard["diagram_ref"] != proposal["diagram_ref"]
        or guard["original_order"] != selection["original_order"]
        or guard["payload_widths"] != [slot["payload_bytes"] for slot in selection["slots"]]
        or guard["property_sha256"] != selection["property_sha256"]
        or guard["edge_relationships_sha256"] != seal(selection["edge_relationships"])
    ):
        raise ValueError("Previous order, proof or lineage changed; prepare and review again.")
    result = {
        "recovery_profile": PROFILE,
        "recovery_scope": SCOPE,
        "recovery_origin": prepared["origin"],
        "recovery_origin_sha256": prepared["origin_sha256"],
    }
    validate_recorded_lineage(result)
    return result


def validate_plan(body, options):
    origin = validate_recorded_lineage(body)
    if options.recovery_parent_receipt is None:
        if origin is not None:
            raise ValueError("An ordinary order review cannot acquire recovery metadata.")
        return
    if (
        origin is None
        or origin["parent_receipt_id"] != options.recovery_parent_receipt
        or body["recovery_origin_sha256"] != options.recovery_origin_sha256
    ):
        raise ValueError("The previous-order review lost its exact recovery lineage.")


def recorded_parent(body):
    """Malformed historical metadata must not break the whole status listing."""
    try:
        origin = validate_recorded_lineage(body)
        return origin["parent_receipt_id"] if origin is not None else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
