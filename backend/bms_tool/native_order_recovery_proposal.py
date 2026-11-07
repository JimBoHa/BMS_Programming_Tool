"""Compile a local previous-order proposal from a matching verified original result."""

from fastapi import APIRouter

from .application_store import encoded
from .moi_identity import seal
from .native_default_recovery import DefaultRecoveryPrepare
from .native_execution_order import NativeExecutionOrder, OrderPreview
from .native_order_result_match import NativeOrderResultMatch

PROFILE = "native-previous-execution-order-proposal/1"
SCOPE = (
    "Local previous-order assistance from an original historically verified execution-order "
    "transfer and an exactly matching retained after application, effective order and static "
    "saved directory. Compile the original permutation with current captured saved settings, "
    "preserving existing members, Unsigned widths, wire phase and every other merged byte. "
    "No current-device verification, field query, old-plan replay, recovery lineage, review "
    "authority or automatic rollback. A separately confirmed fresh controller review, transfer "
    "and full readback remain required; general compiler, CCT and physical acceptance are separate."
)


class NativeOrderRecoveryProposal(NativeOrderResultMatch):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        comparison = self.compare(options.model_dump())
        if (
            comparison["state"] != "application-and-order-match"
            or comparison["comparisons"]["original_saved_directory_matches"] is not True
        ):
            raise ValueError(
                "The retained application, effective order and static directory must match the "
                "verified original after result. Inspect differences instead of guessing a rollback."
            )
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if intent["evidence_sha256"] != comparison["intent_sha256"]:
            raise ValueError("The original order intent changed during proposal preparation.")
        source = comparison["source"]
        proposed = OrderPreview.model_validate(
            {
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
                "source_sha256": source["source_sha256"],
                "diagram_ref": comparison["diagram_ref"],
                "record_sha256": source["archive_record_sha256"],
                "effective_sha256": source["effective_sha256"],
                "effective_record_sha256": source["selection"]["record_sha256"],
                "selection_sha256": source["selection"]["selection_sha256"],
                "proposed_order": intent["order_guard"]["original_order"],
            }
        ).model_dump()
        if proposed["proposed_order"] == source["selection"]["original_order"]:
            raise ValueError("The original transfer has no distinct previous order to propose.")
        _, preview = NativeExecutionOrder(self.records).preview(proposed)
        if encoded(preview["source"]) != encoded(source):
            raise ValueError("The retained source changed during previous-order compilation.")
        origin = {
            "parent_receipt_id": options.receipt_id,
            "parent_intent_sha256": comparison["intent_sha256"],
            "verified_proof": comparison["verified_proof"],
            "original_backup_id": comparison["original_backup_id"],
            "original_snapshot_sha256": comparison["original_snapshot_sha256"],
            "comparison_sha256": comparison["evidence_sha256"],
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "comparison": comparison,
            "origin": origin,
            "origin_sha256": seal(origin),
            "proposal": proposed,
            "preview": preview,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "field_transfer_enabled": False,
            "current_device_verified": False,
            "new_review_required": True,
            "recovery_lineage_recorded": False,
        }
        return {**body, "evidence_sha256": seal(body)}


def order_recovery_proposal_router(records):
    service = NativeOrderRecoveryProposal(records)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/execution-order/recovery")

    @router.post("/prepare")
    def prepare(body: DefaultRecoveryPrepare):
        return service.prepare(body.model_dump())

    return router
