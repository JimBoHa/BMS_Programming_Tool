"""Authored AHU-only hot/cold deck control, distinct from VAV terminal mixing."""

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
    "edition": "18.0",
    "document": "LIT-12011147",
    "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
    "pdf_pages": [
        461,
        462,
        463,
        464,
        466,
        468,
        469,
        470,
        471,
        472,
        473,
        474,
        1078,
        1079,
        1080,
        1081,
        1082,
        1083,
        1090,
        1091,
        1092,
        1093,
        1094,
        1100,
        1101,
        1102,
        1123,
        1132,
        1145,
        1146,
        1147,
    ],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "scope": "MADD-MZ AHU Only, single-speed supply, fixed independent deck targets and separate hot heating/cold cooling feedback qualify this authored profile. Generic MADD variable-fan and zone/VAV terminal configurations are not substituted.",
    "ambiguities": [
        "MADD-MZ core page461 names plain MADD cold sequencing; page1090 maps that to generic MADD while page1092 with-HR mapping explicitly includes MZ. No exact native class/port/state mapping inferred.",
        "Cold-deck attributes on page1091 show one Setpoint while some state prose names heating/cooling setpoints. Independent authored deck contract is explicit, not copied as native truth.",
    ],
}
GAPS = [
    "native JCI allocation, packages, CAF/compiler/transfer and physical firmware acceptance",
    "zone dampers/room control, zone requests/min-max unoccupied arbitration and native zone-mode enumeration mappings",
    "variable/return/relief/exhaust fans, static-pressure loops, multiple sensors, volume matching and G36 optimization",
    "measured OA airflow/ventilation, CO2/enthalpy/humidity, OA/RA/zone deck reset curves and heat recovery",
    "preheat, cold-deck heating, hot-deck cooling, staged/incremental/common coils, pumps and condensate/native alarms",
    "physical freeze/smoke/FSCS/coil protection, travel/ramping/override tracking, bumpless transfer and power-fail persistence",
    "canonical control units or unit-invariant nonlinear execution; coupled F/C parameters do not guarantee identical finite-precision antiwindup/state trajectories",
    "complete manufacturer/Guideline36/Title24 or physical safety acceptance",
]
LIMITS = {
    "scan_seconds": [1, 60],
    "timing_seconds": [1, 3600],
    "absolute_temperature_celsius": [-100, 200],
    "difference_celsius": [0, 100],
    "thermal_gain_per_celsius": [0, 1800000],
    "raw_thermal_gain": [0, 1800000],
    "generated_nodes": 320,
}
PROFILE = {
    "profile": "studio-madd-mz-ahu-only/1",
    "source": SOURCE,
    "limits": LIMITS,
    "gaps": GAPS,
    "semantics": {
        "equipment": "AHU-only one single-speed supply fan, common mixing command, separate hot heating and cold cooling valves. Two deck PVs and independent fixed-target Inputs, no zone/VAV damper control.",
        "parallel_decks": "Hot heating can run concurrently with any cold economizer/mechanical state. No global heat/cool exclusion; cold control never drives the hot valve as preheat. Each PI retains required nonzero command at its own setpoint until low-command/release conditions.",
        "setpoints": "Fixed means no reset curve. Good finite runtime deck SPs outside -100..200C equivalent inhibit all ordinary commands/reset readiness without a new proof latch. Equal/reversed targets or measured decks do not inhibit; nominal/measured spreads are diagnostics. Existing proof latch resets only on operator request off plus reset rising edge.",
        "fan": "Fan starts before independent proof. Full proof then stabilization precede both deck/OA outputs. Startup/recovery deadlines count until readiness including chatter; readiness wins same scan. False proof closes coils/OA immediately on good scan; bounded fan recovery then latched trip. Rising reset only while operator request is off.",
        "hot_deck": "Idle/heating state, error HD_SP-HD_T. Entry/release temperature differences and prior low heating command/dwell control state; inactive error0/output0 holds integral. No hot-deck cooling or native sequencer equivalence.",
        "cold_deck": "Idle/economizer/integrated/mechanical states, errors CD_T-CD_SP. Economizer first; high prior selected damper (including floor100) plus warm CD/dwell admits mechanical at OA100. Low mechanical command/cool release returns econ; econ low release uses demand not floor. Suitability return from mechanical enters integrated; hot state independent.",
        "economizer": "Off, fixed drybulb, or authored differential-plus-absolute-high-limit using selected OA/RA Inputs. Position-only OA floor is not outdoor fraction, airflow, ventilation or actuator travel proof.",
        "quality": "Bad required quality faults/rolls back whole graph, retaining both decks/fan even with same-frame false permission. Good configuration/permission inhibition is different. No native failsoft/per-branch physical shutdown claim.",
        "units": "All independent deck/OA/RA absolute defaults/SPs/cutoffs, entry/release/differential differences and reciprocal thermal gains convert F/C together. Percent/seconds/Booleans unchanged; no pressure choices. Coupled parameter conversion does not guarantee identical trajectories at finite-precision PI antiwindup or state thresholds; existing binary64/core and REAL/native policies remain unchanged. Canonical unit-invariant execution is unresolved.",
        "clock": "Positive whole-second aligned scans/timers. Prior committed commands/state use Delay boundaries; initial state/timers0, failed scans do not advance. New process is fresh start without durable field restart or bumpless guarantee.",
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
Temperature = Annotated[float, Field(strict=True, ge=-1000, le=1000)]
Difference = Annotated[float, Field(strict=True, gt=0, le=180)]
ThermalGain = Annotated[float, Field(strict=True, ge=0, le=1800000)]
Flag = Annotated[bool, Field(strict=True)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=3600)]


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
    configuration: Literal["ahu-only"] = "ahu-only"
    fan: Literal["single-speed"] = "single-speed"
    temperature_unit: Literal["degF", "degC"] = "degF"
    economizer: Literal["off", "fixed-drybulb", "differential-drybulb"]
    economizer_control: Economizer | None = None
    hot_deck_default: Temperature = 75
    cold_deck_default: Temperature = 65
    hot_deck_setpoint: Temperature = 85
    cold_deck_setpoint: Temperature = 55
    hot_entry_delta: Difference = 0.5
    hot_release_delta: Difference = 0.25
    cold_entry_delta: Difference = 0.5
    cold_release_delta: Difference = 0.25
    hot_kp: ThermalGain = 10
    hot_ki: ThermalGain = 0.1
    cold_kp: ThermalGain = 10
    cold_ki: ThermalGain = 0.1
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
    def coherent(self):
        if not self.name.strip() or any(not c.isprintable() for c in self.name):
            raise ValueError("Program name requires visible printable text.")
        if (self.economizer != "off") != (self.economizer_control is not None):
            raise ValueError("Enabled economizer needs explicit controls; off cannot carry them.")
        if (
            self.hot_entry_delta < self.hot_release_delta
            or self.cold_entry_delta < self.cold_release_delta
        ):
            raise ValueError("Each entry difference must be at least its own release difference.")
        if not self.hot_kp and not self.hot_ki or not self.cold_kp and not self.cold_ki:
            raise ValueError("Each deck requires a nonzero declared P or I gain.")
        absolute = [
            self.hot_deck_default,
            self.cold_deck_default,
            self.hot_deck_setpoint,
            self.cold_deck_setpoint,
        ]
        differences = [
            self.hot_entry_delta,
            self.hot_release_delta,
            self.cold_entry_delta,
            self.cold_release_delta,
        ]
        gains = [self.hot_kp, self.hot_ki, self.cold_kp, self.cold_ki]
        times = [
            self.proof_seconds,
            self.stabilize_seconds,
            self.startup_timeout_seconds,
            self.recovery_timeout_seconds,
            self.release_seconds,
        ]
        if self.economizer_control:
            e = self.economizer_control
            if e.enable_below >= e.disable_above:
                raise ValueError("Economizer enable cutoff must be below disable cutoff.")
            if not e.kp and not e.ki:
                raise ValueError("Economizer needs nonzero P or I gain.")
            absolute += [e.oa_default, e.enable_below, e.disable_above]
            gains += [e.kp, e.ki]
            times += [e.assist_seconds]
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
                absolute += [e.ra_default]
                differences += [e.differential_on, e.differential_off]
            elif any(v is not None for v in (e.ra_default, e.differential_on, e.differential_off)):
                raise ValueError("Fixed drybulb cannot carry RA/differential choices.")
        if any(
            not -100 <= (x if self.temperature_unit == "degC" else (x - 32) * 5 / 9) <= 200
            for x in absolute
        ):
            raise ValueError(
                "Absolute defaults/setpoints must be within -100..200 Celsius equivalents."
            )
        if max(differences) > (100 if self.temperature_unit == "degC" else 180):
            raise ValueError("Temperature differences exceed profile limit.")
        divisor = 1 if self.temperature_unit == "degC" else 5 / 9
        if any(g / divisor > 1800000 for g in gains):
            raise ValueError(
                "Thermal gains exceed1800000 per Celsius degree or degree-second equivalent."
            )
        if any(t % self.scan_seconds for t in times):
            raise ValueError("All timings require whole multiples of the declared scan.")
        if (
            min(self.startup_timeout_seconds, self.recovery_timeout_seconds)
            < self.proof_seconds + self.stabilize_seconds + self.scan_seconds
        ):
            raise ValueError("Deadlines must exceed proof plus stabilization by at least one scan.")
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

        for field in (
            "hot_deck_default",
            "cold_deck_default",
            "hot_deck_setpoint",
            "cold_deck_setpoint",
        ):
            data[field] = absolute(data[field])
        for field in (
            "hot_entry_delta",
            "hot_release_delta",
            "cold_entry_delta",
            "cold_release_delta",
        ):
            data[field] *= ratio
        for field in ("hot_kp", "hot_ki", "cold_kp", "cold_ki"):
            data[field] /= ratio
        if data["economizer_control"]:
            e = data["economizer_control"]
            for field in ("oa_default", "ra_default", "enable_below", "disable_above"):
                if e[field] is not None:
                    e[field] = absolute(e[field])
            for field in ("differential_on", "differential_off"):
                if e[field] is not None:
                    e[field] *= ratio
            e["kp"] /= ratio
            e["ki"] /= ratio
    data["temperature_unit"] = temperature_unit
    return Choices.model_validate(data)


def generate(value: Choices) -> Program:
    """Build two independent deck loops as ordinary, editable core nodes."""
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

    def difference(identifier, a, b):
        return binary(
            identifier,
            "TemperatureDifference",
            a,
            b,
            unit="delta-" + value.temperature_unit,
            params={"unit": value.temperature_unit},
        )

    def pi(identifier, sp, pv, enabled, kp, ki, reverse):
        measurement = select(identifier + "_measurement", enabled, pv, sp, value.temperature_unit)
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
    for identifier, default, label in (
        ("hot_deck_temperature", value.hot_deck_default, "Measured/logical hot-deck temperature"),
        (
            "cold_deck_temperature",
            value.cold_deck_default,
            "Measured/logical cold-deck temperature",
        ),
        (
            "hot_deck_setpoint",
            value.hot_deck_setpoint,
            "Independent hot-deck fixed target; no reset curve",
        ),
        (
            "cold_deck_setpoint",
            value.cold_deck_setpoint,
            "Independent cold-deck fixed target; no reset curve",
        ),
    ):
        node(identifier, "Input", {"default": default}, value.temperature_unit, label=label)
    lower = constant(
        "minimum_runtime_setpoint",
        -100 if value.temperature_unit == "degC" else -148,
        value.temperature_unit,
    )
    upper = constant(
        "maximum_runtime_setpoint",
        200 if value.temperature_unit == "degC" else 392,
        value.temperature_unit,
    )
    valid = all_of(
        "setpoints_valid_next",
        ge("hot_setpoint_at_least_minimum", "hot_deck_setpoint", lower),
        le("hot_setpoint_at_most_maximum", "hot_deck_setpoint", upper),
        ge("cold_setpoint_at_least_minimum", "cold_deck_setpoint", lower),
        le("cold_setpoint_at_most_maximum", "cold_deck_setpoint", upper),
    )
    operator_request = all_of(
        "operator_request",
        "occupied",
        "unit_enable",
        gate("holdoff_clear", "Not", "energy_holdoff"),
    )
    permitted = all_of("unit_permitted", operator_request, valid)
    previous_fault = memory("previous_fan_fault", False, boolean=True)
    previous_reset = memory("previous_reset", False, boolean=True)
    had_ready = memory("previous_had_ready", False, boolean=True)
    previous_proof = memory("previous_proof_stable", False, boolean=True)
    reset_edge = all_of("reset_edge", "fan_reset", gate("reset_was_low", "Not", previous_reset))
    reset_accepted = all_of(
        "reset_accepted", reset_edge, gate("operator_request_off", "Not", operator_request)
    )
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
    output("control_permitted", permitted, boolean=True)
    output(
        "setpoints_valid",
        valid,
        boolean=True,
        label="Good runtime deck targets inside authored range; not native safety",
    )
    output("fan_enable", fan, boolean=True, label="Logical fan command, not operation proof")
    output("fan_ready", ready, boolean=True, label="Logical stable fan proof and stabilization")
    output("fan_fault", fault, boolean=True)
    output(
        "nominal_deck_spread",
        difference("nominal_spread", "hot_deck_setpoint", "cold_deck_setpoint"),
        "delta-" + value.temperature_unit,
    )
    output(
        "measured_deck_spread",
        difference("measured_spread", "hot_deck_temperature", "cold_deck_temperature"),
        "delta-" + value.temperature_unit,
    )
    output(
        "hot_target_above_cold",
        binary(
            "nominal_target_order",
            "Greater",
            "hot_deck_setpoint",
            "cold_deck_setpoint",
            boolean=True,
        ),
        boolean=True,
        label="Diagnostic only; equal/reversed deck targets do not inhibit",
    )

    # A separate hot state never selects or suppresses the cold-deck state.
    hot_entry = le(
        "hot_entry",
        "hot_deck_temperature",
        offset(
            "hot_entry_boundary",
            "hot_deck_setpoint",
            constant(
                "hot_negative_entry", -value.hot_entry_delta, "delta-" + value.temperature_unit
            ),
        ),
    )
    hot_release_temperature = ge(
        "hot_release_temperature",
        "hot_deck_temperature",
        offset(
            "hot_release_boundary",
            "hot_deck_setpoint",
            constant(
                "hot_positive_release", value.hot_release_delta, "delta-" + value.temperature_unit
            ),
        ),
    )
    cold_entry = ge(
        "cold_entry",
        "cold_deck_temperature",
        offset(
            "cold_entry_boundary",
            "cold_deck_setpoint",
            constant(
                "cold_positive_entry", value.cold_entry_delta, "delta-" + value.temperature_unit
            ),
        ),
    )
    cold_release_temperature = le(
        "cold_release_temperature",
        "cold_deck_temperature",
        offset(
            "cold_release_boundary",
            "cold_deck_setpoint",
            constant(
                "cold_negative_release",
                -value.cold_release_delta,
                "delta-" + value.temperature_unit,
            ),
        ),
    )
    floor = constant("minimum_oa_position", value.minimum_oa_percent, "%")
    low = constant("low_threshold", value.low_threshold_percent, "%")
    was_hot = memory("previous_hot_active", False, boolean=True)
    old_hot = memory("previous_hot_command", 0, "%")
    old_cool = memory("previous_cooling_command", 0, "%")
    old_econ = memory("previous_economizer_demand", 0, "%")
    old_mad = memory("previous_mixing_command", 0, "%")
    hot_release = timer(
        "hot_release",
        all_of(
            "hot_release_condition",
            ready,
            was_hot,
            hot_release_temperature,
            le("hot_command_low", old_hot, low),
        ),
        value.release_seconds,
    )
    continue_hot = gate("hot_not_released", "Not", hot_release)
    hot_requested = select("hot_requested", was_hot, continue_hot, hot_entry, boolean=True)
    hot_active = all_of("hot_active_next", ready, hot_requested)
    wire(hot_active, was_hot)
    state = memory("previous_cold_state", 0)
    states = {
        name: constant("cold_state_" + name, number)
        for name, number in (("idle", 0), ("economizer", 1), ("integrated", 2), ("mechanical", 3))
    }
    was = {
        name: binary("was_cold_" + name, "Equal", state, code, boolean=True)
        for name, code in states.items()
    }
    econ_release = timer(
        "economizer_release",
        all_of(
            "economizer_release_condition",
            ready,
            was["economizer"],
            cold_release_temperature,
            le("econ_command_low", old_econ, low),
        ),
        value.release_seconds,
    )
    integrated_release = timer(
        "integrated_release",
        all_of(
            "integrated_release_condition",
            ready,
            was["integrated"],
            cold_release_temperature,
            le("integrated_command_low", old_cool, low),
        ),
        value.release_seconds,
    )
    mech_release = timer(
        "mechanical_release",
        all_of(
            "mechanical_release_condition",
            ready,
            was["mechanical"],
            cold_release_temperature,
            le("mechanical_command_low", old_cool, low),
        ),
        value.release_seconds,
    )
    if value.economizer_control:
        e = value.economizer_control
        node("outdoor_temperature", "Input", {"default": e.oa_default}, value.temperature_unit)
        node("economizer_enable", "Input", {"default": e.enable_default}, boolean=True)
        absolute_error = difference(
            "outdoor_high_limit_error",
            constant("outdoor_disable_temperature", e.disable_above, value.temperature_unit),
            "outdoor_temperature",
        )
        delta_zero = constant("zero_temperature_difference", 0, "delta-" + value.temperature_unit)
        available_error = select(
            "permitted_high_limit_error",
            ready,
            absolute_error,
            delta_zero,
            "delta-" + value.temperature_unit,
        )
        suitable = unary(
            "absolute_suitability",
            "Deadband",
            available_error,
            boolean=True,
            unit="delta-" + value.temperature_unit,
            params={"on": e.disable_above - e.enable_below, "off": 0, "initial": False},
        )
        if value.economizer == "differential-drybulb":
            node("return_temperature", "Input", {"default": e.ra_default}, value.temperature_unit)
            delta = difference(
                "return_outdoor_difference", "return_temperature", "outdoor_temperature"
            )
            delta = select(
                "permitted_air_difference",
                ready,
                delta,
                delta_zero,
                "delta-" + value.temperature_unit,
            )
            differential = unary(
                "differential_suitability",
                "Deadband",
                delta,
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
                cold_entry,
                ge("mixing_command_high", old_mad, high),
            ),
            e.assist_seconds,
        )
    else:
        available, assist = false, false
    output("economizer_available", available, boolean=True)
    cooling_start = select(
        "cold_start_state", available, states["economizer"], states["mechanical"]
    )
    idle = select("cold_from_idle", cold_entry, cooling_start, states["idle"])
    from_econ = select("cold_econ_assist", assist, states["integrated"], states["economizer"])
    from_econ = select("cold_econ_released", econ_release, states["idle"], from_econ)
    from_econ = select("cold_econ_unavailable", available, from_econ, states["mechanical"])
    from_integrated = select(
        "cold_integrated_released", integrated_release, states["economizer"], states["integrated"]
    )
    from_integrated = select(
        "cold_integrated_unavailable", available, from_integrated, states["mechanical"]
    )
    from_mech = select("cold_mech_released", mech_release, states["idle"], states["mechanical"])
    from_mech = select("cold_mech_to_integrated", available, states["integrated"], from_mech)
    next_state = idle
    for name, branch in (
        ("economizer", from_econ),
        ("integrated", from_integrated),
        ("mechanical", from_mech),
    ):
        next_state = select("select_cold_" + name, was[name], branch, next_state)
    next_state = select("cold_state_next", ready, next_state, states["idle"])
    wire(next_state, state)
    selected = {
        name: binary("cold_" + name + "_selected", "Equal", next_state, states[name], boolean=True)
        for name in ("economizer", "integrated", "mechanical")
    }
    cooling = all_of(
        "cooling_active",
        ready,
        gate("mechanical_state_selected", "Or", selected["integrated"], selected["mechanical"]),
    )
    economizing = all_of("economizer_active", ready, selected["economizer"])
    hot_command = pi(
        "hot_loop",
        "hot_deck_setpoint",
        "hot_deck_temperature",
        hot_active,
        value.hot_kp,
        value.hot_ki,
        False,
    )
    cool_command = pi(
        "cold_loop",
        "cold_deck_setpoint",
        "cold_deck_temperature",
        cooling,
        value.cold_kp,
        value.cold_ki,
        True,
    )
    econ_command = (
        pi(
            "economizer_loop",
            "cold_deck_setpoint",
            "cold_deck_temperature",
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
        (hot_command, old_hot),
        (cool_command, old_cool),
        (econ_command, old_econ),
        (mad, old_mad),
    ):
        wire(current, previous)
    output("hot_heating_valve", hot_command, "%")
    output("cold_cooling_valve", cool_command, "%")
    output("mixing_damper", mad, "%", label="Common damper command; not measured outdoor airflow")
    output(
        "cold_deck_state",
        next_state,
        label="Authored cold state:0idle1economizer2integrated3mechanical",
    )
    output("hot_heating_active", hot_active, boolean=True)
    output("cold_mechanical_active", cooling, boolean=True)
    output("cold_economizer_active", economizing, boolean=True)
    if len(nodes) > LIMITS["generated_nodes"]:
        raise ValueError("Generated MADD-MZ AHU graph exceeds its bounded node profile.")
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
        description="Authored AHU-only independent hot/cold decks with concurrent heating/cooling. Position is not outdoor airflow. Bad required-input quality retains prior committed outputs; no physical shutdown/native/code acceptance.",
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
            "application": "madd-mz-ahu-only",
            "native_deployment_verified": False,
            "compliance": "Uncertified authored sequence",
            "madd_mz_ahu_wizard": metadata,
        },
    )


def preview(body: PreviewRequest):
    program = generate(body.choices)
    diagnostics = [item.model_dump(exclude_none=True) for item in validate(program)]
    metadata = program.metadata["madd_mz_ahu_wizard"]
    return {
        "format": "bms.madd-mz-ahu-wizard-preview",
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
        project_id="new-madd-mz-ahu-project", name="Independent hot/cold deck AHU", economizer="off"
    )
    defaults = choice_document(base)
    defaults["economizer"] = ""
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
        branches[unit] = {"economizers": {"off": None, **examples}}
    return {
        "format": "bms.madd-mz-ahu-wizard-catalog",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "defaults": defaults,
        "limits": LIMITS,
        "choices_schema": Choices.model_json_schema(),
        "branch_defaults": branches,
    }


def madd_mz_ahu_router():
    router = APIRouter(prefix="/api/madd-mz-ahu-wizard")

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
                "Content-Disposition": 'attachment; filename="madd-mz-ahu-review.json"',
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
