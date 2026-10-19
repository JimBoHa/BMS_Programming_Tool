"""Documented block contracts used by validation, UI, and runtime."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Block:
    title: str
    category: str
    inputs: tuple[str, ...] = ()
    output: str = "number"
    parameters: dict = field(default_factory=dict)
    help: str = ""
    stateful: bool = False


BLOCKS = {
    "Input": Block(
        "Input",
        "I/O",
        parameters={"default": 0, "terminal": ""},
        help="Named input. A disconnected/open-circuit simulation produces bad quality; it does not create a physical sensor.",
    ),
    "Output": Block(
        "Output",
        "I/O",
        ("in",),
        "same",
        {"terminal": ""},
        "Named result, published only after a successful complete scan.",
    ),
    "Constant": Block("Constant", "I/O", parameters={"value": 0}),
    "Add": Block("Add", "Math", ("a", "b")),
    "Subtract": Block("Subtract", "Math", ("a", "b")),
    "Multiply": Block("Multiply", "Math", ("a", "b")),
    "Divide": Block(
        "Divide",
        "Math",
        ("a", "b"),
        help="Division by zero fails the scan without changing retained outputs.",
    ),
    "Min": Block("Minimum", "Math", ("a", "b")),
    "Max": Block("Maximum", "Math", ("a", "b")),
    "Abs": Block("Absolute", "Math", ("in",)),
    "Clamp": Block("Clamp", "Math", ("in",), parameters={"min": 0, "max": 100}),
    "Scale": Block(
        "Linear scale",
        "Math",
        ("in",),
        parameters={
            "in_min": 0,
            "in_max": 100,
            "out_min": 0,
            "out_max": 100,
            "clamp": True,
        },
        help="Explicit engineering-unit scaling. Converts between different declared units.",
    ),
    "Convert": Block(
        "Temperature conversion",
        "Math",
        ("in",),
        parameters={"from": "degF", "to": "degC"},
        help="Absolute temperatures; never use this block for temperature differences.",
    ),
    "Greater": Block("Greater than", "Logic", ("a", "b"), "boolean"),
    "Less": Block("Less than", "Logic", ("a", "b"), "boolean"),
    "Equal": Block("Equal", "Logic", ("a", "b"), "boolean"),
    "And": Block("AND", "Logic", ("a", "b"), "boolean"),
    "Or": Block("OR", "Logic", ("a", "b"), "boolean"),
    "Not": Block("NOT", "Logic", ("in",), "boolean"),
    "Switch": Block("Select", "Logic", ("select", "on", "off"), "same"),
    "Delay": Block(
        "One-scan memory",
        "Control",
        ("in",),
        "same",
        {"initial": 0},
        "Explicit feedback boundary. Publishes previous scan's input.",
        True,
    ),
    "PI": Block(
        "PI controller",
        "Control",
        ("setpoint", "measured"),
        parameters={"kp": 1, "ki": 0.1, "min": 0, "max": 100, "reverse": False},
        help="Euler integral, conditional anti-windup, bounded output. Error = setpoint minus measured; reverse negates it.",
        stateful=True,
    ),
    "Deadband": Block(
        "Hysteresis",
        "Control",
        ("in",),
        "boolean",
        {"on": 1, "off": 0, "initial": False},
        "Switches on at the upper threshold and off at the lower threshold.",
        True,
    ),
    "TimerOn": Block(
        "On-delay timer",
        "Control",
        ("in",),
        "boolean",
        {"seconds": 10},
        "Continuous true input must persist for the configured seconds. False immediately resets the timer.",
        True,
    ),
    "Slew": Block(
        "Rate limiter",
        "Control",
        ("in",),
        parameters={"rate": 1, "initial": 0},
        help="Maximum engineering units per second.",
        stateful=True,
    ),
    "Alarm": Block(
        "Alarm threshold",
        "Supervision",
        ("in",),
        "boolean",
        {"limit": 100, "delay": 0},
        "High alarm with continuous on-delay. Included in scan history.",
        True,
    ),
    "Schedule": Block(
        "Calendar schedule",
        "Supervision",
        output="boolean",
        parameters={
            "start": "08:00",
            "end": "18:00",
            "days": [0, 1, 2, 3, 4],
            "timezone": "",
            "exceptions": [],
        },
        help='Monday=0. Optional IANA timezone and dated exceptions replace the whole local day. Overnight periods belong to their start date. DST repeated minutes run twice; skipped minutes never run. Example exception: [{"date":"2026-12-25","enabled":false}].',
    ),
}


def catalog():
    return [{"kind": k, **asdict(v)} for k, v in BLOCKS.items()]
