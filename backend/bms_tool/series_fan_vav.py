"""Authored occupied series-fan VAV, using editable ordinary control nodes."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .engine import validate
from .equipment_wizard import CFM_TO_LPS
from .models import Edge, Node, Program, StrictModel, Target
from .program_source import SourceMode, source_response

SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [585, 586, 587, 589, 590, 837, 838, 839, 840, 1168, 1169],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Real series fan, calibrated primary-flow regulation and direct proportional hot-water reheat qualify this authored occupied-only foundation. Source close/proof defaults are borrowed logical timing estimates, not physical calibration or native/G36 equivalence.",
    "ambiguities": [
        "Series Fan Determination heading/tables on PDF1168-1169 conflict with an opening sentence calling it parallel. This profile does not reproduce that hidden native module.",
        "G36 startup text on PDF839-840 waits indefinitely for initial status and retains control after later proof loss. This authored profile instead bounds startup and immediately latches lost running proof.",
        "The separate variable-speed G36 algorithm on PDF837-839 and non-G36 balance setting on PDF587 are excluded, not merged into this single-speed sequence.",
        "The user's previously named series reheat was clarified as inline reheat without a fan. That existing application remains distinct from this real fan-powered series topology.",
    ],
}
GAPS = [
    "native JCI CAF allocation, compiler/packages, transfer, firmware and physical controller acceptance",
    "actual damper closure/rotation, fan flow, measured total coil airflow, discharge-temperature limits, wiring and physical protections",
    "unoccupied recovery/purge, standby/bypass/zone-group arbitration and electric or staged heat",
    "variable-speed/parallel fans, warm primary air/reverse action, adaptive tuning and discharge-temperature control",
    "measured outdoor/fresh-air ventilation, exhaust/CO2 tracking and complete Guideline36/Title24 acceptance",
    "arbitrary overridden scan timing, power-fail persistence and general unit-invariant nonlinear trajectories",
]
LIMITS = {
    "temperature_celsius": [-50, 100],
    "temperature_difference_celsius": [0, 100],
    "primary_flow_lps": [0, 1000000],
    "temperature_gain_per_celsius": [0, 1800000],
    "flow_gain_per_lps": [0, 3000000],
    "scan_seconds": [1, 60],
    "timing_seconds": [1, 3600],
    "generated_nodes": 256,
}
PROFILE = {
    "profile": "studio-occupied-series-fan-vav/1",
    "source": SOURCE,
    "limits": LIMITS,
    "flow_conversion": "1cfm=(0.3048m)^3*1000L/m3/60s=0.4719474432L/s",
    "semantics": {
        "equipment": "Occupied-only, single-speed real series fan, calibrated PRIMARY airflow and one proportional hot-water valve. Cold primary air is assumed. No inline/parallel relabel or native package selection.",
        "request": "Raw occupied AND unit_enable AND NOT energy_holdoff is separate from good-value admission. Ordered, bounded heating/cooling setpoints, bounded zone temperature and nonnegative bounded primary flow permit ordinary commands. Invalid good values inhibit commands/readiness and restart startup without themselves adding a fault or counting as operator off.",
        "close": "Whole-second declared scans/aligned durations. A TimerOn counts elapsed close-command intervals; fan starts on the scan after full close completion. First successful requested scan represents one close interval. Default90s is an estimate, never closure proof.",
        "startup": "After close, fan is requested with primary damper/reheat0. Proof counts only while fan is requested and continuously proven. Independent startup deadline spans chatter; stable proof completed at that exact deadline wins. Default proof15s/deadline60s are logical choices, not hardware acceptance.",
        "fault": "Good-quality lost proof after a ready scan immediately latches and stops fan/damper/reheat. Missing startup proof latches at deadline. Only RAW request off plus a fresh rising fan_reset edge clears latch; invalid setpoints/flow cannot impersonate operator off. Next request repeats full close/start.",
        "thermal": "Separate external logical heating/cooling setpoints. Positive entry difference and nonnegative opposite-side release difference define authored hysteresis. Active mode holds until beyond release boundary AND previous selected demand is0; opposite entry may switch directly. Heating/cooling commands are mutually exclusive; active PI may retain nonzero command at setpoint.",
        "control": "Zone cooling PI0..100 maps declared minimum/maximum PRIMARY flow; a forward flow PI regulates primary damper0..100 whenever ready, including neutral/heating. Direct zone heating PI regulates hot-water reheat. Inactive loops see zero error and hold integrals; selected inactive output is0, not an integral reset.",
        "coil": "Hot-water heat uses logical readiness/fan proof only. Primary flow may be0 while a real series fan recirculates; no primary threshold is invented as total coil airflow proof. Measured total flow and physical protection remain absent commissioning dependencies.",
        "quality": "Every required input is evaluated by unchanged transactional Engine/native host semantics. Bad quality/nonfinite arithmetic retains the complete previous outputs/state, possibly positive commands, even with false permission. First fault has no preseeded safe commands; host initial outputs may be empty or0. No physical shutdown claim.",
        "units": "Temperature absolutes/differences/inverse-degree gains and cfm/L/s primary flows/inverse-flow gains convert together. Existing binary64/core and REAL/native policies remain. Parameter conversion is not universal state-trajectory equivalence or physical range certification.",
        "diagnostics": "Authored series_state0off1close2fan-start3run4fault and thermal_state0neutral1heat2cool are not native enums. Boolean close/proof/deadline indicators expose logical timing without claiming measured actuator motion.",
    },
    "gaps": GAPS,
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
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
TemperatureGain = Annotated[float, Field(strict=True, ge=0, le=1800000)]
Flow = Annotated[float, Field(strict=True, ge=0, le=3000000)]
FlowGain = Annotated[float, Field(strict=True, ge=0, le=3000000)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=3600)]
Flag = Annotated[bool, Field(strict=True)]


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    name: str = Field(min_length=1, max_length=200)
    family: Literal["universal-runtime", "johnson-fx", "johnson-metasys"] = "universal-runtime"
    model: str = Field(default="", max_length=80)
    firmware: str = Field(default="", max_length=80)
    release_mode: str = Field(default="", max_length=80)
    operation: Literal["occupied-only"] = "occupied-only"
    fan: Literal["single-speed-series"] = "single-speed-series"
    heating: Literal["proportional-hot-water"] = "proportional-hot-water"
    flow_feedback: Literal["calibrated-primary"] = "calibrated-primary"
    temperature_unit: Literal["degF", "degC"] = "degF"
    flow_unit: Literal["cfm", "L/s"] = "cfm"
    zone_default: Temperature = 74
    heating_setpoint: Temperature = 68
    cooling_setpoint: Temperature = 72
    entry_delta: Difference = 1
    release_delta: Difference = 0
    heating_kp: TemperatureGain = 4
    heating_ki: TemperatureGain = 0.1
    cooling_kp: TemperatureGain = 4
    cooling_ki: TemperatureGain = 0.1
    primary_flow_min: Flow = 100
    primary_flow_max: Flow = 800
    primary_flow_default: Flow = 0
    flow_kp: FlowGain = 0.2
    flow_ki: FlowGain = 0.01
    close_seconds: Seconds = 90
    proof_seconds: Seconds = 15
    startup_timeout_seconds: Seconds = 60
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1
    occupied_default: Flag = False
    unit_enable_default: Flag = False
    energy_holdoff_default: Flag = False
    fan_proven_default: Flag = False
    fan_reset_default: Flag = False

    @model_validator(mode="after")
    def coherent(self):
        if not self.name.strip() or any(not character.isprintable() for character in self.name):
            raise ValueError("Program name requires visible printable text.")
        for field in ("zone_default", "heating_setpoint", "cooling_setpoint"):
            number = getattr(self, field)
            celsius = number if self.temperature_unit == "degC" else (number - 32) * 5 / 9
            if not -50 <= celsius <= 100:
                raise ValueError("Declared temperatures require -50..100 Celsius equivalents.")
        if self.heating_setpoint >= self.cooling_setpoint:
            raise ValueError("Heating setpoint must be below cooling setpoint.")
        if self.entry_delta <= self.release_delta:
            raise ValueError("Entry difference must exceed nonnegative release difference.")
        ratio = 5 / 9 if self.temperature_unit == "degF" else 1
        for field in ("entry_delta", "release_delta"):
            if getattr(self, field) * ratio > 100:
                raise ValueError("Temperature differences exceed100 Celsius degrees.")
        for field in ("heating_kp", "heating_ki", "cooling_kp", "cooling_ki"):
            if getattr(self, field) / ratio > 1800000:
                raise ValueError("Temperature gains exceed the canonical per-Celsius bound.")
        factor = CFM_TO_LPS if self.flow_unit == "cfm" else 1
        for field in ("primary_flow_min", "primary_flow_max", "primary_flow_default"):
            if getattr(self, field) * factor > 1000000:
                raise ValueError("Primary flow exceeds the1,000,000L/s equivalent bound.")
        if self.primary_flow_min >= self.primary_flow_max:
            raise ValueError("Primary minimum flow must be below maximum flow.")
        for field in ("flow_kp", "flow_ki"):
            if getattr(self, field) / factor > 3000000:
                raise ValueError("Flow gains exceed the canonical per-L/s bound.")
        for field in ("close_seconds", "proof_seconds", "startup_timeout_seconds"):
            if getattr(self, field) % self.scan_seconds:
                raise ValueError("Timing seconds require whole multiples of the declared scan.")
        if self.startup_timeout_seconds < self.proof_seconds:
            raise ValueError("Startup deadline cannot precede the stable-proof interval.")
        return self


class PreviewRequest(StrictModel):
    choices: Choices


class UnitsRequest(StrictModel):
    choices: Choices
    temperature_unit: Literal["degF", "degC"]
    flow_unit: Literal["cfm", "L/s"]


def choice_document(value):
    return normalize(value.model_dump())


def convert_units(value, temperature_unit, flow_unit):
    data = value.model_dump()
    if temperature_unit != value.temperature_unit:
        ratio = 5 / 9 if temperature_unit == "degC" else 9 / 5
        for field in ("zone_default", "heating_setpoint", "cooling_setpoint"):
            data[field] = (
                (data[field] - 32) * 5 / 9
                if temperature_unit == "degC"
                else data[field] * 9 / 5 + 32
            )
        for field in ("entry_delta", "release_delta"):
            data[field] *= ratio
        for field in ("heating_kp", "heating_ki", "cooling_kp", "cooling_ki"):
            data[field] /= ratio
    if flow_unit != value.flow_unit:
        ratio = CFM_TO_LPS if flow_unit == "L/s" else 1 / CFM_TO_LPS
        for field in ("primary_flow_min", "primary_flow_max", "primary_flow_default"):
            data[field] *= ratio
        for field in ("flow_kp", "flow_ki"):
            data[field] /= ratio
    data.update(temperature_unit=temperature_unit, flow_unit=flow_unit)
    return Choices.model_validate(data)


def generate(value: Choices):
    nodes, edges = [], []

    def node(identifier, kind, params=None, unit="", boolean=False, label=None):
        index = len(nodes)
        nodes.append(
            Node(
                id=identifier,
                kind=kind,
                params=normalize(params or {}),
                unit=unit,
                value_type="boolean" if boolean else "number",
                label=label or identifier.replace("_", " ").title(),
                x=40 + 300 * (index % 8),
                y=60 + 150 * (index // 8),
            )
        )
        return identifier

    def wire(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def unary(identifier, kind, source, unit="", boolean=False, params=None):
        node(identifier, kind, params, unit, boolean)
        wire(source, identifier)
        return identifier

    def binary(identifier, kind, a, b, unit="", boolean=False):
        node(identifier, kind, unit=unit, boolean=boolean)
        wire(a, identifier, "a")
        wire(b, identifier, "b")
        return identifier

    def gate(identifier, kind, a, b=None):
        return (
            unary(identifier, kind, a, boolean=True)
            if b is None
            else binary(identifier, kind, a, b, boolean=True)
        )

    def all_of(identifier, *sources):
        result = sources[0]
        for index, source in enumerate(sources[1:], 1):
            result = gate(
                identifier if index == len(sources) - 1 else identifier + "_" + str(index),
                "And",
                result,
                source,
            )
        return result

    def select(identifier, condition, on, off, unit="", boolean=False):
        node(identifier, "Switch", unit=unit, boolean=boolean)
        for port, source in (("select", condition), ("on", on), ("off", off)):
            wire(source, identifier, port)
        return identifier

    def constant(identifier, number, unit="", boolean=False):
        return node(identifier, "Constant", {"value": number}, unit, boolean)

    def memory(identifier, initial, unit="", boolean=False):
        return node(identifier, "Delay", {"initial": initial}, unit, boolean)

    def timer(identifier, condition, seconds):
        return unary(identifier, "TimerOn", condition, boolean=True, params={"seconds": seconds})

    def ge(identifier, a, b):
        return gate(identifier, "Not", binary(identifier + "_less", "Less", a, b, boolean=True))

    def le(identifier, a, b):
        return gate(
            identifier, "Not", binary(identifier + "_greater", "Greater", a, b, boolean=True)
        )

    def within(identifier, source, low, high, unit):
        return all_of(
            identifier,
            ge(identifier + "_minimum", source, constant(identifier + "_low", low, unit)),
            le(identifier + "_maximum", source, constant(identifier + "_high", high, unit)),
        )

    def output(identifier, source, unit="", boolean=False, label=None):
        node(identifier, "Output", unit=unit, boolean=boolean, label=label)
        wire(source, identifier)

    def pi(identifier, sp, pv, enabled, kp, ki, unit, reverse=False):
        measurement = select(identifier + "_measurement", enabled, pv, sp, unit)
        node(identifier, "PI", {"kp": kp, "ki": ki, "min": 0, "max": 100, "reverse": reverse}, "%")
        wire(sp, identifier, "setpoint")
        wire(measurement, identifier, "measured")
        return select(identifier + "_selected", enabled, identifier, zero_percent, "%")

    zero_percent = constant("zero_percent", 0, "%")
    zero_flow = constant("zero_flow", 0, value.flow_unit)
    for identifier, default in (
        ("occupied", value.occupied_default),
        ("unit_enable", value.unit_enable_default),
        ("energy_holdoff", value.energy_holdoff_default),
        ("fan_proven", value.fan_proven_default),
        ("fan_reset", value.fan_reset_default),
    ):
        node(identifier, "Input", {"default": default}, boolean=True)
    for identifier, default in (
        ("zone_temperature", value.zone_default),
        ("heating_setpoint", value.heating_setpoint),
        ("cooling_setpoint", value.cooling_setpoint),
    ):
        node(identifier, "Input", {"default": default}, value.temperature_unit)
    node(
        "primary_airflow",
        "Input",
        {"default": value.primary_flow_default},
        value.flow_unit,
        label="Calibrated PRIMARY airflow; not total coil airflow",
    )
    raw_request = all_of(
        "raw_request", "occupied", "unit_enable", gate("holdoff_clear", "Not", "energy_holdoff")
    )

    def absolute(c):
        return c if value.temperature_unit == "degC" else c * 9 / 5 + 32

    valid_sp = all_of(
        "setpoints_admitted",
        binary("ordered_setpoints", "Less", "heating_setpoint", "cooling_setpoint", boolean=True),
        within(
            "heating_in_range",
            "heating_setpoint",
            absolute(-50),
            absolute(100),
            value.temperature_unit,
        ),
        within(
            "cooling_in_range",
            "cooling_setpoint",
            absolute(-50),
            absolute(100),
            value.temperature_unit,
        ),
    )
    valid_zone = within(
        "zone_in_range", "zone_temperature", absolute(-50), absolute(100), value.temperature_unit
    )
    flow_ceiling = 1000000 / CFM_TO_LPS if value.flow_unit == "cfm" else 1000000
    valid_flow = within(
        "primary_flow_admitted", "primary_airflow", 0, flow_ceiling, value.flow_unit
    )
    permitted = all_of("permitted", raw_request, valid_sp, valid_zone, valid_flow)
    previous_fault = memory("previous_fan_fault", False, boolean=True)
    previous_reset = memory("previous_reset", False, boolean=True)
    previous_closed = memory("previous_close_complete", False, boolean=True)
    previous_ready = memory("previous_ready", False, boolean=True)
    reset_edge = all_of(
        "reset_rising", "fan_reset", gate("reset_previously_low", "Not", previous_reset)
    )
    reset = all_of("reset_allowed", reset_edge, gate("raw_request_off", "Not", raw_request))
    starting = all_of(
        "starting_permitted", permitted, gate("prior_fault_clear", "Not", previous_fault)
    )
    closed = timer("close_elapsed", starting, value.close_seconds)
    fan_request = all_of("fan_requested_after_close", starting, previous_closed)
    proof = timer(
        "proof_elapsed", all_of("proof_timing", fan_request, "fan_proven"), value.proof_seconds
    )
    ready_candidate = all_of("ready_candidate", fan_request, "fan_proven", proof)
    deadline = timer(
        "startup_elapsed",
        all_of("startup_timing", fan_request, gate("not_previously_ready", "Not", previous_ready)),
        value.startup_timeout_seconds,
    )
    timeout = all_of(
        "startup_trip", fan_request, deadline, gate("not_ready_candidate", "Not", ready_candidate)
    )
    lost = all_of(
        "running_proof_lost",
        raw_request,
        previous_ready,
        gate("proof_missing", "Not", "fan_proven"),
    )
    retained_fault = all_of(
        "retained_fan_fault", previous_fault, gate("reset_not_accepted", "Not", reset)
    )
    fault = gate("fan_fault_next", "Or", retained_fault, gate("new_trip", "Or", timeout, lost))
    no_fault = gate("fault_clear", "Not", fault)
    fan = all_of("fan_command", fan_request, no_fault)
    ready = all_of("ready_next", ready_candidate, no_fault)
    close_phase = all_of(
        "close_command_phase",
        starting,
        gate("close_previous_incomplete", "Not", previous_closed),
        no_fault,
    )
    for current, previous in (
        (fault, previous_fault),
        ("fan_reset", previous_reset),
        (closed, previous_closed),
        (ready, previous_ready),
    ):
        wire(current, previous)

    delta = "delta-" + value.temperature_unit
    node("heating_error", "TemperatureDifference", {"unit": value.temperature_unit}, delta)
    wire("heating_setpoint", "heating_error", "a")
    wire("zone_temperature", "heating_error", "b")
    node("cooling_error", "TemperatureDifference", {"unit": value.temperature_unit}, delta)
    wire("zone_temperature", "cooling_error", "a")
    wire("cooling_setpoint", "cooling_error", "b")
    entry = constant("positive_entry_difference", value.entry_delta, delta)
    release = constant("negative_release_difference", -value.release_delta, delta)
    heat_enter, cool_enter = (
        ge("heating_enter", "heating_error", entry),
        ge("cooling_enter", "cooling_error", entry),
    )
    previous_heat = memory("previous_heating_active", False, boolean=True)
    previous_cool = memory("previous_cooling_active", False, boolean=True)
    previous_heat_command = memory("previous_heating_command", 0, "%")
    previous_cool_command = memory("previous_cooling_command", 0, "%")
    heat_release = all_of(
        "heat_release",
        le("heat_release_temperature", "heating_error", release),
        le("previous_heat_zero", previous_heat_command, zero_percent),
    )
    cool_release = all_of(
        "cool_release",
        le("cool_release_temperature", "cooling_error", release),
        le("previous_cool_zero", previous_cool_command, zero_percent),
    )
    heat = all_of(
        "heating_next",
        ready,
        gate("no_cooling_entry", "Not", cool_enter),
        gate(
            "heat_enter_or_hold",
            "Or",
            heat_enter,
            all_of("heat_hold", previous_heat, gate("heat_not_released", "Not", heat_release)),
        ),
    )
    cool = all_of(
        "cooling_next",
        ready,
        gate("heat_not_selected", "Not", heat),
        gate(
            "cool_enter_or_hold",
            "Or",
            cool_enter,
            all_of("cool_hold", previous_cool, gate("cool_not_released", "Not", cool_release)),
        ),
    )
    heat_command = pi(
        "zone_heating_loop",
        "heating_setpoint",
        "zone_temperature",
        heat,
        value.heating_kp,
        value.heating_ki,
        value.temperature_unit,
    )
    cool_command = pi(
        "zone_cooling_loop",
        "cooling_setpoint",
        "zone_temperature",
        cool,
        value.cooling_kp,
        value.cooling_ki,
        value.temperature_unit,
        True,
    )
    mapped_flow = unary(
        "mapped_primary_target",
        "Scale",
        cool_command,
        value.flow_unit,
        params={
            "in_min": 0,
            "in_max": 100,
            "out_min": value.primary_flow_min,
            "out_max": value.primary_flow_max,
            "clamp": True,
        },
    )
    flow_target = select("selected_primary_target", ready, mapped_flow, zero_flow, value.flow_unit)
    damper = pi(
        "primary_flow_loop",
        flow_target,
        "primary_airflow",
        ready,
        value.flow_kp,
        value.flow_ki,
        value.flow_unit,
    )
    for current, previous in (
        (heat, previous_heat),
        (cool, previous_cool),
        (heat_command, previous_heat_command),
        (cool_command, previous_cool_command),
    ):
        wire(current, previous)
    states = {
        name: constant("state_" + name, number)
        for name, number in (("off", 0), ("close", 1), ("start", 2), ("run", 3), ("fault", 4))
    }
    series_state = select(
        "selected_series_state",
        fault,
        states["fault"],
        select(
            "active_series_state",
            ready,
            states["run"],
            select(
                "starting_series_state",
                fan,
                states["start"],
                select("closing_series_state", close_phase, states["close"], states["off"]),
            ),
        ),
    )
    thermal_state = select(
        "selected_thermal_state",
        heat,
        states["close"],
        select("selected_cooling_state", cool, states["start"], states["off"]),
    )
    boolean_outputs = {
        "raw_run_request": raw_request,
        "setpoints_valid": valid_sp,
        "zone_range_valid": valid_zone,
        "primary_flow_valid": valid_flow,
        "control_permitted": permitted,
        "close_phase": close_phase,
        "close_complete": all_of("close_complete_visible", closed, no_fault),
        "fan_starting": all_of(
            "fan_starting_visible", fan, gate("not_ready_visible", "Not", ready)
        ),
        "fan_ready": ready,
        "fan_fault": fault,
        "reset_accepted": reset,
        "fan_enable": fan,
        "fan_proof_stable": all_of("proof_visible", proof, fan),
        "startup_deadline_reached": deadline,
        "heating_active": heat,
        "cooling_active": cool,
    }
    for identifier, source in boolean_outputs.items():
        output(identifier, source, boolean=True)
    output("series_state", series_state)
    output("thermal_state", thermal_state)
    output("zone_cooling_demand", cool_command, "%")
    output("zone_heating_demand", heat_command, "%")
    output("primary_flow_target", flow_target, value.flow_unit)
    output("primary_flow_measured", "primary_airflow", value.flow_unit)
    output(
        "primary_damper", damper, "%", label="Logical primary damper command; no closure feedback"
    )
    output(
        "reheat_valve",
        heat_command,
        "%",
        label="Logical hot-water reheat; no measured total coil flow",
    )
    inputs = [
        {
            "id": n.id,
            "label": n.label,
            "value_type": n.value_type,
            "unit": n.unit,
            "default": n.params["default"],
        }
        for n in nodes
        if n.kind == "Input"
    ]
    outputs = [
        {"id": n.id, "label": n.label, "value_type": n.value_type, "unit": n.unit}
        for n in nodes
        if n.kind == "Output"
    ]
    metadata = {
        "profile": PROFILE["profile"],
        "profile_sha256": PROFILE_SHA,
        "source": SOURCE,
        "choices": choice_document(value),
        "choices_sha256": digest(choice_document(value)),
        "unimplemented": GAPS,
        "inputs": inputs,
        "outputs": outputs,
        "inactive_choices": [],
    }
    return Program(
        id=value.project_id,
        name=value.name,
        description="Authored occupied real series-fan VAV with calibrated primary-flow feedback and hot-water reheat. No native/physical/compliance acceptance.",
        scan_seconds=value.scan_seconds,
        target=Target(
            family=value.family,
            model=value.model,
            firmware=value.firmware,
            release_mode=value.release_mode,
        ),
        nodes=nodes,
        edges=edges,
        metadata={
            "application": "occupied-series-fan-vav",
            "native_deployment_verified": False,
            "compliance": "Uncertified authored sequence",
            "series_fan_vav_wizard": metadata,
        },
    )


def preview(body: PreviewRequest):
    program = generate(body.choices)
    diagnostics = [item.model_dump(exclude_none=True) for item in validate(program)]
    metadata = program.metadata["series_fan_vav_wizard"]
    return {
        "format": "bms.series-fan-vav-wizard-preview",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "choices": choice_document(body.choices),
        "choices_sha256": digest(choice_document(body.choices)),
        "program": program.model_dump(mode="json"),
        "program_sha256": program.digest(),
        "diagnostics": diagnostics,
        "can_create": not any(item["level"] == "error" for item in diagnostics),
        "inputs": metadata["inputs"],
        "outputs": metadata["outputs"],
        "inactive_choices": metadata["inactive_choices"],
        "native_compile": False,
        "controller_writes": False,
    }


def catalog_document():
    return {
        "format": "bms.series-fan-vav-wizard-catalog",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "defaults": choice_document(
            Choices(project_id="new-series-vav", name="Occupied series fan-powered VAV")
        ),
        "limits": LIMITS,
        "choices_schema": Choices.model_json_schema(),
    }


def series_fan_vav_router():
    router = APIRouter(prefix="/api/series-fan-vav-wizard")

    @router.get("/catalog")
    def catalog():
        return catalog_document()

    @router.post("/preview")
    def review(body: PreviewRequest, source_transport: SourceMode = False):
        return source_response(preview(body), source_transport)

    @router.post("/export")
    def export(body: PreviewRequest):
        raw = canonical(preview(body))
        return Response(
            raw,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="series-fan-vav-review.json"',
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
            },
        )

    @router.post("/units")
    def units(body: UnitsRequest):
        converted = convert_units(body.choices, body.temperature_unit, body.flow_unit)
        return {
            "profile_sha256": PROFILE_SHA,
            "source_choices": choice_document(body.choices),
            "source_choices_sha256": digest(choice_document(body.choices)),
            "choices": choice_document(converted),
            "choices_sha256": digest(choice_document(converted)),
        }

    return router
