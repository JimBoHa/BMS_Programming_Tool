"""Propose a previous effective Real value from immutable, verified edit evidence.

Preparation is local. Application, static directory and effective-value guards
bind the proposal to the exact recorded outcome; a new field review is required.
"""

import math
import re
import struct

from pydantic import Field

from .application_store import PROFILE as TRANSFER_PROFILE
from .application_store import identifier
from .moi_identity import MoiIdentity, seal, sha
from .native_backup_records import BackupInspectionSource, NativeBackupRecords
from .native_default_transfer import PROFILE as DEFAULT_PROFILE
from .native_default_transfer import compile_default
from .native_signal_compiler import SignalCompilerPreview, compiler_from_snapshot

PROFILE = "native-real-default-recovery-draft/1"
SCOPE = (
    "Local previous-effective-Real-value proposal from a resolved, historically verified "
    "signal-default receipt. Original-after expanded application and static directory must "
    "match the current retained source; other current saved values remain current. "
    "No field query, command, old-plan replay, whole-backup restore or automatic rollback. "
    "A separately confirmed new native review/apply/readback is required."
)


class DefaultRecoveryPrepare(BackupInspectionSource):
    receipt_id: str = Field(pattern=r"^[0-9a-f]{32}$")


def _bits(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}", value):
        raise ValueError("The original Real edit lacks exact finite float32 bits.")
    number = struct.unpack(">f", bytes.fromhex(value))[0]
    if not math.isfinite(number):
        raise ValueError("The original Real edit is outside the finite restoration profile.")
    return number


def _verified_proof(receipt, storage, receipt_id):
    if receipt["pending"]:
        raise ValueError("Reconcile the original transfer before preparing a previous-value edit.")
    intent, result = receipt["intent"], receipt["result"]
    if result is not None and type(result.get("may_have_applied")) is not bool:
        raise ValueError("The original result lacks a qualified dispatch-possibility marker.")
    dispatched = (
        result["may_have_applied"] if result is not None else intent.get("may_have_applied")
    )
    if dispatched is not True:
        raise ValueError("The original receipt records no possible application dispatch.")
    if result and result.get("status") == "verified":
        return {
            "kind": "result",
            "sha256": result["evidence_sha256"],
            "time": result["finished_at"],
        }
    # The first verified readback is an immutable historical fact. Later
    # observations do not rewrite the original attempt or erase that fact.
    event = storage.verified_readback(receipt_id)
    if event is not None:
        return {
            "kind": "readback-event",
            "sha256": event["evidence_sha256"],
            "time": event["created_at"],
        }
    raise ValueError("The original Real-default transfer has no retained verified outcome.")


class NativeDefaultRecovery:
    def __init__(self, records: NativeBackupRecords):
        self.records = records
        self.storage = records.storage

    def _original(self, capture_id):
        # The original intent has its backup ID and native payload hash, rather
        # than a separate backup-manifest field. Reconstructing that payload
        # below additionally binds the verified original files to the intent.
        folder = self.storage.directory / identifier(capture_id)
        if folder.is_symlink():
            raise ValueError("The original backup must remain in its retained folder.")
        try:
            return self.storage.load(capture_id)
        except OSError as exc:
            raise ValueError("The original pre-transfer backup is unavailable.") from exc

    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "signal-default"
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
            raise ValueError("Select an existing separate native Real-default transfer receipt.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id)
        before, original_files = self._original(intent.get("backup_id"))
        old_compiler = compiler_from_snapshot(before, original_files)
        edit = SignalCompilerPreview.model_validate(
            {
                **intent.get("default_edit", {}),
                "capture_id": before["id"],
                "snapshot_sha256": before["evidence_sha256"],
            }
        ).model_dump(include={"record_ref", "encoded_sha256", "value_text"})
        expected, compilation = compile_default(original_files, edit)
        selected = compilation["selected_edit"]
        recorded = intent.get("compilation", {}).get("selected_edit", {})
        if (
            sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
            or any(
                recorded.get(key) != selected[key]
                for key in ("record_ref", "class_id", "before_bits", "after_bits")
            )
            or not selected["changed"]
        ):
            raise ValueError("Original backup, selected edit and recorded native payload disagree.")
        # Also ensure the recorded source field was actually qualified by the
        # snapshot identity/saved-schema compiler, not only a raw byte patch.
        if not any(row["ref"] == edit["record_ref"] for row in old_compiler.fields()):
            raise ValueError("The original selected Real default is not qualified.")
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
                "The current source is not the original recorded controller route and identity."
            )
        if (
            sha(MoiIdentity(files[3]).data) != intent["native_payload_sha256"]
            or files[11] != original_files[11]
        ):
            raise ValueError(
                "The recorded application or static parameter directory changed; use separately reviewed engineering."
            )
        field = next((row for row in compiler.fields() if row["ref"] == edit["record_ref"]), None)
        if field is None or field["class_id"] != selected["class_id"]:
            raise ValueError("The original selected Real field no longer matches this source.")
        prior, after = _bits(selected["before_bits"]), _bits(selected["after_bits"])
        if field["effective_bits"] not in (selected["before_bits"], selected["after_bits"]):
            raise ValueError(
                "The selected current effective value changed from the recorded outcome."
            )
        already = field["effective_bits"] == selected["before_bits"]
        proposal = {
            "capture_id": current["id"],
            "snapshot_sha256": current["evidence_sha256"],
            "record_ref": field["ref"],
            "encoded_sha256": field["encoded_sha256"],
            "value_text": repr(prior),
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
            "previous_effective_bits": selected["before_bits"],
            "recorded_after_bits": selected["after_bits"],
            "current_effective_bits": field["effective_bits"],
            "proposal_bits": selected["before_bits"],
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
