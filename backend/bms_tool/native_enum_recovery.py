"""Previous Enum codes require immutable verified transfer and current source evidence."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_effective_enum import compiler_from_snapshot
from .moi_identity import MoiIdentity, seal, sha
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof
from .native_enum_copies import EnumCopyPreview
from .native_enum_transfer import PROFILE as ENUM_TRANSFER_PROFILE
from .native_enum_transfer import compile_enum_default

PROFILE = "native-enum-default-recovery-draft/1"
SCOPE = (
    "Local previous-effective-Enum-code proposal from a resolved, historically verified "
    "Enum-default receipt. Current expanded application, static directory, selected fixed "
    "storage and encoded state metadata must match the recorded outcome. Other current "
    "saved values remain current. Code meanings and membership remain unverified. No "
    "controller query, old-plan replay, whole-backup restore or automatic rollback. "
    "A separately confirmed new Enum review/apply/full readback is required."
)


def code(value):
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError("Recorded Enum recovery codes require actual unsigned16 integers.")
    return value


def encoding(compiler, reference):
    _, prop = compiler.effective.candidates[reference]
    return compiler.effective.editor.data[
        prop["value_start_offset"] : prop["value_end_offset"]
    ].hex()


class NativeEnumRecovery(NativeDefaultRecovery):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        recorded_compilation = intent.get("compilation")
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "enum-default"
            or intent.get("operation_profile") != ENUM_TRANSFER_PROFILE
            or intent.get("enum_semantics_verified") is not False
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent["old_instance"] != intent.get("new_instance")
            or not isinstance(intent.get("old_name"), str)
            or intent["old_name"] != intent.get("new_name")
            or type(intent.get("default_edit")) is not dict
            or type(recorded_compilation) is not dict
            or type(recorded_compilation.get("selected_edit")) is not dict
            or "states_text_encoded_sha256" not in recorded_compilation
            or type(intent.get("identity")) is not dict
            or type(intent.get("target")) is not dict
        ):
            raise ValueError(
                "Select a native Enum-default receipt with recorded state metadata binding."
            )
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="Enum-default")
        before, original_files = self._original(intent.get("backup_id"))
        compiler_from_snapshot(before, original_files)
        edit = EnumCopyPreview.model_validate(
            {
                **intent["default_edit"],
                "capture_id": before["id"],
                "snapshot_sha256": before["evidence_sha256"],
                "source_sha256": sha(original_files[3]),
            }
        ).model_dump(include={"record_ref", "encoded_sha256", "value"})
        expected, compilation = compile_enum_default(original_files, edit)
        selected, recorded = compilation["selected_edit"], recorded_compilation["selected_edit"]
        keys = (
            "record_ref",
            "class_id",
            "property",
            "datatype",
            "encoded_sha256",
            "before_value",
            "after_value",
            "before_encoding_hex",
            "after_encoding_hex",
        )
        if (
            sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
            or seal({key: recorded.get(key) for key in keys})
            != seal({key: selected[key] for key in keys})
            or compilation["states_text_encoded_sha256"]
            != recorded_compilation["states_text_encoded_sha256"]
            or compilation["saved_storage"] != recorded_compilation.get("saved_storage")
            or not selected["changed"]
        ):
            raise ValueError(
                "Original Enum backup, code, state metadata, storage and native payload disagree."
            )
        prior, after = code(selected["before_value"]), code(selected["after_value"])
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
                "The current Enum source has a different controller route or identity."
            )
        if (
            sha(MoiIdentity(files[3]).data) != intent["native_payload_sha256"]
            or files[11] != original_files[11]
        ):
            raise ValueError(
                "The recorded Enum application or static directory changed; use separate engineering."
            )
        field = next((row for row in compiler.fields() if row["ref"] == edit["record_ref"]), None)
        if field is None or field["class_id"] != selected["class_id"]:
            raise ValueError("The original selected Enum field no longer matches this source.")
        if field["saved_storage"] is None or field["saved_storage"] != compilation["saved_storage"]:
            raise ValueError(
                "Enum recovery requires the unchanged captured selected fixed storage."
            )
        if field["states_text_encoded_sha256"] != compilation["states_text_encoded_sha256"]:
            raise ValueError(
                "The current selected Enum state metadata changed from the recorded outcome."
            )
        value = code(field["effective_value"])
        if value not in (prior, after):
            raise ValueError("The current effective Enum code is outside the recorded outcome.")
        already = value == prior
        proposed = compiler.effective.preview(
            source_sha256=compiler.effective.editor.source_sha256,
            record_ref=field["ref"],
            encoded_sha256=field["encoded_sha256"],
            value=prior,
        )
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
            "current_effective_value": value,
            "proposal_value": prior,
            "previous_encoding_hex": selected["before_encoding_hex"],
            "recorded_after_encoding_hex": selected["after_encoding_hex"],
            "current_encoding_hex": encoding(compiler, field["ref"]),
            "proposal_encoding_hex": proposed["after_encoding_hex"],
            "states_text_encoded_sha256": field["states_text_encoded_sha256"],
            "saved_storage": field["saved_storage"],
            "enum_semantics_verified": False,
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": self.records.envelope(current, files),
            "origin": origin,
            "origin_sha256": seal(origin),
            "previous_effective_value": prior,
            "recorded_after_value": after,
            "current_effective_value": value,
            "already_recorded": already,
            "proposal": None if already else proposal,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "new_review_required": not already,
            "enum_semantics_verified": False,
        }
        return {**body, "evidence_sha256": seal(body)}
