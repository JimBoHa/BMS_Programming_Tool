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


class DualDuctChoices(StrictModel):
    layout: Literal["none", "hot-cold", "hot-total", "cold-total"]
    hot_damper_min: Annotated[float, Field(strict=True, ge=0, le=100)] = 0.0
    hot_damper_max: Annotated[float, Field(strict=True, ge=0, le=100)] = 100.0
    hot_flow_min: Number = 100.0
    hot_flow_max: Number = 800.0
    hot_flow_default: Number = 200.0
    total_flow_default: Number = 600.0


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=200)
    equipment: Literal["cooling-only", "inline-reheat", "parallel-fan-reheat", "dual-duct"] = (
        "cooling-only"
    )
    dual_duct: DualDuctChoices | None = Field(default=None, exclude_if=lambda value: value is None)
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
        if self.equipment == "dual-duct":
            if self.dual_duct is None:
                raise ValueError(
                    "Dual duct requires an explicit airflow pickup/layout declaration."
                )
            dual = self.dual_duct
            if self.control == "position":
                if dual.layout != "none":
                    raise ValueError(
                        "Dual-duct position mapping requires explicit no-airflow layout."
                    )
                if dual.hot_damper_min >= dual.hot_damper_max:
                    raise ValueError("Hot-deck minimum position must be below maximum position.")
            else:
                if dual.layout == "none":
                    raise ValueError(
                        "Dual-duct feedback requires two explicit calibrated airflow pickups."
                    )
                if dual.hot_flow_min >= dual.hot_flow_max:
                    raise ValueError("Hot-deck minimum airflow must be below maximum airflow.")
                if dual.layout == "hot-total" and dual.total_flow_default < dual.hot_flow_default:
                    raise ValueError(
                        "Total default airflow cannot be below the measured hot-deck default."
                    )
                if dual.layout == "cold-total" and dual.total_flow_default < self.flow_default:
                    raise ValueError(
                        "Total default airflow cannot be below the measured cold-deck default."
                    )
                factor = CFM_TO_LPS if self.flow_unit == "cfm" else 1.0
                active = [dual.hot_flow_min, dual.hot_flow_max]
                if dual.layout in ("hot-cold", "hot-total"):
                    active.append(dual.hot_flow_default)
                if dual.layout != "hot-cold":
                    active.append(dual.total_flow_default)
                if any(number * factor > 1e6 for number in active):
                    raise ValueError(
                        "Declared dual-deck airflow exceeds the 1,000,000 L/s equivalent bound."
                    )
        elif self.dual_duct is not None:
            raise ValueError("Dual-deck declarations belong only to dual-duct equipment.")
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
        active_flow = [self.flow_min, self.flow_max]
        if self.dual_duct is None or self.dual_duct.layout != "hot-total":
            active_flow.append(self.flow_default)
        if self.control == "flow-feedback" and any(v * flow_factor > 1e6 for v in active_flow):
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

DUAL_SOURCE = SOURCE | {
    "pdf_pages": [594, 595, 596],
    "scope": "Documented dual-duct hot/cold/total pickup choices qualify the selection workflow. Studio authors the fixed-gain portable sequence and guards; no vendor adaptive tuning, actuator allocation or standard CAF semantics are reproduced.",
}
DUAL_GAPS = [
    gap for gap in GAPS if gap != "runtime external-setpoint range/deadband enforcement"
] + [
    "runtime external-setpoint physical ranges, occupancy/reset and complete deadband policy",
    "native dual-duct integrated/proportional/incremental actuator allocation",
    "total-only pickup mixing control, vendor adaptive tuning, auto-calibration and balancing",
    "exhaust tracking, supplemental heat, discharge-temperature limits and smoke control",
    "simultaneous minimum-flow ventilation/energy compliance",
]
DUAL_PROFILE = {
    "profile": "studio-vav-dual-duct/1",
    "source": DUAL_SOURCE,
    "units": UNITS,
    "gaps": DUAL_GAPS,
    "semantics": "Authored portable fixed-gain P/PI hot/cold demand, gated by zone heating/cooling mode. Independent declared minima may mix both decks. Two calibrated pickups derive the third flow by sum/difference without clamping. Strict negative derived/deck flow or crossed setpoints closes both logical commands and holds PI integrals through zero error. This is an explicit Studio policy, not native JCI sequence or physical safety proof. Total-only pickup is unsupported.",
}
DUAL_PROFILE_SHA = digest(DUAL_PROFILE)


def selected_profile(value):
    return (
        (DUAL_PROFILE, DUAL_PROFILE_SHA)
        if value.equipment == "dual-duct"
        else (PROFILE, PROFILE_SHA)
    )


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
        if value.dual_duct is not None:
            for field in ("hot_flow_min", "hot_flow_max", "hot_flow_default", "total_flow_default"):
                data["dual_duct"][field] *= ratio
    data.update(temperature_unit=temperature_unit, flow_unit=flow_unit)
    return Choices.model_validate(data)


