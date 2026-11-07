"""Fresh previous-batch transfers rederive immutable lineage before dispatch."""

from .moi_identity import seal
from .native_default_batch import BatchPreview
from .native_default_batch_recovery import PROFILE as ORIGIN_PROFILE

PROFILE = "native-default-batch-recovery-transfer/1"
SCOPE = (
    "Apply only previous effective typed defaults derived from a resolved, verified "
    "original batch receipt and matching retained current source. Revalidate that "
    "lineage before preview and durable intent; preserve fresh unselected settings. "
    "Require a new confirmed one-use restore and complete native/effective readback. "
    "No old-token replay, general rollback, graph allocation, CCT or physical acceptance."
)
METADATA = {"recovery_profile", "recovery_scope", "recovery_origin", "recovery_origin_sha256"}


def recovery_origin(service, options, compilation):
    if options.recovery_parent_receipt is None:
        return {}
    prepared = service.default_batch_recovery.prepare(
        {
            "receipt_id": options.recovery_parent_receipt,
            "capture_id": options.capture_id,
            "snapshot_sha256": options.snapshot_sha256,
        }
    )
    proposal = options.model_dump(include=set(BatchPreview.model_fields))
    if (
        prepared["proposal"] is None
        or prepared["proposal"] != proposal
        or prepared["origin_sha256"] != options.recovery_origin_sha256
        or compilation["batch_guard"] != prepared["compilation"]["batch_guard"]
    ):
        raise ValueError(
            "Previous batch lineage or selected values changed; prepare and review again."
        )
    return {
        "recovery_profile": PROFILE,
        "recovery_scope": SCOPE,
        "recovery_origin": prepared["origin"],
        "recovery_origin_sha256": prepared["origin_sha256"],
    }


def validate_plan(body, options):
    if options.recovery_parent_receipt is None:
        if METADATA.intersection(body):
            raise ValueError("An ordinary batch review cannot acquire recovery metadata.")
        return
    origin = body.get("recovery_origin")
    if (
        not METADATA.issubset(body)
        or body["recovery_profile"] != PROFILE
        or body["recovery_scope"] != SCOPE
        or not isinstance(origin, dict)
        or origin.get("profile") != ORIGIN_PROFILE
        or origin.get("parent_receipt_id") != options.recovery_parent_receipt
        or origin.get("current_capture_id") != options.capture_id
        or origin.get("current_snapshot_sha256") != options.snapshot_sha256
        or body["recovery_origin_sha256"] != options.recovery_origin_sha256
        or seal(origin) != options.recovery_origin_sha256
    ):
        raise ValueError("The previous batch review lost its exact recovery lineage.")
