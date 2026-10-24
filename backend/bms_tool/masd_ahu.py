"""Authored ordinary-core mixed-air AHU controller, never native JCI compilation."""

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
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [
        375,
        376,
        377,
        378,
        382,
        383,
        385,
        389,
        392,
        394,
        395,
        396,
        397,
        1078,
        1079,
        1080,
        1081,
        1082,
        1083,
        1097,
        1098,
        1099,
        1100,
        1286,
        1287,
        1334,
        1335,
        1336,
    ],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "Single-fan, discharge-temperature, proportional-coil, mixing/economizer and pressure-feedback dependencies qualify this authored foundation. Current MASD AHU uses MASD-with-HR v51; adjacent MASD-only rooftop mapping is not substituted. No native FSM/PID/CAF equivalence.",
}
GAPS = [
    "native JCI allocation, packages, compiler, transfer and physical firmware acceptance",
    "measured outdoor airflow, ventilation calculations/acceptance and OA-flow override tracking",
    "return/relief/exhaust/dual fans, multiple pressure sensors, volume matching and G36 optimization",
    "enthalpy, humidity, CO2, heat recovery, zone/return primary control and cascaded/reset strategies",
    "physical freeze/smoke/FSCS/coil protection, water flush, coil pumps, staged/incremental/common coils and native alarm managers",
    "actuator/fan travel, ramping, manual override tracking, bumpless transfer and power-fail persistence",
    "condensate-specific strategies, complete manufacturer/Guideline36/Title24 or physical safety acceptance",
]
LIMITS = {
    "scan_seconds": [1, 60],
    "timing_seconds": [1, 3600],
    "temperature_celsius": [-100, 200],
    "difference_celsius": [0, 100],
    "pressure_pa": [0, 10000],
    "generated_nodes": 320,
    "thermal_gain_per_celsius": [0, 1800000],
    "raw_thermal_gain": [0, 1800000],
}
PROFILE = {
    "profile": "studio-masd-ahu/1",
    "source": SOURCE,
    "limits": LIMITS,
    "gaps": GAPS,
    "semantics": {
        "equipment": "One constant/variable supply fan; common proportional mixing command; separate modulating heating/cooling valves; continuous occupied fan and downstream SAT control, not fan-coil zone control.",
        "minimum_oa": "Position-only0..100% command floor after readiness. No outdoor airflow, fraction, damper travel or ventilation proof.",
        "pressure": "Variable fan uses explicit Pa feedback/setpoint and fixed-gain PI after readiness; declared startup speed beforehand. Constant fan omits this branch. No inch-water conversion or physical minimum-speed/ramping guarantee.",
        "proof": "Fan can start before independent proof. Full proof then stabilization precedes readiness. Startup/recovery deadlines count until readiness, including chatter; readiness wins same-frame deadline. False proof immediately closes coils/OA; bounded recovery can keep fan on, then latched trip. Rising reset only with no run request clears trip.",
        "temperature": "SAT center plus positive band derives heating/cooling setpoints. Entry thresholds start modes. Active PI stays active at setpoint with nonzero command; release needs low previous committed command plus release temperature/dwell. Opposite entry changes mode exclusively.",
        "economizer": "Off, fixed-drybulb, or authored differential-plus-absolute-high-limit. OA/RA inputs only as selected. Economizer SAT loop first; warm SAT plus previous high selected damper command/dwell admits mechanical assist with OA100%. Low mechanical command plus cool release/dwell returns to economizer. Mechanical-to-suitable handoff enters integrated mode; no bumpless/physical response claim.",
        "pi": "Existing bounded Euler PI/conditional anti-windup. Inactive loops receive zero error and output0, preserving integral; active zero-error loop can retain nonzero command. Transition command tests use Delay of prior successful scan, not native controller status/actual actuator feedback.",
        "permission": "Occupied and unit_enable must be true, holdoff false. Good false permission or latched trip commands0. Bad required input quality instead faults/rolls back whole scan and retains previous outputs/state, even with same-frame false permission. No physical fail-safe claim.",
        "clock": "Whole-second aligned timing. Initial state/timers0; first successful scan is one declared interval; faults do not advance state/timers. Fresh process restarts state, without durable field restart semantics.",
        "units": "Absolute SAT/OA/RA/setpoints/cutoffs and delta band/entry/release/differential values convert together, inverse-degree gains reciprocally. Pa/percent/seconds/Booleans unchanged. Generator choice normalization is explicit and not native evidence encoding.",
    },
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def normalize(value):
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(PROFILE)
Number = Annotated[float, Field(strict=True, ge=0, le=1e6)]
ThermalGain = Annotated[float, Field(strict=True, ge=0, le=1.8e6)]
Temperature = Annotated[float, Field(strict=True, ge=-1000, le=1000)]
Difference = Annotated[float, Field(strict=True, gt=0, le=180)]
Flag = Annotated[bool, Field(strict=True)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=3600)]


