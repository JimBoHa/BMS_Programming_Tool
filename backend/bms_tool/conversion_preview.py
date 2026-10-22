"""Bounded source conversion evidence; never connect, compile or deploy."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from .engine import validate
from .formats import export_program, import_program
from .macros import expand_macros
from .models import Program
from .source_profiles import source_profile

PROFILE = "conversion-preview/1"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
SOURCE_FORMATS = (
    ("json", "BMS project"),
    ("st", "IEC Structured Text"),
    ("plcopen", "PLCopen XML with Structured Text"),
    ("graphml", "GraphML authoring graph"),
    ("bog", "Tridium Niagara BOG primitive profile"),
    ("temco-bas", "Temco Control Basic"),
)


def _notes(format, calendars):
    notes = [
        {
            "code": "not-deployment",
            "severity": "review",
            "message": "Source generation and editable round-trip checks do not prove target compilation, physical I/O mapping or controller acceptance.",
        }
    ]
    if format in ("st", "plcopen", "sedona"):
        notes.append(
            {
                "code": "float32",
                "severity": "difference",
                "message": "Target REAL/float arithmetic uses 32-bit precision; the local graph uses Python numeric arithmetic. Rounding, overflow and retained-state behavior need independent target execution.",
            }
        )
    if format in ("st", "plcopen", "sedona", "temco-bas"):
        notes.append(
            {
                "code": "host-scan-clock-io",
                "severity": "requirement",
                "message": "The destination must supply the declared scan cadence, inputs, clock and physical output bindings. Export does not configure hardware.",
            }
        )
        if calendars:
            notes.append(
                {
                    "code": "host-calendar",
                    "severity": "requirement",
                    "nodes": calendars,
                    "message": "These schedules require destination-host calendar active/valid provisioning. Export preserves authoring rules; an unprovisioned calendar does not become a working field schedule.",
                }
            )
    if format == "bog":
        notes.extend(
            [
                {
                    "code": "niagara-execution",
                    "severity": "difference",
                    "message": "Niagara component/event execution, status propagation and priority behavior differ from an atomic Studio scan. Genuine module metadata is checked by the adapter; licensed station execution remains unverified.",
                },
                {
                    "code": "niagara-profile",
                    "severity": "requirement",
                    "message": "This is the supported primitive BOG profile, not full station conversion. Review required modules, facets and native links in the destination station.",
                },
            ]
        )
    if format == "temco-bas":
        notes.extend(
            [
                {
                    "code": "temco-fixed-point",
                    "severity": "difference",
                    "message": "The native interpreter uses signed 32-bit fixed point at 0.001 resolution. Source representability does not prove intermediate arithmetic or compiled resource fit.",
                },
                {
                    "code": "temco-quality",
                    "severity": "difference",
                    "message": "The Control Basic source profile does not carry sensor quality flags. Commission fault handling and the emitted IN/OUT/VAR bindings separately.",
                },
            ]
        )
    if format in ("json", "graphml"):
        notes.append(
            {
                "code": "authoring-artifact",
                "severity": "scope",
                "message": "This retains the authoring project, not a running process, force map, live field state or deployable manufacturer application.",
            }
        )
    return notes


def conversion_preview(program: Program):
    """Exercise existing in-process encoders, reporting every target independently.

    No native toolchain is invoked. Native-only formats get a source-lowering
    assessment with an explicit uncompiled outcome, never an inferred success.
    """
    diagnostics = [d.model_dump() for d in validate(program)]
    try:
        expanded = expand_macros(program)
        expansion_error = None
    except ValueError as exc:
        expanded, expansion_error = program, str(exc)
    calendars = [
        n.id
        for n in expanded.nodes
        if n.kind == "Schedule" and (n.params.get("timezone") or n.params.get("exceptions"))
    ]
    report = {
        "profile": PROFILE,
        "created_at": datetime.now(UTC).isoformat(),
        "program": {
            "id": program.id,
            "name": program.name,
            "revision": program.revision,
            "sha256": program.digest(),
        },
        "source": {
            "nodes": len(program.nodes),
            "expanded_nodes": len(expanded.nodes),
            "edges": len(expanded.edges),
            "block_kinds": sorted({n.kind for n in expanded.nodes}),
            "inputs": [n.id for n in expanded.nodes if n.kind == "Input"],
            "outputs": [n.id for n in expanded.nodes if n.kind == "Output"],
            "host_calendar_nodes": calendars,
            "expansion_error": expansion_error,
        },
        "diagnostics": diagnostics,
        "targets": [],
        "scope": "Offline source assessment only. No native compiler, field interface, transfer or runtime execution is invoked. Editable round-trip equality does not prove executable semantic equivalence.",
    }
    for format, name in SOURCE_FORMATS:
        row = {
            "format": format,
            "name": name,
            "status": "blocked",
            "artifact": None,
            "editable_round_trip": None,
            "notes": _notes(format, calendars),
            "error": None,
            "native_compilation": "not-run",
            "controller_acceptance": "unverified",
        }
        if format in ("st", "plcopen"):
            row["source_generator"] = source_profile()
        try:
            content, mime, extension = export_program(program, format)
            if len(content) > MAX_ARTIFACT_BYTES:
                raise ValueError("Preview artifact exceeds the 4 MiB per-format bound.")
            restored = import_program(content, "preview." + extension)
            equal = restored.digest() == program.digest()
            row.update(
                status="source-generated" if equal else "source-generated-review-required",
                artifact={
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mime": mime,
                    "extension": extension,
                },
                editable_round_trip={
                    "exact": equal,
                    "restored_sha256": restored.digest(),
                    "changed_fields": [
                        key
                        for key, value in program.model_dump().items()
                        if value != restored.model_dump()[key]
                    ],
                },
            )
            if not equal:
                row["notes"].append(
                    {
                        "code": "authoring-round-trip-changes",
                        "severity": "difference",
                        "message": "Re-import changed authoring fields. This is not a proof of execution equivalence or failure; inspect the changed fields before using this artifact.",
                    }
                )
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            row["error"] = str(exc)[:4096]
        report["targets"].append(row)
    sedona = {
        "format": "sedona",
        "name": "Native Sedona bundle / SAX / SAB",
        "status": "blocked",
        "artifact": None,
        "editable_round_trip": None,
        "native_compilation": "not-run",
        "controller_acceptance": "unverified",
        "notes": _notes("sedona", calendars),
        "error": None,
        "source_generator": source_profile(),
    }
    try:
        from .sedona import application_xml, kit_source

        source = kit_source(program)
        application_xml(
            "preview",
            scan_seconds=program.scan_seconds,
            native_document=program.metadata.get("native_sedona"),
        )
        if len(source) > MAX_ARTIFACT_BYTES:
            raise ValueError("Sedona source exceeds the 4 MiB preview bound.")
        sedona["status"] = "source-lowering-checked"
        sedona["notes"].append(
            {
                "code": "sedona-kit-image",
                "severity": "requirement",
                "message": "Actual bundle/SAX/SAB export requires the Sedona SDK and generated compatible kit/image. Only the bundle preserves the editable graph. This preview does not invoke Java, compiler or SVM.",
            }
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        sedona["error"] = str(exc)[:4096]
    report["targets"].append(sedona)
    for format, name in (
        ("jci-caf", "Johnson Controls FX / Metasys CAF"),
        ("alc", "ALC native controller program"),
        ("honeywell-spyder", "Honeywell Spyder native program"),
    ):
        report["targets"].append(
            {
                "format": format,
                "name": name,
                "status": "no-verified-encoder",
                "artifact": None,
                "editable_round_trip": None,
                "native_compilation": "unavailable",
                "controller_acceptance": "unverified",
                "notes": [],
                "error": "No verified graph-to-native encoder and acceptance path exists for this target. Existing archive inspection or narrow native edits do not establish arbitrary graph conversion.",
            }
        )
    return report