def generate(value: Choices):
    if value.equipment == "dual-duct":
        return generate_dual_duct(value)
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


def generate_dual_duct(value: Choices):
    """Fixed declared gains and explicit portable guards, not a vendor sequence."""
    dual = value.dual_duct
    nodes, edges = [], []

    def node(id, kind, label, params=None, unit="", typ="number"):
        index = len(nodes)
        nodes.append(
            Node(
                id=id,
                kind=kind,
                label=label,
                x=40 + 340 * (index % 6),
                y=70 + 170 * (index // 6),
                params=params or {},
                unit=unit,
                value_type=typ,
            )
        )
        return id

    def wire(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def binary(id, kind, label, a, b, unit="", typ="number"):
        node(id, kind, label, unit=unit, typ=typ)
        wire(a, id, "a")
        wire(b, id, "b")
        return id

    def select(id, label, condition, on, off, unit):
        node(id, "Switch", label, unit=unit)
        wire(condition, id, "select")
        wire(on, id, "on")
        wire(off, id, "off")
        return id

    def output(id, label, source, unit="", typ="number"):
        node(id, "Output", label, unit=unit, typ=typ)
        wire(source, id)

    node(
        "zone", "Input", "Zone temperature", {"default": value.zone_default}, value.temperature_unit
    )
    for id, label, number in (
        ("cool_sp", "Cooling setpoint", value.cooling_setpoint),
        ("heat_sp", "Heating setpoint", value.heating_setpoint),
    ):
        node(
            id,
            "Constant" if value.setpoints == "fixed" else "Input",
            label,
            {"value" if value.setpoints == "fixed" else "default": number},
            value.temperature_unit,
        )
    zero = node("zero_command", "Constant", "Zero portable command", {"value": 0}, "%")
    ordered = binary(
        "setpoint_order",
        "Less",
        "Heating setpoint below cooling setpoint",
        "heat_sp",
        "cool_sp",
        typ="boolean",
    )
    output("setpoints_ordered", "Declared setpoint order valid", ordered, typ="boolean")
    raw = {}
    if value.control == "flow-feedback":
        for deck, default in (
            ("hot", dual.hot_flow_default),
            ("cold", value.flow_default),
            ("total", dual.total_flow_default),
        ):
            if deck in dual.layout.split("-"):
                raw[deck] = node(
                    f"{deck}_airflow",
                    "Input",
                    f"Measured {deck}-deck airflow"
                    if deck != "total"
                    else "Measured total airflow",
                    {"default": default},
                    value.flow_unit,
                )
        if dual.layout == "hot-cold":
            raw["total"] = binary(
                "total_calculated",
                "Add",
                "Calculated total airflow",
                raw["hot"],
                raw["cold"],
                value.flow_unit,
            )
        else:
            missing = "cold" if dual.layout == "hot-total" else "hot"
            measured = "hot" if missing == "cold" else "cold"
            raw[missing] = binary(
                f"{missing}_calculated",
                "Subtract",
                f"Derived {missing}-deck airflow: total minus measured deck",
                raw["total"],
                raw[measured],
                value.flow_unit,
            )
        for deck in ("cold", "hot", "total"):
            output(
                f"{deck}_flow", f"Raw measured/derived {deck} airflow", raw[deck], value.flow_unit
            )
        flow_zero = node(
            "flow_zero", "Constant", "Zero declared airflow", {"value": 0}, value.flow_unit
        )
        negative = [
            binary(
                f"{deck}_negative",
                "Less",
                f"{deck.title()} airflow is negative",
                raw[deck],
                flow_zero,
                typ="boolean",
            )
            for deck in ("cold", "hot")
        ]
        bad = binary("negative_flow", "Or", "Any negative deck airflow", *negative, typ="boolean")
        node("flow_consistent", "Not", "Nonnegative deck arithmetic", typ="boolean")
        wire(bad, "flow_consistent")
        output(
            "airflow_consistent",
            "Nonnegative airflow arithmetic only",
            "flow_consistent",
            typ="boolean",
        )
        permitted = binary(
            "permission",
            "And",
            "Setpoint order and flow arithmetic permit control",
            ordered,
            "flow_consistent",
            typ="boolean",
        )
    else:
        permitted = ordered
    output("control_permitted", "Portable guard permits logical commands", permitted, typ="boolean")
    for deck, sp, comparison in (("cold", "cool_sp", "Greater"), ("hot", "heat_sp", "Less")):
        demand_mode = binary(
            f"{deck}_mode",
            comparison,
            f"Zone requires {deck}-deck demand",
            "zone",
            sp,
            typ="boolean",
        )
        active = binary(
            f"{deck}_active",
            "And",
            f"Permitted {deck}-deck mode",
            demand_mode,
            permitted,
            typ="boolean",
        )
        measured = select(
            f"{deck}_zone_measurement",
            "Inactive/invalid zone loop receives its own setpoint",
            active,
            "zone",
            sp,
            value.temperature_unit,
        )
        loop = node(
            f"{deck}_temperature_loop",
            "PI",
            f"Declared {deck}-deck temperature P/PI",
            {
                "kp": value.temperature_kp,
                "ki": value.temperature_ki,
                "min": 0,
                "max": 100,
                "reverse": deck == "cold",
            },
            "%",
        )
        wire(measured, loop, "measured")
        wire(sp, loop, "setpoint")
        demand = select(
            f"{deck}_demand_selected",
            f"Inactive {deck}-deck demand is zero",
            active,
            loop,
            zero,
            "%",
        )
        output(f"{deck}_demand", f"Selected {deck}-deck demand", demand, "%")
        if value.control == "position":
            minimum, maximum = (
                (value.damper_min, value.damper_max)
                if deck == "cold"
                else (dual.hot_damper_min, dual.hot_damper_max)
            )
            command = node(
                f"{deck}_position_map",
                "Scale",
                f"Declared {deck}-deck position mapping",
                {"in_min": 0, "in_max": 100, "out_min": minimum, "out_max": maximum, "clamp": True},
                "%",
            )
            wire(demand, command)
        else:
            minimum, maximum = (
                (value.flow_min, value.flow_max)
                if deck == "cold"
                else (dual.hot_flow_min, dual.hot_flow_max)
            )
            target = node(
                f"{deck}_flow_target",
                "Scale",
                f"Declared {deck}-deck airflow setpoint",
                {"in_min": 0, "in_max": 100, "out_min": minimum, "out_max": maximum, "clamp": True},
                value.flow_unit,
            )
            wire(demand, target)
            output(
                f"{deck}_flow_setpoint",
                f"{deck.title()}-deck airflow setpoint",
                target,
                value.flow_unit,
            )
            measured = select(
                f"{deck}_flow_measurement",
                "Invalid flow loop receives its own setpoint",
                permitted,
                raw[deck],
                target,
                value.flow_unit,
            )
            command = node(
                f"{deck}_flow_loop",
                "PI",
                f"Declared {deck}-deck airflow P/PI",
                {"kp": value.flow_kp, "ki": value.flow_ki, "min": 0, "max": 100, "reverse": False},
                "%",
            )
            wire(target, command, "setpoint")
            wire(measured, command, "measured")
        gated = select(
            f"{deck}_command_guard",
            "Invalid portable configuration gives zero command",
            permitted,
            command,
            zero,
            "%",
        )
        output(f"{deck}_damper", f"{deck.title()}-deck logical damper command", gated, "%")
    if value.control == "flow-feedback":
        total_target = binary(
            "total_target",
            "Add",
            "Sum of declared deck airflow targets",
            "cold_flow_target",
            "hot_flow_target",
            value.flow_unit,
        )
        output(
            "total_flow_setpoint", "Total declared airflow setpoint", total_target, value.flow_unit
        )
    inactive = ["fan_on", "fan_off"]
    if value.control == "position":
        inactive += [
            "flow_unit",
            "flow_min",
            "flow_max",
            "flow_default",
            "flow_kp",
            "flow_ki",
            "flow_loop",
            "dual_duct.hot_flow_min",
            "dual_duct.hot_flow_max",
            "dual_duct.hot_flow_default",
            "dual_duct.total_flow_default",
        ]
    else:
        inactive += [
            "damper_min",
            "damper_max",
            "dual_duct.hot_damper_min",
            "dual_duct.hot_damper_max",
        ]
        if dual.layout == "hot-cold":
            inactive.append("dual_duct.total_flow_default")
        elif dual.layout == "hot-total":
            inactive.append("flow_default")
        else:
            inactive.append("dual_duct.hot_flow_default")
    for item in nodes:
        item.params = portable_numbers(item.params)
    return Program(
        id=value.project_id,
        name=value.name,
        scan_seconds=value.scan_seconds,
        description="Illustrative portable dual-duct VAV. Explicit deck minima may mix hot/cold air; no ventilation or energy compliance is inferred. Native actuator allocation, adaptive tuning, calibration, balancing and complete vendor/G36/Title24 sequences remain unverified.",
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
                "profile_sha256": DUAL_PROFILE_SHA,
                "choices_sha256": digest(choice_document(value)),
                "choices": choice_document(value),
                "inactive_choices": inactive,
                "source": DUAL_SOURCE,
                "units": UNITS,
                "unimplemented": DUAL_GAPS,
                "target_scope": "Operator declaration only; no native compatibility, physical terminals or package availability inferred.",
            },
        },
    )


def preview(value: Choices):
    program = generate(value)
    profile, profile_sha = selected_profile(value)
    issues = [row.model_dump() for row in validate(program)]
    return {
        "format": "bms.equipment-wizard-preview",
        "version": 1,
        "profile_sha256": profile_sha,
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
        "profile": profile,
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
            "dual_duct": {
                "profile": DUAL_PROFILE,
                "profile_sha256": DUAL_PROFILE_SHA,
                "defaults": DualDuctChoices(layout="none").model_dump() | {"layout": ""},
            },
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
            "profile_sha256": selected_profile(body.choices)[1],
        }

    return router
