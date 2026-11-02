"""Previous point names require exact original, outcome and current-source evidence."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_identity import MoiIdentity, controller_name, seal, sha
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof
from .native_point_names import PROFILE as POINT_PROFILE
from .native_point_names import PointNameCompiler, PointNameEdit, compile_point_name, replace_name
from .native_signal_compiler import compiler_from_snapshot

PROFILE = "native-point-name-recovery-draft/1"
SCOPE = (
    "Local previous point-name proposal from a resolved historically verified point-name "
    "transfer. Require the same point identifier/reference, Device identity, route, static "
    "directory and otherwise unchanged original-after application. Other current saved "
    "settings remain current. No field query, old-plan replay, allocation or automatic "
    "rollback. A new confirmed point-name review, transfer and full readback are required."
)


class NativePointNameRecovery(NativeDefaultRecovery):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("operation_profile") != POINT_PROFILE
            or intent.get("change_kind") != "point-name"
            or intent.get("point_name_confirmed") is not True
            or intent.get("application_transfer_confirmed") is not True
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent.get("new_instance") != intent["old_instance"]
            or type(intent.get("new_instance")) is not int
            or type(intent.get("identity")) is not dict
            or type(intent.get("target")) is not dict
            or type(intent.get("compilation")) is not dict
        ):
            raise ValueError("Select a confirmed native point-name transfer receipt.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="point-name")
        before, originals = self._original(intent.get("backup_id"))
        compiler_from_snapshot(before, originals)
        edit = PointNameEdit.model_validate(intent.get("point_name_edit")).model_dump()
        if edit != intent["point_name_edit"]:
            raise ValueError("Original point-name edit is not canonical.")
        expected, compilation = compile_point_name(originals, edit)
        selected = compilation["selected_edit"]
        previous = controller_name(selected["before"])
        after = selected["after"]
        if (
            not selected["changed"]
            or seal(compilation) != seal(intent["compilation"])
            or sha(expected) != intent.get("payload_sha256")
            or sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
            or before["device"] != f"device,{intent['old_instance']}"
            or seal(before["identity"]) != seal(intent["identity"])
            or seal(before["target"]) != seal(intent["target"])
            or before["identity"].get("object-name") != intent.get("old_name")
            or intent.get("old_name") != intent.get("new_name")
        ):
            raise ValueError("Original point-name backup, identity, edit or payload disagree.")
        current, files = self.records.load_files(
            {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        )
        compiler_from_snapshot(current, files)
        if (
            current["device"] != before["device"]
            or seal(current["identity"]) != seal(before["identity"])
            or seal(current["target"]) != seal(before["target"])
            or files[11] != originals[11]
        ):
            raise ValueError(
                "Current point-name source identity, route or static directory changed."
            )
        compiler = PointNameCompiler(files)
        field = next((p for p in compiler.fields() if p["object_id"] == edit["object_id"]), None)
        if not field or field["record_ref"] != edit["record_ref"]:
            raise ValueError("The original point identifier or native reference changed.")
        name = field["name"]
        if name not in (previous, after):
            raise ValueError("The current point name differs from its recorded before/after names.")
        # Compare raw File3 rather than a fresh saved-value merge. Only this
        # existing name is normalized; current other saved settings stay current.
        raw = MoiIdentity(files[3])
        candidates = [
            r
            for r in raw.records
            if raw.reader.scalar(r, 75) == edit["object_id"]
            and raw.reader.scalar(r, 32527) == edit["record_ref"]
        ]
        if len(candidates) != 1:
            raise ValueError("The current native point is not unambiguous.")
        normalized, change = replace_name(raw, candidates[0], after)
        if change["before"] != name or MoiIdentity(normalized).data != MoiIdentity(expected).data:
            raise ValueError("The recorded application changed beyond this point name.")
        proposal_edit = PointNameEdit(
            object_id=field["object_id"],
            record_ref=field["record_ref"],
            encoded_sha256=field["encoded_sha256"],
            new_name=previous,
        ).model_dump()
        # The regular compiler independently checks collisions, encoding and
        # preservation for the previous name against current effective settings.
        compile_point_name(files, proposal_edit)
        already = name == previous
        origin = {
            "profile": PROFILE,
            "parent_receipt_id": options.receipt_id,
            "parent_intent_sha256": intent["evidence_sha256"],
            "original_dispatch": "possible",
            "verified_proof": proof,
            "original_backup_id": before["id"],
            "original_snapshot_sha256": before["evidence_sha256"],
            "original_after_native_sha256": intent["native_payload_sha256"],
            "current_capture_id": current["id"],
            "current_snapshot_sha256": current["evidence_sha256"],
            "current_archive_sha256": sha(files[3]),
            "object_id": field["object_id"],
            "record_ref": field["record_ref"],
            "current_name_sha256": field["encoded_sha256"],
            "native_class": field["native_class"],
            "property": 2390,
            "character_encoding": selected["character_encoding"],
            "previous_name": previous,
            "recorded_after_name": after,
            "current_name": name,
            "proposal_name": previous,
        }
        proposal = {
            **proposal_edit,
            "capture_id": current["id"],
            "snapshot_sha256": current["evidence_sha256"],
            "recovery_parent_receipt": options.receipt_id,
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": self.records.envelope(current, files),
            "origin": origin,
            "origin_sha256": seal(origin),
            "previous_name": previous,
            "recorded_after_name": after,
            "current_name": name,
            "already_recorded": already,
            "proposal": None if already else proposal,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "new_review_required": not already,
        }
        return {**body, "evidence_sha256": seal(body)}
