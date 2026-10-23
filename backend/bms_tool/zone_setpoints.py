"""Editable authored effective-zone-target composition, without unit commands."""

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
    "pdf_pages": [753, 754, 755, 756, 854, 855, 1129, 1130],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
    "training": {
        "title": "ASHRAE Guideline 36 Presentation",
        "edition": "2021-06",
        "pdf_pages": [5],
        "sha256": "075565f9664a80f9720ae68c1020c84cb08ad12aaaa7aef5d329ad4ac2d9ed3d",
    },
    "scope": "Separate occupied/unoccupied heating/cooling targets, timed occupied-but-unpopulated offset and higher-priority window target pair qualify this authored portable compositor. Native occupancy hierarchy, hidden module logic and complete unit operating/airflow policies are not reproduced.",
    "ambiguities": [
        "Native C/F default pairs are rounded and are not exact conversions. The training slide omits explicit units; reference presets here start in F and convert as chosen values.",
        "Legacy separate Standby presets and the G36 timed unpopulated offset are distinct layers; this profile uses the latter only.",
        "The WindowOpen attribute description mentions airflows in a setpoint module. No airflow command or physical protection is inferred.",
    ],
}
GAPS = [
    "native CAF, sensor/network object allocation, MV enumeration, compiler/packages, transfer and physical acceptance",
    "demand-limit levels/stacking and local-adjustment freeze; hardware/network adjustment arbitration and fallback",
    "occupancy overrides, bypass/temporary occupancy and warmup/cooldown/setup/setback/freeze zone-group arbitration",
    "equipment enable, unoccupied operation, airflow/ventilation, actuator/sensor verification and hardware safety",
    "canonical unit-invariant nonlinear execution or complete Guideline36/Title24 acceptance",
]
LIMITS = {
    "absolute_celsius": [-50, 100],
    "scan_seconds": [1, 60],
    "timing_seconds": [1, 3600],
    "generated_nodes": 80,
}
PROFILE = {
    "profile": "studio-zone-effective-setpoints/1",
    "source": SOURCE,
    "limits": LIMITS,
    "gaps": GAPS,
    "semantics": {
        "base": "One scheduled_occupied Boolean selects fixed declared occupied or unoccupied heating/cooling pairs; no native mode enumeration or equipment enable inferred.",
        "population": "Optional separate populated Boolean. Continuous occupied/unpopulated entry dwell activates a deadband-expanding delta; active delta clears after full continuous populated release dwell or immediately on unoccupied. Initial memory/timers false/zero.",
        "window": "Optional window_open Boolean selects its absolute pair above both base and population delta. Population timers continue behind the window override; closing the window reveals current state. That timer policy is explicitly authored.",
        "diagnostics": "population_setback_ready is latent timed state even behind window; population_offset_applied means delta actually selected. Profile codes0unoccupied1occupied2occupied-offset3window are authored, not native enums.",
        "clock_quality": "Positive whole-second scan/aligned timers; first successful scan represents one elapsed interval. Bad required quality rolls back the complete transaction, including targets/timers even during window override. No physical shutdown claim.",
        "units": "All fixed absolute pairs and population delta convert together. Reference F presets convert as values rather than substituting rounded vendor C defaults. Existing binary64/core and REAL/native policies remain; no general unit-invariant trajectory or physical-range guarantee.",
    },
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
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
Flag = Annotated[bool, Field(strict=True)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=3600)]


class Population(StrictModel):
    offset: Annotated[float, Field(strict=True, gt=0, le=180)] = 1
    entry_seconds: Seconds = 300
    release_seconds: Seconds = 60
    populated_default: Flag = True


