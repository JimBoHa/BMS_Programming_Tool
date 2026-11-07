"""Compare retained typed sources with reconstructed verified batch results."""

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_default_batch import EffectiveDefaultBatchCompiler
from .moi_identity import MoiIdentity, seal, sha
from .native_default_batch import NativeDefaultBatch
from .native_default_batch_recovery import typed_value
from .native_default_batch_recovery_ledger import recovery_namespace, recovery_reference
from .native_default_batch_transfer import PROFILE as BATCH_PROFILE
from .native_default_batch_transfer import compile_batch_defaults, validate_batch_evidence
from .native_default_recovery import DefaultRecoveryPrepare, NativeDefaultRecovery, _verified_proof

PROFILE = "native-default-batch-result-match/1"
SCOPE = (
    "Local retained-source comparison with a reconstructed, historically verified typed "
    "batch result. Report captured route/identity, expanded application, effective saved "
    "values and original directory differences separately. No current-device verification, "
    "parent revalidation, compilation authority, recovery proposal, field review or transfer."
)


class NativeDefaultBatchResultMatch(NativeDefaultRecovery):
    def compare(self, request):
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
            raise ValueError("Select a supported typed native batch result.")
        recovery = recovery_namespace(intent)
        if (
            recovery
            and recovery_reference(intent)["native_default_batch_recovery"]["state"] != "recorded"
        ):
            raise ValueError("The recorded recovery child has inconsistent typed lineage.")
        proof = _verified_proof(receipt, self.storage, options.receipt_id, label="typed batch")
        before, original = self._original(intent.get("backup_id"))
        EffectiveDefaultBatchCompiler(original, snapshot=before)
        edit, guard = validate_batch_evidence(intent.get("batch_edit"), intent.get("batch_guard"))
        payload, compilation = compile_batch_defaults(
            original, edit.model_dump(), fresh=True, expected_guard=guard.model_dump()
        )
        expected = MoiIdentity(payload)
        if (
            compilation != intent.get("compilation")
            or compilation["changed_count"] < 1
            or sha(payload) != intent.get("payload_sha256")
            or sha(expected.data) != intent.get("native_payload_sha256")
            or before["device"] != f"device,{intent['new_instance']}"
            or seal(before["identity"]) != seal(intent["identity"])
            or seal(before["target"]) != seal(intent["target"])
        ):
            raise ValueError(
                "The original batch files, identity, guards and complete result disagree."
            )
        query = {"capture_id": options.capture_id, "snapshot_sha256": options.snapshot_sha256}
        current, files = self.records.load_files(query)
        compiler = EffectiveDefaultBatchCompiler(files, snapshot=current)
        source = NativeDefaultBatch(self.records).source(query)
        fields = {r["field"]["ref"]: r for r in compiler.fields()}
        selected = []
        for g in guard.fields:
            candidate = fields.get(g.record_ref)
            observed = None
            schema_matches = None
            if candidate is not None:
                f, kind = candidate["field"], candidate["kind"]
                if kind == "enum":
                    value = f["effective_value"]
                    if type(value) is not int or not 0 <= value <= 4294967295:
                        raise ValueError(
                            "The retained Enum comparison needs an actual Unsigned32 code."
                        )
                    value = {"value": value}
                else:
                    value = (
                        {"bits": f["effective_bits"]}
                        if kind == "real"
                        else typed_value(kind, f["effective_value"])
                    )
                observed = {
                    "kind": kind,
                    "class_id": f["class_id"],
                    "property": f["property"],
                    "value": value,
                    "encoded_sha256": f["encoded_sha256"],
                }
                if g.kind == "enum":
                    schema_matches = (
                        kind == "enum"
                        and f["saved_storage"] == g.saved_storage.model_dump()
                        and f["states_text_encoded_sha256"] == g.states_text_encoded_sha256
                    )
            value = typed_value(
                g.kind, expected.reader.scalar(expected.reader.records[g.record_ref], 3113)
            )
            matches = (
                observed is not None
                and observed["kind"] == g.kind
                and observed["class_id"] == g.class_id
                and observed["property"] == 3113
                and observed["value"] == value
            )
            selected.append(
                {
                    "kind": g.kind,
                    "record_ref": g.record_ref,
                    "class_id": g.class_id,
                    "property": 3113,
                    "expected": value,
                    "current": observed,
                    "matches": matches,
                    "enum_schema_matches": schema_matches,
                }
            )
        comparisons = {
            "route_matches": seal(current["target"]) == seal(intent["target"]),
            "identity_matches": seal(current["identity"]) == seal(intent["identity"]),
            "expanded_application_matches": sha(MoiIdentity(files[3]).data) == sha(expected.data),
            "effective_application_matches": sha(MoiIdentity(compiler.merged).data)
            == sha(expected.data),
            "selected_values_match": all(r["matches"] for r in selected),
            "original_saved_directory_matches": files[11] == original[11],
        }
        matched = source["source_identity_matches"] is True and all(
            comparisons[k]
            for k in (
                "route_matches",
                "identity_matches",
                "expanded_application_matches",
                "effective_application_matches",
                "selected_values_match",
            )
        )
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "receipt_id": options.receipt_id,
            "intent_sha256": intent["evidence_sha256"],
            "verified_proof": proof,
            "recorded_recovery_child": recovery,
            "original_backup_id": before["id"],
            "original_snapshot_sha256": before["evidence_sha256"],
            "recorded_target": intent["target"],
            "current_target": current["target"],
            "recorded_identity": intent["identity"],
            "expected_native_sha256": intent["native_payload_sha256"],
            "current_native_sha256": sha(MoiIdentity(files[3]).data),
            "current_effective_sha256": sha(compiler.merged),
            "current_effective_native_sha256": sha(MoiIdentity(compiler.merged).data),
            "source": {
                k: source[k]
                for k in (
                    "capture_id",
                    "snapshot_sha256",
                    "source_sha256",
                    "effective_sha256",
                    "target",
                    "identity",
                    "captured_at",
                    "source_identity_matches",
                    "files",
                )
            },
            "state": "application-and-values-match" if matched else "different",
            "comparisons": comparisons,
            "selected": selected,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
            "can_apply": False,
            "field_transfer_enabled": False,
            "current_device_verified": False,
            "parent_revalidated": False,
            "enum_semantics_verified": False,
        }
        return {**body, "evidence_sha256": seal(body)}
