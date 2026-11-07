"""Opt-in ordinary-graph VAV setpoint ranges and authored thermal deadband policy."""

from pydantic import Field, model_validator

from .models import Edge, StrictModel

PROFILE = "portable-vav-setpoint-guard/1"
EPSILON_F = 1e-9
REFERENCE = {
    "title": "2025 Building Energy Efficiency Standards",
    "document": "CEC-400-2025-010-F",
    "edition": "July 2025",
    "url": "https://www.energy.ca.gov/sites/default/files/2025-07/CEC-400-2025-010-F_0.pdf",
    "sha256": "83c43852d3b72e89386fabdb7562b3dd077df90a7bec0b4c332fdae833f8afaa",
    "pdf_pages": [235, 236],
    "sections": ["120.2(b)1-3", "120.2(b)3 exceptions"],
    "scope": "Thermostatic capability/deadband reference, including exceptions; not complete VAV logic, project applicability or code certification.",
}
RULES = {
    "profile": PROFILE,
    "families": ["cooling-only", "inline-reheat", "parallel-fan-reheat"],
    "range": "Inclusive declared absolute setpoint bounds. Raw values must equal their clamped copies.",
    "deadband": "Reheat requires non-descending bounded heating/cooling setpoints and declared minimum gap, with 1e-9 delta-degF equivalent binary64 gap tolerance. Cooling-only uses only cooling range.",
    "thermal_modes": "Cooling only above its checked setpoint; heating only below its checked setpoint. No thermal demand inside the band or with invalid configuration.",
    "integral": "Inhibited temperature PI sees identical bounded setpoint/measured values; its integral holds. Its output is gated to zero. Airflow PI continues to the declared minimum request.",
    "fan": "Parallel fan receives gated heating demand; zero demand resets the existing nonnegative hysteresis off threshold.",
    "quality": "Ordinary whole-scan bad-quality/fault handling retains prior committed outputs and diagnostics. This adds no physical fail-safe or native reliability behavior.",
    "references": [REFERENCE],
    "native_compile": False,
    "controller_writes": False,
    "code_certified": False,
}


class SetpointGuardChoices(StrictModel):
    minimum: float = Field(default=50, strict=True, ge=-1000, le=1000)
    maximum: float = Field(default=90, strict=True, ge=-1000, le=1000)
    minimum_deadband: float = Field(default=5, strict=True, ge=0, le=2000)

    @model_validator(mode="after")
    def coherent(self):
        if self.minimum >= self.maximum:
            raise ValueError("Setpoint guard minimum must be below its maximum.")
        if self.minimum_deadband > self.maximum - self.minimum:
            raise ValueError("Setpoint guard deadband exceeds its declared range.")
        return self


def epsilon(unit):
    return EPSILON_F if unit == "degF" else EPSILON_F * 5 / 9


def defaults(unit):
    return (
        SetpointGuardChoices().model_dump()
        if unit == "degF"
        else {
            "minimum": (50 - 32) * 5 / 9,
            "maximum": (90 - 32) * 5 / 9,
            "minimum_deadband": 5 * 5 / 9,
        }
    )


def validate_guard(value):
    guard = value.setpoint_guard
    if guard is None:
        return
    if value.equipment not in RULES["families"]:
        raise ValueError("This setpoint guard belongs to the three single-duct VAV families.")
    if not guard.minimum <= value.cooling_setpoint <= guard.maximum:
        raise ValueError("Nominal cooling setpoint is outside the declared guard range.")
    if value.equipment != "cooling-only" and (
        not guard.minimum <= value.heating_setpoint <= guard.maximum
        or value.cooling_setpoint - value.heating_setpoint + epsilon(value.temperature_unit)
        < guard.minimum_deadband
    ):
        raise ValueError(
            "Nominal heating/cooling setpoints do not meet the declared range/deadband."
        )


