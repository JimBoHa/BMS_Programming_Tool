"""A previous Device number needs verified before/after native source evidence."""

from .application_preservation import verify_preservation
from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_identity import MoiIdentity, number, seal, sha
from .native_default_recovery import DefaultRecoveryPrepare, _verified_proof
from .native_name_recovery import NativeNameRecovery
from .native_signal_compiler import compiler_from_snapshot

PROFILE = "native-controller-instance-recovery-draft/1"
SOURCE_PROFILE = "native-controller-instance-recovery-source/1"
SCOPE = (
    "Local previous Device-instance proposal from a resolved, historically verified instance-only "
    "native transfer and its original/verified-after backups. Require the same route, name, model "
    "and other identity, the original-after application image and verified-after static directory. "
    "Only typed root-instance directory aliases may normalize for an already-recorded previous "
    "number. Other current saved settings remain current. No allocation, field query, old-plan "
    "replay or automatic rollback. A new reserved-number confirmation, fresh collision checks, "
    "confirmed native transfer and full readback are required."
)


def normalized_directory(directory, *, root_class, current_instance, recorded_instance):
    """Normalize only existing root-selector object-number bytes; preserve every other byte."""
    number(current_instance)
    number(recorded_instance)
    if not isinstance(directory, bytes) or not 1 <= len(directory) <= 128 * 1024:
        raise ValueError("Select a bounded, qualified static parameter directory.")
    result = bytearray(directory)
    offset, changes = 0, 0
    while offset < len(directory):
        size = int.from_bytes(directory[offset : offset + 2], "big")
        if size < 14 or offset + size > len(directory):
            raise ValueError("The static directory has invalid record framing.")
        oid = int.from_bytes(directory[offset + 2 : offset + 6], "big")
        cid = int.from_bytes(directory[offset + 10 : offset + 12], "big")
        if cid == root_class and oid & 4194303 == current_instance:
            mapped = (oid & ~4194303) | recorded_instance
            result[offset + 2 : offset + 6] = mapped.to_bytes(4, "big")
            changes += int(mapped != oid)
        offset += size
    return bytes(result), changes


