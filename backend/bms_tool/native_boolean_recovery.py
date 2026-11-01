"""Previous strict effective Boolean values require original verified transfer evidence."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_effective_boolean import compiler_from_snapshot
from .moi_identity import MoiIdentity, seal, sha
from .native_boolean_copies import BooleanCopyPreview
from .native_boolean_transfer import PROFILE as DEFAULT_PROFILE
from .native_boolean_transfer import compile_boolean_default
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof

PROFILE = "native-boolean-default-recovery-draft/1"
SCOPE = (
    "Local previous-effective-Boolean-value proposal from a resolved, historically verified "
    "Boolean-default receipt. The current retained expanded application and static directory "
    "must match the original recorded outcome; other current saved values remain current. "
    "No field query, command, old-plan replay, whole-backup restore or automatic rollback. "
    "A separately confirmed new Boolean review/apply/full readback is required."
)


def tag(value):
    if type(value) is not bool:
        raise ValueError("The recorded Boolean recovery value must be an actual Boolean.")
    return "11" if value else "10"


class NativeBooleanRecovery(NativeDefaultRecovery):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "boolean-default"
            or intent.get("operation_profile") != DEFAULT_PROFILE
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent.get("old_instance") != intent.get("new_instance")
            or not isinstance(intent.get("old_name"), str)
            or intent.get("old_name") != intent.get("new_name")
            or not isinstance(intent.get("default_edit"), dict)
            or not isinstance(intent.get("compilation"), dict)
            or not isinstance(intent["compilation"].get("selected_edit"), dict)
            or not isinstance(intent.get("identity"), dict)
            or not isinstance(intent.get("target"), dict)
        ):
            raise ValueError("Select an existing separate native Boolean-default transfer receipt.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="Boolean-default")
        before, original_files = self._original(intent.get("backup_id"))
        compiler_from_snapshot(before, original_files)
        edit = BooleanCopyPreview.model_validate(
            {
                **intent["default_edit"],
                "capture_id": before["id"],
                "snapshot_sha256": before["evidence_sha256"],
                "source_sha256": sha(original_files[3]),
            }
        ).model_dump(include={"record_ref", "encoded_sha256", "value"})
        expected, compilation = compile_boolean_default(original_files, edit)
        selected = compilation["selected_edit"]
        recorded = intent["compilation"]["selected_edit"]
        keys = (
            "record_ref",
            "class_id",
            "property",
            "datatype",
            "before_value",
            "after_value",
            "before_tag",
            "after_tag",
        )
        if (
            sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
            or seal({key: recorded.get(key) for key in keys})
            != seal({key: selected[key] for key in keys})
            or not selected["changed"]
        ):
            raise ValueError("Original Boolean backup, edit and recorded native payload disagree.")
        prior, after = selected["before_value"], selected["after_value"]
        if tag(prior) != selected["before_tag"] or tag(after) != selected["after_tag"]:
            raise ValueError("The original Boolean values and native tags disagree.")
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
                "The current Boolean source has a different controller route or identity."
            )
        if (
            sha(MoiIdentity(files[3]).data) != intent["native_payload_sha256"]
            or files[11] != original_files[11]
        ):
            raise ValueError(
                "The recorded Boolean application or static directory changed; use separate engineering."
            )
        field = next((row for row in compiler.fields() if row["ref"] == edit["record_ref"]), None)
        if field is None or field["class_id"] != selected["class_id"]:
            raise ValueError("The original selected Boolean field no longer matches this source.")
        current_tag = tag(field["effective_value"])
        if field["effective_value"] is not prior and field["effective_value"] is not after:
            raise ValueError("The current effective Boolean value is outside the recorded outcome.")
        already = field["effective_value"] is prior
        proposal = {
            "capture_id": current["id"],
            "snapshot_sha256": current["evidence_sha256"],
            "source_sha256": sha(files[3]),
            "record_ref": field["ref"],
            "encoded_sha256": field["encoded_sha256"],
            "value": prior,
            "recovery_parent_receipt": options.receipt_id,
        }
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
            "record_ref": field["ref"],
            "class_id": field["class_id"],
            "property": 3113,
            "previous_effective_value": prior,
            "recorded_after_value": after,
            "current_effective_value": field["effective_value"],
            "proposal_value": prior,
            "previous_tag": tag(prior),
            "recorded_after_tag": tag(after),
            "current_tag": current_tag,
            "proposal_tag": tag(prior),
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": self.records.envelope(current, files),
            "origin": origin,
            "origin_sha256": seal(origin),
            "previous_effective_value": prior,
            "recorded_after_value": after,
            "current_effective_value": field["effective_value"],
            "already_recorded": already,
            "proposal": None if already else proposal,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "new_review_required": not already,
        }
        return {**body, "evidence_sha256": seal(body)}
