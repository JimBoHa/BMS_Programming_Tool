"""Local previous-effective batch proposals from verified immutable evidence."""

import struct

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_default_batch import EffectiveDefaultBatchCompiler
from .moi_identity import MoiIdentity, seal, sha
from .native_default_batch import NativeDefaultBatch
from .native_default_batch_transfer import PROFILE as BATCH_PROFILE
from .native_default_batch_transfer import compile_batch_defaults, validate_batch_evidence
from .native_default_recovery import (
    DefaultRecoveryPrepare,
    NativeDefaultRecovery,
    _bits,
    _verified_proof,
)

PROFILE = "native-default-batch-recovery-draft/1"
SCOPE = (
    "Prepare previous effective typed defaults from one resolved, historically verified "
    "native batch receipt and matching retained current files. Preserve current unselected "
    "settings and exact Real bits, Boolean values and fixed Enum storage/state metadata. "
    "This is local evidence and a hypothetical compiled copy, not current-device acceptance, "
    "a controller review or rollback. No controller query, retained plan, old-token replay "
    "or automatic transfer. Fresh recovery deployment is a separate operation."
)


def typed_value(kind, value):
    if kind == "real":
        bits = struct.pack(">f", value).hex()
        _bits(bits)
        return {"bits": bits}
    if kind == "boolean" and type(value) is bool:
        return {"value": value}
    if kind == "enum" and type(value) is int and 0 <= value <= 65535:
        return {"value": value}
    raise ValueError("The recorded batch value is outside its strict typed profile.")


class NativeDefaultBatchRecovery(NativeDefaultRecovery):
    def prepare(self, request):
        options = DefaultRecoveryPrepare.model_validate(request)
        receipt = self.storage.receipt(options.receipt_id, include_events=False)
        intent = receipt["intent"]
        if (
            intent.get("profile") != TRANSFER_PROFILE
            or intent.get("change_kind") != "default-batch"
            or intent.get("operation_profile") != BATCH_PROFILE
            or intent.get("enum_semantics_verified") is not False
            or type(intent.get("old_instance")) is not int
            or not 0 <= intent["old_instance"] <= 4194302
            or intent["old_instance"] != intent.get("new_instance")
            or not isinstance(intent.get("old_name"), str)
            or intent["old_name"] != intent.get("new_name")
            or type(intent.get("identity")) is not dict
            or type(intent.get("target")) is not dict
        ):
            raise ValueError("Select a separate supported typed native batch transfer receipt.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="typed batch")
        before, original = self._original(intent.get("backup_id"))
        EffectiveDefaultBatchCompiler(original, snapshot=before)
        edit, guard = validate_batch_evidence(intent.get("batch_edit"), intent.get("batch_guard"))
        payload, compilation = compile_batch_defaults(
            original, edit.model_dump(), fresh=True, expected_guard=guard.model_dump()
        )
        native = MoiIdentity(payload)
        if (
            compilation != intent.get("compilation")
            or compilation["changed_count"] < 1
            or sha(payload) != intent.get("payload_sha256")
            or sha(native.data) != intent.get("native_payload_sha256")
        ):
            raise ValueError(
                "Original batch files, typed guards, compilation and payload disagree."
            )
        query = {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        current, files = self.records.load_files(query)
        compiler = EffectiveDefaultBatchCompiler(files, snapshot=current)
        source = NativeDefaultBatch(self.records).source(query)
        if (
            current["device"] != before["device"]
            or current["device"] != f"device,{intent['new_instance']}"
            or before["identity"].get("object-name") != intent["old_name"]
            or any(seal(s["target"]) != seal(intent["target"]) for s in (before, current))
            or any(seal(s["identity"]) != seal(intent["identity"]) for s in (before, current))
            or source["source_identity_matches"] is not True
        ):
            raise ValueError(
                "The retained batch sources have a different controller route or identity."
            )
        if sha(MoiIdentity(files[3]).data) != sha(native.data) or files[11] != original[11]:
            raise ValueError("The recorded batch application or static directory changed.")
        fields = {(r["kind"], r["field"]["ref"]): r["field"] for r in compiler.fields()}
        rows, changes = [], []
        for g in guard.fields:
            field = fields.get((g.kind, g.record_ref))
            if field is None or field["class_id"] != g.class_id or field["property"] != 3113:
                raise ValueError("An original selected typed batch field no longer matches.")
            if g.kind == "enum" and (
                field["saved_storage"] != g.saved_storage.model_dump()
                or field["states_text_encoded_sha256"] != g.states_text_encoded_sha256
            ):
                raise ValueError("Selected Enum storage or state metadata changed.")
            previous = {"bits": g.prior_bits} if g.kind == "real" else {"value": g.prior_value}
            after = typed_value(
                g.kind, native.reader.scalar(native.reader.records[g.record_ref], 3113)
            )
            value = (
                {"bits": field["effective_bits"]}
                if g.kind == "real"
                else typed_value(g.kind, field["effective_value"])
            )
            if value not in (previous, after):
                raise ValueError("A current selected value is outside its recorded batch outcome.")
            rows.append(
                {
                    "kind": g.kind,
                    "record_ref": g.record_ref,
                    "class_id": g.class_id,
                    "property": 3113,
                    "previous": previous,
                    "recorded_after": after,
                    "current": value,
                    "already_recorded": value == previous,
                    "current_encoded_sha256": field["encoded_sha256"],
                }
            )
            changes.append(
                {
                    "kind": g.kind,
                    "record_ref": g.record_ref,
                    "encoded_sha256": field["encoded_sha256"],
                    **(
                        {"value_text": repr(_bits(g.prior_bits))}
                        if g.kind == "real"
                        else {"value": g.prior_value}
                    ),
                }
            )
        already = all(r["already_recorded"] for r in rows)
        proposal = (
            None
            if already
            else {
                **query,
                "source_sha256": source["source_sha256"],
                "effective_sha256": source["effective_sha256"],
                "changes": changes,
            }
        )
        output, recovery_compile = (
            (None, None) if already else compile_batch_defaults(files, proposal)
        )
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
            "recorded_native_payload_sha256": intent["native_payload_sha256"],
            "fields": rows,
            "enum_semantics_verified": False,
        }
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "source": source,
            "origin": origin,
            "origin_sha256": seal(origin),
            "proposal": proposal,
            "compilation": recovery_compile,
            "output_sha256": None if output is None else sha(output),
            "already_recorded": already,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "field_transfer_enabled": False,
            "new_review_required": not already,
            "enum_semantics_verified": False,
        }
        return {**body, "evidence_sha256": seal(body)}