class NativeInstanceRecovery(NativeNameRecovery):
    def source(self, request):
        return {**super().source(request), "profile": SOURCE_PROFILE}

    def qualified_inverse(self, files, previous):
        output, compilation = self.compile_identity(files, previous)
        preservation = verify_preservation(
            files,
            {**files, 3: output},
            old_instance=MoiIdentity(files[3]).instance,
            new_instance=previous,
        )
        return output, compilation, preservation

    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "instance"
            or intent.get("allocation_confirmed") is not True
            or intent.get("application_transfer_confirmed") is not True
            or not isinstance(intent.get("identity"), dict)
            or not isinstance(intent.get("target"), dict)
            or not isinstance(intent.get("compilation"), dict)
            or not isinstance(intent.get("old_name"), str)
            or intent.get("old_name") != intent.get("new_name")
        ):
            raise ValueError(
                "Select a confirmed, separate native Device-instance transfer receipt."
            )
        previous, after = number(intent.get("old_instance")), number(intent.get("new_instance"))
        if previous == after:
            raise ValueError("The original receipt contains no Device-instance change.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="instance-only")
        verified = (
            receipt["result"]
            if proof["kind"] == "result"
            else self.storage.verified_readback(options.receipt_id)["detail"]
        )
        before, original_files = self._original(intent.get("backup_id"))
        original = compiler_from_snapshot(before, original_files)
        expected, compilation = self.compile_identity(original_files, after)
        if (
            before["device"] != f"device,{previous}"
            or seal(before["identity"]) != seal(intent["identity"])
            or before["identity"].get("object-name") != intent["old_name"]
            or seal(before["target"]) != seal(intent["target"])
            or seal(compilation) != seal(intent["compilation"])
            or sha(expected) != intent.get("payload_sha256")
            or sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
        ):
            raise ValueError(
                "Original backup, instance edit and recorded verified payload disagree."
            )
        post, post_files = self._original(verified.get("verification_capture_id"))
        post_compiler = compiler_from_snapshot(post, post_files)
        expected_identity = {**intent["identity"]}
        if "device" in expected_identity:
            expected_identity["device"] = f"device,{after}"
        if (
            post["device"] != f"device,{after}"
            or seal(post["target"]) != seal(intent["target"])
            or seal(post["identity"]) != seal(expected_identity)
            or sha(post_compiler.archive.editor.data) != intent["native_payload_sha256"]
            or post_compiler.archive.editor.ref != original.archive.editor.ref
            or post_compiler.archive.editor.root["class_id"]
            != original.archive.editor.root["class_id"]
        ):
            raise ValueError(
                "The retained verified-after backup does not match the original outcome."
            )
        preservation = verify_preservation(
            original_files, post_files, old_instance=previous, new_instance=after
        )
        current, files = self.records.load_files(
            {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        )
        compiler = compiler_from_snapshot(current, files)
        editor = compiler.archive.editor
        current_instance = editor.instance
        current_identity = {**intent["identity"]}
        if "device" in current_identity:
            current_identity["device"] = current["device"]
        if (
            current_instance not in (previous, after)
            or current["device"] != f"device,{current_instance}"
            or seal(current["target"]) != seal(intent["target"])
            or seal(current["identity"]) != seal(current_identity)
            or editor.ref != original.archive.editor.ref
            or editor.root["class_id"] != original.archive.editor.root["class_id"]
        ):
            raise ValueError("The current retained station, identity or Device number changed.")
        static, aliases = normalized_directory(
            files[11],
            root_class=editor.root["class_id"],
            current_instance=current_instance,
            recorded_instance=after,
        )
        if static != post_files[11]:
            raise ValueError("The current static directory differs from the verified outcome.")
        query = dict(
            source_sha256=editor.source_sha256,
            expected_instance=current_instance,
            new_instance=after,
        )
        plan = editor.preview(**query)
        normalized, _ = editor.export(**query, plan_sha256=plan["plan_sha256"])
        if sha(MoiIdentity(normalized).data) != intent["native_payload_sha256"]:
            raise ValueError("The recorded application changed beyond its Device instance.")
        # A formerly unmatched root slot can become an application setting at
        # the previous number. Qualify the destination merge as well; do not
        # dispatch first and rely on later readback to discover that change.
        _, _, destination = self.qualified_inverse(files, previous)
        already = current_instance == previous
        origin = {
            "profile": PROFILE,
            "parent_receipt_id": options.receipt_id,
            "parent_intent_sha256": intent["evidence_sha256"],
            "original_dispatch": "possible",
            "verified_proof": proof,
            "original_backup_id": before["id"],
            "original_snapshot_sha256": before["evidence_sha256"],
            "original_after_native_sha256": intent["native_payload_sha256"],
            "verified_after_capture_id": post["id"],
            "verified_after_snapshot_sha256": post["evidence_sha256"],
            "verified_after_static_sha256": sha(post_files[11]),
            "verified_after_preservation_sha256": seal(preservation),
            "proposal_preservation_sha256": seal(destination),
            "current_capture_id": current["id"],
            "current_snapshot_sha256": current["evidence_sha256"],
            "current_archive_sha256": sha(files[3]),
            "current_static_sha256": sha(files[11]),
            "normalized_static_sha256": sha(static),
            "normalized_root_selectors": aliases,
            "root_ref": editor.ref,
            "root_class": editor.root["class_id"],
            "property": 75,
            "previous_instance": previous,
            "recorded_after_instance": after,
            "current_instance": current_instance,
            "proposal_instance": previous,
            "unchanged_name": editor.summary()["name"],
        }
        proposal = {
            "capture_id": current["id"],
            "snapshot_sha256": current["evidence_sha256"],
            "new_instance": previous,
            "recovery_parent_receipt": options.receipt_id,
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": self.records.envelope(current, files),
            "origin": origin,
            "origin_sha256": seal(origin),
            "previous_instance": previous,
            "recorded_after_instance": after,
            "current_instance": current_instance,
            "unchanged_name": origin["unchanged_name"],
            "already_recorded": already,
            "proposal": None if already else proposal,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "new_review_required": not already,
        }
        return {**body, "evidence_sha256": seal(body)}
