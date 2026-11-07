"""Bounded native order witnesses from retained files, without field authority."""

import json

from .moi_identity import sha
from .native_removal_capabilities import removal_capabilities

PROFILE = "native-backup-operation-capabilities/22"
LOCAL_ROW = "effective-execution-order-compile"
TRANSFER_ROW = "execution-order-transfer-prerequisites"
LIMITS = {"diagrams": 8, "compile_attempts": 8, "witness_bytes": 96 * 1024}


def order_evidence(snapshot, files, records):
    # Resolve the transfer service after inspection models finish importing.
    from .native_execution_order import EffectiveOrderCompiler, NativeExecutionOrder
    from .native_order_transfer import compile_order

    result = {
        "status": "unsupported-source",
        "error": None,
        "limits": dict(LIMITS),
        "diagram_count": None,
        "examined_diagrams": 0,
        "compile_attempts": 0,
        "witness": None,
        "transfer_error": None,
    }
    if (
        snapshot.get("source_identity_matches") is not True
        or type(snapshot.get("identity", {}).get("vendor-identifier")) is not int
        or snapshot["identity"]["vendor-identifier"] != 5
    ):
        result.update(
            status="source-mismatch", error="Select a recorded identity-qualified vendor 5 source."
        )
        return result
    try:
        compiler = EffectiveOrderCompiler(snapshot, files)
        diagrams = [
            r for r in compiler.archive.reader.records.values() if r["class_id"] in (536, 575)
        ]
        result["diagram_count"] = len(diagrams)
        service = NativeExecutionOrder(records)
        for record in diagrams[: LIMITS["diagrams"]]:
            result["examined_diagrams"] += 1
            try:
                ref = record["ref"]
                selected = compiler.effective.inspect(ref)
                order = selected["original_order"]
                blocked = {
                    frozenset((edge["source_index"], edge["target_index"]))
                    for edge in selected["edge_relationships"]
                }
                candidate = None
                for position in range(len(order) - 1):
                    a, b = order[position : position + 2]
                    if (
                        frozenset((a, b)) not in blocked
                        and b < 1 << (selected["slots"][position]["payload_bytes"] * 8)
                        and a < 1 << (selected["slots"][position + 1]["payload_bytes"] * 8)
                    ):
                        candidate = list(order)
                        candidate[position : position + 2] = [b, a]
                        break
                if candidate is None:
                    continue
                if result["compile_attempts"] >= LIMITS["compile_attempts"]:
                    break
                result["compile_attempts"] += 1
                query = {
                    "capture_id": snapshot["id"],
                    "snapshot_sha256": snapshot["evidence_sha256"],
                    "source_sha256": sha(files[3]),
                    "diagram_ref": ref,
                    "record_sha256": record["sha256"],
                }
                request = {
                    **query,
                    "effective_sha256": selected["source_sha256"],
                    "effective_record_sha256": selected["record_sha256"],
                    "selection_sha256": selected["selection_sha256"],
                    "proposed_order": candidate,
                }
                output, review = service.preview(request)
                if (
                    review["source"]["files"] != compiler.files
                    or review["source"]["parameter_merge"] != compiler.parameters
                    or review["output_sha256"] != sha(output)
                ):
                    raise ValueError(
                        "The retained order source changed during capability analysis."
                    )
                transfer = None
                transfer_error = None
                try:
                    field_output, transfer = compile_order(files, request)
                    if field_output != output:
                        raise ValueError("Local and transfer prerequisite compilation disagree.")
                except ValueError as exc:
                    transfer = None
                    transfer_error = str(exc)[:512] or "Transfer prerequisites were not qualified."
                witness = {
                    "record": {
                        "ref": ref,
                        "record_sha256": record["sha256"],
                        "class_id": record["class_id"],
                    },
                    "request": request,
                    "review": review,
                    "transfer_compilation": transfer,
                }
                if (
                    len(json.dumps(witness, ensure_ascii=True, separators=(",", ":")).encode())
                    > LIMITS["witness_bytes"]
                ):
                    result["error"] = (
                        "The actual order witness exceeds this bounded analysis's readable evidence limit. Inspect and review the diagram separately."
                    )
                    continue
                result.update(
                    status="source-qualified",
                    error=None,
                    witness=witness,
                    transfer_error=transfer_error,
                )
                return result
            except ValueError as exc:
                result["error"] = str(exc)[:512] or "This recorded diagram did not qualify."
        result.update(
            status="not-evaluated",
            error=result["error"]
            or "No nontrivial adjacent order witness qualified in this bounded search. This does not establish that no other permutation is possible.",
        )
    except ValueError as exc:
        result["error"] = str(exc)[:512] or "No qualified native order source is available."
    return result


def order_capabilities(snapshot, files, application, *, records, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit native execution-order capability profile.")
    report = removal_capabilities(snapshot, files, application)
    evidence = order_evidence(snapshot, files, records)
    report["qualification"]["execution_order"] = evidence
    witness = evidence["witness"]
    field_status = (
        evidence["status"]
        if witness is None
        else "unsupported-source"
        if witness["transfer_compilation"] is None
        else "preflight-required"
        if report["qualification"]["captured_plain_ipv4"]
        else "transport-unavailable"
    )
    report["operations"].extend(
        [
            {
                "id": LOCAL_ROW,
                "operation": "Compile an existing native execution-order permutation",
                "status": evidence["status"],
                "basis": "One actual saved-effective diagram passes an independent complete local compilation/readback witness, preserving recorded wire phases and original index widths."
                if witness
                else evidence["error"],
                "next_step": "Inspect the recorded diagram in Program, choose Change execution order and select the intended permutation. This hypothetical witness creates no draft, field review or controller authority.",
            },
            {
                "id": TRANSFER_ROW,
                "operation": "Inspect native execution-order transfer prerequisites",
                "status": field_status,
                "basis": evidence["transfer_error"]
                or evidence["error"]
                or "The actual order transfer compiler, configuration guard and saved-field qualification pass. Captured transport is separate from current controller access.",
                "next_step": "Use the separate selected-controller order review/apply/readback workflow. Fresh identity/configuration/settings, capacity, credentials, one-use confirmation and full readback remain mandatory. This analysis queries no controller and prepares no field action; native runtime/CCT and physical acceptance remain unverified.",
            },
        ]
    )
    report["capability_profile"] = PROFILE
    return report