def apply_guard(value, nodes, edges, node, wire):
    """Append editable ordinary blocks; rewrite only the selected temperature loop wiring."""
    guard = value.setpoint_guard
    if guard is None:
        return
    unit = value.temperature_unit
    reheat = value.equipment != "cooling-only"
    loops = ["cool"] + (["heat"] if reheat else [])
    # Rewrite original wires before adding guard wires so the PI-to-gate wire
    # cannot accidentally become a self-link.
    changed = []
    for edge in edges:
        if any(
            edge.target == part + "_loop" and edge.target_port in ("setpoint", "measured")
            for part in loops
        ):
            continue
        source = (
            "spguard_" + edge.source.replace("_loop", "_demand")
            if edge.source in [part + "_loop" for part in loops]
            else edge.source
        )
        changed.append(
            edge
            if source == edge.source
            else Edge(
                **{
                    **edge.model_dump(),
                    "id": f"{source}_{edge.target}_{edge.target_port}",
                    "source": source,
                }
            )
        )
    edges[:] = changed
    row = 0

    def add(key, kind, label, params=None, engineering_unit="", typ="number"):
        nonlocal row
        row += 1
        name = "spguard_" + key
        node(
            name,
            kind,
            label,
            40 + ((row - 1) % 4) * 340,
            1040 + ((row - 1) // 4) * 180,
            params,
            engineering_unit,
            typ,
        )
        return name

    def binary(key, kind, a, b, *, engineering_unit="", params=None):
        name = add(
            key,
            kind,
            key.replace("_", " "),
            params,
            engineering_unit,
            "boolean" if kind in ("Equal", "Less", "Greater", "And") else "number",
        )
        wire(a, name, "a")
        wire(b, name, "b")
        return name

    def invert(key, source):
        name = add(key, "Not", key.replace("_", " "), typ="boolean")
        wire(source, name)
        return name

    bounded, ranged = {}, {}
    for part in loops:
        bounded[part] = add(
            part + "_bounded",
            "Clamp",
            "Bounded " + part + " setpoint copy",
            {"min": guard.minimum, "max": guard.maximum},
            unit,
        )
        wire(part + "_sp", bounded[part])
        ranged[part] = binary(part + "_in_range", "Equal", part + "_sp", bounded[part])
    valid = ranged["cool"]
    if reheat:
        span = binary(
            "checked_gap",
            "TemperatureDifference",
            bounded["cool"],
            bounded["heat"],
            engineering_unit="delta-" + unit,
            params={"unit": unit},
        )
        minimum = add(
            "required_gap",
            "Constant",
            "Declared minimum gap with binary64 tolerance",
            {"value": max(0, guard.minimum_deadband - epsilon(unit))},
            "delta-" + unit,
        )
        gap_ok = invert("gap_accepted", binary("gap_too_small", "Less", span, minimum))
        order_ok = invert(
            "ordered", binary("reversed_setpoints", "Less", bounded["cool"], bounded["heat"])
        )
        valid = binary("ranges_accepted", "And", ranged["cool"], ranged["heat"])
        valid = binary(
            "gap_and_order_accepted", "And", valid, binary("ordered_gap", "And", gap_ok, order_ok)
        )
    valid_out = add(
        "configuration_valid",
        "Output",
        "Setpoint configuration accepted on last completed scan",
        typ="boolean",
    )
    wire(valid, valid_out)
    zero = add("zero_demand", "Constant", "Inhibited thermal demand", {"value": 0}, "%")
    for part in loops:
        demand = binary(
            part + "_zone_request", "Greater" if part == "cool" else "Less", "zone", bounded[part]
        )
        allowed = binary(part + "_permitted", "And", valid, demand)
        diagnostic = add(
            part + "_permitted_output",
            "Output",
            part.title() + " thermal mode on last completed scan",
            typ="boolean",
        )
        wire(allowed, diagnostic)
        measured = add(
            part + "_measured",
            "Switch",
            "Hold " + part + " PI integral when inhibited",
            engineering_unit=unit,
        )
        wire(allowed, measured, "select")
        wire("zone", measured, "on")
        wire(bounded[part], measured, "off")
        wire(measured, part + "_loop", "measured")
        wire(bounded[part], part + "_loop", "setpoint")
        # This stable ID is the source used by original outgoing loop wires.
        gated = "spguard_" + part + "_demand"
        node(
            gated,
            "Switch",
            "Permitted " + part + " demand",
            1420,
            1040 + loops.index(part) * 180,
            unit="%",
        )
        wire(allowed, gated, "select")
        wire(part + "_loop", gated, "on")
        wire(zero, gated, "off")
