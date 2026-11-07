"""Correlate retained native order snapshots with reconstructed historical results."""

from fastapi import APIRouter

from .application_store import PROFILE as APPLICATION_PROFILE
from .application_store import encoded
from .moi_execution_order import MoiExecutionOrder
from .moi_identity import MoiIdentity, seal, sha
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof
from .native_execution_order import EffectiveOrderCompiler, NativeExecutionOrder
from .native_order_transfer import PROFILE as TRANSFER_PROFILE
from .native_order_transfer import compile_order, validate_order_evidence

PROFILE = "native-execution-order-result-match/1"
SCOPE = (
    "Local retained-source comparison with a reconstructed, historically verified native "
    "execution-order result. Compare original route/identity, expanded/effective application "
    "and recorded membership/order/widths/wire relationships separately. No current-device "
    "verification, field query, recovery proposal, review, compilation artifact or transfer."
)


def members(selection):
    return [
        {key: row[key] for key in ("index", "ref", "class_id", "object")}
        for row in selection["members"]
    ]


def order_comparisons(expected, current):
    return {
        "diagram_class_matches": current["diagram_class_id"] == expected["diagram_class_id"],
        "membership_matches": members(current) == members(expected),
        "selected_order_matches": current["original_order"] == expected["original_order"],
        "payload_widths_match": [row["payload_bytes"] for row in current["slots"]]
        == [row["payload_bytes"] for row in expected["slots"]],
        "wire_relationships_match": current["edge_relationships"] == expected["edge_relationships"],
    }


class NativeOrderResultMatch(NativeDefaultRecovery):
    def proof(self, receipt, reference):
        intent = receipt["intent"]
        proof = (
            receipt["result"]
            if reference["kind"] == "result"
            else self.storage.verified_readback(intent["id"])
        )
        if (
            type(proof) is not dict
            or proof.get("receipt_id") != intent["id"]
            or proof.get("evidence_sha256") != reference["sha256"]
            or seal({k: v for k, v in proof.items() if k != "evidence_sha256"})
            != reference["sha256"]
            or (
                reference["kind"] == "result"
                and proof.get("intent_sha256") != intent["evidence_sha256"]
            )
        ):
            raise ValueError(
                "The retained order verification proof does not bind its original intent."
            )
        observed = proof if reference["kind"] == "result" else proof.get("detail")
        preservation = observed.get("preservation") if type(observed) is dict else None
        if (
            type(observed) is not dict
            or observed.get("status") != "verified"
            or observed.get("operational") is not True
            or type(observed.get("system_status")) is not int
            or observed["system_status"] != 0
            or observed.get("native_sha256") != intent.get("native_payload_sha256")
            or observed.get("expected_native_sha256") != intent.get("native_payload_sha256")
            or type(observed.get("readback")) is not dict
            or observed["readback"].get("identity") != intent.get("identity")
            or observed["readback"].get("status") != "verified_new"
            or type(preservation) is not dict
            or preservation.get("application_matches_reviewed_order_and_fresh_settings") is not True
            or preservation.get("other_merged_application_bytes_preserved") is not True
            or preservation.get("identity_unchanged") is not True
            or preservation.get("preserved_native_sha256") != intent.get("native_payload_sha256")
            or preservation.get("controller_writes") is not False
        ):
            raise ValueError(
                "The retained order verification proof has inconsistent native evidence."
            )
        return preservation

    def compare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != APPLICATION_PROFILE
            or intent.get("change_kind") != "execution-order"
            or intent.get("operation_profile") != TRANSFER_PROFILE
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent["old_instance"] != intent.get("new_instance")
            or type(intent.get("old_name")) is not str
            or intent["old_name"] != intent.get("new_name")
            or type(intent.get("identity")) is not dict
            or type(intent.get("target")) is not dict
            or any(key.startswith("recovery_") for key in intent)
        ):
            raise ValueError("Select a supported original native execution-order transfer result.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="execution-order")
        preservation = self.proof(receipt, proof)
        before, original = self._original(intent.get("backup_id"))
        EffectiveOrderCompiler(before, original)
        edit, guard = intent.get("order_edit"), intent.get("order_guard")
        validate_order_evidence(edit, guard)
        if encoded(preservation.get("selected_order")) != encoded(
            {
                "diagram_ref": edit["diagram_ref"],
                "before": guard["original_order"],
                "after": edit["proposed_order"],
                "payload_widths": guard["payload_widths"],
                "edge_relationships_sha256": guard["edge_relationships_sha256"],
                "effective_order_verified": True,
            }
        ):
            raise ValueError("The retained order proof differs from the original permutation.")
        payload, compilation = compile_order(original, edit, fresh=True, expected_guard=guard)
        expected = MoiIdentity(payload)
        if (
            encoded(compilation) != encoded(intent.get("compilation"))
            or sha(payload) != intent.get("payload_sha256")
            or sha(expected.data) != intent.get("native_payload_sha256")
            or before["device"] != f"device,{intent['new_instance']}"
            or seal(before["identity"]) != seal(intent["identity"])
            or seal(before["target"]) != seal(intent["target"])
        ):
            raise ValueError(
                "Original order files, guards, compilation, identity and result disagree."
            )
        query = {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        snapshot, files = self.records.load_files(query)
        compiler = EffectiveOrderCompiler(snapshot, files)
        diagram = edit["diagram_ref"]
        if diagram not in compiler.archive.reader.records:
            raise ValueError("The selected retained snapshot lacks the original recorded diagram.")
        source_query = {
            **query,
            "source_sha256": sha(files[3]),
            "diagram_ref": diagram,
            "record_sha256": compiler.archive.reader.records[diagram]["sha256"],
        }
        source = NativeExecutionOrder(self.records).source(source_query)
        archive = compiler.archive.inspect(diagram)
        current = source["selection"]
        expected_selection = MoiExecutionOrder(payload).inspect(diagram)
        comparisons = {
            "route_matches": seal(snapshot["target"]) == seal(intent["target"]),
            "identity_matches": seal(snapshot["identity"]) == seal(intent["identity"]),
            "expanded_application_matches": archive["source_native_sha256"] == sha(expected.data),
            "effective_application_matches": current["source_native_sha256"] == sha(expected.data),
            "original_saved_directory_matches": files[11] == original[11],
            **order_comparisons(expected_selection, current),
        }
        matched = snapshot.get("source_identity_matches") is True and all(
            value for key, value in comparisons.items() if key != "original_saved_directory_matches"
        )
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "receipt_id": options.receipt_id,
            "intent_sha256": intent["evidence_sha256"],
            "verified_proof": proof,
            "original_backup_id": before["id"],
            "original_snapshot_sha256": before["evidence_sha256"],
            "recorded_target": intent["target"],
            "current_target": snapshot["target"],
            "recorded_identity": intent["identity"],
            "diagram_ref": diagram,
            "expected_native_sha256": sha(expected.data),
            "source": source,
            "archive_selection": archive,
            "expected_selection": expected_selection,
            "comparisons": comparisons,
            "state": "application-and-order-match" if matched else "different",
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "field_transfer_enabled": False,
            "current_device_verified": False,
            "parent_revalidated": False,
        }
        return {**body, "evidence_sha256": seal(body)}


def order_result_match_router(records):
    service = NativeOrderResultMatch(records)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/execution-order/result")

    @router.post("/compare")
    def compare(body: DefaultRecoveryPrepare):
        return service.compare(body.model_dump())

    return router
