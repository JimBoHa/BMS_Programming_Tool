"""Recorded previous-order lineage without parent, capture or controller access."""

import copy
import re

from .application_store import PROFILE as APPLICATION_PROFILE
from .moi_identity import seal
from .native_execution_order import OrderPreview
from .native_order_recovery_transfer import validate_recorded_lineage
from .native_order_transfer import PROFILE as ORDER_PROFILE
from .native_order_transfer import OrderConfigurationGuard, validate_order_evidence

PROFILE = "native-execution-order-recovery-recorded/1"
SCOPE = (
    "Recorded previous-order origin seal and child-receipt bindings only. Parent receipts, "
    "backup files and current controller state are not revalidated. This projection grants "
    "no recovery or transfer authority."
)


def recovery_namespace(body):
    return type(body) is dict and any(key.startswith("recovery_") for key in body)


def recovery_reference(body):
    unavailable = {
        "native_order_recovery": {
            "state": "unavailable",
            "scope": "Previous-order lineage is incomplete or inconsistent; inspect original evidence.",
        }
    }
    try:
        origin = validate_recorded_lineage(body)
        validate_order_evidence(body.get("order_edit"), body.get("order_guard"))
        edit = OrderPreview.model_validate(body["order_edit"])
        guard = OrderConfigurationGuard.model_validate(body["order_guard"])
        c = body["compilation"]
        selection = c["order_edit"]["selection"]
        instance = body["old_instance"]
        if (
            origin is None
            or body.get("profile") != APPLICATION_PROFILE
            or body.get("change_kind") != "execution-order"
            or body.get("operation_profile") != ORDER_PROFILE
            or type(instance) is not int
            or not 0 <= instance <= 4194302
            or type(body.get("new_instance")) is not int
            or body.get("new_instance") != instance
            or body.get("identity", {}).get("device") != f"device,{instance}"
            or type(body["identity"].get("vendor-identifier")) is not int
            or body["identity"]["vendor-identifier"] != 5
            or not re.fullmatch(r"[a-f0-9]{32}", body.get("id", ""))
            or body.get("review_capture_id") != edit.capture_id
            or body.get("review_snapshot_sha256") != edit.snapshot_sha256
            or c["order_guard"] != guard.model_dump()
            or c["order_edit"]["proposed_order"] != edit.proposed_order
            or selection["diagram_ref"] != edit.diagram_ref
            or selection["original_order"] != guard.original_order
            or [slot["payload_bytes"] for slot in selection["slots"]] != guard.payload_widths
            or c["order_compilation_sha256"]
            != seal({k: v for k, v in c.items() if k != "order_compilation_sha256"})
            or body.get("payload_sha256") != c["compiled_sha256"]
            or body.get("native_payload_sha256") != c["compiled_native_sha256"]
            or not re.fullmatch(r"[a-f0-9]{64}", c["compiled_native_sha256"])
        ):
            return unavailable
        return {
            "native_order_recovery": {
                "state": "recorded",
                "profile": PROFILE,
                "scope": SCOPE,
                "child_receipt_id": body["id"],
                "instance": instance,
                "diagram_ref": edit.diagram_ref,
                "before": guard.original_order,
                "after": edit.proposed_order,
                "payload_widths": guard.payload_widths,
                "review_capture_id": edit.capture_id,
                "review_snapshot_sha256": edit.snapshot_sha256,
                "origin": copy.deepcopy(origin),
                "origin_sha256": body["recovery_origin_sha256"],
                "compiled_native_sha256": c["compiled_native_sha256"],
                "field_authority": False,
                "parent_revalidated": False,
                "source_revalidated": False,
                "current_device_verified": False,
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return unavailable
