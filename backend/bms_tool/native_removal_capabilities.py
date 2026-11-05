"""Explicit local connection-removal witnesses, preserving older capability reports."""

from .moi_connection_removal import MoiConnectionRemoval
from .moi_effective_connection_removal import compiler_from_snapshot
from .native_backup_capabilities import CONNECTION_TRANSFER_PROFILE, backup_capabilities

PROFILE = "native-backup-operation-capabilities/14"


def eligible_removal(compiler):
    failure = None
    for diagram in compiler.wire.reader.summary()["diagrams"]:
        try:
            info = compiler.inspect(diagram["ref"], 0)
            if not info["available"]:
                continue
            wire = info["selected_wire"]
            return {
                "diagram_ref": info["diagram_ref"],
                "wire_index": info["wire_index"],
                "old": wire["old"],
                "source_ref": wire["source_ref"],
                "target_ref": wire["target_ref"],
                "connection_count": info["connection_count"],
                "block_count": info["block_count"],
                "continuation_metadata": info["continuation_metadata"],
                "source_sha256": compiler.editor.source_sha256,
                "record_sha256": info["record_sha256"],
                "property_sha256": info["property_sha256"],
                "metadata_property_sha256": info["metadata_property_sha256"],
                "native_fallback_or_retention_verified": False,
                "field_transfer_enabled": False,
            }, failure
        except ValueError as exc:
            failure = str(exc)[:512]
    return None, failure


def removal_capabilities(snapshot, files, application, *, capability_profile=PROFILE):
    if capability_profile != PROFILE:
        raise ValueError("Select the explicit local connection-removal capability profile.")
    # Keep the complete older implementation and all of its release contracts intact.
    report = backup_capabilities(
        snapshot, files, application, capability_profile=CONNECTION_TRANSFER_PROFILE
    )
    original = effective = None
    original_error = effective_error = None
    try:
        original, original_error = eligible_removal(MoiConnectionRemoval(files[3]))
    except ValueError as exc:
        original_error = str(exc)[:512]
    try:
        effective, effective_error = eligible_removal(
            compiler_from_snapshot(snapshot, files).effective
        )
    except ValueError as exc:
        effective_error = str(exc)[:512]
    report["capability_profile"] = PROFILE
    report["qualification"].update(
        archive_connection_removal=original,
        archive_connection_removal_error=original_error,
        effective_connection_removal=effective,
        effective_connection_removal_error=effective_error,
    )
    rows = []
    for key, title, witness, error, basis in [
        (
            "connection-removal-copy",
            "Save an existing connection removal archive copy",
            original,
            original_error,
            "An actual recorded connection and its aligned optional continuation pass the local archive removal inspector.",
        ),
        (
            "effective-connection-removal-compile",
            "Compile a saved-effective connection removal copy",
            effective,
            effective_error,
            "The identity-qualified retained saved merge preserves graph and continuation structure, then admits an exact existing connection for local removal.",
        ),
    ]:
        rows.append(
            {
                "id": key,
                "operation": title,
                "status": "source-qualified" if witness else "unsupported-source",
                "basis": basis
                if witness
                else error or "No existing connection passes this local removal source profile.",
                "next_step": "Choose Remove existing connection in the recorded Program diagram, select the matching original or saved-effective basis and review a local file copy. The destination becomes unwired; native fallback/retention, field transfer and inverse recovery remain unqualified.",
            }
        )
    position = (
        next(
            i
            for i, row in enumerate(report["operations"])
            if row["id"] == "effective-connection-compile"
        )
        + 1
    )
    report["operations"][position:position] = rows
    next(row for row in report["operations"] if row["id"] == "general-logic")["basis"] = (
        "Installed compilers cover typed identity/defaults and scoped existing-member wire source, matching connection and connection-removal copies, including separately qualified retained saved merges. General native block authoring and resource/package/runtime validation remain separate."
    )
    return report
