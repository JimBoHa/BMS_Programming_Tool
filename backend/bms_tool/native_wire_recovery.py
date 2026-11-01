"""Derive one previous existing wire source from a verified retained transfer."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_effective_wire import compiler_from_snapshot
from .moi_identity import MoiIdentity, seal, sha
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof
from .native_wire_compiler import EffectiveWirePreview
from .native_wire_transfer import PROFILE as WIRE_PROFILE
from .native_wire_transfer import compile_wire

PROFILE = "native-wire-source-recovery-draft/1"
SCOPE = (
    "Local previous-source proposal for one existing native connection from a resolved, "
    "historically verified wire transfer. Require the recorded expanded application (or "
    "its exact previous merged image), static directory, route and controller identity. "
    "Other current saved values remain current. No field query, old-plan replay, whole "
    "backup restore or automatic rollback. A new reviewed one-use transfer and full "
    "readback are required; original pin, order, cycle and width restrictions still apply."
)


class NativeWireRecovery(NativeDefaultRecovery):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "wire-source"
            or intent.get("operation_profile") != WIRE_PROFILE
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent.get("old_instance") != intent.get("new_instance")
            or not isinstance(intent.get("old_name"), str)
            or intent.get("old_name") != intent.get("new_name")
            or not isinstance(intent.get("wire_edit"), dict)
            or not isinstance(intent.get("compilation"), dict)
            or not isinstance(intent["compilation"].get("wire_edit"), dict)
            or not isinstance(intent.get("identity"), dict)
            or not isinstance(intent.get("target"), dict)
        ):
            raise ValueError("Select an existing separate native wire-source transfer receipt.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="Wire-source")
        before, original_files = self._original(intent.get("backup_id"))
        old_compiler = compiler_from_snapshot(before, original_files)
        edit = EffectiveWirePreview.model_validate(intent["wire_edit"]).model_dump()
        expected, compilation = self._forward(original_files, edit, intent=intent)
        selected = compilation["wire_edit"]
        recorded = intent["compilation"]["wire_edit"]
        keys = (
            "diagram_ref",
            "wire_index",
            "old",
            "new",
            "old_source_ref",
            "source_ref",
            "target_ref",
            "source_class",
            "source_index_offset",
            "source_index_bytes",
        )
        if (
            sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
            or seal({key: recorded.get(key) for key in keys})
            != seal({key: selected[key] for key in keys})
            or not selected["changed"]
        ):
            raise ValueError(
                "Original wire backup, edit, configuration and native payload disagree."
            )
        current, files = self.records.load_files(
            {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        )
        compiler = compiler_from_snapshot(current, files)
        if (
            current["device"] != before["device"]
            or current["device"] != f"device,{intent['new_instance']}"
            or seal(current["target"]) != seal(intent["target"])
            or seal(before["target"]) != seal(intent["target"])
            or seal(current["identity"]) != seal(intent["identity"])
            or seal(before["identity"]) != seal(intent["identity"])
        ):
            raise ValueError(
                "The current wire source has a different controller route or identity."
            )
        native_hash = sha(MoiIdentity(files[3]).data)
        previous_hash = sha(MoiIdentity(old_compiler.merged).data)
        if (
            native_hash not in (intent["native_payload_sha256"], previous_hash)
            or files[11] != original_files[11]
        ):
            raise ValueError(
                "The recorded wire application or static directory changed; use separate engineering."
            )
        inspection = compiler.effective.inspect(edit["diagram_ref"], edit["wire_index"])
        wire = inspection["selected_wire"]
        already = native_hash == previous_hash
        wanted_tuple = selected["old"] if already else selected["new"]
        wanted_ref = selected["old_source_ref"] if already else selected["source_ref"]
        if (
            wire is None
            or seal(wire["old"]) != seal(wanted_tuple)
            or wire["source_ref"] != wanted_ref
            or wire["target_ref"] != selected["target_ref"]
            or wire["source_index_bytes"] != selected["source_index_bytes"]
        ):
            raise ValueError("The current effective connection differs from the recorded outcome.")
        proposal = {
            "capture_id": current["id"],
            "snapshot_sha256": current["evidence_sha256"],
            "source_sha256": sha(files[3]),
            "diagram_ref": edit["diagram_ref"],
            "record_sha256": compiler.archive.reader.records[edit["diagram_ref"]]["sha256"],
            "wire_index": edit["wire_index"],
            "property_sha256": inspection["property_sha256"],
            "old": wire["old"],
            "source_ref": selected["old_source_ref"],
            "effective_sha256": compiler.effective.editor.source_sha256,
            "effective_record_sha256": inspection["record_sha256"],
        }
        # Re-run the existing compiler's pin/configuration/order/cycle/width checks.
        # Knowing a prior source does not authorize an otherwise unsupported edit.
        _, inverse = self._inverse(
            files, proposal, original=(before, old_compiler), selected=selected
        )
        if seal(inverse["wire_edit"]["new"]) != seal(selected["old"]):
            raise ValueError("The previous source no longer has its original connection index.")
        origin = {
            "profile": PROFILE,
            "parent_receipt_id": options.receipt_id,
            "parent_intent_sha256": intent["evidence_sha256"],
            "original_dispatch": "possible",
            "verified_proof": proof,
            "original_backup_id": before["id"],
            "original_snapshot_sha256": before["evidence_sha256"],
            "current_capture_id": current["id"],
            "current_snapshot_sha256": current["evidence_sha256"],
            "diagram_ref": edit["diagram_ref"],
            "class_id": compiler.archive.reader.records[edit["diagram_ref"]]["class_id"],
            "property": 3118,
            "wire_index": edit["wire_index"],
            "previous_tuple": selected["old"],
            "recorded_after_tuple": selected["new"],
            "current_tuple": wire["old"],
            "proposal_tuple": selected["old"],
            "previous_source_ref": selected["old_source_ref"],
            "recorded_after_source_ref": selected["source_ref"],
            "current_source_ref": wire["source_ref"],
            "proposal_source_ref": selected["old_source_ref"],
            "target_ref": wire["target_ref"],
            "source_index_bytes": selected["source_index_bytes"],
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": self.records.envelope(current, files),
            "origin": origin,
            "origin_sha256": seal(origin),
            "already_recorded": already,
            "proposal": None
            if already
            else {**proposal, "recovery_parent_receipt": options.receipt_id},
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "new_review_required": not already,
        }
        return self._report(body, inverse, compiler)

    def _inverse(self, files, proposal, *, original, selected):
        return compile_wire(files, proposal)

    def _forward(self, files, edit, *, intent):
        return compile_wire(files, edit, fresh=True, expected_guard=intent.get("wire_guard"))

    def _report(self, body, inverse, compiler):
        return {**body, "evidence_sha256": seal(body)}