class VariableFan(StrictModel):
    pressure_default_pa: Annotated[float, Field(strict=True, ge=0, le=10000)] = 0
    setpoint_pa: Annotated[float, Field(strict=True, gt=0, le=10000)] = 250
    minimum_percent: Annotated[float, Field(strict=True, ge=0, le=100)] = 20
    startup_percent: Annotated[float, Field(strict=True, ge=0, le=100)] = 30
    maximum_percent: Annotated[float, Field(strict=True, ge=0, le=100)] = 100
    kp: Number = 0.1
    ki: Number = 0.001

    @model_validator(mode="after")
    def valid(self):
        if (
            not self.minimum_percent < self.maximum_percent
            or not self.minimum_percent <= self.startup_percent <= self.maximum_percent
        ):
            raise ValueError(
                "Variable fan requires minimum < maximum and startup inside those limits."
            )
        if not self.kp and not self.ki:
            raise ValueError("Pressure control requires a nonzero declared P or I gain.")
        return self


class Economizer(StrictModel):
    oa_default: Temperature = 50
    ra_default: Temperature | None = None
    enable_below: Temperature = 60
    disable_above: Temperature = 65
    differential_on: Difference | None = None
    differential_off: Annotated[float, Field(strict=True, ge=0, le=180)] | None = None
    kp: ThermalGain = 10
    ki: ThermalGain = 0.1
    assist_seconds: Seconds = 60
    high_threshold_percent: Annotated[float, Field(strict=True, ge=99, le=100)] = 99.5
    enable_default: Flag = True


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    name: str = Field(min_length=1, max_length=200)
    family: Literal["universal-runtime", "johnson-fx", "johnson-metasys"] = "universal-runtime"
    model: str = Field(default="", max_length=80)
    firmware: str = Field(default="", max_length=80)
    release_mode: str = Field(default="", max_length=80)
    temperature_unit: Literal["degF", "degC"] = "degF"
    fan: Literal["constant-speed", "variable-speed"]
    variable_fan: VariableFan | None = None
    economizer: Literal["off", "fixed-drybulb", "differential-drybulb"]
    economizer_control: Economizer | None = None
    sat_default: Temperature = 55
    sat_setpoint: Temperature = 55
    temperature_band: Difference = 2
    entry_delta: Difference = 0.5
    release_delta: Difference = 0.25
    heating_kp: ThermalGain = 10
    heating_ki: ThermalGain = 0.1
    cooling_kp: ThermalGain = 10
    cooling_ki: ThermalGain = 0.1
    minimum_oa_percent: Annotated[float, Field(strict=True, ge=0, le=100)] = 10
    low_threshold_percent: Annotated[float, Field(strict=True, ge=0, le=5)] = 0.5
    proof_seconds: Seconds = 5
    stabilize_seconds: Seconds = 10
    startup_timeout_seconds: Seconds = 60
    recovery_timeout_seconds: Seconds = 30
    release_seconds: Seconds = 5
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1
    occupied_default: Flag = False
    unit_enable_default: Flag = False
    energy_holdoff_default: Flag = False
    fan_proven_default: Flag = False
    fan_reset_default: Flag = False

    @model_validator(mode="after")
    def valid(self):
        if not self.name.strip() or any(not c.isprintable() for c in self.name):
            raise ValueError("Program name requires visible printable text.")
        if (self.fan == "variable-speed") != (self.variable_fan is not None):
            raise ValueError(
                "Variable fan needs explicit Pa options; constant fan cannot carry them."
            )
        if (self.economizer != "off") != (self.economizer_control is not None):
            raise ValueError(
                "Enabled economizer needs explicit control options; off cannot carry them."
            )
        if self.temperature_band <= 2 * self.release_delta or self.entry_delta < self.release_delta:
            raise ValueError(
                "Temperature band must exceed twice release difference; entry difference must be at least release difference."
            )
        if (
            not self.heating_kp
            and not self.heating_ki
            or not self.cooling_kp
            and not self.cooling_ki
        ):
            raise ValueError("Heating and cooling each require a nonzero declared P or I gain.")
        temperatures = [
            self.sat_default,
            self.sat_setpoint - self.temperature_band / 2,
            self.sat_setpoint + self.temperature_band / 2,
        ]
        differences = [self.temperature_band, self.entry_delta, self.release_delta]
        durations = [
            self.proof_seconds,
            self.stabilize_seconds,
            self.startup_timeout_seconds,
            self.recovery_timeout_seconds,
            self.release_seconds,
        ]
        if self.economizer_control:
            e = self.economizer_control
            if e.enable_below >= e.disable_above:
                raise ValueError("Economizer enable temperature must be below disable temperature.")
            if not e.kp and not e.ki:
                raise ValueError("Economizer requires a nonzero declared P or I gain.")
            temperatures += [e.oa_default, e.enable_below, e.disable_above]
            if self.economizer == "differential-drybulb":
                if (
                    e.ra_default is None
                    or e.differential_on is None
                    or e.differential_off is None
                    or e.differential_on <= e.differential_off
                ):
                    raise ValueError(
                        "Differential economizer requires RA and ordered on/off differences."
                    )
                temperatures += [e.ra_default]
                differences += [e.differential_on, e.differential_off]
            elif any(v is not None for v in (e.ra_default, e.differential_on, e.differential_off)):
                raise ValueError("Fixed drybulb cannot carry RA/differential options.")
            durations += [e.assist_seconds]
        for t in temperatures:
            c = t if self.temperature_unit == "degC" else (t - 32) * 5 / 9
            if not -100 <= c <= 200:
                raise ValueError(
                    "Declared absolute temperatures must be within -100..200 Celsius equivalents."
                )
        if max(differences) > (100 if self.temperature_unit == "degC" else 180):
            raise ValueError("Declared temperature differences exceed the profile bound.")
        thermal_gains = [self.heating_kp, self.heating_ki, self.cooling_kp, self.cooling_ki]
        if self.economizer_control:
            thermal_gains += [self.economizer_control.kp, self.economizer_control.ki]
        divisor = 1 if self.temperature_unit == "degC" else 5 / 9
        if any(gain / divisor > 1.8e6 for gain in thermal_gains):
            raise ValueError(
                "Thermal gains must not exceed1800000 percent per Celsius degree (or per degree-second); Fahrenheit gains convert with the same inverse-degree bound."
            )
        if any(t % self.scan_seconds for t in durations):
            raise ValueError("All timings must be whole multiples of the declared scan.")
        if (
            min(self.startup_timeout_seconds, self.recovery_timeout_seconds)
            < self.proof_seconds + self.stabilize_seconds + self.scan_seconds
        ):
            raise ValueError(
                "Startup/recovery deadlines must exceed proof plus stabilization by one scan."
            )
        return self


