"""Illustrative VAV control graphs, not Title 24 certified sequences."""

from .models import Edge, Node, Program, Target


def vav(variant="cooling-only", family="universal-runtime"):
    if variant not in ("cooling-only", "inline-reheat", "parallel-fan-reheat"):
        raise ValueError("Unknown VAV variant.")
    if family not in ("universal-runtime", "johnson-fx", "johnson-metasys"):
        raise ValueError("Unknown controller family.")
    nodes = []
    edges = []

    def node(id, kind, label, x, y, params=None, unit="", value_type="number"):
        nodes.append(
            Node(
                id=id,
                kind=kind,
                label=label,
                x=x,
                y=y,
                params=params or {},
                unit=unit,
                value_type=value_type,
            )
        )
        return id

    def wire(a, b, port="in"):
        edges.append(Edge(id=f"{a}_{b}_{port}", source=a, target=b, target_port=port))

    node("zone", "Input", "Zone temperature", 40, 90, {"default": 74}, "degF")
    node("cool_sp", "Constant", "Cooling setpoint", 40, 250, {"value": 72}, "degF")
    node(
        "cool_loop",
        "PI",
        "Cooling demand",
        360,
        140,
        {"kp": 20, "ki": 0.1, "reverse": True},
        "%",
    )
    wire("zone", "cool_loop", "measured")
    wire("cool_sp", "cool_loop", "setpoint")
    node(
        "min_flow",
        "Scale",
        "Damper position mapping",
        650,
        140,
        {"in_min": 0, "in_max": 100, "out_min": 20, "out_max": 100},
        "%",
    )
    node("damper", "Output", "Damper command", 960, 140, unit="%")
    wire("cool_loop", "min_flow")
    wire("min_flow", "damper")
    if variant != "cooling-only":
        node("heat_sp", "Constant", "Heating setpoint", 40, 440, {"value": 68}, "degF")
        node("heat_loop", "PI", "Heating demand", 360, 440, {"kp": 20, "ki": 0.1}, "%")
        node("reheat", "Output", "Reheat valve", 960, 440, unit="%")
        wire("zone", "heat_loop", "measured")
        wire("heat_sp", "heat_loop", "setpoint")
        wire("heat_loop", "reheat")
    if variant == "parallel-fan-reheat":
        node(
            "fan_enable",
            "Deadband",
            "Fan hysteresis",
            650,
            680,
            {"on": 5, "off": 1},
            unit="",
        )
        node(
            "heat_signal",
            "Scale",
            "Heat demand ratio",
            360,
            680,
            {"in_min": 0, "in_max": 100, "out_min": 0, "out_max": 100},
            unit="",
        )
        node("fan", "Output", "Parallel fan", 960, 680, value_type="boolean")
        wire("heat_loop", "heat_signal")
        wire("heat_signal", "fan_enable")
        wire("fan_enable", "fan")
    model = (
        "FX-PCV1630-0"
        if family == "johnson-fx"
        else "MS-VMA1630-0"
        if family == "johnson-metasys"
        else ""
    )
    return Program(
        id=f"{family}-{variant}",
        name=f"{variant.replace('-', ' ').title()} · {family.replace('johnson-', '').upper()}",
        description="Illustrative control and simulation template. Does not implement a complete Guideline 36 sequence and is not a Title 24 compliance claim. Verify design airflow, heating interlocks, fan proof, discharge limits, ventilation, occupancy and target firmware before deployment.",
        target=Target(family=family, model=model),
        nodes=nodes,
        edges=edges,
        metadata={
            "application": variant,
            "compliance": "Uncertified illustrative sequence",
            "native_deployment_verified": False,
        },
    )


def all_templates():
    return [
        vav(v, f)
        for f in ("universal-runtime", "johnson-fx", "johnson-metasys")
        for v in ("cooling-only", "inline-reheat", "parallel-fan-reheat")
    ]
