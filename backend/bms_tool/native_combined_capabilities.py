"""Local paired-compiler evidence, separate from current field-transfer authority."""

from .moi_default_wire import EffectiveDefaultWireCompiler
from .moi_graph_candidates import eligible_wire
from .native_encoded_analog_capabilities import encoded_analog_capabilities
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-backup-operation-capabilities/19"
ROWS = ("combined-default-wire-compile", "combined-default-wire-transfer")
PAIR_LIMIT = 16


def combined_evidence(snapshot, files, records):
    # These services reuse the actual source/selection readers. Import after the
    # inspection service is constructed; its module also registers this analyzer.
    from .native_default_wire import NativeDefaultWire
    from .native_signal_compiler import SignalCompilerService

    result = {
        "status": "unsupported-source",
        "error": None,
        "pair_attempts": 0,
        "pair_limit": PAIR_LIMIT,
        "witness": None,
        "transfer_qualification": None,
        "transfer_error": None,
    }
    try:
        compiler = EffectiveDefaultWireCompiler(files, snapshot=snapshot)
        service = NativeDefaultWire(records)
        request = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
        source = service.source(request)
        signal = SignalCompilerService(records.storage).source(snapshot["id"])
        if source["fields"] != signal["fields"] or source["parameter_merge"] != compiler.parameters:
            raise ValueError("The paired compiler source changed during local qualification.")
        fields = source["fields"]
        if not fields:
            raise ValueError("No supported existing Real default is recorded in this saved merge.")
        wire, failure = eligible_wire(compiler.wire.effective)
        if wire is None:
            raise ValueError(failure or "No recorded connection has a qualified alternate source.")
        diagram = next(d for d in source["diagrams"] if d["ref"] == wire["diagram_ref"])
        query = {
            **request,
            "source_sha256": source["source_sha256"],
            "effective_sha256": source["effective_sha256"],
            "diagram_ref": diagram["ref"],
            "record_sha256": diagram["archive_record_sha256"],
            "wire_index": wire["wire_index"],
        }
        selected = service.selection(query)
        selection = selected["selection"]
        replacement = next(c for c in selection["candidates"] if not c["current_source"])
        failure = "No paired edit qualified within this local witness search."
        for field in fields[:PAIR_LIMIT]:
            result["pair_attempts"] += 1
            edit = {
                **query,
                "effective_record_sha256": selection["record_sha256"],
                "property_sha256": selection["property_sha256"],
                "old": selection["selected_wire"]["old"],
                "source_ref": replacement["ref"],
                "record_ref": field["ref"],
                "encoded_sha256": field["encoded_sha256"],
                "value_text": "1" if field["effective_bits"] == "00000000" else "0",
            }
            try:
                output, compilation = compiler.compile(
                    **{
                        k: v
                        for k, v in edit.items()
                        if k
                        not in {"capture_id", "snapshot_sha256", "source_sha256", "record_sha256"}
                    }
                )
                if not (
                    compilation["selected_default"]["changed"]
                    and compilation["selected_wire"]["changed"]
                ):
                    raise ValueError("The capability witness must demonstrate two actual changes.")
                result.update(
                    status="source-qualified",
                    witness={
                        "signal": signal,
                        "source": source,
                        "selection": selected,
                        "edit": edit,
                        "compilation": compilation,
                    },
                )
                try:
                    result["transfer_qualification"] = qualify_parameter_additions(
                        output, compilation["parameter_merge"]
                    )
                except ValueError as exc:
                    result["transfer_error"] = (
                        str(exc)[:512] or "Native parameter-type qualification is unavailable."
                    )
                return result
            except ValueError as exc:
                failure = str(exc)[:512] or "This paired edit did not qualify."
        # One eligible wire and at most sixteen Real fields were considered.
        # A bounded unsuccessful probe is not proof that every pair is impossible.
        result.update(status="not-evaluated", error=failure)
    except (ValueError, StopIteration) as exc:
        result["error"] = str(exc)[:512] or "No paired native witness is available."
    return result


def combined_capabilities(snapshot, files, application, *, records, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit combined native operation capability profile.")
    report = encoded_analog_capabilities(snapshot, files, application)
    evidence = combined_evidence(snapshot, files, records)
    q = report["qualification"]
    q["combined_default_wire"] = evidence
    supported = evidence["witness"] is not None
    field_status = (
        "source-mismatch"
        if not q["recorded_identity_verified"]
        else evidence["status"]
        if not supported
        else "unsupported-source"
        if evidence["transfer_qualification"] is None
        else "preflight-required"
        if q["captured_plain_ipv4"]
        else "transport-unavailable"
    )
    report["operations"].extend(
        [
            {
                "id": ROWS[0],
                "operation": "Compile an existing Real default and connection together",
                "status": evidence["status"],
                "basis": (
                    "One actual pair passes both existing compilers, both composition orders and "
                    "exact preservation of all other merged native bytes."
                    if supported
                    else evidence["error"]
                ),
                "next_step": (
                    "Open Program → Native backup defaults, choose the intended Real value and "
                    "connection, then review a local combined copy. This hypothetical witness "
                    "does not stage a draft, return an export review or create a field plan."
                ),
            },
            {
                "id": ROWS[1],
                "operation": "Review a combined Real default and connection transfer",
                "status": field_status,
                "basis": (
                    evidence["transfer_error"]
                    or "The paired source passes native parameter-type "
                    "qualification; the recorded interface determines only preflight availability."
                    if supported
                    else evidence["error"]
                ),
                "next_step": (
                    "Use the combined controller task for fresh identity/interface/default/graph/"
                    "settings/capacity review, explicit confirmations, one-use Apply and full "
                    "readback. This retained analysis grants no transfer or physical acceptance."
                ),
            },
        ]
    )
    report["capability_profile"] = PROFILE
    return report
