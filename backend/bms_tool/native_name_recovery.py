"""Local previous-name proposals require original verified native transfer evidence."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_identity import MoiIdentity, controller_name, seal, sha
from .native_backup_records import BackupInspectionSource
from .native_default_recovery import (
    DefaultRecoveryPrepare,
    NativeDefaultRecovery,
    _verified_proof,
)
from .native_signal_compiler import compiler_from_snapshot

PROFILE = "native-controller-name-recovery-draft/1"
SCOPE = (
    "Local previous-name proposal from a resolved, historically verified name-only native "
    "transfer. Require the same Device instance, route, model, other identity, original-after "
    "application and static parameter directory. Other current saved values remain current. "
    "No field query, old-plan replay, instance reassignment or automatic rollback. A new "
    "confirmed name-only review, application transfer and full readback are required."
)


class NativeNameRecovery(NativeDefaultRecovery):
    def __init__(self, records, compile_identity):
        super().__init__(records)
        self.compile_identity = compile_identity

    def source(self, request):
        options = BackupInspectionSource.model_validate(request)
        snapshot, files = self.records.load_files(options.model_dump())
        compiler = compiler_from_snapshot(snapshot, files)
        return {
            **self.records.envelope(snapshot, files),
            "profile": "native-controller-name-recovery-source/1",
            "application": compiler.archive.editor.summary(),
            "can_apply": False,
        }

    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "name"
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent.get("old_instance") != intent.get("new_instance")
            or intent.get("name_change_confirmed") is not True
            or intent.get("application_transfer_confirmed") is not True
            or not isinstance(intent.get("compilation"), dict)
            or not isinstance(intent.get("identity"), dict)
            or not isinstance(intent.get("target"), dict)
        ):
            raise ValueError("Select an existing confirmed native name-only transfer receipt.")
        previous = controller_name(intent.get("old_name"))
        after = controller_name(intent.get("new_name"))
        if previous == after:
            raise ValueError("The original receipt contains no controller name change.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="name-only")
        before, original_files = self._original(intent.get("backup_id"))
        original = compiler_from_snapshot(before, original_files)
        expected, compilation = self.compile_identity(original_files, intent["old_instance"], after)
        if (
            before["device"] != f"device,{intent['old_instance']}"
            or seal(before["identity"]) != seal(intent["identity"])
            or before["identity"].get("object-name") != previous
            or seal(before["target"]) != seal(intent["target"])
            or seal(compilation) != seal(intent["compilation"])
            or sha(expected) != intent.get("payload_sha256")
            or sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
        ):
            raise ValueError("Original backup, identity, name edit and verified payload disagree.")
        current, files = self.records.load_files(
            {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        )
        compiler = compiler_from_snapshot(current, files)
        editor = compiler.archive.editor
        name = editor.summary()["name"]
        if (
            current["device"] != before["device"]
            or seal(current["target"]) != seal(intent["target"])
            or seal(current["identity"]) != seal({**intent["identity"], "object-name": name})
            or files[11] != original_files[11]
            or editor.ref != original.archive.editor.ref
            or editor.root["class_id"] != original.archive.editor.root["class_id"]
        ):
            raise ValueError(
                "Current source route, identity or static parameter directory changed."
            )
        if name not in (previous, after):
            raise ValueError("The current controller name changed from the recorded outcome.")
        # Normalize only the existing name in the original archive, without
        # merging fresh saved values into this application-image comparison.
        change = dict(
            source_sha256=editor.source_sha256,
            expected_instance=editor.instance,
            new_instance=editor.instance,
            expected_name=name,
            new_name=after,
        )
        reviewed = editor.preview(**change)
        normalized, _ = editor.export(**change, plan_sha256=reviewed["plan_sha256"])
        if MoiIdentity(normalized).data != MoiIdentity(expected).data:
            raise ValueError("The recorded application changed beyond its controller name.")
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
            "root_ref": editor.ref,
            "root_class": editor.root["class_id"],
            "instance": editor.instance,
            "property": 2390,
            "previous_name": previous,
            "recorded_after_name": after,
            "current_name": name,
            "proposal_name": previous,
        }
        proposal = {
            "capture_id": current["id"],
            "snapshot_sha256": current["evidence_sha256"],
            "new_instance": editor.instance,
            "new_name": previous,
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