class Window(StrictModel):
    heating_setpoint: Temperature = 40
    cooling_setpoint: Temperature = 120
    open_default: Flag = False


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    name: str = Field(min_length=1, max_length=200)
    family: Literal["universal-runtime", "johnson-fx", "johnson-metasys"] = "universal-runtime"
    model: str = Field(default="", max_length=80)
    firmware: str = Field(default="", max_length=80)
    release_mode: str = Field(default="", max_length=80)
    temperature_unit: Literal["degF", "degC"] = "degF"
    occupied_heating_setpoint: Temperature = 70
    occupied_cooling_setpoint: Temperature = 74
    unoccupied_heating_setpoint: Temperature = 61
    unoccupied_cooling_setpoint: Temperature = 82
    population: Literal["off", "timed-offset"]
    population_control: Population | None = None
    window: Literal["off", "absolute-pair"]
    window_control: Window | None = None
    scheduled_occupied_default: Flag = False
    scan_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 1

    @model_validator(mode="after")
    def coherent(self):
        if not self.name.strip() or any(not c.isprintable() for c in self.name):
            raise ValueError("Program name requires visible printable text.")
        if (self.population != "off") != (self.population_control is not None):
            raise ValueError(
                "Population branch requires explicit matching controls; off cannot carry them."
            )
        if (self.window != "off") != (self.window_control is not None):
            raise ValueError(
                "Window branch requires explicit matching controls; off cannot carry them."
            )
        pairs = [
            (self.occupied_heating_setpoint, self.occupied_cooling_setpoint),
            (self.unoccupied_heating_setpoint, self.unoccupied_cooling_setpoint),
        ]
        if self.population_control:
            p = self.population_control
            if p.entry_seconds % self.scan_seconds or p.release_seconds % self.scan_seconds:
                raise ValueError("Population timings require whole multiples of the declared scan.")
            pairs.append(
                (
                    self.occupied_heating_setpoint - p.offset,
                    self.occupied_cooling_setpoint + p.offset,
                )
            )
        if self.window_control:
            pairs.append(
                (self.window_control.heating_setpoint, self.window_control.cooling_setpoint)
            )
        for heating, cooling in pairs:
            if heating >= cooling:
                raise ValueError("Every reachable heating target must be below its cooling target.")
            for value in (heating, cooling):
                celsius = value if self.temperature_unit == "degC" else (value - 32) * 5 / 9
                if not -50 <= celsius <= 100:
                    raise ValueError(
                        "Every reachable target must be within -50..100 Celsius equivalents."
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

        def absolute(number):
            return (number - 32) * 5 / 9 if temperature_unit == "degC" else number * 9 / 5 + 32

        for field in (
            "occupied_heating_setpoint",
            "occupied_cooling_setpoint",
            "unoccupied_heating_setpoint",
            "unoccupied_cooling_setpoint",
        ):
            data[field] = absolute(data[field])
        if data["window_control"]:
            for field in ("heating_setpoint", "cooling_setpoint"):
                data["window_control"][field] = absolute(data["window_control"][field])
        if data["population_control"]:
            data["population_control"]["offset"] *= 5 / 9 if temperature_unit == "degC" else 9 / 5
    data["temperature_unit"] = temperature_unit
    return Choices.model_validate(data)


def generate(value: Choices):
    nodes, edges = [], []
    absolute, delta = value.temperature_unit, "delta-" + value.temperature_unit

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
                x=40 + 280 * (index % 6),
                y=60 + 140 * (index // 6),
            )
        )
        return identifier

    def wire(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def gate(identifier, kind, a, b=None):
        node(identifier, kind, boolean=True)
        if b is None:
            wire(a, identifier)
        else:
            wire(a, identifier, "a")
            wire(b, identifier, "b")
        return identifier

    def select(identifier, condition, on, off, unit="", boolean=False):
        node(identifier, "Switch", unit=unit, boolean=boolean)
        for port, source in (("select", condition), ("on", on), ("off", off)):
            wire(source, identifier, port)
        return identifier

    def constant(identifier, number, unit="", boolean=False):
        return node(identifier, "Constant", {"value": number}, unit, boolean)

    def offset(identifier, base, difference):
        node(
            identifier, "TemperatureOffset", {"unit": absolute, "difference_unit": delta}, absolute
        )
        wire(base, identifier, "base")
        wire(difference, identifier, "difference")
        return identifier

    def timer(identifier, source, seconds):
        node(identifier, "TimerOn", {"seconds": seconds}, boolean=True)
        wire(source, identifier)
        return identifier

    def output(identifier, source, unit="", boolean=False, label=None):
        node(identifier, "Output", unit=unit, boolean=boolean, label=label)
        wire(source, identifier)

    false = constant("false", False, boolean=True)
    delta_zero = constant("zero_delta", 0, delta)
    node("scheduled_occupied", "Input", {"default": value.scheduled_occupied_default}, boolean=True)
    for identifier, number in (
        ("occupied_heating", value.occupied_heating_setpoint),
        ("occupied_cooling", value.occupied_cooling_setpoint),
        ("unoccupied_heating", value.unoccupied_heating_setpoint),
        ("unoccupied_cooling", value.unoccupied_cooling_setpoint),
    ):
        constant(identifier, number, absolute)
    setback = false
    selected_heat, selected_cool = "occupied_heating", "occupied_cooling"
    applied_delta = delta_zero
    if value.population_control:
        p = value.population_control
        node("populated", "Input", {"default": p.populated_default}, boolean=True)
        previous = node("previous_population_setback", "Delay", {"initial": False}, boolean=True)
        enter = timer(
            "population_entry_elapsed",
            gate(
                "occupied_unpopulated",
                "And",
                "scheduled_occupied",
                gate("not_populated", "Not", "populated"),
            ),
            p.entry_seconds,
        )
        populated = gate("occupied_populated", "And", "scheduled_occupied", "populated")
        leave = timer(
            "population_release_elapsed",
            gate("release_timing", "And", previous, populated),
            p.release_seconds,
        )
        retained = gate(
            "retain_population_setback", "And", previous, gate("release_not_elapsed", "Not", leave)
        )
        setback = gate(
            "population_setback_next",
            "And",
            "scheduled_occupied",
            gate("enter_or_retain", "Or", enter, retained),
        )
        wire(setback, previous)
        positive = constant("population_positive_delta", p.offset, delta)
        negative = constant("population_negative_delta", -p.offset, delta)
        selected_heat = select(
            "population_heating_selection",
            setback,
            offset("population_heating", "occupied_heating", negative),
            "occupied_heating",
            absolute,
        )
        selected_cool = select(
            "population_cooling_selection",
            setback,
            offset("population_cooling", "occupied_cooling", positive),
            "occupied_cooling",
            absolute,
        )
        applied_delta = select("population_delta_selection", setback, positive, delta_zero, delta)
    heating = select(
        "base_heating_selection",
        "scheduled_occupied",
        selected_heat,
        "unoccupied_heating",
        absolute,
    )
    cooling = select(
        "base_cooling_selection",
        "scheduled_occupied",
        selected_cool,
        "unoccupied_cooling",
        absolute,
    )
    window = false
    if value.window_control:
        node("window_open", "Input", {"default": value.window_control.open_default}, boolean=True)
        window = "window_open"
        heating = select(
            "window_heating_selection",
            window,
            constant("window_heating", value.window_control.heating_setpoint, absolute),
            heating,
            absolute,
        )
        cooling = select(
            "window_cooling_selection",
            window,
            constant("window_cooling", value.window_control.cooling_setpoint, absolute),
            cooling,
            absolute,
        )
    no_window = gate("window_closed", "Not", window)
    applied = gate("population_applied", "And", setback, no_window)
    applied_delta = select("visible_population_delta", window, delta_zero, applied_delta, delta)
    mode = select(
        "base_profile",
        "scheduled_occupied",
        constant("profile_occupied", 1),
        constant("profile_unoccupied", 0),
    )
    mode = select("population_profile", setback, constant("profile_population", 2), mode)
    mode = select("window_profile", window, constant("profile_window", 3), mode)
    output("effective_heating_setpoint", heating, absolute)
    output("effective_cooling_setpoint", cooling, absolute)
    output(
        "occupied_base_selected",
        gate("occupied_base_visible", "And", "scheduled_occupied", no_window),
        boolean=True,
    )
    output(
        "population_setback_ready",
        setback,
        boolean=True,
        label="Latent timed population state; may be hidden by window",
    )
    output("population_offset_applied", applied, boolean=True)
    output("window_override_active", window, boolean=True)
    output("applied_population_offset", applied_delta, delta)
    output(
        "setpoint_profile",
        mode,
        label="Authored profile:0unoccupied1occupied2occupied-offset3window",
    )
    if len(nodes) > LIMITS["generated_nodes"]:
        raise ValueError("Generated setpoint graph exceeds bounded node profile.")
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
        scan_seconds=value.scan_seconds,
        description="Authored occupied/unoccupied and optional population/window effective targets only. No unit enable, physical sensor/MV/airflow mapping, native JCI or compliance acceptance.",
        target=Target(
            family=value.family,
            model=value.model,
            firmware=value.firmware,
            release_mode=value.release_mode,
        ),
        nodes=nodes,
        edges=edges,
        metadata={
            "application": "zone-effective-setpoints",
            "native_deployment_verified": False,
            "compliance": "Uncertified authored setpoint composition",
            "zone_setpoint_wizard": metadata,
        },
    )


