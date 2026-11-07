"""Retained-source batch transfer prerequisites without controller authority."""

from .moi_default_batch import LIMIT, EffectiveDefaultBatchCompiler
from .moi_identity import MoiIdentity, sha
from .native_batch_capabilities import batch_capabilities, batch_change

PROFILE = "native-backup-operation-capabilities/21"
ROW = "typed-default-batch-transfer-prerequisites"


def transfer_evidence(snapshot, files, records):
    # Inspection models must finish importing before resolving the source and
    # transfer services which depend on those models.
    from .native_default_batch import NativeDefaultBatch
    from .native_default_batch_transfer import PROFILE as TRANSFER_PROFILE
    from .native_default_batch_transfer import compile_batch_defaults

    result = {
        "status": "unsupported-source",
        "error": None,
        "field_limit": LIMIT,
        "field_count": None,
        "candidate_count": 0,
        "selected_count": 0,
        "compile_attempts": 0,
        "source": None,
        "fields": [],
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
            or source["source_identity_matches"] is not True
        ):
            raise ValueError("The actual batch source changed or lacks recorded identity evidence.")
        candidates = []
        descriptions = []
        for row in fields:
            f = row["field"]
            candidate = row["kind"] != "enum" or f["saved_storage"] is not None
            descriptions.append(
                {
                    "kind": row["kind"],
                    "record_ref": f["ref"],
                    "class_id": f["class_id"],
                    "property": f["property"],
                    "encoded_sha256": f["encoded_sha256"],
                    "prerequisite": "candidate-for-review"
                    if candidate
                    else "requires-fixed-enum-slot",
                }
            )
            if candidate:
                candidates.append(row)
        result.update(
            source=source,
            fields=descriptions,
            field_count=len(fields),
            candidate_count=len(candidates),
        )
        if not candidates:
            result["error"] = (
                "No recorded default has this transfer profile's saved-storage prerequisites."
            )
            return result
        request = {
            **query,
            "source_sha256": source["source_sha256"],
            "effective_sha256": source["effective_sha256"],
            "changes": [batch_change(row) for row in candidates[:LIMIT]],
        }
        result.update(selected_count=len(request["changes"]), compile_attempts=1)
        try:
            output, compilation = compile_batch_defaults(files, request)
            if (
                compilation["changed_count"] != result["selected_count"]
                or compilation["compiled_sha256"] != sha(output)
                or compilation["compiled_native_sha256"] != sha(MoiIdentity(output).data)
            ):
                raise ValueError(
                    "The transfer prerequisite witness must demonstrate every selected change."
                )
        except ValueError as exc:
            result.update(
                status="not-evaluated",
                error=str(exc)[:512] or "This bounded transfer witness did not qualify.",
            )
            return result
        result.update(
            status="source-qualified",
            witness={
                "transfer_profile": TRANSFER_PROFILE,
                "request": request,
                "compilation": compilation,
            },
        )
    except ValueError as exc:
        result["error"] = str(exc)[:512] or "No qualified retained batch source is available."
    return result


def batch_transfer_capabilities(
    snapshot, files, application, *, records, capability_profile=PROFILE
):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit typed batch transfer prerequisite profile.")
    report = batch_capabilities(snapshot, files, application, records=records)
    evidence = transfer_evidence(snapshot, files, records)
    report["qualification"]["typed_default_batch_transfer"] = evidence
    report["operations"].append(
        {
            "id": ROW,
            "operation": "Inspect typed default batch transfer prerequisites",
            "status": evidence["status"],
            "basis": (
                f"{evidence['selected_count']} hypothetical changes among {evidence['candidate_count']} "
                f"candidate defaults ({evidence['field_count']} recorded) pass the actual transfer "
                "compiler, typed configuration guards and saved-parameter qualification."
                if evidence["witness"] is not None
                else evidence["error"]
            ),
            "next_step": (
                "Inspect the recorded field prerequisites, select intended values in Program's "
                "typed batch task, and request a separate fresh controller review. This bounded "
                "source witness creates no draft, review token, journal, current-device check or "
                "transfer authority. Enum meanings, runtime/CCT and physical acceptance remain unverified."
            ),
        }
    )
    report["capability_profile"] = PROFILE
    return report
