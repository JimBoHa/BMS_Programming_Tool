"""Authored thermal parallel-fan request and raw-heating-low purge activity."""

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
    "pdf_pages": [1167, 1168],
    "tables": [950, 951],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Heating or cooling fan requests, separate on/off thresholds and heating-below-off purge; defaults 5%, 0.1% and 120 seconds. Exact equality, domain, counter, startup, invalid-good and transaction policies below are authored, not native JCI reliability/Timer/Enum equivalence.",
}
PROFILE = {
    "profile": "studio-parallel-fan-purge-template/1",
    "source": SOURCE,
    "limits": {
        "command_percent": [0, 100],
        "thresholds": "0 < off < on < 100; no epsilon",
        "purge_seconds": [0, 86400],
        "declared_scan_seconds": [1, 60],
    },
    "semantics": {
        "topology": "One shared activity2 graph, five required numeric inputs heating_percent_command%, cooling_percent_command%, fan_on_threshold%, fan_off_threshold% and heating_purge_duration seconds. Two terminal Boolean outputs fan_request and request_configuration_valid. Exactly 51 ordinary nodes/73 edges with two Delay memories: previous request false and previous heat-low elapsed 0 seconds.",
        "defaults": "Heating/cooling commands 0%, on 5%, off 0.1%, purge 120 seconds and declared scan h=1 second. Typed defaults are standalone simulation values; every instantiated input remains required.",
        "validity": "Original commands and thresholds equal safe clamped 0..100 copies, original duration equals its safe 0..86400 copy, and 0<off<on<100. Exact off0/on100, equal/reversed thresholds and out-of-domain good values are invalid. These authored bounds avoid unreachable strict release/start boundaries; they are not native parameter limits.",
        "request": "start = heat>on OR cool>on; raw heat_low = heat<off; cool_low = cool<off. release = heat_low AND cool_low AND next_elapsed>=duration. candidate_request = start OR (previous_request AND NOT release). selected_request = valid ? candidate_request : previous_request. In-band/equal commands retain a previous request unless all release conditions hold. No occupancy, enable, hard shutdown or proof input is invented.",
        "purge": "q_safe=clamp(previous_elapsed,0,86400); candidate_elapsed=clamp(q_safe+h,0,86400); next_elapsed=(valid AND raw heat_low)?candidate_elapsed:0. A committed raw heat>=off resets elapsed even if a heating-hysteresis latch would remain false. Cooling does not reset heat-low elapsed, but must be below off for release. Duration never caps the counter: increasing a live duration preserves already counted low time; lowering it can release on the current successful scan. Zero duration releases on a committed both-low scan. Initial low heat can count while request remains false.",
        "invalid_good": "A successful invalid-good configuration publishes false diagnostic, holds previous request and resets elapsed to 0, breaking untrusted continuity. Repair starts low-time accounting afresh. This is not physical shutdown and can retain an On request.",
        "quality": "Unchanged whole-transaction bad-quality/type/nonfinite/clock/arithmetic rollback retains time, both memories and all outputs, possibly true diagnostic, On request and old elapsed time. Failed intervals are not counted. Continuous raw-low means consecutive accepted valid scans, not physical uninterrupted conditions through a quality gap. Before first success, unchanged portable empty/native zero outputs are not secretly preseeded.",
        "clock": "h is strict whole 1..60 seconds and the reviewed explicit activity2 parent must declare the same scan. The ordinary graph adds constant h per accepted scan; definition metadata is not an independent clock and the graph cannot read actual dt. dt overrides, generic imports into other cadences, internal forces or manual edits can leave recorded qualification. No global engine clock gate is added.",
        "arithmetic": "All evaluated branches use bounded safe inputs. Remembered q is clamped before addition, so q+h<=86460; no division. Starting from q0 with whole h, unforced counter values are integers exactly representable in binary32 below 2^24. Live fractional duration/threshold rounding can still change comparisons. Existing numeric/symbol/SDK/compiler profiles and tolerances remain unchanged.",
        "force": "Only internal selected_request and next_elapsed feed their own Delay memories. Both published output aliases are terminal. Portable terminal-output forcing does not rewrite those memories in this graph; this is not a universal activity-force rule or native internal-port force capability.",
        "source_guard": "Profile+choices determine reusable definition identity. Outer parent reference binds supplied source/revision/declared clock. Reviewed import revalidates fresh DTO source/profile/clock and delegates to unchanged activity2 canonical-conflict import. Stateless provenance is not stored review/CAS, authentication, field permission or identity. No automatic instance/wire/save/network/power action.",
        "widths": "NativeIEC separately rejects inputs outside +/-3e38 or nonzero samples rounding to REAL zero before graph evaluation. Width rounding can coalesce ordered thresholds or round tiny positive off to zero and change admission; preserve those observed limits without epsilon, bound widening or cross-width trace promises.",
    },
    "source_unknowns": [
        "Exact native equalities, Timer duration-clamping bounds/event order, startup and per-input last-reliable/default mechanics are not established here or reproduced by whole-transaction rollback.",
        "The Boolean request is an authored proxy for the documented desired Off/On state, not a native Enum code, run proof or fan-speed command.",
    ],
    "gaps": [
        "flow-assisted/occupancy/standby/bypass parallel-fan requests and native Enum/reliability/Timer mapping",
        "actual-dt-aware live-duration timer, arbitrary cadence equivalence and durable device restart/force migration",
        "motor minimum times, fan/airflow proof, electric-heat protection, physical commands/wiring and complete VAV control",
        "native JCI packages, CAF/compiler/transfer, hardware acceptance and G36/Title24/physical protection",
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
Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Percent = Annotated[Finite, Field(ge=0, le=100)]
Threshold = Annotated[Finite, Field(gt=0, lt=100)]


class Choices(StrictModel):
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1
    heating_percent_command_default: Percent = 0.0
    cooling_percent_command_default: Percent = 0.0
    fan_on_threshold_default: Threshold = 5.0
    fan_off_threshold_default: Threshold = 0.1
    heating_purge_duration_default: Annotated[Finite, Field(ge=0, le=86400)] = 120.0

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.fan_off_threshold_default >= self.fan_on_threshold_default:
            raise ValueError("Fan thresholds require 0 < off < on < 100.")
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
            raise ValueError("Parallel fan purge profile changed; review again.")
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
    identifier = (
        "parallel_fan_purge_" + digest({"profile_sha256": PROFILE_SHA, "choices": values})[:24]
    )
    inputs = [
        (
            "heating_percent_command",
            "Heating percent command",
            "%",
            choices.heating_percent_command_default,
        ),
        (
            "cooling_percent_command",
            "Cooling percent command",
            "%",
            choices.cooling_percent_command_default,
        ),
        ("fan_on_threshold", "Fan on threshold", "%", choices.fan_on_threshold_default),
        ("fan_off_threshold", "Fan off threshold", "%", choices.fan_off_threshold_default),
        (
            "heating_purge_duration",
            "Heating below-off purge duration",
            "s",
            choices.heating_purge_duration_default,
        ),
    ]
    nodes = [
        Node(
            id=id, kind="Input", label=label, unit=unit, params={"default": default}, x=0, y=180 * i
        )
        for i, (id, label, unit, default) in enumerate(inputs)
    ]
    graph = [
        ("heat_safe", "Clamp", "%", {"min": 0, "max": 100}),
        ("cool_safe", "Clamp", "%", {"min": 0, "max": 100}),
        ("on_safe", "Clamp", "%", {"min": 0, "max": 100}),
        ("off_safe", "Clamp", "%", {"min": 0, "max": 100}),
        ("duration_safe", "Clamp", "s", {"min": 0, "max": 86400}),
        ("heat_in_range", "Equal", "", {}),
        ("cool_in_range", "Equal", "", {}),
        ("on_in_range", "Equal", "", {}),
        ("off_in_range", "Equal", "", {}),
        ("duration_in_range", "Equal", "", {}),
        ("zero_percent", "Constant", "%", {"value": 0}),
        ("hundred_percent", "Constant", "%", {"value": 100}),
        ("zero_seconds", "Constant", "s", {"value": 0}),
        ("scan_step", "Constant", "s", {"value": choices.scan_seconds}),
        ("threshold_order", "Greater", "", {}),
        ("off_positive", "Greater", "", {}),
        ("on_below_ceiling", "Less", "", {}),
        ("commands_in_range", "And", "", {}),
        ("thresholds_in_range", "And", "", {}),
        ("percent_ranges_valid", "And", "", {}),
        ("all_ranges_valid", "And", "", {}),
        ("threshold_order_valid", "And", "", {}),
        ("threshold_domain_valid", "And", "", {}),
        ("request_config_ok", "And", "", {}),
        ("heat_below_off", "Less", "", {}),
        ("cool_below_off", "Less", "", {}),
        ("heat_start", "Greater", "", {}),
        ("cool_start", "Greater", "", {}),
        ("thermal_start", "Or", "", {}),
        ("previous_request", "Delay", "", {"initial": False}),
        ("previous_elapsed", "Delay", "s", {"initial": 0}),
        ("bounded_previous_elapsed", "Clamp", "s", {"min": 0, "max": 86400}),
        ("incremented_elapsed", "Add", "s", {}),
        ("capped_elapsed", "Clamp", "s", {"min": 0, "max": 86400}),
        ("elapsed_permission", "And", "", {}),
        ("next_elapsed", "Switch", "s", {}),
        ("purge_not_satisfied", "Less", "", {}),
        ("purge_satisfied", "Not", "", {}),
        ("both_commands_low", "And", "", {}),
        ("release_request", "And", "", {}),
        ("not_release_request", "Not", "", {}),
        ("held_request", "And", "", {}),
        ("candidate_request", "Or", "", {}),
        ("selected_request", "Switch", "", {}),
    ]
    boolean = {"Equal", "Greater", "Less", "And", "Or", "Not"}
    for i, (id, kind, unit, params) in enumerate(graph):
        nodes.append(
            Node(
                id=id,
                kind=kind,
                label=id.replace("_", " ").capitalize(),
                unit=unit,
                value_type="boolean"
                if kind in boolean or id in ("previous_request", "selected_request")
                else "number",
                params=params,
                x=300 + 300 * (i // 7),
                y=180 * (i % 7),
            )
        )
    nodes.extend(
        Node(id=id, kind="Output", label=label, value_type="boolean", x=2400, y=400 + i * 250)
        for i, (id, label) in enumerate(
            [
                ("fan_request", "Parallel fan logical request"),
                ("request_configuration_valid", "Last committed request configuration valid"),
            ]
        )
    )
    wires = []
    for original, safe, in_range in [
        ("heating_percent_command", "heat_safe", "heat_in_range"),
        ("cooling_percent_command", "cool_safe", "cool_in_range"),
        ("fan_on_threshold", "on_safe", "on_in_range"),
        ("fan_off_threshold", "off_safe", "off_in_range"),
        ("heating_purge_duration", "duration_safe", "duration_in_range"),
    ]:
        wires.extend([(original, safe, "in"), (original, in_range, "a"), (safe, in_range, "b")])
    wires.extend(
        [
            ("on_safe", "threshold_order", "a"),
            ("off_safe", "threshold_order", "b"),
            ("off_safe", "off_positive", "a"),
            ("zero_percent", "off_positive", "b"),
            ("on_safe", "on_below_ceiling", "a"),
            ("hundred_percent", "on_below_ceiling", "b"),
            ("heat_in_range", "commands_in_range", "a"),
            ("cool_in_range", "commands_in_range", "b"),
            ("on_in_range", "thresholds_in_range", "a"),
            ("off_in_range", "thresholds_in_range", "b"),
            ("commands_in_range", "percent_ranges_valid", "a"),
            ("thresholds_in_range", "percent_ranges_valid", "b"),
            ("percent_ranges_valid", "all_ranges_valid", "a"),
            ("duration_in_range", "all_ranges_valid", "b"),
            ("threshold_order", "threshold_order_valid", "a"),
            ("off_positive", "threshold_order_valid", "b"),
            ("threshold_order_valid", "threshold_domain_valid", "a"),
            ("on_below_ceiling", "threshold_domain_valid", "b"),
            ("all_ranges_valid", "request_config_ok", "a"),
            ("threshold_domain_valid", "request_config_ok", "b"),
            ("heat_safe", "heat_below_off", "a"),
            ("off_safe", "heat_below_off", "b"),
            ("cool_safe", "cool_below_off", "a"),
            ("off_safe", "cool_below_off", "b"),
            ("heat_safe", "heat_start", "a"),
            ("on_safe", "heat_start", "b"),
            ("cool_safe", "cool_start", "a"),
            ("on_safe", "cool_start", "b"),
            ("heat_start", "thermal_start", "a"),
            ("cool_start", "thermal_start", "b"),
            ("previous_elapsed", "bounded_previous_elapsed", "in"),
            ("bounded_previous_elapsed", "incremented_elapsed", "a"),
            ("scan_step", "incremented_elapsed", "b"),
            ("incremented_elapsed", "capped_elapsed", "in"),
            ("request_config_ok", "elapsed_permission", "a"),
            ("heat_below_off", "elapsed_permission", "b"),
            ("elapsed_permission", "next_elapsed", "select"),
            ("capped_elapsed", "next_elapsed", "on"),
            ("zero_seconds", "next_elapsed", "off"),
            ("next_elapsed", "purge_not_satisfied", "a"),
            ("duration_safe", "purge_not_satisfied", "b"),
            ("purge_not_satisfied", "purge_satisfied", "in"),
            ("heat_below_off", "both_commands_low", "a"),
            ("cool_below_off", "both_commands_low", "b"),
            ("both_commands_low", "release_request", "a"),
            ("purge_satisfied", "release_request", "b"),
            ("release_request", "not_release_request", "in"),
            ("previous_request", "held_request", "a"),
            ("not_release_request", "held_request", "b"),
            ("thermal_start", "candidate_request", "a"),
            ("held_request", "candidate_request", "b"),
            ("request_config_ok", "selected_request", "select"),
            ("candidate_request", "selected_request", "on"),
            ("previous_request", "selected_request", "off"),
            ("selected_request", "previous_request", "in"),
            ("next_elapsed", "previous_elapsed", "in"),
            ("selected_request", "fan_request", "in"),
            ("request_config_ok", "request_configuration_valid", "in"),
        ]
    )
    program = Program(
        id=identifier,
        name="Authored parallel fan thermal request and purge",
        scan_seconds=choices.scan_seconds,
        description="Fixed-declared-scan thermal request and separate raw-heating-below-off purge. Five live inputs; invalid-good holds request/resets elapsed, bad quality rolls back. Not physical fan/motor protection or native JCI logic.",
        nodes=nodes,
        edges=[
            Edge(id=f"wire{i}", source=a, target=b, target_port=port)
            for i, (a, b, port) in enumerate(wires)
        ],
        metadata={
            "parallel_fan_purge_template": {
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
        "format": "bms.parallel-fan-purge-template-preview",
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


def parallel_fan_purge_template_router():
    router = APIRouter(prefix="/api/activities/templates/parallel-fan-purge")

    @router.get("/catalog")
    def catalog():
        return {
            "format": "bms.parallel-fan-purge-template-catalog",
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
        suffix = (
            ".bms-activities.json" if body.format == "bundle" else ".parallel-fan-purge-review.json"
        )
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
