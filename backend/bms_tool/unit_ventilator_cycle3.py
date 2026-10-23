"""Authored occupied UV Cycle III graph; no native JCI module equivalence."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .engine import validate
from .models import Edge, Node, Program, StrictModel, Target
from .program_source import SourceMode, source_response

SOURCE = {
    "title": "Controller Tool Help",
    "edition": "18.0",
    "document": "LIT-12011147",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [490, 491, 492, 493, 494, 1112, 1113, 1114, 1273, 1274, 1275, 1276],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Distinct occupied single-speed Unit Ventilator Cycle III: direct zone hydronic coils and MAT damper regulation with zone-limited OA command. The ordinary graph is authored, not a recovered native v51 FSM.",
    "ambiguities": [
        "Figure143 native High/Low/IsResponding and fast-setpoint flags are not available as ordinary PI control status. Previous selected heating command100 and explicit unavailable heat form an authored limiter condition instead.",
        "Shared damper module defaults include Process ID ZN-T, while its UV-specific text says MAT main PV and zone low-limit PV. This graph wires these roles explicitly.",
        "Source55F/13C are rounded alternative presets. This profile converts Fahrenheit references, not rounded Celsius manufacturer presets.",
    ],
}
GAPS = [
    "native JCI packages, CAF allocation/compiler/transfer, firmware and physical commissioning",
    "measured airflow/ventilation, physical protections, actuator linkage/direction and proven cold-outdoor mixing action",
    "Cycles I/II/W, variable/three-speed/fan-by-others, DX/electric/staged/changeover/face-bypass coils",
    "unoccupied recovery/coil protection, OAT/RAT suitability, warm-outdoor reversal and discharge-air limit control",
    "native ControlStatus/IsResponding, adaptive tuning/EWMA, output override tracking, tuning reset and FSCS commands",
    "arbitrary scan overrides, restart state persistence, general unit-invariant nonlinear trajectories and ASHRAE/G36/Title24 acceptance",
]
LIMITS = {
    "temperature_celsius": [-50, 100],
    "difference_celsius": [0, 100],
    "gain_per_celsius": [0, 1800000],
    "percent": [0, 100],
    "scan_seconds": [1, 60],
    "timing_seconds": [1, 3600],
    "generated_nodes": 256,
}
PROFILE = {
    "profile": "studio-occupied-uv-cycle3/1",
    "source": SOURCE,
    "limits": LIMITS,
    "gaps": GAPS,
    "semantics": {
        "scope": "Occupied-only single owned speed fan, separate proportional hydronic coils and one OA/mixed-air command. Increasing OA is assumed to cool MAT; no RA complement, physical point or automatic external setpoint link is generated.",
        "inputs": "13 required logical inputs. External heating target intentionally also supplies zone low-limit target. All are evaluated by unchanged transactional quality policy, even when permission is false.",
        "admission": "Raw occupied AND unit_enable AND NOT holdoff is separate from good-value admission. setpoints_valid checks three setpoint ranges and ordered heating/cooling; temperature_range_valid checks zone/MAT ranges. Invalid good values inhibit all commands/readiness and restart startup without counting as operator off.",
        "fan": "No damper close estimate. First requested successful scan requests fan and counts one proof/deadline interval. Authored default5s stable proof and60s deadline span chatter; exact-deadline proof wins. Good lost running proof immediately latches all commands off. Reset requires raw off and fresh rising reset edge, not value inhibition.",
        "condensate": "Explicit disable-cooling or shutdown-unit. Alarm always inhibits cooling. Shutdown also inhibits fan/MAT/heating/readiness and resets timers, without changing raw request or authorizing fault reset. No extra condensate latch.",
        "thermal": "Inclusive positive entry thresholds; strict beyond-opposite-side release only when previous SELECTED coil command is zero. Opposite entry switches directly. Readiness clears modes. Availability gates the respective selected command, not held request mode. Inactive PIs see zero error and retain integrals.",
        "MAT": "Reverse PI on MAT minus MAT target yields raw0..100, mapped to minimum OA..100, including defined minimum100. Active whenever ready; unavailable mechanical cooling does not disable MAT ventilation.",
        "zone_limit": "Ready heating mode, zone below heating target, and prior selected heating valve100 or unavailable heating selects the zone limiter. Forward zone-cold PI correction0..100 gives latent allowance100-correction. Select max(minimumOA,min(mappedMAT,allowance)); never reduce below declared minimum. This affects damper only, never boosts heat.",
        "diagnostics": "29 outputs. Heating/cooling requested are held modes; active means loop permission, not positive command or physical proof. Zone correction/allowance retain latent PI memory, while zone_limit_restricting means final selected OA is actually below mapped MAT. reset_accepted is an admitted clear edge, even with no prior latch. Authored unit_state0off1start2run3fault and thermal_state0neutral1heat2cool3zone-limited-heat are not native enums.",
        "quality": "Bad quality/nonfinite arithmetic rolls back the complete scan, retaining prior outputs/state, possibly positive commands even when another input asks off. Before first success existing core output is empty/native0; no safe command set is preseeded. No physical shutdown claim.",
        "representation": "Authored finite choice/default numbers and generated parameters canonicalize positive integral floats to integers while preserving negative zero. Actual server Program source tokens and original exports remain authoritative; no global source/SDK number normalization or authentication claim.",
        "units": "Absolute temperatures, differences and inverse-degree gains convert together. Existing binary64 and native REAL policies remain; no state migration or unit-invariant nonlinear trajectory promise. Collapsed adjacent differences refuse instead of widening.",
    },
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def normalize(value):
    if (
        type(value) is float
        and value.is_integer()
        and not (value == 0 and math.copysign(1, value) < 0)
    ):
        return int(value)
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


PROFILE_SHA = digest(PROFILE)
Temperature = Annotated[float, Field(strict=True, ge=-1000, le=1000)]
Difference = Annotated[float, Field(strict=True, ge=0, le=180)]
Gain = Annotated[float, Field(strict=True, ge=0, le=1800000)]
Flag = Annotated[bool, Field(strict=True)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=3600)]
ABSOLUTES = (
    "zone_default",
    "mixed_air_default",
    "heating_setpoint",
    "cooling_setpoint",
    "mixed_air_setpoint",
)
GAINS = (
    "heating_kp",
    "heating_ki",
    "cooling_kp",
    "cooling_ki",
    "mixed_air_kp",
    "mixed_air_ki",
    "zone_limit_kp",
    "zone_limit_ki",
)


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    name: str = Field(min_length=1, max_length=200)
    family: Literal["universal-runtime", "johnson-fx", "johnson-metasys"] = "universal-runtime"
    model: str = Field(default="", max_length=80)
    firmware: str = Field(default="", max_length=80)
    release_mode: str = Field(default="", max_length=80)
    operation: Literal["occupied-only"] = "occupied-only"
    fan: Literal["single-speed"] = "single-speed"
    cycle: Literal["authored-cycle-3"] = "authored-cycle-3"
    coils: Literal["separate-proportional-hydronic"] = "separate-proportional-hydronic"
    mixing_action: Literal["cold-outdoor-only"] = "cold-outdoor-only"
    condensate_policy: Literal["disable-cooling", "shutdown-unit"]
    temperature_unit: Literal["degF", "degC"] = "degF"
    zone_default: Temperature = 72
    mixed_air_default: Temperature = 55
    heating_setpoint: Temperature = 70
    cooling_setpoint: Temperature = 74
    mixed_air_setpoint: Temperature = 55
    entry_delta: Difference = 1
    release_delta: Difference = 0
    heating_kp: Gain = 4
    heating_ki: Gain = 0.1
    cooling_kp: Gain = 4
    cooling_ki: Gain = 0.1
    mixed_air_kp: Gain = 5
    mixed_air_ki: Gain = 0.1
    zone_limit_kp: Gain = 5
    zone_limit_ki: Gain = 0.1
    minimum_outdoor_position: Annotated[float, Field(strict=True, ge=0, le=100)] = 10
    proof_seconds: Seconds = 5
    startup_timeout_seconds: Seconds = 60
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1
    occupied_default: Flag = False
    unit_enable_default: Flag = False
    energy_holdoff_default: Flag = False
    airflow_proven_default: Flag = False
    fan_reset_default: Flag = False
    condensate_alarm_default: Flag = False
    heating_available_default: Flag = True
    cooling_available_default: Flag = True

    @model_validator(mode="after")
    def coherent(self):
        if not self.name.strip() or any(not x.isprintable() for x in self.name):
            raise ValueError("Program name requires visible printable text.")
        for key in ABSOLUTES:
            n = getattr(self, key)
            c = n if self.temperature_unit == "degC" else (n - 32) * 5 / 9
            if not -50 <= c <= 100:
                raise ValueError("Temperatures require -50..100 Celsius equivalents.")
        if self.heating_setpoint >= self.cooling_setpoint:
            raise ValueError("Heating setpoint must be below cooling setpoint.")
        if self.entry_delta <= self.release_delta:
            raise ValueError(
                "Positive entry difference must exceed nonnegative release difference."
            )
        ratio = 5 / 9 if self.temperature_unit == "degF" else 1
        if any(getattr(self, k) * ratio > 100 for k in ("entry_delta", "release_delta")):
            raise ValueError("Differences exceed100 Celsius degrees.")
        if any(getattr(self, k) / ratio > 1800000 for k in GAINS):
            raise ValueError("Gain exceeds canonical per-Celsius bound.")
        if (
            self.proof_seconds % self.scan_seconds
            or self.startup_timeout_seconds % self.scan_seconds
        ):
            raise ValueError("Durations require whole multiples of the declared scan.")
        if self.startup_timeout_seconds < self.proof_seconds:
            raise ValueError("Startup deadline cannot precede stable proof.")
        return self


class PreviewRequest(StrictModel):
    choices: Choices


class UnitsRequest(StrictModel):
    choices: Choices
    temperature_unit: Literal["degF", "degC"]


def choice_document(value):
    return normalize(value.model_dump())


def convert_units(value, unit):
    data = value.model_dump()
    if unit != value.temperature_unit:
        ratio = 5 / 9 if unit == "degC" else 9 / 5
        for key in ABSOLUTES:
            data[key] = (data[key] - 32) * 5 / 9 if unit == "degC" else data[key] * 9 / 5 + 32
        for key in ("entry_delta", "release_delta"):
            data[key] *= ratio
        for key in GAINS:
            data[key] /= ratio
    data["temperature_unit"] = unit
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

    def pi(identifier, sp, pv, enabled, kp, ki, reverse=False):
        measured = select(identifier + "_measurement", enabled, pv, sp, value.temperature_unit)
        node(identifier, "PI", {"kp": kp, "ki": ki, "min": 0, "max": 100, "reverse": reverse}, "%")
        wire(sp, identifier, "setpoint")
        wire(measured, identifier, "measured")
        return identifier

    zero = constant("uv_zero", 0, "%")
    hundred = constant("uv_hundred", 100, "%")
    minimum = constant("uv_minimum_oa", value.minimum_outdoor_position, "%")
    for identifier, default in (
        ("occupied", value.occupied_default),
        ("unit_enable", value.unit_enable_default),
        ("energy_holdoff", value.energy_holdoff_default),
        ("airflow_proven", value.airflow_proven_default),
        ("fan_reset", value.fan_reset_default),
        ("condensate_alarm", value.condensate_alarm_default),
        ("heating_available", value.heating_available_default),
        ("cooling_available", value.cooling_available_default),
    ):
        node(identifier, "Input", {"default": default}, boolean=True)
    for identifier, default in (
        ("zone_temperature", value.zone_default),
        ("mixed_air_temperature", value.mixed_air_default),
        ("heating_setpoint", value.heating_setpoint),
        ("cooling_setpoint", value.cooling_setpoint),
        ("mixed_air_setpoint", value.mixed_air_setpoint),
    ):
        node(identifier, "Input", {"default": default}, value.temperature_unit)
    raw = all_of(
        "uv_raw_request",
        "occupied",
        "unit_enable",
        gate("uv_holdoff_clear", "Not", "energy_holdoff"),
    )

    def absolute(c):
        return c if value.temperature_unit == "degC" else c * 9 / 5 + 32

    ranges = {
        id: within("uv_" + id + "_range", id, absolute(-50), absolute(100), value.temperature_unit)
        for id in (
            "zone_temperature",
            "mixed_air_temperature",
            "heating_setpoint",
            "cooling_setpoint",
            "mixed_air_setpoint",
        )
    }
    valid_sp = all_of(
        "uv_setpoints_admitted",
        ranges["heating_setpoint"],
        ranges["cooling_setpoint"],
        ranges["mixed_air_setpoint"],
        binary(
            "uv_setpoints_ordered", "Less", "heating_setpoint", "cooling_setpoint", boolean=True
        ),
    )
    valid_temp = all_of(
        "uv_temperatures_admitted", ranges["zone_temperature"], ranges["mixed_air_temperature"]
    )
    shutdown = (
        "condensate_alarm"
        if value.condensate_policy == "shutdown-unit"
        else constant("uv_condensate_no_shutdown", False, boolean=True)
    )
    permitted = all_of(
        "uv_permitted", raw, valid_sp, valid_temp, gate("uv_condensate_clear", "Not", shutdown)
    )
    prior_fault = memory("uv_previous_fault", False, boolean=True)
    prior_ready = memory("uv_previous_ready", False, boolean=True)
    prior_reset = memory("uv_previous_reset", False, boolean=True)
    reset = all_of(
        "uv_reset_allowed",
        gate("uv_reset_rising", "And", "fan_reset", gate("uv_prior_reset_low", "Not", prior_reset)),
        gate("uv_raw_off", "Not", raw),
    )
    fan_requested = all_of(
        "uv_fan_request", permitted, gate("uv_prior_fault_clear", "Not", prior_fault)
    )
    stable = timer(
        "uv_proof_elapsed",
        all_of("uv_proof_timing", fan_requested, "airflow_proven"),
        value.proof_seconds,
    )
    candidate = all_of("uv_ready_candidate", fan_requested, "airflow_proven", stable)
    deadline = timer(
        "uv_startup_elapsed",
        all_of(
            "uv_startup_timing", fan_requested, gate("uv_not_previously_ready", "Not", prior_ready)
        ),
        value.startup_timeout_seconds,
    )
    timeout = all_of(
        "uv_timeout", fan_requested, deadline, gate("uv_candidate_missing", "Not", candidate)
    )
    lost = all_of(
        "uv_proof_loss", raw, prior_ready, gate("uv_proof_missing", "Not", "airflow_proven")
    )
    retained = all_of("uv_fault_retained", prior_fault, gate("uv_reset_not_accepted", "Not", reset))
    fault = gate("uv_fault_next", "Or", retained, gate("uv_new_trip", "Or", timeout, lost))
    clear = gate("uv_fault_clear", "Not", fault)
    fan = all_of("uv_fan_selected", fan_requested, clear)
    ready = all_of("uv_ready", candidate, clear)
    for current, previous in (
        (fault, prior_fault),
        (ready, prior_ready),
        ("fan_reset", prior_reset),
    ):
        wire(current, previous)
    delta = "delta-" + value.temperature_unit

    def difference(identifier, a, b):
        node(identifier, "TemperatureDifference", {"unit": value.temperature_unit}, delta)
        wire(a, identifier, "a")
        wire(b, identifier, "b")
        return identifier

    heat_error = difference("uv_heating_error", "heating_setpoint", "zone_temperature")
    cool_error = difference("uv_cooling_error", "zone_temperature", "cooling_setpoint")
    entry = constant("uv_entry", value.entry_delta, delta)
    release = constant("uv_negative_release", -value.release_delta, delta)
    heat_enter = ge("uv_heat_enter", heat_error, entry)
    cool_enter = ge("uv_cool_enter", cool_error, entry)
    prior_heat = memory("uv_previous_heat", False, boolean=True)
    prior_cool = memory("uv_previous_cool", False, boolean=True)
    prior_heat_cmd = memory("uv_previous_selected_heat", 0, "%")
    prior_cool_cmd = memory("uv_previous_selected_cool", 0, "%")
    heat_exit = all_of(
        "uv_heat_exit",
        binary("uv_heat_beyond_release", "Less", heat_error, release, boolean=True),
        le("uv_previous_heat_zero", prior_heat_cmd, zero),
    )
    cool_exit = all_of(
        "uv_cool_exit",
        binary("uv_cool_beyond_release", "Less", cool_error, release, boolean=True),
        le("uv_previous_cool_zero", prior_cool_cmd, zero),
    )
    heat = all_of(
        "uv_heat_next",
        ready,
        gate("uv_no_cool_entry", "Not", cool_enter),
        gate(
            "uv_heat_enter_or_hold",
            "Or",
            heat_enter,
            all_of("uv_heat_hold", prior_heat, gate("uv_heat_not_released", "Not", heat_exit)),
        ),
    )
    cool = all_of(
        "uv_cool_next",
        ready,
        gate("uv_no_heat_entry", "Not", heat_enter),
        gate(
            "uv_cool_enter_or_hold",
            "Or",
            cool_enter,
            all_of("uv_cool_hold", prior_cool, gate("uv_cool_not_released", "Not", cool_exit)),
        ),
    )
    heating = all_of("uv_heating_enabled", heat, "heating_available")
    cooling = all_of(
        "uv_cooling_enabled",
        cool,
        "cooling_available",
        gate("uv_no_condensate", "Not", "condensate_alarm"),
    )
    hraw = pi(
        "uv_heating_loop",
        "heating_setpoint",
        "zone_temperature",
        heating,
        value.heating_kp,
        value.heating_ki,
    )
    craw = pi(
        "uv_cooling_loop",
        "cooling_setpoint",
        "zone_temperature",
        cooling,
        value.cooling_kp,
        value.cooling_ki,
        True,
    )
    hcmd = select("uv_heating_command", heating, hraw, zero, "%")
    ccmd = select("uv_cooling_command", cooling, craw, zero, "%")
    mraw = pi(
        "uv_mixed_air_loop",
        "mixed_air_setpoint",
        "mixed_air_temperature",
        ready,
        value.mixed_air_kp,
        value.mixed_air_ki,
        True,
    )
    mapped = unary(
        "uv_mixed_air_mapped",
        "Scale",
        mraw,
        "%",
        params={
            "in_min": 0,
            "in_max": 100,
            "out_min": value.minimum_outdoor_position,
            "out_max": 100,
            "clamp": True,
        },
    )
    mdemand = select("uv_mixed_air_visible", ready, mapped, zero, "%")
    unable = gate(
        "uv_heating_unable",
        "Or",
        ge("uv_heating_previously_saturated", prior_heat_cmd, hundred),
        gate("uv_heating_unavailable", "Not", "heating_available"),
    )
    limit = all_of(
        "uv_limit_selected",
        ready,
        heat,
        binary(
            "uv_zone_below_heating", "Less", "zone_temperature", "heating_setpoint", boolean=True
        ),
        unable,
    )
    correction = pi(
        "uv_zone_limit_loop",
        "heating_setpoint",
        "zone_temperature",
        limit,
        value.zone_limit_kp,
        value.zone_limit_ki,
    )
    allowed = binary("uv_zone_allowance", "Subtract", hundred, correction, "%")
    reduced = binary(
        "uv_limited_damper",
        "Max",
        minimum,
        binary("uv_limit_minimum", "Min", mapped, allowed, "%"),
        "%",
    )
    damper = select(
        "uv_damper_command", ready, select("uv_damper_mode", limit, reduced, mapped, "%"), zero, "%"
    )
    restricting = all_of(
        "uv_limit_restricting",
        limit,
        binary("uv_actual_reduction", "Less", damper, mapped, boolean=True),
    )
    for current, previous in (
        (heat, prior_heat),
        (cool, prior_cool),
        (hcmd, prior_heat_cmd),
        (ccmd, prior_cool_cmd),
    ):
        wire(current, previous)
    states = {
        name: constant("uv_state_" + name, n)
        for name, n in (("off", 0), ("start", 1), ("run", 2), ("fault", 3))
    }
    unit = select(
        "uv_unit_state",
        fault,
        states["fault"],
        select(
            "uv_running_state",
            ready,
            states["run"],
            select("uv_starting_state", fan, states["start"], states["off"]),
        ),
    )
    thermal = select(
        "uv_thermal_state",
        limit,
        states["fault"],
        select(
            "uv_heat_state",
            heat,
            states["start"],
            select("uv_cool_state", cool, states["run"], states["off"]),
        ),
    )
    for id, source in {
        "raw_run_request": raw,
        "setpoints_valid": valid_sp,
        "temperature_range_valid": valid_temp,
        "control_permitted": permitted,
        "fan_starting": all_of("uv_start_visible", fan, gate("uv_not_ready", "Not", ready)),
        "fan_ready": ready,
        "fan_fault": fault,
        "reset_accepted": reset,
        "fan_enable": fan,
        "fan_proof_stable": all_of("uv_proof_visible", stable, fan),
        "startup_deadline_reached": deadline,
        "heating_requested": heat,
        "cooling_requested": cool,
        "heating_active": heating,
        "cooling_active": cooling,
        "zone_limit_active": limit,
        "zone_limit_restricting": restricting,
        "condensate_inhibits_cooling": "condensate_alarm",
        "condensate_shutdown": shutdown,
    }.items():
        output(id, source, boolean=True)
    output("unit_state", unit)
    output("thermal_state", thermal)
    for id, source in (
        ("heating_demand", hcmd),
        ("cooling_demand", ccmd),
        ("mixed_air_damper_demand", mdemand),
        ("zone_limit_correction", correction),
        ("zone_limit_allowed", allowed),
        ("outdoor_damper", damper),
        ("heating_valve", hcmd),
        ("cooling_valve", ccmd),
    ):
        output(id, source, "%")
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
        description="Authored occupied UV Cycle III, cold-outdoor mixing action, separate hydronic coils. No native/physical/compliance acceptance.",
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
            "application": "occupied-uv-cycle3",
            "native_deployment_verified": False,
            "compliance": "Uncertified authored sequence",
            "unit_ventilator_cycle3_wizard": metadata,
        },
    )


def preview(body: PreviewRequest):
    program = generate(body.choices)
    diagnostics = [x.model_dump(exclude_none=True) for x in validate(program)]
    metadata = program.metadata["unit_ventilator_cycle3_wizard"]
    return {
        "format": "bms.unit-ventilator-cycle3-wizard-preview",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "choices": choice_document(body.choices),
        "choices_sha256": digest(choice_document(body.choices)),
        "program": program.model_dump(mode="json"),
        "program_sha256": program.digest(),
        "diagnostics": diagnostics,
        "can_create": not any(x["level"] == "error" for x in diagnostics),
        "inputs": metadata["inputs"],
        "outputs": metadata["outputs"],
        "inactive_choices": [],
        "native_compile": False,
        "controller_writes": False,
    }


def catalog_document():
    defaults = choice_document(
        Choices(
            project_id="new-uv-cycle3",
            name="Occupied unit ventilator Cycle III",
            condensate_policy="disable-cooling",
        )
    )
    defaults["condensate_policy"] = ""
    return {
        "format": "bms.unit-ventilator-cycle3-wizard-catalog",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "defaults": defaults,
        "limits": LIMITS,
        "choices_schema": Choices.model_json_schema(),
    }


def unit_ventilator_cycle3_router():
    router = APIRouter(prefix="/api/unit-ventilator-cycle3-wizard")

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
                "Content-Disposition": 'attachment; filename="unit-ventilator-cycle3-review.json"',
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
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
