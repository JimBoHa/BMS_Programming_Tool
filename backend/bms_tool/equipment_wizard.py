"""Illustrative portable VAV authoring; no native allocation or certified sequence."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import Field, model_validator

from .engine import validate
from .models import Edge, Node, Program, StrictModel, Target
from .program_source import SourceMode, source_response

Number = Annotated[float, Field(strict=True, ge=0, le=1e12)]
Temperature = Annotated[float, Field(strict=True, ge=-1000, le=1000)]
Text = Annotated[str, Field(max_length=80)]
SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "pdf_pages": [149, 150, 151, 153, 154],
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Equipment/component/strategy/unit selection workflow; generated graphs are authored Studio examples, not vendor standard CAF sequences.",
}
CFM_TO_LPS = 0.4719474432
UNITS = {
    "flow_formula": "1cfm=(0.3048m)^3*1000L/m3/60s=0.4719474432L/s",
    "foot_definition_source": "https://www.nist.gov/pml/us-surveyfoot/revised-unit-conversion-factors",
    "temperature": "F=(C*9/5)+32; temperature differences scale by9/5 without offsets; inverse-degree gains scale reciprocally.",
    "normalization": "Generated editable parameter/choice JSON normalizes integral floats and signed zero to integers before hashing; this is an intentional generator schema, not a native receipt.",
    "gain": "kp has percent per input-unit; ki has percent per input-unit per second. Unit changes convert input values and both inverse-unit gains together.",
}
GAPS = [
    "native CAF allocation/compiler/package/firmware acceptance",
    "physical sensor calibration, terminals and actuator direction",
    "measured/design airflow when position mapping is selected",
    "ventilation, occupancy and air-handling coordination",
    "fan proof, heating safety interlocks and discharge temperature limits",
    "runtime external-setpoint range/deadband enforcement",
    "complete Guideline 36/Title 24 sequence or certification",
]


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def portable_numbers(value):
    """Intentional generator normalization for editable browser JSON, not native evidence."""
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: portable_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_numbers(item) for item in value]
    return value


def choice_document(value):
    return portable_numbers(value.model_dump())


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=200)
    equipment: Literal["cooling-only", "inline-reheat", "parallel-fan-reheat"] = "cooling-only"
    family: Literal["universal-runtime", "johnson-fx", "johnson-metasys"] = "universal-runtime"
    model: Text = ""
    firmware: Text = ""
    release_mode: Text = ""
    temperature_unit: Literal["degF", "degC"] = "degF"
    flow_unit: Literal["cfm", "L/s"] = "cfm"
    control: Literal["position", "flow-feedback"] = "position"
    setpoints: Literal["fixed", "inputs"] = "fixed"
    temperature_loop: Literal["P", "PI"] = "PI"
    flow_loop: Literal["P", "PI"] = "PI"
    zone_default: Temperature = 74.0
    cooling_setpoint: Temperature = 72.0
    heating_setpoint: Temperature = 68.0
    temperature_kp: Number = 20.0
    temperature_ki: Number = 0.1
    damper_min: Annotated[float, Field(strict=True, ge=0, le=100)] = 20.0
    damper_max: Annotated[float, Field(strict=True, ge=0, le=100)] = 100.0
    flow_min: Number = 200.0
    flow_max: Number = 1000.0
    flow_default: Number = 400.0
    flow_kp: Number = 0.1
    flow_ki: Number = 0.001
    fan_on: Annotated[float, Field(strict=True, ge=0, le=100)] = 5.0
    fan_off: Annotated[float, Field(strict=True, ge=0, le=100)] = 1.0
    scan_seconds: Annotated[float, Field(strict=True, ge=0.01, le=60)] = 1.0

    @model_validator(mode="after")
    def coherent(self):
        if not self.name.strip():
            raise ValueError("Project name requires visible text.")
        if self.control == "position" and self.damper_min >= self.damper_max:
            raise ValueError("Minimum damper position must be below maximum position.")
        if self.control == "flow-feedback" and self.flow_min >= self.flow_max:
            raise ValueError("Minimum declared airflow must be below maximum airflow.")
        if self.equipment != "cooling-only" and self.heating_setpoint >= self.cooling_setpoint:
            raise ValueError("Heating setpoint must be below cooling setpoint.")
        if self.equipment == "parallel-fan-reheat" and self.fan_off >= self.fan_on:
            raise ValueError("Fan off threshold must be below fan on threshold.")
        if self.temperature_loop == "P" and self.temperature_ki != 0:
            raise ValueError("P-only temperature control requires integral gain zero.")
        if self.control == "flow-feedback" and self.flow_loop == "P" and self.flow_ki != 0:
            raise ValueError("P-only airflow control requires integral gain zero.")
        flow_factor = CFM_TO_LPS if self.flow_unit == "cfm" else 1.0
        if self.control == "flow-feedback" and any(
            v * flow_factor > 1e6 for v in (self.flow_min, self.flow_max, self.flow_default)
        ):
            raise ValueError("Declared airflow exceeds the 1,000,000 L/s equivalent bound.")
        temperature_factor = 9 / 5 if self.temperature_unit == "degF" else 1.0
        if (
            any(v * temperature_factor > 1e6 for v in (self.temperature_kp, self.temperature_ki))
            or self.control == "flow-feedback"
            and any(v / flow_factor > 1e6 for v in (self.flow_kp, self.flow_ki))
        ):
            raise ValueError("Control gain exceeds the canonical inverse-unit bound.")
        for value in (self.zone_default, self.cooling_setpoint) + (
            (self.heating_setpoint,) if self.equipment != "cooling-only" else ()
        ):
            c = (value - 32) * 5 / 9 if self.temperature_unit == "degF" else value
            if not -50 <= c <= 100:
                raise ValueError(
                    "Illustrative zone/setpoint temperatures must be within -50..100degC equivalent."
                )
        return self


PROFILE = {
    "profile": "studio-vav-selection/1",
    "source": SOURCE,
    "units": UNITS,
    "gaps": GAPS,
    "semantics": "Cooling PI uses zone minus cooling setpoint; heating PI uses heating setpoint minus zone. Demand 0..100 maps to position bounds or declared airflow setpoint. Feedback PI uses desired minus measured airflow and outputs 0..100% damper. Parallel fan follows heat-demand hysteresis, without physical fan proof. Fresh editable portable graph only.",
}
PROFILE_SHA = digest(PROFILE)


def convert_units(value: Choices, temperature_unit, flow_unit):
    if temperature_unit not in ("degF", "degC") or flow_unit not in ("cfm", "L/s"):
        raise ValueError("Unsupported wizard engineering units.")
    data = value.model_dump()
    if temperature_unit != value.temperature_unit:
        ratio = 5 / 9 if temperature_unit == "degC" else 9 / 5
        for field in ("zone_default", "cooling_setpoint", "heating_setpoint"):
            data[field] = (
                (data[field] - 32) * 5 / 9
                if temperature_unit == "degC"
                else data[field] * 9 / 5 + 32
            )
        for field in ("temperature_kp", "temperature_ki"):
            data[field] /= ratio
    if flow_unit != value.flow_unit:
        ratio = CFM_TO_LPS if flow_unit == "L/s" else 1 / CFM_TO_LPS
        for field in ("flow_min", "flow_max", "flow_default"):
            data[field] *= ratio
        for field in ("flow_kp", "flow_ki"):
            data[field] /= ratio
    data.update(temperature_unit=temperature_unit, flow_unit=flow_unit)
    return Choices.model_validate(data)


def generate(value: Choices):
    nodes, edges = [], []

    def node(id, kind, label, x, y, params=None, unit="", typ="number"):
        nodes.append(
            Node(
                id=id,
                kind=kind,
                label=label,
                x=x,
                y=y,
                params=params or {},
                unit=unit,
                value_type=typ,
            )
        )

    def wire(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def setpoint(id, label, value, y):
        node(
            id,
            "Constant" if value_choice.setpoints == "fixed" else "Input",
            label,
            40,
            y,
            {"value" if value_choice.setpoints == "fixed" else "default": value},
            value_choice.temperature_unit,
        )

    value_choice = value
    node(
        "zone",
        "Input",
        "Zone temperature",
        40,
        70,
        {"default": value.zone_default},
        value.temperature_unit,
    )
    setpoint("cool_sp", "Cooling setpoint", value.cooling_setpoint, 210)
    common = {"kp": value.temperature_kp, "ki": value.temperature_ki, "min": 0, "max": 100}
    node("cool_loop", "PI", "Cooling demand", 340, 140, common | {"reverse": True}, "%")
    wire("zone", "cool_loop", "measured")
    wire("cool_sp", "cool_loop", "setpoint")
    if value.control == "position":
        node(
            "position_map",
            "Scale",
            "Damper position mapping",
            620,
            140,
            {
                "in_min": 0,
                "in_max": 100,
                "out_min": value.damper_min,
                "out_max": value.damper_max,
                "clamp": True,
            },
            "%",
        )
        wire("cool_loop", "position_map")
        damper_source = "position_map"
    else:
        node(
            "flow_sp",
            "Scale",
            "Declared airflow setpoint",
            620,
            140,
            {
                "in_min": 0,
                "in_max": 100,
                "out_min": value.flow_min,
                "out_max": value.flow_max,
                "clamp": True,
            },
            value.flow_unit,
        )
        node(
            "airflow",
            "Input",
            "Measured airflow input",
            620,
            310,
            {"default": value.flow_default},
            value.flow_unit,
        )
        node(
            "flow_loop",
            "PI",
            "Airflow feedback loop",
            900,
            140,
            {"kp": value.flow_kp, "ki": value.flow_ki, "min": 0, "max": 100, "reverse": False},
            "%",
        )
        node("flow_setpoint", "Output", "Airflow setpoint", 900, 310, unit=value.flow_unit)
        wire("cool_loop", "flow_sp")
        wire("flow_sp", "flow_loop", "setpoint")
        wire("airflow", "flow_loop", "measured")
        wire("flow_sp", "flow_setpoint")
        damper_source = "flow_loop"
    node("damper", "Output", "Damper position command", 1180, 140, unit="%")
    wire(damper_source, "damper")
    if value.equipment != "cooling-only":
        setpoint("heat_sp", "Heating setpoint", value.heating_setpoint, 520)
        node("heat_loop", "PI", "Heating demand", 340, 520, common | {"reverse": False}, "%")
        node("reheat", "Output", "Modulating hot-water reheat command", 1180, 520, unit="%")
        wire("zone", "heat_loop", "measured")
        wire("heat_sp", "heat_loop", "setpoint")
        wire("heat_loop", "reheat")
    if value.equipment == "parallel-fan-reheat":
        node(
            "fan_signal",
            "Scale",
            "Heat demand percentage points",
            340,
            700,
            {"in_min": 0, "in_max": 100, "out_min": 0, "out_max": 100, "clamp": True},
        )
        node(
            "fan_enable",
            "Deadband",
            "Parallel fan demand hysteresis",
            620,
            700,
            {"on": value.fan_on, "off": value.fan_off},
            typ="boolean",
        )
        node("fan", "Output", "Parallel fan enable", 1180, 700, typ="boolean")
        wire("heat_loop", "fan_signal")
        wire("fan_signal", "fan_enable")
        wire("fan_enable", "fan")
    inactive = []
    if value.control == "position":
        inactive += [
            "flow_unit",
            "flow_min",
            "flow_max",
            "flow_default",
            "flow_kp",
            "flow_ki",
            "flow_loop",
        ]
    else:
        inactive += ["damper_min", "damper_max"]
    if value.equipment == "cooling-only":
        inactive += ["heating_setpoint", "fan_on", "fan_off"]
    elif value.equipment == "inline-reheat":
        inactive += ["fan_on", "fan_off"]
    for item in nodes:
        item.params = portable_numbers(item.params)
    return Program(
        id=value.project_id,
        name=value.name,
        scan_seconds=value.scan_seconds,
        description="Illustrative portable VAV authoring. Position is not measured airflow. Feedback airflow requires a valid calibrated input. Native hardware/package allocation and full ventilation/heating/fan-proof/discharge/Title24/Guideline36 behavior remain unverified.",
        target=Target(
            family=value.family,
            model=value.model,
            firmware=value.firmware,
            release_mode=value.release_mode,
        ),
        nodes=nodes,
        edges=edges,
        metadata={
            "application": value.equipment,
            "native_deployment_verified": False,
            "compliance": "Uncertified illustrative sequence",
            "equipment_wizard": {
                "profile_sha256": PROFILE_SHA,
                "choices_sha256": digest(choice_document(value)),
                "choices": choice_document(value),
                "inactive_choices": inactive,
                "source": SOURCE,
                "units": UNITS,
                "unimplemented": GAPS,
                "target_scope": "Operator declaration only; no native compatibility, physical terminals or package availability inferred.",
            },
        },
    )


def preview(value: Choices):
    program = generate(value)
    issues = [row.model_dump() for row in validate(program)]
    return {
        "format": "bms.equipment-wizard-preview",
        "version": 1,
        "profile_sha256": PROFILE_SHA,
        "choices": choice_document(value),
        "choices_sha256": digest(choice_document(value)),
        "program": program.model_dump(mode="json"),
        "program_sha256": program.digest(),
        "issues": issues,
        "can_create": not any(row["level"] == "error" for row in issues),
        "points": [
            {
                "id": n.id,
                "label": n.label,
                "role": n.kind,
                "type": n.value_type,
                "unit": n.unit,
                "binding": "Logical portable signal; no physical/native allocation",
            }
            for n in program.nodes
            if n.kind in ("Input", "Output")
        ],
        "topology": {
            "nodes": len(program.nodes),
            "edges": len(program.edges),
            "control": value.control,
            "airflow_feedback": value.control == "flow-feedback",
        },
        "profile": PROFILE,
        "native_compile": False,
        "controller_writes": False,
    }


class UnitRequest(StrictModel):
    choices: Choices
    temperature_unit: Literal["degF", "degC"]
    flow_unit: Literal["cfm", "L/s"]


def wizard_router():
    router = APIRouter(prefix="/api/equipment-wizard")

    @router.get("/catalog")
    def catalog():
        return {
            "profile": PROFILE,
            "profile_sha256": PROFILE_SHA,
            "defaults": Choices(project_id="new-vav-project", name="New VAV project").model_dump(),
        }

    @router.post("/preview")
    def review(body: Choices, source_transport: SourceMode = False):
        return source_response(preview(body), source_transport)

    @router.post("/units")
    def units(body: UnitRequest):
        return {
            "choices": convert_units(
                body.choices, body.temperature_unit, body.flow_unit
            ).model_dump(),
            "source_choices": choice_document(body.choices),
            "profile_sha256": PROFILE_SHA,
        }

    return router
