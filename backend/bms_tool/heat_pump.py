"""Authored portable single-compressor sequencing, never a native JCI encoder."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .engine import validate
from .models import Edge, Node, Program, StrictModel, Target
from .program_source import SourceMode, source_response

SOURCE = {
    "title": "Controller Tool Help",
    "document": "LIT-12011147",
    "edition": "18.0",
    "pdf_pages": [484, 485, 486, 487, 488, 489, 1383, 1384, 1385, 1386],
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Heat-pump selections, polarity, airflow and separate compressor/valve timing qualify this foundation. Fixed hysteresis, uniform minimum-on priority, startup and idle policies below are authored Studio behavior, not recovered native PID/MSC behavior.",
}
GAPS = [
    "native JCI CAF allocation, packages, compiler, transfer and controller firmware acceptance",
    "two-compressor staging, lead-lag, supplemental heating, economizer and water-side isolation",
    "native adaptive PID/MSC/PMAC, EWMA diagnostics, output-priority tracking and native mode codes",
    "physical airflow/fan/pressure/temperature/smoke/freeze protection and wiring acceptance",
    "unoccupied setbacks, frost protection, power-fail persistence/restart and warmup/cooldown",
    "arbitrary fractional/overridden scan timing, complete Guideline36/Title24 or safety certification",
]
LIMITS = {
    "scan_seconds": [1, 60],
    "timing_seconds": [1, 3600],
    "temperature_celsius": [-100, 200],
    "difference": {"degF": [0, 180], "degC": [0, 100]},
    "nodes": 200,
}
PROFILE = {
    "profile": "studio-single-compressor-heat-pump/1",
    "source": SOURCE,
    "semantics": {
        "equipment": "One reversible compressor and single-speed fan with explicit On-for-Heating/On-for-Cooling output polarity. Initial valve mode is explicit; the idle or disabled valve holds its last committed mode, including its possibly energized command.",
        "demand": "Fixed temperature hysteresis: demand on at error >= demand_on_delta, off at error <= demand_off_delta; on > off >= 0. Heating/cooling setpoints must remain ordered. This is authored thermostat logic, not adaptive PID or the native MSC.",
        "timing": "Whole-second declared scans and positive whole-second timing multiples. Minimum-off and off-before-valve dwell count only while the previous committed compressor is off. A valve change resets valve settling. Compressor start requires matching requested/valve mode, full minimum-off and valve-settle readiness. No valve change while the previous compressor is on.",
        "minimum_on": "Ordinary demand loss holds the running compressor until minimum-on expires. Unit/occupancy/holdoff, explicit airflow loss, condensate shutdown/inhibit, crossed setpoints and requested mode reversal override minimum-on immediately. This uniform authored priority differs from native Heating-Off/Cooling-Off behavior.",
        "startup": "Compressor state and all timers start off/zero. The first successful scan represents one declared elapsed scan interval from boot, not an observed wall-clock startup. A fresh Engine/compiled process restarts that sequence. No checkpoint or power-loss guarantee.",
        "fan": "Continuous-occupied or request/current-compressor cycling. Fan command does not establish airflow. The separate logical airflow_proven input defaults false, while a permitted fan can start before that permission, avoiding a proof/start deadlock.",
        "condensate": "None, immediate cooling-only inhibit or unit shutdown. Cooling-only inhibit leaves heating and permitted continuous fan operation available. Bad quality instead faults the complete scan and retains all prior outputs/state; it is not a physical shutdown claim.",
        "units": "F/C absolute temperatures and hysteresis differences convert together; timings and Boolean choices do not change. Declared generator numeric choices normalize integral floats intentionally; existing Program/evidence rules are unchanged.",
        "scope": "Target family/model/firmware/release are operator declarations, not native compatibility, physical terminal assignments or deployment proof. Editing the graph or overriding its scan timing changes this profile's assumptions.",
    },
    "limits": LIMITS,
    "gaps": GAPS,
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def normalize(value):
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(PROFILE)
Temperature = Annotated[float, Field(strict=True, ge=-1000, le=1000)]
Difference = Annotated[float, Field(strict=True, ge=0, le=180)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=3600)]
Flag = Annotated[bool, Field(strict=True)]


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=200)
    family: Literal["universal-runtime", "johnson-fx", "johnson-metasys"] = "universal-runtime"
    model: str = Field(default="", max_length=80)
    firmware: str = Field(default="", max_length=80)
    release_mode: str = Field(default="", max_length=80)
    temperature_unit: Literal["degF", "degC"] = "degF"
    setpoints: Literal["fixed", "inputs"] = "fixed"
    zone_default: Temperature = 74.0
    heating_setpoint: Temperature = 68.0
    cooling_setpoint: Temperature = 72.0
    demand_on_delta: Difference = 1.0
    demand_off_delta: Difference = 0.0
    reversing_polarity: Literal["on-for-heating", "on-for-cooling"]
    initial_mode: Literal["heating", "cooling"]
    fan_policy: Literal["continuous-occupied", "cycle-on-demand"]
    condensate: Literal["none", "disable-cooling", "shutdown-unit"]
    minimum_on_seconds: Seconds = 120
    minimum_off_seconds: Seconds = 120
    valve_off_seconds: Seconds = 6
    valve_settle_seconds: Seconds = 6
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1
    occupied_default: Flag = True
    unit_enable_default: Flag = True
    energy_holdoff_default: Flag = False
    airflow_proven_default: Flag = False
    condensate_default: Flag = False

    @model_validator(mode="after")
    def coherent(self):
        if not self.name.strip() or not all(c.isprintable() for c in self.name):
            raise ValueError("Program name requires visible printable text.")
        for field in ("zone_default", "heating_setpoint", "cooling_setpoint"):
            temperature = getattr(self, field)
            celsius = temperature if self.temperature_unit == "degC" else (temperature - 32) * 5 / 9
            if not -100 <= celsius <= 200:
                raise ValueError(
                    "Temperatures must be within -100..200 Celsius or their Fahrenheit equivalents."
                )
        if (
            self.temperature_unit == "degC"
            and max(self.demand_on_delta, self.demand_off_delta) > 100
        ):
            raise ValueError(
                "Temperature differences must not exceed100 Celsius degrees (180 Fahrenheit degrees)."
            )
        if self.heating_setpoint >= self.cooling_setpoint:
            raise ValueError("Heating setpoint must be below cooling setpoint.")
        if self.demand_on_delta <= self.demand_off_delta:
            raise ValueError("Demand on difference must exceed off difference.")
        for field in (
            "minimum_on_seconds",
            "minimum_off_seconds",
            "valve_off_seconds",
            "valve_settle_seconds",
        ):
            if getattr(self, field) % self.scan_seconds:
                raise ValueError(
                    "Timing seconds must be whole multiples of the declared scan interval."
                )
        return self


class PreviewRequest(StrictModel):
    choices: Choices


class UnitsRequest(StrictModel):
    choices: Choices
    temperature_unit: Literal["degF", "degC"]


def choice_document(choices):
    return normalize(choices.model_dump())


def convert_units(choices, temperature_unit):
    data = choices.model_dump()
    if temperature_unit != choices.temperature_unit:
        ratio = 5 / 9 if temperature_unit == "degC" else 9 / 5
        for field in ("zone_default", "heating_setpoint", "cooling_setpoint"):
            data[field] = (
                (data[field] - 32) * 5 / 9
                if temperature_unit == "degC"
                else data[field] * 9 / 5 + 32
            )
        for field in ("demand_on_delta", "demand_off_delta"):
            data[field] *= ratio
    data["temperature_unit"] = temperature_unit
    return Choices.model_validate(data)


OUTPUTS = {
    key: key
    for key in (
        "compressor",
        "reversing_valve",
        "fan",
        "heating_request",
        "cooling_request",
        "heating_mode",
        "heating_active",
        "cooling_active",
        "minimum_on_hold",
        "minimum_off_ready",
        "valve_settled",
        "unit_permitted",
    )
}


def generate(choices):
    nodes, edges = [], []

    def node(identifier, kind, params=None, *, boolean=True, unit="", label=None):
        index = len(nodes)
        nodes.append(
            Node(
                id=identifier,
                kind=kind,
                label=label or identifier.replace("_", " ").title(),
                params=normalize(params or {}),
                value_type="boolean" if boolean else "number",
                unit=unit,
                x=40 + 280 * (index % 6),
                y=60 + 150 * (index // 6),
            )
        )
        return identifier

    def wire(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def gate(identifier, kind, *sources):
        node(identifier, kind)
        for port, source in zip(("in",) if len(sources) == 1 else ("a", "b"), sources, strict=True):
            wire(source, identifier, port)
        return identifier

    def all_of(identifier, *sources):
        result = sources[0]
        for index, source in enumerate(sources[1:], 1):
            result = gate(
                identifier if index == len(sources) - 1 else f"{identifier}_{index}",
                "And",
                result,
                source,
            )
        return result

    def same(identifier, a, b):
        both = gate(identifier + "_both", "And", a, b)
        neither = gate(
            identifier + "_neither",
            "And",
            gate(identifier + "_not_a", "Not", a),
            gate(identifier + "_not_b", "Not", b),
        )
        return gate(identifier, "Or", both, neither)

    def select(identifier, selector, on, off):
        node(identifier, "Switch")
        for port, source in (("select", selector), ("on", on), ("off", off)):
            wire(source, identifier, port)
        return identifier

    def timer(identifier, source, seconds):
        node(identifier, "TimerOn", {"seconds": seconds})
        wire(source, identifier)
        return identifier

    def output(role, source):
        node(role, "Output")
        wire(source, role)

    true = node("true_value", "Constant", {"value": True})
    false = node("false_value", "Constant", {"value": False})
    for identifier, default in (
        ("occupied", choices.occupied_default),
        ("unit_enable", choices.unit_enable_default),
        ("energy_holdoff", choices.energy_holdoff_default),
        ("airflow_proven", choices.airflow_proven_default),
    ):
        node(identifier, "Input", {"default": default})
    node(
        "zone",
        "Input",
        {"default": choices.zone_default},
        boolean=False,
        unit=choices.temperature_unit,
    )
    for identifier, value in (
        ("heat_sp", choices.heating_setpoint),
        ("cool_sp", choices.cooling_setpoint),
    ):
        node(
            identifier,
            "Constant" if choices.setpoints == "fixed" else "Input",
            {"value" if choices.setpoints == "fixed" else "default": value},
            boolean=False,
            unit=choices.temperature_unit,
        )
    ordered = node("setpoints_ordered", "Less")
    wire("heat_sp", ordered, "a")
    wire("cool_sp", ordered, "b")
    base = all_of(
        "base_permitted",
        "occupied",
        "unit_enable",
        gate("not_holdoff", "Not", "energy_holdoff"),
        ordered,
    )
    clear = true
    if choices.condensate != "none":
        node("condensate_alarm", "Input", {"default": choices.condensate_default})
        clear = gate("condensate_clear", "Not", "condensate_alarm")
        if choices.condensate == "shutdown-unit":
            base = gate("shutdown_clear", "And", base, clear)
    for mode, a, b in (("heat", "heat_sp", "zone"), ("cool", "zone", "cool_sp")):
        error = node(
            mode + "_error",
            "TemperatureDifference",
            {"unit": choices.temperature_unit},
            boolean=False,
            unit="delta-" + choices.temperature_unit,
        )
        wire(a, error, "a")
        wire(b, error, "b")
        demand = node(
            mode + "_thermostat",
            "Deadband",
            {"on": choices.demand_on_delta, "off": choices.demand_off_delta, "initial": False},
        )
        magnitude = node(
            mode + "_error_magnitude",
            "Scale",
            {"in_min": 0, "in_max": 1, "out_min": 0, "out_max": 1, "clamp": False},
            boolean=False,
            label=mode.title() + " error magnitude in declared degrees",
        )
        wire(error, magnitude)
        wire(magnitude, demand)
        permitted = (
            base
            if mode == "heat" or choices.condensate != "disable-cooling"
            else gate("cooling_permitted", "And", base, clear)
        )
        gate(mode + "_request", "And", demand, permitted)
    wanted = gate("demand_requested", "Or", "heat_request", "cool_request")
    previous = node("previous_compressor", "Delay", {"initial": False})
    previous_mode = node(
        "previous_heating_mode", "Delay", {"initial": choices.initial_mode == "heating"}
    )
    off = gate("previous_off", "Not", previous)
    off_ready = timer("off_timer", off, choices.minimum_off_seconds)
    off_dwell = timer("valve_off_timer", off, choices.valve_off_seconds)
    on_ready = timer("on_timer", previous, choices.minimum_on_seconds)
    requested_mode = select(
        "requested_heating_mode",
        "heat_request",
        true,
        select("cool_request_mode", "cool_request", false, previous_mode),
    )
    can_switch = all_of("mode_change_permitted", off, off_dwell, base)
    mode = select("next_heating_mode", can_switch, requested_mode, previous_mode)
    stable = same("mode_stable", mode, previous_mode)
    settled = timer(
        "settle_timer", gate("off_and_stable", "And", off, stable), choices.valve_settle_seconds
    )
    match = same("request_matches_mode", requested_mode, mode)
    soft_hold = gate(
        "minimum_on_pending", "And", previous, gate("minimum_on_not_ready", "Not", on_ready)
    )
    demand_or_hold = gate("demand_or_hold", "Or", wanted, soft_hold)
    can_start = gate("start_ready", "And", off_ready, settled)
    run_or_start = gate("running_or_start_ready", "Or", previous, can_start)
    run_permission = all_of("run_permitted", base, "airflow_proven", match)
    if choices.condensate == "disable-cooling":
        run_permission = gate(
            "condensate_mode_permission",
            "And",
            run_permission,
            gate("heating_or_condensate_clear", "Or", mode, clear),
        )
    compressor = all_of("compressor_command", run_permission, run_or_start, demand_or_hold)
    valve = (
        mode
        if choices.reversing_polarity == "on-for-heating"
        else gate("cooling_valve_command", "Not", mode)
    )
    fan_demand = (
        true
        if choices.fan_policy == "continuous-occupied"
        else gate("fan_requested", "Or", wanted, compressor)
    )
    fan = gate("fan_command", "And", base, fan_demand)
    for role, source in {
        "compressor": compressor,
        "reversing_valve": valve,
        "fan": fan,
        "heating_request": "heat_request",
        "cooling_request": "cool_request",
        "heating_mode": mode,
        "heating_active": gate("heating_run", "And", compressor, mode),
        "cooling_active": gate(
            "cooling_run", "And", compressor, gate("not_heating_mode", "Not", mode)
        ),
        "minimum_on_hold": all_of(
            "held_for_minimum_on", compressor, soft_hold, gate("no_demand", "Not", wanted)
        ),
        "minimum_off_ready": off_ready,
        "valve_settled": settled,
        "unit_permitted": base,
    }.items():
        output(role, source)
    wire(compressor, previous)
    wire(mode, previous_mode)
    inactive = ["condensate_default"] if choices.condensate == "none" else []
    return Program(
        id=choices.project_id,
        name=choices.name,
        scan_seconds=choices.scan_seconds,
        description="Authored single-compressor heat-pump foundation with explicit logical permissions and scanned timers. Bad quality retains prior committed outputs. Native JCI allocation/compiler/transfer, physical protections and complete manufacturer/code acceptance remain unverified.",
        target=Target(
            family=choices.family,
            model=choices.model,
            firmware=choices.firmware,
            release_mode=choices.release_mode,
        ),
        nodes=nodes,
        edges=edges,
        metadata={
            "application": "heat-pump",
            "native_deployment_verified": False,
            "compliance": "Uncertified authored sequence",
            "heat_pump_wizard": {
                "profile_sha256": PROFILE_SHA,
                "choices_sha256": digest(choice_document(choices)),
                "choices": choice_document(choices),
                "source": SOURCE,
                "unimplemented": GAPS,
                "inactive_choices": inactive,
                "target_scope": PROFILE["semantics"]["scope"],
                "outputs": OUTPUTS,
            },
        },
    )


def preview(body):
    program = generate(body.choices)
    diagnostics = [item.model_dump(exclude_none=True) for item in validate(program)]
    return {
        "format": "bms.heat-pump-wizard-preview",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "choices": choice_document(body.choices),
        "choices_sha256": digest(choice_document(body.choices)),
        "program": program.model_dump(mode="json"),
        "program_sha256": program.digest(),
        "diagnostics": diagnostics,
        "can_create": not any(item["level"] == "error" for item in diagnostics),
        "outputs": OUTPUTS,
        "inactive_choices": program.metadata["heat_pump_wizard"]["inactive_choices"],
        "native_compile": False,
        "controller_writes": False,
    }


def heat_pump_router():
    router = APIRouter(prefix="/api/heat-pump-wizard")

    @router.get("/catalog")
    def catalog():
        defaults = choice_document(
            Choices(
                project_id="new-heat-pump-project",
                name="Heat-pump project",
                reversing_polarity="on-for-heating",
                initial_mode="cooling",
                fan_policy="continuous-occupied",
                condensate="none",
            )
        )
        defaults.update(reversing_polarity="", initial_mode="", fan_policy="", condensate="")
        return {
            "format": "bms.heat-pump-wizard-catalog",
            "version": 1,
            "profile": PROFILE,
            "profile_sha256": PROFILE_SHA,
            "defaults": defaults,
            "limits": LIMITS,
        }

    @router.post("/preview")
    def review(body: PreviewRequest, source_transport: SourceMode = False):
        return source_response(preview(body), source_transport)

    @router.post("/export")
    def export(body: PreviewRequest):
        content = canonical(preview(body))
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="heat-pump-review.json"',
                "X-File-SHA256": hashlib.sha256(content).hexdigest(),
            },
        )

    @router.post("/units")
    def units(body: UnitsRequest):
        converted = convert_units(body.choices, body.temperature_unit)
        return {
            "profile_sha256": PROFILE_SHA,
            "source_choices": choice_document(body.choices),
            "source_choices_sha256": digest(choice_document(body.choices)),
            "choices": choice_document(converted),
            "choices_sha256": digest(choice_document(converted)),
        }

    return router
