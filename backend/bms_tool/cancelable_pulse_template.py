"""A fixed-duration, scan-qualified pulse composed from ordinary typed blocks."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .engine import validate
from .macros import MacroArchive, MacroDefinition, MacroLibrary, import_macro_library
from .models import Edge, Node, Program, StrictModel
from .program_source import SourceMode, source_response

SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "date": "2025-10-06",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [1698, 1699, 1700],
    "tables": [1375],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Rising input starts a pulse; input false cancels it. Native dynamic duration, Reset Action, timing resolution and restart semantics are separate from this authored fixed-scan graph.",
}
PROFILE = {
    "profile": "studio-cancelable-pulse-template/1",
    "source": SOURCE,
    "limits": {"duration_seconds": [1, 86400], "scan_seconds": [1, 60]},
    "semantics": {
        "topology": "Exactly6ordinary nodes/6edges: required Boolean request -> TimerOn(D) -> Boolean Delay(initialfalse) -> Not; request AND Not -> Boolean Output. Independent state per macro instance.",
        "alignment": "D and h are whole seconds; D>=h and D%h=0. DefaultsD5/h1. These are authored bounds, not native manufacturer timing limits or rounding. Preview/export/import require the current parent Program.scan_seconds==h.",
        "phase": "Each successful scan adds h to elapsed while requesttrue. Pulse=request AND NOT previous committed TimerOn-done. First true is published at h, remains true at h..D, becomes false at D+h when request stays true. Published true-to-false interval is D; no physical edge-at-time0 claim.",
        "cancel": "A committed false request immediately publishes false, resets elapsed to0 and stores donefalse. A later true starts a new pulse. Heldtrue after expiry never retriggers automatically. D=h emits one true scan then false.",
        "restart": "Fresh engine/session state uses elapsed0, previousdonefalse and requestdefaultfalse. An explicitly true first input starts a new pulse. No separate reset/enable input, retained state or emulated native Reset Action.",
        "quality": "Unchanged whole-scan bad-quality/nonfinite rollback retains previous state/time/outputs, including a positive pulse. False with bad quality is not a committed cancellation or physical shutdown.",
        "source_guard": "Review binds canonical current parent Program digest and declared scan. Narrow import rechecks profile, current supplied parent digest and clock before unchanged generic macro merge. Stateless reviewed_parent_sha256 is a stale-payload/provenance check, not persisted review, server CAS, authentication or physical identity.",
        "qualification": "Macro execution inherits its parent clock. Manual generic imports, later parent clock edits and per-step dt overrides may leave this historical fixed-scan qualification. No global runtime admission gate is added; generated metadata is historical generation evidence.",
        "numbers": "Original portable Program atoms and unchanged host binary64/native REAL policies remain. Whole admitted seconds are exactly representable up to D; no arbitrary-dt, native JCI or cross-runtime trajectory claim.",
    },
    "source_conflicts": [
        "Manual prose minimum5seconds conflicts with effective-duration clamp minimum1second. This authored profile deliberately permits1second independently.",
        "Manual duration resolution switches below/above6535seconds with equality unspecified. This authored graph uses admitted whole seconds through86400 without native minute rounding.",
    ],
    "gaps": [
        "native JCI Timer identity/reliability, CAF/package/compiler/transfer and physical controller acceptance",
        "dynamic Duration, Setup, Reset Action, Time Remaining and other timer modes",
        "arbitrary dt, native power/re-enable behavior, retained restart state or physical protection",
    ],
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(PROFILE)
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class Choices(StrictModel):
    duration_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] = 5
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1

    @model_validator(mode="after")
    def aligned(self):
        if self.duration_seconds < self.scan_seconds:
            raise ValueError("Duration must be at least one declared scan.")
        if self.duration_seconds % self.scan_seconds:
            raise ValueError("Duration must be a whole multiple of the declared scan seconds.")
        return self


class TemplateRequest(StrictModel):
    program: Program
    choices: Choices

    @model_validator(mode="after")
    def parent_clock(self):
        if self.program.scan_seconds != self.choices.scan_seconds:
            raise ValueError("Current parent Program scan seconds must equal the reviewed scan.")
        return self


class ExportRequest(TemplateRequest):
    format: Literal["review", "bundle"] = "review"


class ImportRequest(TemplateRequest):
    profile_sha256: Hash
    reviewed_parent_sha256: Hash

    @model_validator(mode="after")
    def current_source(self):
        if self.profile_sha256 != PROFILE_SHA:
            raise ValueError("Cancelable pulse profile changed; review the current profile again.")
        if self.reviewed_parent_sha256 != self.program.digest():
            raise ValueError("Current parent Program differs from the reviewed parent source.")
        return self


def definition(choices: Choices) -> MacroDefinition:
    choices = Choices.model_validate(
        choices.model_dump() if isinstance(choices, Choices) else choices
    )
    values = choices.model_dump(mode="json")
    identifier = f"studio-cancelable-pulse-d{choices.duration_seconds}-s{choices.scan_seconds}"
    nodes = [
        Node(
            id="request",
            kind="Input",
            label="Request",
            value_type="boolean",
            params={"default": False},
            x=40,
            y=80,
        ),
        Node(
            id="elapsed",
            kind="TimerOn",
            label="Continuous request elapsed",
            value_type="boolean",
            params={"seconds": choices.duration_seconds},
            x=240,
            y=200,
        ),
        Node(
            id="expired_previous",
            kind="Delay",
            label="Previous committed expiry",
            value_type="boolean",
            params={"initial": False},
            x=440,
            y=200,
        ),
        Node(
            id="not_expired",
            kind="Not",
            label="Previous scan not expired",
            value_type="boolean",
            x=640,
            y=200,
        ),
        Node(id="pulse", kind="And", label="Cancelable pulse", value_type="boolean", x=850, y=80),
        Node(id="result", kind="Output", label="Pulse", value_type="boolean", x=1080, y=80),
    ]
    edges = [
        Edge(id="request_elapsed", source="request", target="elapsed"),
        Edge(id="elapsed_memory", source="elapsed", target="expired_previous"),
        Edge(id="memory_inversion", source="expired_previous", target="not_expired"),
        Edge(id="request_pulse", source="request", target="pulse", target_port="a"),
        Edge(id="expiry_pulse", source="not_expired", target="pulse", target_port="b"),
        Edge(id="publish", source="pulse", target="result"),
    ]
    program = Program(
        id=identifier,
        name=f"Cancelable pulse ({choices.duration_seconds}s / {choices.scan_seconds}s scan)",
        scan_seconds=choices.scan_seconds,
        description="Authored fixed-duration cancelable pulse. First publishedtrue at h, expiryfalse at D+h; false request cancels. Bad quality retains previous committed outputs. Macro inherits parent clock; no native JCI/physical protection acceptance.",
        nodes=nodes,
        edges=edges,
        metadata={
            "cancelable_pulse_template": {
                "profile": PROFILE["profile"],
                "profile_sha256": PROFILE_SHA,
                "choices": values,
                "choices_sha256": digest(values),
                "source": copy.deepcopy(SOURCE),
                "unimplemented": copy.deepcopy(PROFILE["gaps"]),
            },
            "native_deployment_verified": False,
        },
    )
    return MacroDefinition(id=identifier, name=program.name, program=program)


def archive(choices: Choices):
    item = definition(choices)
    return MacroArchive(
        format="bms-macro-library/1",
        root=item.id,
        library=MacroLibrary(version=1, definitions=[item]),
    ).model_dump(mode="json")


def preview(request: TemplateRequest):
    # Revalidate direct callers as well as HTTP DTOs. This does not rewrite the parent.
    request = TemplateRequest.model_validate(
        request.model_dump() if isinstance(request, TemplateRequest) else request
    )
    item = definition(request.choices)
    bundle = archive(request.choices)
    diagnostics = [row.model_dump() for row in validate(item.program)]
    import_macro_library(Program(), bundle)
    values = request.choices.model_dump(mode="json")
    return {
        "format": "bms.cancelable-pulse-template-preview",
        "version": 1,
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "choices": values,
        "choices_sha256": digest(values),
        "parent_reference": {
            "id": request.program.id,
            "revision": request.program.revision,
            "scan_seconds": request.program.scan_seconds,
            "program_sha256": request.program.digest(),
        },
        "definition_id": item.id,
        "definition_sha256": digest(item.model_dump(mode="json")),
        "program": item.program.model_dump(mode="json"),
        "program_sha256": item.program.digest(),
        "bundle": bundle,
        "bundle_sha256": digest(bundle),
        "inputs": [
            {
                "id": "request",
                "label": "Request",
                "value_type": "boolean",
                "unit": "",
                "required": True,
            }
        ],
        "output": {"id": "result", "label": "Pulse", "value_type": "boolean", "unit": ""},
        "diagnostics": diagnostics,
        "can_import": not any(row["level"] == "error" for row in diagnostics),
        "native_compile": False,
        "controller_writes": False,
    }


def import_reviewed(request: ImportRequest):
    request = ImportRequest.model_validate(
        request.model_dump() if isinstance(request, ImportRequest) else request
    )
    return import_macro_library(request.program, archive(request.choices))


def cancelable_pulse_template_router():
    router = APIRouter(prefix="/api/macros/templates/cancelable-pulse")

    @router.get("/catalog")
    def catalog():
        return {
            "format": "bms.cancelable-pulse-template-catalog",
            "version": 1,
            "profile": copy.deepcopy(PROFILE),
            "profile_sha256": PROFILE_SHA,
            "defaults": Choices().model_dump(mode="json"),
            "choices_schema": Choices.model_json_schema(),
            "request_schema": TemplateRequest.model_json_schema(),
            "import_schema": ImportRequest.model_json_schema(),
            "exports": ["review", "bundle"],
            "native_compile": False,
            "controller_writes": False,
        }

    @router.post("/preview")
    def preview_route(body: TemplateRequest, source_transport: SourceMode = False):
        return source_response(preview(body), source_transport)

    @router.post("/export")
    def export_route(body: ExportRequest):
        report = preview(TemplateRequest(program=body.program, choices=body.choices))
        raw = canonical(report["bundle"] if body.format == "bundle" else report)
        suffix = ".bms-macro.json" if body.format == "bundle" else ".pulse-review.json"
        return Response(
            raw,
            media_type="application/json",
            headers={
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
                "Content-Disposition": f'attachment; filename="{report["definition_id"]}{suffix}"',
            },
        )

    @router.post("/import")
    def import_route(body: ImportRequest, source_transport: SourceMode = False):
        return source_response(import_reviewed(body), source_transport)

    return router
