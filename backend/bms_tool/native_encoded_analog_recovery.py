"""Prepare a previous-terminal draft from a verified move; create no field authority."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import MoiIdentity, seal, sha
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof
from .native_encoded_terminal_input import PROFILE as TERMINAL_PROFILE
from .native_encoded_terminal_input import EncodedAnalogTerminalCompiler
from .native_inputs import InputEdit, NativeInputCompiler

PROFILE = "native-encoded-analog-terminal-recovery-draft/1"
SCOPE = (
    "Local previous-terminal proposal from a resolved historically verified configured analog terminal "
    "move. Require original files, exact route/identity/static directory, recorded native "
    "application and unchanged selected input configuration. Preserve other current saved "
    "settings. No controller query, old-plan replay, retained edit, wiring verification or "
    "automatic rollback. A separately confirmed fresh review, transfer and readback are required."
)


class NativeEncodedAnalogRecovery(NativeDefaultRecovery):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("operation_profile") != TERMINAL_PROFILE
            or intent.get("change_kind") != "input"
            or any(
                intent.get(k) is not True
                for k in (
                    "physical_wiring_confirmed",
                    "input_change_confirmed",
                    "application_transfer_confirmed",
                )
            )
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or type(intent.get("new_instance")) is not int
            or intent["new_instance"] != intent["old_instance"]
            or type(intent.get("identity")) is not dict
            or type(intent.get("target")) is not dict
            or type(intent.get("compilation")) is not dict
        ):
            raise ValueError("Select a confirmed native configured analog terminal-move receipt.")
        proof = _verified_proof(
            receipt, self.storage, options.receipt_id, label="configured analog terminal"
        )
        verified = (
            receipt["result"]
            if proof["kind"] == "result"
            else self.storage.verified_readback(options.receipt_id)["detail"]
        )
        if (
            verified.get("operational") is not True
            or type(verified.get("system_status")) is not int
            or verified["system_status"] != 0
            or verified.get("native_sha256") != intent.get("native_payload_sha256")
            or verified.get("preservation", {}).get("profile") != TERMINAL_PROFILE
            or verified.get("preservation", {}).get("identity_unchanged") is not True
            or verified.get("preservation", {}).get("other_configuration_preserved") is not True
            or seal(verified.get("preservation", {}).get("selected_edit"))
            != seal(intent.get("input_edit"))
        ):
            raise ValueError(
                "The verified terminal outcome lacks matching complete native preservation."
            )
        before, originals = self._original(intent.get("backup_id"))
        qualified_saved_merge(before, originals)
        original = NativeInputCompiler(originals)
        edit = InputEdit.model_validate(intent.get("input_edit"))
        if edit.action != "encoded-terminal" or seal(edit.model_dump()) != seal(
            intent["input_edit"]
        ):
            raise ValueError("The original terminal edit is not canonical profile 4.")
        expected, compilation = original.compile(edit)
        selected = compilation["terminal_compilation"]
        if (
            seal(compilation) != seal(intent["compilation"])
            or sha(expected) != intent.get("payload_sha256")
            or sha(MoiIdentity(expected).data) != intent.get("native_payload_sha256")
            or before["device"] != f"device,{intent['old_instance']}"
            or seal(before["identity"]) != seal(intent["identity"])
            or seal(before["target"]) != seal(intent["target"])
            or before["identity"].get("object-name") != intent.get("old_name")
            or intent.get("old_name") != intent.get("new_name")
        ):
            raise ValueError("Original terminal backup, compilation, identity or payload disagree.")
        current, files = self.records.load_files(
            {
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        qualified_saved_merge(current, files)
        if (
            current["device"] != before["device"]
            or seal(current["identity"]) != seal(before["identity"])
            or seal(current["target"]) != seal(before["target"])
            or files[11] != originals[11]
        ):
            raise ValueError("Current terminal source identity, route or static directory changed.")
        native = sha(MoiIdentity(files[3]).data)
        previous = sha(original.app.data)
        if native not in (intent["native_payload_sha256"], previous):
            raise ValueError("The recorded native application changed beyond this terminal move.")
        already = native == previous
        compiler = NativeInputCompiler(files)
        field = next(
            (
                p
                for p in EncodedAnalogTerminalCompiler(compiler).source()["inputs"]
                if p["object_id"] == compilation["object_id"]
            ),
            None,
        )
        if (
            field is None
            or field["record_ref"] != compilation["record_ref"]
            or field["slot"] != (selected["old_slot"] if already else selected["destination_slot"])
            or field.get("configuration_error") is not None
            or seal(field.get("stored_configuration")) != seal(compilation["stored_configuration"])
            or seal(field.get("configuration_storage"))
            != seal(compilation["configuration_storage"])
        ):
            raise ValueError(
                "The selected effective input identity, terminal or configuration changed."
            )
        proposal = inverse = output = None
        if not already:
            inverse_edit = InputEdit(
                action="encoded-terminal",
                object_instance=edit.object_instance,
                slot=selected["old_slot"],
                configuration_sha256=field["configuration_sha256"],
            )
            output, inverse = compiler.compile(inverse_edit)
            moved = inverse["terminal_compilation"]
            if (moved["old_slot"], moved["destination_slot"]) != (
                selected["destination_slot"],
                selected["old_slot"],
            ):
                raise ValueError(
                    "The inverse terminal compiler did not restore the original binding."
                )
            proposal = {
                "capture_id": current["id"],
                "snapshot_sha256": current["evidence_sha256"],
                "edit": inverse_edit.model_dump(),
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
            "object_id": compilation["object_id"],
            "record_ref": compilation["record_ref"],
            "previous_slot": selected["old_slot"],
            "recorded_after_slot": selected["destination_slot"],
            "current_slot": field["slot"],
            "proposal_slot": selected["old_slot"],
            "current_configuration_sha256": field["configuration_sha256"],
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": self.records.envelope(current, files),
            "origin": origin,
            "origin_sha256": seal(origin),
            "current_effective_sha256": compiler.app.source_sha256,
            "already_recorded": already,
            "proposal": proposal,
            "inverse_compilation": inverse,
            "inverse_output_sha256": sha(output) if output is not None else None,
            "read_only": True,
            "controller_queries": False,
            "controller_writes": False,
            "field_actions": False,
            "can_apply": False,
            "new_review_required": not already,
            "parent_lineage_enforced_by_field_transfer": False,
        }
        return {**body, "evidence_sha256": seal(body)}