def preview(body: PreviewRequest):
    program = generate(body.choices)
    diagnostics = [d.model_dump(exclude_none=True) for d in validate(program)]
    meta = program.metadata["zone_setpoint_wizard"]
    return {
        "format": "bms.zone-setpoint-wizard-preview",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "choices": choice_document(body.choices),
        "choices_sha256": digest(choice_document(body.choices)),
        "program": program.model_dump(mode="json"),
        "program_sha256": program.digest(),
        "diagnostics": diagnostics,
        "can_create": not any(d["level"] == "error" for d in diagnostics),
        "inputs": meta["inputs"],
        "outputs": meta["outputs"],
        "inactive_choices": [],
        "native_compile": False,
        "controller_writes": False,
    }


def catalog_document():
    base = Choices(
        project_id="new-zone-setpoint-project",
        name="Zone effective targets",
        population="off",
        window="off",
    )
    defaults = choice_document(base) | {"population": "", "window": ""}
    branches = {}
    for unit in ("degF", "degC"):
        p = Choices.model_validate(
            base.model_dump()
            | {
                "population": "timed-offset",
                "population_control": Population().model_dump(),
                "window": "absolute-pair",
                "window_control": Window().model_dump(),
            }
        )
        converted = choice_document(convert_units(p, unit))
        branches[unit] = {
            "population": {"off": None, "timed-offset": converted["population_control"]},
            "window": {"off": None, "absolute-pair": converted["window_control"]},
        }
    return {
        "format": "bms.zone-setpoint-wizard-catalog",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "defaults": defaults,
        "limits": LIMITS,
        "choices_schema": Choices.model_json_schema(),
        "branch_defaults": branches,
    }


def zone_setpoint_router():
    router = APIRouter(prefix="/api/zone-setpoint-wizard")

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
                "Content-Disposition": 'attachment; filename="zone-setpoint-review.json"',
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