class PreviewRequest(StrictModel):
    choices: Choices


class UnitsRequest(StrictModel):
    choices: Choices
    temperature_unit: Literal["degF", "degC"]


def choice_document(value):
    return normalize(value.model_dump())


def convert_units(value, temperature_unit):
    data = value.model_dump()
    if temperature_unit != value.temperature_unit:
        ratio = 5 / 9 if temperature_unit == "degC" else 9 / 5

        def absolute(v):
            return (v - 32) * 5 / 9 if temperature_unit == "degC" else v * 9 / 5 + 32

        for name in ("sat_default", "sat_setpoint"):
            data[name] = absolute(data[name])
        for name in ("temperature_band", "entry_delta", "release_delta"):
            data[name] *= ratio
        for name in ("heating_kp", "heating_ki", "cooling_kp", "cooling_ki"):
            data[name] /= ratio
        if data["economizer_control"]:
            e = data["economizer_control"]
            for name in ("oa_default", "ra_default", "enable_below", "disable_above"):
                if e[name] is not None:
                    e[name] = absolute(e[name])
            for name in ("differential_on", "differential_off"):
                if e[name] is not None:
                    e[name] *= ratio
            e["kp"] /= ratio
            e["ki"] /= ratio
    data["temperature_unit"] = temperature_unit
    return Choices.model_validate(data)


