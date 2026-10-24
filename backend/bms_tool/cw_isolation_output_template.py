"""Authored fixed-scan, two-output CW command ramp using ordinary activity2."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, model_validator

from .activities import ActivityArchive, ActivityDefinition, ActivityLibrary, import_bundle
from .engine import validate
from .models import Edge, Node, Program, StrictModel
from .program_source import SourceMode, source_response

SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "date": "2025-10-06",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [905, 906],
    "tables": [571, 572],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Enabled command ramp, unramped disable and distinct OnOff/Effective Command roles. Numerical ramp, minimum, Boolean proxy and reset policies below are authored substitutions, not native JCI/G36 equivalence.",
}
PROFILE = {
    "profile": "studio-cw-iso-output-template/1",
    "source": SOURCE,
    "limits": {"minimum_command": [0, 100], "stroke_seconds": [1, 86400], "scan_seconds": [1, 60]},
    "semantics": {
        "topology": "Exactly13 ordinary nodes/14 edges in one activity2 definition, two required inputs device_enable:Boolean and command:number%, two named outputs device_on_off:Boolean and effective_command:number%. One shared Delay stores previous committed selected command; no duplicated ramp state.",
        "alignment": "T and h are strict whole seconds with T>=h and T%h=0; defaults minimum0/T60/h1. step=100*h/T percent per declared scan. These are authored bounds. Preview/export/import bind an explicit activity2 parent whose declared scan equals h. Definition scan does not create a separate clock.",
        "ramp": "target=max(minimum,clamp(command,0,100)); candidate=q+clamp(target-q,-step,+step); effective=device_enable?candidate:0; next q=effective. Enabled upward/downward target changes use the same rate. Minimum is an enabled target floor; transient command may remain below it.",
        "disable_restart": "A committed disable immediately publishes false/0 without a downramp and commits q0. A later enable ramps fresh from0. Fresh sessions use q0, device_enable defaultfalse and command default0. No retained physical valve/pump state is inferred.",
        "boolean": "device_on_off is an authored Boolean logical proxy for enable, not a native Off/On Enum code, run/flow proof or threshold. It can be true with analog0 at minimum0/command0.",
        "quality": "Unchanged full-scan bad-quality/type/arithmetic rollback retains prior time/memory/all outputs, possibly true OnOff and positive command. Bad command quality with a false enable is not a committed disable or physical shutdown.",
        "numbers": "Minimum is a typed float; integer JSON input may become float deliberately, while signedzero is preserved in choices/constants/source. Opaque parent params/metadata are not projected. Existing binary64/REAL/fixed-point profiles and tolerances are unchanged. Full stroke is a nominal rate; last tiny increment/equality time may differ across finite widths.",
        "force": "Output aliases are terminal in this generated graph; selected internal command drives Delay directly. A portable published-output force does not rewrite q. This is graph-specific, not a universal activity isolation rule; no native internal-port forcing is added.",
        "source_guard": "Outer parent_reference binds current validated Program identity/revision/digest/clock. Reviewed import rechecks source/profile/clock then delegates to unchanged activity2 import. Stateless provenance is not persisted review/CAS, authentication, field permission or identity.",
        "idempotence": "Profile+choices determine a stable reusable definition; parent binding is outer only. Repreview after import with the same choices has the same definition/Program/archive hashes. Existing exact source conflict rules remain.",
        "qualification": "Generic imports, later definition/parent clock changes and dt overrides can leave the recorded fixed-scan qualification. No global engine gate or physical actuator model is added.",
    },
    "source_unknowns": [
        "Native numerical ramp and enabled direction policy, transient minimum treatment, disabled analog value and midstroke/restart state are unspecified by the cited pages.",
        "Native bounds/rounding/Enum and reliability behavior are not reproduced. Neighboring dedicated-pump/stager timing, proof and ramp-down logic are separate.",
    ],
    "gaps": [
        "native JCI activity algorithms, Off/On Enum/reliability mapping, CAF/packages/compiler/transfer",
        "actual pump/valve position, flow/run proof, mechanical stroke calibration and physical protection",
        "stager/plant sequencing, minimum-flow/speed acceptance, dynamic stroke/minimum inputs and retained device restart",
        "arbitrary dt or cross-width trajectory equivalence, G36/Title24/physical controller acceptance",
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
    minimum_command: Annotated[float, Field(strict=True, ge=0, le=100)] = 0.0
    stroke_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] = 60
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1

    @model_validator(mode="after")
    def aligned(self):
        if self.stroke_seconds < self.scan_seconds or self.stroke_seconds % self.scan_seconds:
            raise ValueError("Stroke time must be at least one scan and a whole multiple of it.")
        return self


class TemplateRequest(StrictModel):
    program: Program
    choices: Choices

    @model_validator(mode="after")
    def parent_context(self):
        library = self.program.metadata.get("macros")
        if not (
            isinstance(library, dict)
            and type(library.get("version")) is int
            and library["version"] == 2
        ):
            raise ValueError("An explicit activity2 parent is required; review migration first.")
        if self.program.scan_seconds != self.choices.scan_seconds:
            raise ValueError("Current parent scan must equal the reviewed fixed-scan choice.")
        return self


class ExportRequest(TemplateRequest):
    format: Literal["review", "bundle"] = "review"


class ImportRequest(TemplateRequest):
    profile_sha256: Hash
    reviewed_parent_sha256: Hash

    @model_validator(mode="after")
    def current_source(self):
        if self.profile_sha256 != PROFILE_SHA:
            raise ValueError("CW output template profile changed; review again.")
        if self.reviewed_parent_sha256 != self.program.digest():
            raise ValueError("Current parent source differs from the reviewed source.")
        return self


def _fresh(model, value):
    def plain(item):
        if isinstance(item, BaseModel):
            return plain(item.model_dump())
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain(child) for child in item]
        return item

    return model.model_validate(plain(value))


def definition(choices):
    choices = _fresh(Choices, choices)
    values = choices.model_dump(mode="json")
    identifier = "cw_iso_" + digest({"profile_sha256": PROFILE_SHA, "choices": values})[:24]
    step = 100 * choices.scan_seconds / choices.stroke_seconds
    nodes = [
        Node(
            id="device_enable",
            kind="Input",
            label="Logical device enable",
            value_type="boolean",
            params={"default": False},
            x=0,
            y=0,
        ),
        Node(
            id="command",
            kind="Input",
            label="Requested percent command",
            unit="%",
            params={"default": 0},
            x=0,
            y=250,
        ),
        Node(
            id="minimum",
            kind="Constant",
            label="Enabled target floor",
            unit="%",
            params={"value": choices.minimum_command},
            x=280,
            y=450,
        ),
        Node(
            id="zero",
            kind="Constant",
            label="Disabled command",
            unit="%",
            params={"value": 0},
            x=1100,
            y=480,
        ),
        Node(
            id="bounded_command",
            kind="Clamp",
            label="Clamp finite command",
            unit="%",
            params={"min": 0, "max": 100},
            x=280,
            y=250,
        ),
        Node(id="target", kind="Max", label="Minimum as target floor", unit="%", x=560, y=250),
        Node(
            id="previous",
            kind="Delay",
            label="Previous committed selected command",
            unit="%",
            params={"initial": 0},
            x=560,
            y=600,
        ),
        Node(
            id="difference", kind="Subtract", label="Target minus previous", unit="%", x=820, y=250
        ),
        Node(
            id="limited_difference",
            kind="Clamp",
            label="Fixed declared-scan increment",
            unit="%",
            params={"min": -step, "max": step},
            x=1100,
            y=250,
        ),
        Node(id="candidate", kind="Add", label="Enabled ramp candidate", unit="%", x=1380, y=250),
        Node(
            id="selected",
            kind="Switch",
            label="Immediate committed disable",
            unit="%",
            x=1660,
            y=250,
        ),
        Node(
            id="device_on_off",
            kind="Output",
            label="Logical device on/off",
            value_type="boolean",
            x=1940,
            y=0,
        ),
        Node(
            id="effective_command",
            kind="Output",
            label="Effective percent command",
            unit="%",
            x=1940,
            y=300,
        ),
    ]
    wires = [
        ("command", "bounded_command", "in"),
        ("minimum", "target", "a"),
        ("bounded_command", "target", "b"),
        ("target", "difference", "a"),
        ("previous", "difference", "b"),
        ("difference", "limited_difference", "in"),
        ("previous", "candidate", "a"),
        ("limited_difference", "candidate", "b"),
        ("device_enable", "selected", "select"),
        ("candidate", "selected", "on"),
        ("zero", "selected", "off"),
        ("selected", "previous", "in"),
        ("device_enable", "device_on_off", "in"),
        ("selected", "effective_command", "in"),
    ]
    program = Program(
        id=identifier,
        name="Authored CW isolation/pump output",
        scan_seconds=choices.scan_seconds,
        description="Fixed-scan authored percent ramp with immediate committed disable0/reset. Minimum is a target floor, Boolean is an enable proxy. No native JCI/G36 or physical protection acceptance.",
        nodes=nodes,
        edges=[
            Edge(id=f"wire{index}", source=source, target=target, target_port=port)
            for index, (source, target, port) in enumerate(wires)
        ],
        metadata={
            "cw_isolation_output_template": {
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
    return ActivityDefinition(id=identifier, name=program.name, program=program)


def archive(choices):
    item = definition(choices)
    return ActivityArchive(
        format="bms-macro-library/2",
        root=item.id,
        library=ActivityLibrary(version=2, definitions=[item]),
    ).model_dump(mode="json")


def preview(request):
    request = _fresh(TemplateRequest, request)
    item, bundle = definition(request.choices), archive(request.choices)
    # Existing activity admission validates the definition/library while allowing
    # unfinished ordinary parent wiring. This is pure, with no revision save.
    import_bundle(request.program, bundle)
    diagnostics = [row.model_dump() for row in validate(item.program)]

    def ports(kind):
        return [
            {
                "id": n.id,
                "label": n.label,
                "value_type": n.value_type,
                "unit": n.unit,
                **({"required": True} if kind == "Input" else {}),
            }
            for n in item.program.nodes
            if n.kind == kind
        ]

    values = request.choices.model_dump(mode="json")
    return {
        "format": "bms.cw-iso-output-template-preview",
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
        "inputs": ports("Input"),
        "outputs": ports("Output"),
        "diagnostics": diagnostics,
        "can_import": not any(row["level"] == "error" for row in diagnostics),
        "native_compile": False,
        "controller_writes": False,
    }


def import_reviewed(request):
    request = _fresh(ImportRequest, request)
    return import_bundle(request.program, archive(request.choices))


def cw_isolation_output_template_router():
    router = APIRouter(prefix="/api/activities/templates/cw-iso-output")

    @router.get("/catalog")
    def catalog():
        return {
            "format": "bms.cw-iso-output-template-catalog",
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
        suffix = ".bms-activities.json" if body.format == "bundle" else ".cw-iso-review.json"
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
