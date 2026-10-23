"""Source-qualified eight-input sum built from unchanged portable Add blocks."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Response

from .engine import validate
from .macros import MacroArchive, MacroDefinition, MacroLibrary, import_macro_library
from .models import Edge, Node, Program, StrictModel
from .program_source import SourceMode, source_response

Unit = Literal["", "A", "kW", "cfm", "L/s"]
UNITS = {
    "": "dimensionless",
    "A": "amperes",
    "kW": "kilowatts",
    "cfm": "cfm",
    "L/s": "litres per second",
}
UNIT_IDS = {"": "dimensionless", "A": "amperes", "kW": "kw", "cfm": "cfm", "L/s": "lps"}
SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "date": "2025-10-06",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [677],
    "tables": [276, 277],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Add-8: Input1 through Input8 sum to CH-TOT; zero defaults; editable logic. Chiller Load Total Calc use is not a full capacity calculation or native binding.",
}
PROFILE = {
    "profile": "studio-sum8-macro-template/1",
    "source": SOURCE,
    "units": list(UNITS),
    "semantics": {
        "topology": "Exactly8required numeric ports i1..i8,7ordinary Add blocks and1Output result:16definition nodes. Existing macro expansion/import/instantiate rules unchanged.",
        "order": "Left fold (((((((i1+i2)+i3)+i4)+i5)+i6)+i7)+i8). Manufacturer source does not specify evaluation order; this order is authored. No reassociation or compensated sum.",
        "unused": "Explicitly wire unused contributions to zero. All8macro ports remain required; standalone definition inputs have default0. No hidden missing-writer identity.",
        "units": "All inputs/intermediates/output share one declared catalog unit. No conversion, physical measurement/rating/capacity inference or absolute-temperature summation. Unit names are authored labels, not manufacturer enum codes.",
        "quality": "Unchanged whole-scan bad-quality/nonfinite rollback; retained outputs can be nonzero. No native per-block reliability/underflow signaling or physical protection claim.",
        "numbers": "Use unchanged host binary64 and native REAL/float32 policies. Order does not imply equal trajectories across widths. Actual source atoms, signed zero and scientific spelling are not normalized by this template.",
        "provenance": "Profile/choices/definition/Program/bundle digests bind original generation. Later edits retain historical provenance, not a claim that the edited definition remains the generated template. Hashes do not authenticate manufacturer origin.",
    },
    "gaps": [
        "native JCI Add-8 identity, CAF/package/compiler/transfer and physical controller acceptance",
        "Capacity Calculation rated/running/available/usage semantics and G36/Title24 acceptance",
        "manufacturer operation order, native reliability and arbitrary-width bitwise equivalence",
    ],
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(PROFILE)


class TemplateRequest(StrictModel):
    unit: Unit


class ExportRequest(TemplateRequest):
    format: Literal["review", "bundle"] = "review"


def definition(unit: Unit) -> MacroDefinition:
    # Validate direct callers too; a unit never changes the arithmetic or scale.
    unit = TemplateRequest(unit=unit).unit
    identifier = "studio-sum8-" + UNIT_IDS[unit]
    nodes = [
        Node(
            id=f"i{i}",
            kind="Input",
            label=f"Input {i}",
            x=40.0,
            y=float(i * 80),
            unit=unit,
            params={"default": 0.0},
        )
        for i in range(1, 9)
    ]
    edges = []
    previous = "i1"
    for i in range(2, 9):
        current = f"sum_{i}"
        nodes.append(
            Node(
                id=current,
                kind="Add",
                label=f"Sum through input {i}",
                x=float(220 + i * 140),
                y=320.0,
                unit=unit,
            )
        )
        edges.extend(
            [
                Edge(id=f"sum_{i}_a", source=previous, target=current, target_port="a"),
                Edge(id=f"sum_{i}_b", source=f"i{i}", target=current, target_port="b"),
            ]
        )
        previous = current
    nodes.append(Node(id="result", kind="Output", label="Sum", x=1500.0, y=320.0, unit=unit))
    edges.append(Edge(id="publish_sum", source=previous, target="result"))
    program = Program(
        id=identifier,
        name="Eight-input sum (" + UNITS[unit] + ")",
        description="Authored fixed-order portable sum. Wire all8inputs, using explicit zero for unused contributions. No native JCI or physical capacity acceptance.",
        nodes=nodes,
        edges=edges,
        metadata={
            "sum8_macro_template": {
                "profile": PROFILE["profile"],
                "profile_sha256": PROFILE_SHA,
                "choices": {"unit": unit},
                "choices_sha256": digest({"unit": unit}),
                "source": copy.deepcopy(SOURCE),
                "unimplemented": copy.deepcopy(PROFILE["gaps"]),
            },
            "native_deployment_verified": False,
        },
    )
    return MacroDefinition(id=identifier, name=program.name, program=program)


def preview(request: TemplateRequest):
    item = definition(request.unit)
    bundle = MacroArchive(
        format="bms-macro-library/1",
        root=item.id,
        library=MacroLibrary(version=1, definitions=[item]),
    ).model_dump(mode="json")
    diagnostics = [row.model_dump() for row in validate(item.program)]
    # Exercise the established definition validator, without modifying a caller.
    import_macro_library(Program(), bundle)
    return {
        "format": "bms.sum8-macro-template-preview",
        "version": 1,
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "choices": {"unit": request.unit},
        "choices_sha256": digest({"unit": request.unit}),
        "definition_id": item.id,
        "definition_sha256": digest(item.model_dump(mode="json")),
        "program": item.program.model_dump(mode="json"),
        "program_sha256": item.program.digest(),
        "bundle": bundle,
        "bundle_sha256": digest(bundle),
        "inputs": [
            {
                "id": f"i{i}",
                "label": f"Input {i}",
                "value_type": "number",
                "unit": request.unit,
                "required": True,
            }
            for i in range(1, 9)
        ],
        "output": {"id": "result", "label": "Sum", "value_type": "number", "unit": request.unit},
        "diagnostics": diagnostics,
        "can_import": not any(row["level"] == "error" for row in diagnostics),
        "native_compile": False,
        "controller_writes": False,
    }


def sum8_macro_template_router():
    router = APIRouter(prefix="/api/macros/templates/sum8")

    @router.get("/catalog")
    def catalog():
        return {
            "format": "bms.sum8-macro-template-catalog",
            "version": 1,
            "profile": copy.deepcopy(PROFILE),
            "profile_sha256": PROFILE_SHA,
            "units": [{"value": unit, "label": label} for unit, label in UNITS.items()],
            "exports": ["review", "bundle"],
            "request_schema": TemplateRequest.model_json_schema(),
            "native_compile": False,
            "controller_writes": False,
        }

    @router.post("/preview")
    def preview_route(body: TemplateRequest, source_transport: SourceMode = False):
        return source_response(preview(body), source_transport)

    @router.post("/export")
    def export_route(body: ExportRequest):
        report = preview(TemplateRequest(unit=body.unit))
        raw = canonical(report["bundle"] if body.format == "bundle" else report)
        suffix = ".bms-macro.json" if body.format == "bundle" else ".sum8-review.json"
        return Response(
            raw,
            media_type="application/json",
            headers={
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
                "Content-Disposition": f'attachment; filename="{report["definition_id"]}{suffix}"',
            },
        )

    return router