def generate(value: Choices):
    nodes, edges = [], []

    def node(identifier, kind, params=None, unit="", boolean=False, label=None):
        index = len(nodes)
        nodes.append(
            Node(
                id=identifier,
                kind=kind,
                label=label or identifier.replace("_", " ").title(),
                params=normalize(params or {}),
                unit=unit,
                value_type="boolean" if boolean else "number",
                x=40 + 300 * (index % 8),
                y=60 + 150 * (index // 8),
            )
        )
        return identifier

    def wire(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def unary(identifier, kind, source, *, boolean=False, unit="", params=None):
        node(identifier, kind, params, unit, boolean)
        wire(source, identifier)
        return identifier

    def binary(identifier, kind, a, b, *, boolean=False, unit="", params=None):
        node(identifier, kind, params, unit, boolean)
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

    def constant(identifier, val, unit="", boolean=False):
        return node(identifier, "Constant", {"value": val}, unit, boolean)

    def memory(identifier, initial, unit="", boolean=False):
        return node(identifier, "Delay", {"initial": initial}, unit, boolean)

    def timer(identifier, condition, seconds):
        return unary(identifier, "TimerOn", condition, boolean=True, params={"seconds": seconds})

    def output(identifier, source, unit="", boolean=False, label=None):
        node(identifier, "Output", unit=unit, boolean=boolean, label=label)
        wire(source, identifier)
        return identifier

    def ge(identifier, a, b):
        return gate(identifier, "Not", binary(identifier + "_less", "Less", a, b, boolean=True))

    def le(identifier, a, b):
        return gate(
            identifier, "Not", binary(identifier + "_greater", "Greater", a, b, boolean=True)
        )

    def offset(identifier, base, delta):
        node(
            identifier,
            "TemperatureOffset",
            {"unit": value.temperature_unit, "difference_unit": "delta-" + value.temperature_unit},
            value.temperature_unit,
        )
        wire(base, identifier, "base")
        wire(delta, identifier, "difference")
        return identifier

    def pi(identifier, sp, pv, enabled, kp, ki, reverse):
        measurement = select(
            identifier + "_measurement",
            enabled,
            pv,
            sp,
            value.temperature_unit if identifier != "pressure_loop" else "Pa",
        )
        node(identifier, "PI", {"kp": kp, "ki": ki, "min": 0, "max": 100, "reverse": reverse}, "%")
        wire(sp, identifier, "setpoint")
        wire(measurement, identifier, "measured")
        return select(identifier + "_selected", enabled, identifier, zero, "%")

    false = constant("false", False, boolean=True)
    zero = constant("zero", 0, "%")
    hundred = constant("hundred", 100, "%")
    for identifier, default in (
        ("occupied", value.occupied_default),
        ("unit_enable", value.unit_enable_default),
        ("energy_holdoff", value.energy_holdoff_default),
        ("fan_proven", value.fan_proven_default),
        ("fan_reset", value.fan_reset_default),
    ):
        node(identifier, "Input", {"default": default}, boolean=True)
    node(
        "sat",
        "Input",
        {"default": value.sat_default},
        value.temperature_unit,
        label="Measured/logical supply air temperature",
    )
    node("sat_setpoint", "Input", {"default": value.sat_setpoint}, value.temperature_unit)
    permitted = all_of(
        "unit_permitted", "occupied", "unit_enable", gate("holdoff_clear", "Not", "energy_holdoff")
    )
    previous_fault = memory("previous_fan_fault", False, boolean=True)
    previous_reset = memory("previous_reset", False, boolean=True)
    had_ready = memory("previous_had_ready", False, boolean=True)
    previous_proof = memory("previous_proof_stable", False, boolean=True)
    reset_edge = all_of("reset_edge", "fan_reset", gate("reset_was_low", "Not", previous_reset))
    reset_accepted = all_of("reset_accepted", reset_edge, gate("no_run_request", "Not", permitted))
    starting = all_of("run_before_trip", permitted, gate("old_fault_clear", "Not", previous_fault))
    stable = timer(
        "proof_stable", all_of("proof_timing", starting, "fan_proven"), value.proof_seconds
    )
    settled = timer(
        "air_stabilized",
        all_of("stabilize_timing", starting, "fan_proven", previous_proof),
        value.stabilize_seconds,
    )
    ready_before_trip = all_of("ready_before_trip", starting, "fan_proven", stable, settled)
    unready = all_of("not_ready_running", starting, gate("not_ready", "Not", ready_before_trip))
    startup_expired = timer(
        "startup_expired",
        all_of("startup_timing", unready, gate("not_previously_ready", "Not", had_ready)),
        value.startup_timeout_seconds,
    )
    recovery_expired = timer(
        "recovery_expired",
        all_of("recovery_timing", unready, had_ready),
        value.recovery_timeout_seconds,
    )
    trip = all_of(
        "trip_now", unready, gate("deadline_expired", "Or", startup_expired, recovery_expired)
    )
    retained_fault = all_of(
        "retained_fault", previous_fault, gate("reset_not_accepted", "Not", reset_accepted)
    )
    fault = gate("fan_fault_next", "Or", retained_fault, trip)
    fan = all_of("fan_command", permitted, gate("fault_clear", "Not", fault))
    ready = all_of("fan_ready_next", ready_before_trip, gate("no_current_trip", "Not", fault))
    had_ready_next = all_of("had_ready_next", fan, gate("ready_seen", "Or", had_ready, ready))
    for current, previous in (
        (fault, previous_fault),
        ("fan_reset", previous_reset),
        (had_ready_next, had_ready),
        (stable, previous_proof),
    ):
        wire(current, previous)
    # The public output has a distinct ID from its internal permission expression.
    output("control_permitted", permitted, boolean=True)
    output("fan_enable", fan, boolean=True, label="Logical fan command, not operation proof")
    output("fan_ready", ready, boolean=True, label="Logical stable fan proof and stabilization")
    output("fan_fault", fault, boolean=True)
    if value.variable_fan:
        f = value.variable_fan
        node("duct_pressure", "Input", {"default": f.pressure_default_pa}, "Pa")
        node("duct_pressure_setpoint", "Input", {"default": f.setpoint_pa}, "Pa")
        pressure = pi(
            "pressure_loop", "duct_pressure_setpoint", "duct_pressure", ready, f.kp, f.ki, False
        )
        mapped = unary(
            "pressure_speed",
            "Scale",
            pressure,
            unit="%",
            params={
                "in_min": 0,
                "in_max": 100,
                "out_min": f.minimum_percent,
                "out_max": f.maximum_percent,
                "clamp": True,
            },
        )
        startup_speed = constant("startup_speed", f.startup_percent, "%")
        requested_speed = select("requested_fan_speed", ready, mapped, startup_speed, "%")
        output("fan_speed", select("gated_fan_speed", fan, requested_speed, zero, "%"), "%")

    half_band = value.temperature_band / 2
    heat_sp = offset(
        "heating_setpoint",
        "sat_setpoint",
        constant("negative_half_band", -half_band, "delta-" + value.temperature_unit),
    )
    cool_sp = offset(
        "cooling_setpoint",
        "sat_setpoint",
        constant("positive_half_band", half_band, "delta-" + value.temperature_unit),
    )
    negative_entry = constant(
        "negative_entry", -value.entry_delta, "delta-" + value.temperature_unit
    )
    positive_entry = constant(
        "positive_entry", value.entry_delta, "delta-" + value.temperature_unit
    )
    heat_entry = le("heat_entry", "sat", offset("heat_entry_temperature", heat_sp, negative_entry))
    cool_entry = ge("cool_entry", "sat", offset("cool_entry_temperature", cool_sp, positive_entry))
    positive_release = constant(
        "positive_release", value.release_delta, "delta-" + value.temperature_unit
    )
    negative_release = constant(
        "negative_release", -value.release_delta, "delta-" + value.temperature_unit
    )
    heat_release_temp = ge(
        "heat_release_temperature",
        "sat",
        offset("heat_release_boundary", heat_sp, positive_release),
    )
    cool_release_temp = le(
        "cool_release_temperature",
        "sat",
        offset("cool_release_boundary", cool_sp, negative_release),
    )
    floor = constant("minimum_oa_position", value.minimum_oa_percent, "%")
    low = constant("low_threshold", value.low_threshold_percent, "%")
    state = memory("previous_thermal_state", 0)
    states = {
        name: constant("state_" + name, number)
        for name, number in (
            ("satisfied", 0),
            ("heating", 1),
            ("economizer", 2),
            ("integrated", 3),
            ("mechanical", 4),
        )
    }
    was = {
        name: binary("was_" + name, "Equal", state, code, boolean=True)
        for name, code in states.items()
    }
    old_heat = memory("previous_heat_command", 0, "%")
    old_cool = memory("previous_cooling_command", 0, "%")
    old_econ = memory("previous_economizer_demand", 0, "%")
    old_mad = memory("previous_mixing_command", 0, "%")
    heat_release = timer(
        "heating_release",
        all_of(
            "heating_release_condition",
            ready,
            was["heating"],
            heat_release_temp,
            le("heat_low", old_heat, low),
        ),
        value.release_seconds,
    )
    econ_release = timer(
        "economizer_release",
        all_of(
            "economizer_release_condition",
            ready,
            was["economizer"],
            cool_release_temp,
            le("econ_low", old_econ, low),
        ),
        value.release_seconds,
    )
    integrated_release = timer(
        "integrated_release",
        all_of(
            "integrated_release_condition",
            ready,
            was["integrated"],
            cool_release_temp,
            le("integrated_low", old_cool, low),
        ),
        value.release_seconds,
    )
    mech_release = timer(
        "mechanical_release",
        all_of(
            "mechanical_release_condition",
            ready,
            was["mechanical"],
            cool_release_temp,
            le("mechanical_low", old_cool, low),
        ),
        value.release_seconds,
    )
    if value.economizer_control:
        e = value.economizer_control
        node("outdoor_temperature", "Input", {"default": e.oa_default}, value.temperature_unit)
        node("economizer_enable", "Input", {"default": e.enable_default}, boolean=True)
        offset_error = binary(
            "outdoor_high_limit_error",
            "TemperatureDifference",
            constant("outdoor_disable_temperature", e.disable_above, value.temperature_unit),
            "outdoor_temperature",
            unit="delta-" + value.temperature_unit,
            params={"unit": value.temperature_unit},
        )
        error = select(
            "permitted_high_limit_error",
            ready,
            offset_error,
            constant("zero_temperature_difference", 0, "delta-" + value.temperature_unit),
            "delta-" + value.temperature_unit,
        )
        suitable = unary(
            "absolute_suitability",
            "Deadband",
            error,
            boolean=True,
            unit="delta-" + value.temperature_unit,
            params={"on": e.disable_above - e.enable_below, "off": 0, "initial": False},
        )
        if value.economizer == "differential-drybulb":
            node("return_temperature", "Input", {"default": e.ra_default}, value.temperature_unit)
            difference = binary(
                "return_outdoor_difference",
                "TemperatureDifference",
                "return_temperature",
                "outdoor_temperature",
                unit="delta-" + value.temperature_unit,
                params={"unit": value.temperature_unit},
            )
            difference = select(
                "permitted_air_difference",
                ready,
                difference,
                "zero_temperature_difference",
                "delta-" + value.temperature_unit,
            )
            differential = unary(
                "differential_suitability",
                "Deadband",
                difference,
                boolean=True,
                unit="delta-" + value.temperature_unit,
                params={"on": e.differential_on, "off": e.differential_off, "initial": False},
            )
            suitable = all_of("combined_suitability", suitable, differential)
        available = all_of("economizer_available_next", ready, "economizer_enable", suitable)
        high = constant("high_command_threshold", e.high_threshold_percent, "%")
        assist = timer(
            "mechanical_assist_ready",
            all_of(
                "assist_condition",
                ready,
                was["economizer"],
                available,
                cool_entry,
                ge("mixing_command_high", old_mad, high),
            ),
            e.assist_seconds,
        )
    else:
        available = false
        assist = false
    output("economizer_available", available, boolean=True)
    cooling_start = select(
        "cooling_start_state", available, states["economizer"], states["mechanical"]
    )
    idle = select("idle_cooling", cool_entry, cooling_start, states["satisfied"])
    idle = select("idle_heating", heat_entry, states["heating"], idle)
    from_heat = select("heat_released", heat_release, states["satisfied"], states["heating"])
    from_heat = select("heat_to_cooling", cool_entry, cooling_start, from_heat)
    from_econ = select("econ_assist", assist, states["integrated"], states["economizer"])
    from_econ = select("econ_released", econ_release, states["satisfied"], from_econ)
    from_econ = select("econ_unavailable", available, from_econ, states["mechanical"])
    from_econ = select("econ_to_heat", heat_entry, states["heating"], from_econ)
    from_integrated = select(
        "integrated_released", integrated_release, states["economizer"], states["integrated"]
    )
    from_integrated = select(
        "integrated_unavailable", available, from_integrated, states["mechanical"]
    )
    from_integrated = select("integrated_to_heat", heat_entry, states["heating"], from_integrated)
    from_mech = select("mech_released", mech_release, states["satisfied"], states["mechanical"])
    from_mech = select("mech_to_integrated", available, states["integrated"], from_mech)
    from_mech = select("mech_to_heat", heat_entry, states["heating"], from_mech)
    next_state = idle
    for name, branch in (
        ("heating", from_heat),
        ("economizer", from_econ),
        ("integrated", from_integrated),
        ("mechanical", from_mech),
    ):
        next_state = select("select_" + name, was[name], branch, next_state)
    next_state = select("thermal_state_next", ready, next_state, states["satisfied"])
    wire(next_state, state)
    selected = {
        name: binary(name + "_selected", "Equal", next_state, states[name], boolean=True)
        for name in ("heating", "economizer", "integrated", "mechanical")
    }
    heating = all_of("heating_active", ready, selected["heating"])
    cooling = all_of(
        "cooling_active",
        ready,
        gate("mechanical_state_selected", "Or", selected["integrated"], selected["mechanical"]),
    )
    economizing = all_of("economizer_active", ready, selected["economizer"])
    heat_command = pi(
        "heating_loop", heat_sp, "sat", heating, value.heating_kp, value.heating_ki, False
    )
    cool_command = pi(
        "cooling_loop", cool_sp, "sat", cooling, value.cooling_kp, value.cooling_ki, True
    )
    econ_command = (
        pi(
            "economizer_loop",
            cool_sp,
            "sat",
            economizing,
            value.economizer_control.kp,
            value.economizer_control.ki,
            True,
        )
        if value.economizer_control
        else zero
    )
    selected_econ = binary("economizer_with_minimum", "Max", floor, econ_command, unit="%")
    normal_mad = select(
        "economizer_mixing_selection", selected["economizer"], selected_econ, floor, "%"
    )
    normal_mad = select(
        "integrated_mixing_selection", selected["integrated"], hundred, normal_mad, "%"
    )
    mad = select("mixing_command", ready, normal_mad, zero, "%")
    for current, previous in (
        (heat_command, old_heat),
        (cool_command, old_cool),
        (econ_command, old_econ),
        (mad, old_mad),
    ):
        wire(current, previous)
    output("heating_valve", heat_command, "%")
    output("cooling_valve", cool_command, "%")
    output("mixing_damper", mad, "%", label="Common damper command; not measured outdoor airflow")
    output(
        "ahu_state",
        next_state,
        label="Authored thermal state:0satisfied1heat2econ3integrated4mechanical",
    )
    output("heating_active_output", heating, boolean=True)
    output("mechanical_cooling_active", cooling, boolean=True)
    output("economizer_active_output", economizing, boolean=True)
    if len(nodes) > LIMITS["generated_nodes"]:
        raise ValueError("Generated AHU graph exceeds its bounded node profile.")
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
        "choices": choice_document(value),
        "choices_sha256": digest(choice_document(value)),
        "source": SOURCE,
        "unimplemented": GAPS,
        "inputs": inputs,
        "outputs": outputs,
        "inactive_choices": [],
    }
    return Program(
        id=value.project_id,
        name=value.name,
        description="Authored SAT/pressure/economizer AHU foundation. Position is not outdoor airflow. Bad required-input quality retains prior committed outputs; no physical shutdown/native/code acceptance.",
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
            "application": "mixed-air-single-duct-ahu",
            "native_deployment_verified": False,
            "compliance": "Uncertified authored sequence",
            "masd_ahu_wizard": metadata,
        },
    )


