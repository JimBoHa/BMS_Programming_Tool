"""Actual bounded local batch witnesses, without export review or field authority."""

from .moi_default_batch import LIMIT, EffectiveDefaultBatchCompiler
from .moi_identity import MoiIdentity, sha
from .native_combined_capabilities import combined_capabilities

PROFILE = "native-backup-operation-capabilities/20"
ROW = "typed-default-batch-compile"


def batch_change(row):
    """Choose a different representable value, without inventing Enum meanings."""
    field, kind = row["field"], row["kind"]
    return {
        "kind": kind,
        "record_ref": field["ref"],
        "encoded_sha256": field["encoded_sha256"],
        **(
            {"value_text": "1" if field["effective_bits"] == "00000000" else "0"}
            if kind == "real"
            else {"value": not field["effective_value"]}
            if kind == "boolean"
            else {"value": 1 if field["effective_value"] == 0 else 0}
        ),
    }


def batch_evidence(snapshot, files, records):
    # NativeDefaultBatch imports the inspection models. Resolve it only after
    # that module has finished constructing the inspection service.
    from .native_default_batch import NativeDefaultBatch

    result = {
        "status": "unsupported-source",
        "error": None,
        "field_limit": LIMIT,
        "field_count": None,
        "selected_count": 0,
        "compile_attempts": 0,
        "witness": None,
    }
    try:
        compiler = EffectiveDefaultBatchCompiler(files, snapshot=snapshot)
        query = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
        source = NativeDefaultBatch(records).source(query)
        fields = compiler.fields()
        if (
            source["fields"] != fields
            or source["files"] != compiler.files
            or source["effective_sha256"] != sha(compiler.merged)
            or source["parameter_merge"] != compiler.parameters
        ):
            raise ValueError("The batch compiler source changed during local qualification.")
        result["field_count"] = len(fields)
        if not fields:
            raise ValueError(
                "No supported existing typed defaults are recorded in this saved merge."
            )
        changes = [batch_change(row) for row in fields[:LIMIT]]
        result.update(selected_count=len(changes), compile_attempts=1)
        try:
            output, compilation = compiler.compile(changes)
            if (
                compilation["changed_count"] != len(changes)
                or compilation["compiled_sha256"] != sha(output)
                or compilation["compiled_native_sha256"] != sha(MoiIdentity(output).data)
            ):
                raise ValueError("The batch witness must demonstrate each actual native change.")
        except ValueError as exc:
            # Only the first sixteen fields were probed. Failure says nothing
            # about another subset or another representable value.
            result.update(
                status="not-evaluated", error=str(exc)[:512] or "This batch did not qualify."
            )
            return result
        result.update(
            status="source-qualified",
            witness={
                "source": source,
                "request": {
                    **query,
                    "source_sha256": source["source_sha256"],
                    "effective_sha256": source["effective_sha256"],
                    "changes": changes,
                },
                "compilation": compilation,
            },
        )
    except ValueError as exc:
        result["error"] = str(exc)[:512] or "No typed batch source is available."
    return result


def batch_capabilities(snapshot, files, application, *, records, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit typed batch capability profile.")
    report = combined_capabilities(snapshot, files, application, records=records)
    evidence = batch_evidence(snapshot, files, records)
    report["qualification"]["typed_default_batch"] = evidence
    supported = evidence["witness"] is not None
    report["operations"].append(
        {
            "id": ROW,
            "operation": "Compile up to sixteen existing typed native defaults together",
            "status": evidence["status"],
            "basis": (
                f"{evidence['selected_count']} actual changes among {evidence['field_count']} "
                "recorded defaults pass independent typed compilers, literal byte preservation "
                "and both composition orders over one retained saved merge."
                if supported
                else evidence["error"]
            ),
            "next_step": (
                "Open Program → Native backup defaults → Compile several native defaults "
                "together, choose the intended values and review a local copy. This bounded "
                "hypothetical witness stages no draft, export review or controller plan. Batch "
                "field deployment, Enum meanings, general logic, package/runtime validation "
                "and physical acceptance remain separate."
            ),
        }
    )
    report["capability_profile"] = PROFILE
    return report
