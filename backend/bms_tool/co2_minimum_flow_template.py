"""Authored live-endpoint CO2 minimum-airflow reset using one ordinary activity2."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, model_validator

from .activities import ActivityArchive, ActivityDefinition, ActivityLibrary, import_bundle
from .engine import validate
from .equipment_wizard import CFM_TO_LPS
from .models import Edge, Node, Program, StrictModel
from .program_source import SourceMode, source_response

SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "date": "2025-10-06",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [736, 737],
    "tables": [350, 351],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Five live inputs, airflow output in cfm, 800 / 1000 ppm and 425 / 825 cfm defaults and last reliable wording. In-band linear curve, domain, invalid-configuration hold, diagnostic and transaction policy are authored substitutions, not native JCI/G36 equivalence.",
}
PROFILE = {
    "profile": "studio-co2-minimum-flow-template/1",
    "source": SOURCE,
    "limits": {"CO2_endpoint_ppm": [0, 1000000], "flow_endpoint_Lps_equivalent": [0, 1000000]},
    "flow_units": ["cfm", "L/s"],
    "conversion_factor_cfm_to_Lps": "0.4719474432",
    "semantics": {
        "topology": "Exactly 38 ordinary nodes and 57 edges, five required numeric runtime inputs co2, co2_reset_a, co2_reset_b, flow_low, flow_high and two terminal outputs minimum_airflow (number in the chosen flow unit) and reset_configuration_valid (Boolean). One Delay retains previous selected unforced airflow; no duplicate graph per output.",
        "defaults": "Documented cfm defaults are measured CO2 = 800 ppm, A = 800 ppm, B = 1000 ppm, L = 425 cfm and H = 825 cfm. Metric defaults are derived using the stated existing factor, not substituted rounded manufacturer values. Defaults are standalone-definition simulation values; every instance port remains required.",
        "validity": "Original endpoint inputs must equal their safe clamped copies; original CO2 endpoints lie in 0–1,000,000 ppm and flow endpoints in 0–1,000,000 L/s equivalent. B > A and H >= L; flat flow is valid. Measured CO2 may be any finite portable sample. Typed defaults must already satisfy this domain/order; runtime wiring can produce invalid good-quality configurations.",
        "arithmetic": "Using safe clamped A, B, L and H: denominator = (B > A) ? B - A : 1 ppm; sample = max(A, min(B, co2)); fraction = clamp((sample - A) / denominator, 0, 1); candidate = max(L, min(H, L + fraction * (H - L))). Both evaluated Switch branches use bounded arithmetic; no short-circuit, epsilon or hidden Divide behavior is assumed.",
        "hold": "selected = configuration_valid ? candidate : previous_valid_flow; next previous_valid_flow = selected. A successful invalid good-quality configuration publishes false diagnostic and holds previous selected airflow. First such scan explicitly falls back to 0 flow. Repair resumes immediately; no reset, enable or timer input is invented.",
        "quality": "Existing whole transaction bad-quality/type/nonfinite/clock/arithmetic rollback retains prior time/state/all outputs, possibly true diagnostic and positive flow. Diagnostic means last committed configuration, not current input quality/module reliability/occupancy/plant permission or measured ventilation. Before any successful scan, unchanged Python empty / native zero startup remains; outputs are not preseeded.",
        "units": "Flow defaults only are converted using the existing stated factor. Typed floats deliberately admit integer JSON numbers as float; signed zero is retained. Conversion revalidates bounds and refuses nonzero-to-zero underflow or collapse of a previously nonflat flow pair. No exact round trip or cross-width trajectory promise.",
        "clock": "No timing parameter or independent clock. Normal parent scan/dt semantics apply, including valid parent scans of 0.5 or 3 seconds. Outer reviewed parent reference binds validated actual source/revision/declared clock without requiring equality to definition metadata of 1.0 seconds.",
        "source_guard": "Profile + choices determine reusable definition identity; parent binding is outer only. Reviewed import revalidates supplied canonical parent/profile and delegates to unchanged activity2 canonical-conflict import. Stateless provenance is not persisted review/CAS, authentication, field permission or physical identity. No autosave, instance, network or power action.",
        "force": "Both output aliases are terminal; only selected internal unforced flow feeds Delay. Portable terminal force does not rewrite retained flow in this graph. This is not a universal activity-force isolation rule or native internal-port forcing. Forces/manual edits can leave authored bounds.",
        "widths": "Unchanged portable binary64/native REAL numeric profiles apply. NativeIEC rejects inputs outside ±3e38 or nonzero samples rounding to REAL zero before the graph; a portable finite sample need not be native-representable. Endpoint rounding can coalesce a native span and commit false/held flow where portable still computes true. Adjacent/near-min-normal cases do not establish arbitrary-width equivalence or physical response.",
        "application": "Output is a minimum-airflow request, not percent damper position or an inferred physical AO/VAV primary minimum. Appropriate downstream airflow control and engineering are separate. Generic imports/edits may leave this template's recorded qualification; no global enforcement is added.",
    },
    "source_unknowns": [
        "Native in-band curve, invalid-band/startup/reliability granularity and complete connection/default/last reliable mechanics are unspecified here and not reproduced by whole transaction policy.",
        "MAD-MINPOS/position wording does not change the cited cfm output into a percent command. Application/physical controller packages and algorithm identity remain unverified.",
    ],
    "gaps": [
        "native JCI algorithm/Enum / reliability/application-tree bindings, controller packages, CAF compiler / transfer",
        "OA sensor/flow calibration, physical downstream airflow control, mechanical response and ventilation sizing",
        "population/area and occupancy calculations, project G36 / Title 24 compliance and field/Bluetooth acceptance",
        "arbitrary finite-width/roundtrip equivalence, native internal-port forcing and physical protection",
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
FlowUnit = Literal["cfm", "L/s"]


def flow_cap(unit):
    return 1000000 / CFM_TO_LPS if unit == "cfm" else 1000000


class Choices(StrictModel):
    flow_unit: FlowUnit = "cfm"
    co2_default: Finite = 800.0
    co2_reset_a_default: Annotated[Finite, Field(ge=0, le=1000000)] = 800.0
    co2_reset_b_default: Annotated[Finite, Field(ge=0, le=1000000)] = 1000.0
    flow_low_default: Annotated[Finite, Field(ge=0)] = 425.0
    flow_high_default: Annotated[Finite, Field(ge=0)] = 825.0

    @model_validator(mode="after")
    def valid_defaults(self):
        if self.co2_reset_b_default <= self.co2_reset_a_default:
            raise ValueError("CO2 Reset B default must exceed Reset A default.")
        if self.flow_high_default < self.flow_low_default:
            raise ValueError("High minimum-airflow default must be at least the low default.")
        if max(self.flow_low_default, self.flow_high_default) > flow_cap(self.flow_unit):
            raise ValueError("Flow defaults exceed the authored 1,000,000 L/s-equivalent domain.")
        return self


class TemplateRequest(StrictModel):
    program: Program
    choices: Choices

    @model_validator(mode="after")
    def activity_parent(self):
        library = self.program.metadata.get("macros")
        if not (
            isinstance(library, dict)
            and type(library.get("version")) is int
            and library["version"] == 2
        ):
            raise ValueError("An explicit activity2 parent is required; review migration first.")
        return self


class ExportRequest(TemplateRequest):
    format: Literal["review", "bundle"] = "review"


class ImportRequest(TemplateRequest):
    profile_sha256: Hash
    reviewed_parent_sha256: Hash

    @model_validator(mode="after")
    def current_source(self):
        if self.profile_sha256 != PROFILE_SHA:
            raise ValueError("CO2 flow template profile changed; review again.")
        if self.reviewed_parent_sha256 != self.program.digest():
            raise ValueError("Current parent source differs from the reviewed source.")
        return self


class UnitsRequest(StrictModel):
    choices: Choices
    flow_unit: FlowUnit
    profile_sha256: Hash

    @model_validator(mode="after")
    def current_profile(self):
        if self.profile_sha256 != PROFILE_SHA:
            raise ValueError("CO2 flow template profile changed; reload criteria.")
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


def convert_units(value, flow_unit):
    request = _fresh(
        UnitsRequest, {"choices": value, "flow_unit": flow_unit, "profile_sha256": PROFILE_SHA}
    )
    values = request.choices.model_dump(mode="json")
    if request.flow_unit != request.choices.flow_unit:
        ratio = CFM_TO_LPS if request.flow_unit == "L/s" else 1 / CFM_TO_LPS
        for name in ("flow_low_default", "flow_high_default"):
            converted = values[name] * ratio
            if values[name] != 0 and converted == 0:
                raise ValueError("Flow conversion underflow would erase a nonzero endpoint.")
            values[name] = converted
        if (
            request.choices.flow_high_default > request.choices.flow_low_default
            and values["flow_high_default"] == values["flow_low_default"]
        ):
            raise ValueError("Flow conversion would collapse a nonflat endpoint pair.")
    values["flow_unit"] = request.flow_unit
    return _fresh(Choices, values)


def definition(choices):
    choices = _fresh(Choices, choices)
    values = choices.model_dump(mode="json")
    identifier = "co2_min_flow_" + digest({"profile_sha256": PROFILE_SHA, "choices": values})[:24]
    unit, cap = choices.flow_unit, flow_cap(choices.flow_unit)
    inputs = [
        ("co2", "Measured CO2", "ppm", choices.co2_default),
        ("co2_reset_a", "CO2 Reset A", "ppm", choices.co2_reset_a_default),
        ("co2_reset_b", "CO2 Reset B", "ppm", choices.co2_reset_b_default),
        ("flow_low", "Low minimum airflow", unit, choices.flow_low_default),
        ("flow_high", "High minimum airflow", unit, choices.flow_high_default),
    ]
    nodes = [
        Node(id=id, kind="Input", label=label, unit=u, params={"default": default}, x=0, y=180 * i)
        for i, (id, label, u, default) in enumerate(inputs)
    ]
    arithmetic = [
        ("a_safe", "Clamp", "ppm", {"min": 0, "max": 1000000}),
        ("b_safe", "Clamp", "ppm", {"min": 0, "max": 1000000}),
        ("low_safe", "Clamp", unit, {"min": 0, "max": cap}),
        ("high_safe", "Clamp", unit, {"min": 0, "max": cap}),
        ("a_in_range", "Equal", "", {}),
        ("b_in_range", "Equal", "", {}),
        ("low_in_range", "Equal", "", {}),
        ("high_in_range", "Equal", "", {}),
        ("ordered_co2", "Greater", "", {}),
        ("descending_flow", "Less", "", {}),
        ("ordered_flow", "Not", "", {}),
        ("bands_in_range", "And", "", {}),
        ("flows_in_range", "And", "", {}),
        ("ranges_valid", "And", "", {}),
        ("orders_valid", "And", "", {}),
        ("reset_config_ok", "And", "", {}),
        ("fallback_span", "Constant", "ppm", {"value": 1}),
        ("co2_span", "Subtract", "ppm", {}),
        ("denominator", "Switch", "ppm", {}),
        ("co2_upper", "Min", "ppm", {}),
        ("co2_bounded", "Max", "ppm", {}),
        ("above_lower", "Subtract", "ppm", {}),
        ("fraction", "Divide", "", {}),
        ("bounded_fraction", "Clamp", "", {"min": 0, "max": 1}),
        ("flow_span", "Subtract", unit, {}),
        ("scaled_span", "Multiply", unit, {}),
        ("raw_candidate", "Add", unit, {}),
        ("candidate_upper", "Min", unit, {}),
        ("bounded_candidate", "Max", unit, {}),
        ("previous_valid_flow", "Delay", unit, {"initial": 0}),
        ("selected_flow", "Switch", unit, {}),
    ]
    boolean = {"Equal", "Greater", "Less", "Not", "And"}
    for i, (id, kind, u, params) in enumerate(arithmetic):
        nodes.append(
            Node(
                id=id,
                kind=kind,
                label=id.replace("_", " ").capitalize(),
                unit=u,
                value_type="boolean" if kind in boolean else "number",
                params=params,
                x=300 + 300 * (i // 6),
                y=180 * (i % 6),
            )
        )
    nodes.extend(
        [
            Node(
                id="minimum_airflow",
                kind="Output",
                label="Minimum airflow request",
                unit=unit,
                x=2200,
                y=650,
            ),
            Node(
                id="reset_configuration_valid",
                kind="Output",
                label="Last committed reset configuration valid",
                value_type="boolean",
                x=2200,
                y=900,
            ),
        ]
    )
    wires = [
        ("co2_reset_a", "a_safe", "in"),
        ("co2_reset_b", "b_safe", "in"),
        ("flow_low", "low_safe", "in"),
        ("flow_high", "high_safe", "in"),
        ("co2_reset_a", "a_in_range", "a"),
        ("a_safe", "a_in_range", "b"),
        ("co2_reset_b", "b_in_range", "a"),
        ("b_safe", "b_in_range", "b"),
        ("flow_low", "low_in_range", "a"),
        ("low_safe", "low_in_range", "b"),
        ("flow_high", "high_in_range", "a"),
        ("high_safe", "high_in_range", "b"),
        ("b_safe", "ordered_co2", "a"),
        ("a_safe", "ordered_co2", "b"),
        ("high_safe", "descending_flow", "a"),
        ("low_safe", "descending_flow", "b"),
        ("a_in_range", "bands_in_range", "a"),
        ("b_in_range", "bands_in_range", "b"),
        ("low_in_range", "flows_in_range", "a"),
        ("high_in_range", "flows_in_range", "b"),
        ("bands_in_range", "ranges_valid", "a"),
        ("flows_in_range", "ranges_valid", "b"),
        ("ordered_co2", "orders_valid", "a"),
        ("ordered_flow", "orders_valid", "b"),
        ("ranges_valid", "reset_config_ok", "a"),
        ("orders_valid", "reset_config_ok", "b"),
        ("b_safe", "co2_span", "a"),
        ("a_safe", "co2_span", "b"),
        ("co2", "co2_upper", "a"),
        ("b_safe", "co2_upper", "b"),
        ("co2_upper", "co2_bounded", "a"),
        ("a_safe", "co2_bounded", "b"),
        ("co2_bounded", "above_lower", "a"),
        ("a_safe", "above_lower", "b"),
        ("above_lower", "fraction", "a"),
        ("denominator", "fraction", "b"),
        ("high_safe", "flow_span", "a"),
        ("low_safe", "flow_span", "b"),
        ("bounded_fraction", "scaled_span", "a"),
        ("flow_span", "scaled_span", "b"),
        ("low_safe", "raw_candidate", "a"),
        ("scaled_span", "raw_candidate", "b"),
        ("raw_candidate", "candidate_upper", "a"),
        ("high_safe", "candidate_upper", "b"),
        ("candidate_upper", "bounded_candidate", "a"),
        ("low_safe", "bounded_candidate", "b"),
        ("descending_flow", "ordered_flow", "in"),
        ("ordered_co2", "denominator", "select"),
        ("co2_span", "denominator", "on"),
        ("fallback_span", "denominator", "off"),
        ("fraction", "bounded_fraction", "in"),
        ("reset_config_ok", "selected_flow", "select"),
        ("bounded_candidate", "selected_flow", "on"),
        ("previous_valid_flow", "selected_flow", "off"),
        ("selected_flow", "previous_valid_flow", "in"),
        ("selected_flow", "minimum_airflow", "in"),
        ("reset_config_ok", "reset_configuration_valid", "in"),
    ]
    program = Program(
        id=identifier,
        name="Authored CO2 minimum-airflow reset",
        description="Five live endpoints, authored bounded linear minimum-flow reset and committed invalid-config hold. Not a percent damper command or native JCI/G36/ventilation acceptance.",
        nodes=nodes,
        edges=[
            Edge(id=f"wire{i}", source=a, target=b, target_port=port)
            for i, (a, b, port) in enumerate(wires)
        ],
        metadata={
            "co2_minimum_flow_template": {
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
        "format": "bms.co2-minimum-flow-template-preview",
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


def co2_minimum_flow_template_router():
    router = APIRouter(prefix="/api/activities/templates/co2-minimum-flow")

    @router.get("/catalog")
    def catalog():
        return {
            "format": "bms.co2-minimum-flow-template-catalog",
            "version": 1,
            "profile": copy.deepcopy(PROFILE),
            "profile_sha256": PROFILE_SHA,
            "defaults": Choices().model_dump(mode="json"),
            "defaults_by_unit": {
                unit: convert_units(Choices(), unit).model_dump(mode="json")
                for unit in ("cfm", "L/s")
            },
            "flow_caps": {unit: flow_cap(unit) for unit in ("cfm", "L/s")},
            "choices_schema": Choices.model_json_schema(),
            "request_schema": TemplateRequest.model_json_schema(),
            "import_schema": ImportRequest.model_json_schema(),
            "units_schema": UnitsRequest.model_json_schema(),
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
        suffix = ".bms-activities.json" if body.format == "bundle" else ".co2-flow-review.json"
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

    @router.post("/units")
    def units_route(body: UnitsRequest):
        body = _fresh(UnitsRequest, body)
        source_choices = body.choices.model_dump(mode="json")
        choices = convert_units(body.choices, body.flow_unit).model_dump(mode="json")
        return {
            "format": "bms.co2-minimum-flow-template-units",
            "version": 1,
            "profile_sha256": PROFILE_SHA,
            "source_choices": source_choices,
            "source_choices_sha256": digest(source_choices),
            "choices": choices,
            "choices_sha256": digest(choices),
        }

    return router