def preview(body: PreviewRequest):
    program = generate(body.choices)
    diagnostics = [item.model_dump(exclude_none=True) for item in validate(program)]
    metadata = program.metadata["masd_ahu_wizard"]
    return {
        "format": "bms.masd-ahu-wizard-preview",
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
    base = Choices(
        project_id="new-masd-ahu-project",
        name="Mixed-air single-duct AHU",
        fan="constant-speed",
        economizer="off",
    )
    defaults = choice_document(base)
    defaults.update(fan="", economizer="")
    branches = {}
    for unit in ("degF", "degC"):
        examples = {}
        for mode in ("fixed-drybulb", "differential-drybulb"):
            controls = (
                Economizer(ra_default=72, differential_on=3, differential_off=1)
                if mode == "differential-drybulb"
                else Economizer()
            )
            chosen = Choices.model_validate(
                base.model_dump()
                | {"economizer": mode, "economizer_control": controls.model_dump()}
            )
            examples[mode] = choice_document(convert_units(chosen, unit))["economizer_control"]
        branches[unit] = {
            "variable_fan": normalize(VariableFan().model_dump()),
            "economizers": {"off": None, **examples},
        }
    return {
        "format": "bms.masd-ahu-wizard-catalog",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "defaults": defaults,
        "limits": LIMITS,
        "choices_schema": Choices.model_json_schema(),
        "branch_defaults": branches,
    }


def masd_ahu_router():
    router = APIRouter(prefix="/api/masd-ahu-wizard")

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
                "Content-Disposition": 'attachment; filename="masd-ahu-review.json"',
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
