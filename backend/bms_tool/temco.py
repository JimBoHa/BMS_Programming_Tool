"""Real Temco Control Basic source conversion and optional native verification.

All graph block types lower to real statements, with persistent private local
state and explicit host calendar flags. Arbitrary foreign state/jumps require a
different import profile. The optional manufacturer compiler and decode.c host
execute actual Temco bytecode locally; they do not connect to or download an
application into a controller.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .blocks import BLOCKS
from .calendar_schedule import compile_schedule
from .engine import Engine, execution_order, output_type, validate
from .macros import expand_macros
from .models import Edge, Node, Program, Target

UPSTREAM = "https://github.com/temcocontrols/T3000_Building_Automation_System"
PIN = "ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b"
STATEFUL = frozenset({"Delay", "PI", "Deadband", "TimerOn", "Slew", "Alarm"})
STATELESS = frozenset(
    {
        "Input",
        "Output",
        "Constant",
        "Add",
        "Subtract",
        "Multiply",
        "Divide",
        "Min",
        "Max",
        "Abs",
        "Clamp",
        "Scale",
        "Convert",
        "Greater",
        "Less",
        "Equal",
        "And",
        "Or",
        "Not",
        "Switch",
    }
)
SUPPORTED = frozenset(BLOCKS)
POINT = re.compile(
    r"(?:IN(?:[1-9]|[1-5][0-9]|6[0-4])|OUT(?:[1-9]|[1-5][0-9]|6[0-4])|VAR(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-6]))\Z"
)
NAME = re.compile(r"[A-Z][A-Z0-9_]{0,29}\Z")
TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d*)?|\.\d+)|([A-Za-z][A-Za-z0-9_]*)|(<>|<=|>=|[()+*/=,<>&-]))")
LIMIT = 2_000_000
RESERVED = frozenset(
    "AVG COM1 PIDPROP PIDRATE PIDRESET CLEARPORT DOW DOM DOY MOY INPUT INT INTERVAL LN LN_1 READNET OUTPUT POWER_LOSS SCANS SQR STATUS RUNTIME TBL TIME TIME_FORMAT TIME_ON TIME_OFF SCH_ON WR_ON SCH_OFF WR_OFF SENSOR_ON SENSOR_OFF UNACK USER_A USER_B SUNDAY MONDAY TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY JANUARY FEBRUARY MARCH APRIL MAY JUNE JULY AUGUST SEPTEMBER OCTOBER NOVEMBER DECEMBER MB_BLOCKREAD MB_BLOCKWRITE MB_BWCOIL PVAR SIN COS RGB ALARM ALARM_AT CALL CLEAR CLOSE DALARM DECLARE DISABLE ENABLE END FOR TO STEP GOSUB GOTO HANGUP IF ELSE LET MOD NEXT ON ON_ALARM ON_ERROR OPEN PHONE PRINT PRINT_AT REM REMOTE_GET REMOTE_SET RETURN RUN_MACRO SET_PRINTER START STOP WAIT XOR DIM INTEGER STRING BYTE FLOAT LONG ABS MIN MAX NOT AND OR THEN".split()
)


class TemcoError(ValueError):
    """A source or target semantic contract cannot be represented safely."""


def capabilities():
    return {
        "format": "temco-control-basic/2",
        "source_extension": ".bas",
        "source_url": UPSTREAM,
        "source_commit": PIN,
        "supported_blocks": sorted(SUPPORTED),
        "unsupported_blocks": sorted(BLOCKS.keys() - SUPPORTED),
        "numeric_resolution": 0.001,
        "literal_absolute_limit": LIMIT,
        "native_bytecode_limit": 1999,
        "maximum_source_lines": 180,
        "maximum_native_symbols": 400,
        "maximum_local_storage_bytes": 1800,
        "maximum_operand_postfix_bytes": 8,
        "maximum_statement_code_bytes": 400,
        "physical_io": "Explicit local IN1..64 / OUT1..64 / VAR1..256 bindings",
        "native_verification": "Manufacturer compiler and decode.c with simulated points",
        "limitations": [
            "Persistent local state advances by the declared scan_seconds per invocation; a physical host must provide that scan cadence.",
            "Schedules require explicit host-evaluated active/valid VAR bindings; an unbound calendar holds state and published outputs.",
            "Native arithmetic uses signed 32-bit fixed point; precision differs from the portable simulator.",
            "Input quality is unavailable in this source profile; commission physical sensor range and fault handling separately.",
            "Division guards retain published outputs when the divisor is zero.",
            "Controller download, hardware configuration and live physical execution are not implemented by this adapter.",
        ],
    }


def _literal(value):
    if type(value) is bool:
        return "1" if value else "0"
    try:
        valid = type(value) in (int, float) and abs(value) <= LIMIT and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise TemcoError(f"Control Basic literals must be finite and within ±{LIMIT}.")
    scaled = value * 1000
    if not math.isclose(scaled, round(scaled), abs_tol=1e-7, rel_tol=0):
        raise TemcoError(
            "Control Basic literals require increments of 0.001; conversion would lose precision."
        )
    return f"{value:.3f}".rstrip("0").rstrip(".") if value else "0"


def _bindings(program, bindings):
    bindings = {} if bindings is None else dict(bindings)
    interfaces = {n.id: n for n in program.nodes if n.kind in ("Input", "Output")}
    if bindings.keys() - interfaces.keys():
        raise TemcoError("Point bindings reference an unknown graph interface.")
    result = {}
    counts = {"Input": 0, "Output": 0}
    for node in interfaces.values():
        counts[node.kind] += 1
        default = ("IN" if node.kind == "Input" else "OUT") + str(counts[node.kind])
        point = bindings.get(node.id, default)
        if not isinstance(point, str) or not POINT.fullmatch(point):
            raise TemcoError("Use bare IN1..64, OUT1..64 or VAR1..256 point bindings.")
        if node.kind == "Input" and point.startswith("OUT"):
            raise TemcoError("Graph inputs bind to IN or VAR points.")
        if node.kind == "Output" and point.startswith("IN"):
            raise TemcoError("Graph outputs bind to OUT or VAR points.")
        result[node.id] = point
    if len(set(result.values())) != len(result):
        raise TemcoError("Every graph interface requires its own point binding.")
    return result


def _calendar_bindings(program, points):
    available = [f"VAR{i}" for i in range(256, 0, -1) if f"VAR{i}" not in points.values()]
    result = {}
    for node in program.nodes:
        if node.kind == "Schedule":
            if len(available) < 2:
                raise TemcoError("Schedules require two unused VAR points per calendar.")
            result[node.id] = {"active": available.pop(0), "valid": available.pop(0)}
    return result


def export_source(program: Program, *, bindings=None) -> str:
    """Lower a supported graph into actual numbered Control Basic statements."""
    original = program
    program = expand_macros(program)
    if "native_sedona" in program.metadata:
        raise TemcoError("Native Sedona extensions cannot be exported as Control Basic.")
    errors = [d.message for d in validate(program) if d.level == "error"]
    if errors:
        raise TemcoError("; ".join(errors))
    unsupported = {n.kind for n in program.nodes} - SUPPORTED
    if unsupported:
        raise TemcoError(
            "Control Basic profile does not support: " + ", ".join(sorted(unsupported))
        )
    points = _bindings(program, bindings)
    calendars = _calendar_bindings(program, points)
    nodes = {node.id: node for node in program.nodes}
    links = {(edge.target, edge.target_port): edge.source for edge in program.edges}
    names = {node.id: f"T{i + 1}" for i, node in enumerate(program.nodes)}
    lines = ["REM BMS STUDIO CONTROL BASIC PROFILE 2", "REM FIXED POINT 0.001 - LOCAL POINTS ONLY"]
    if any(node.kind in STATEFUL or node.kind == "Schedule" for node in program.nodes):
        # Standard REM comments preserve authoring state while the numbered body
        # remains real executable BASIC. Import regenerates and compares the
        # entire body before trusting these annotations. They are excluded from
        # native bytecode because controller memory is only 2 KB.
        payload = json.dumps(
            {
                "format": "bms-temco-authoring/2",
                "program": original.model_dump(mode="json"),
                "bindings": points,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        if len(payload) > 512000:
            raise TemcoError(
                "Control Basic authoring annotations exceed the 512 KB expanded limit."
            )
        encoded = base64.b64encode(zlib.compress(payload)).decode("ascii")
        lines += ["REM BMSIR2 " + encoded[i : i + 160] for i in range(0, len(encoded), 160)]
    for node in program.nodes:
        if output_type(node) == "boolean":
            lines.append("REM BOOL " + names[node.id])
            if node.kind in ("Input", "Output"):
                lines.append("REM BOOL " + points[node.id])
    for binding in calendars.values():
        lines.append(f"IF {binding['valid']} = 0 THEN END")
    initializers = []
    commits = []
    for index, node in enumerate(program.nodes, 1):
        if node.kind in STATEFUL:
            p = {**BLOCKS[node.kind].parameters, **node.params}
            initial = p.get("initial", 0)
            if initial:
                initializers.append(f"IF BMSINIT = 0 THEN S{index} = {_literal(initial)}")
            commits.append(f"S{index} = U{index}")
    lines += initializers
    for identifier in execution_order(program):
        node = nodes[identifier]
        kind = node.kind
        name = names[identifier]
        p = {**BLOCKS[kind].parameters, **node.params}
        index = program.nodes.index(node) + 1
        state, staged = f"S{index}", f"U{index}"
        interval = _literal(program.scan_seconds)

        def a(port, current=identifier):
            return names[links[(current, port)]]

        if kind == "Input":
            expression = points[identifier]
        elif kind == "Output":
            expression = a("in")
        elif kind == "Constant":
            expression = _literal(p["value"])
        elif kind in (
            "Add",
            "Subtract",
            "Multiply",
            "Divide",
            "Greater",
            "Less",
            "Equal",
            "And",
            "Or",
        ):
            operator = {
                "Add": "+",
                "Subtract": "-",
                "Multiply": "*",
                "Divide": "/",
                "Greater": ">",
                "Less": "<",
                "Equal": "=",
                "And": "AND",
                "Or": "OR",
            }[kind]
            if kind == "Divide":
                lines.append(f"IF {a('b')} = 0 THEN END")
            expression = f"{a('a')} {operator} {a('b')}"
        elif kind in ("Min", "Max"):
            expression = f"{kind.upper()}({a('a')}, {a('b')})"
        elif kind == "Abs":
            expression = f"ABS({a('in')})"
        elif kind == "Not":
            expression = f"NOT {a('in')}"
        elif kind == "Clamp":
            expression = f"MAX({_literal(p['min'])}, MIN({_literal(p['max'])}, {a('in')}))"
        elif kind == "Scale":
            ratio = f"(({a('in')} - {_literal(p['in_min'])}) / ({_literal(p['in_max'])} - {_literal(p['in_min'])}))"
            if p["clamp"]:
                ratio = f"MAX(0, MIN(1, {ratio}))"
            expression = f"{_literal(p['out_min'])} + ({ratio} * ({_literal(p['out_max'])} - {_literal(p['out_min'])}))"
            # When the gain is exactly representable, avoid quantizing a 0..1
            # intermediate before multiplying by the output span. A 0.001 ratio
            # error would otherwise become 0.08 units in a 20..100 VAV scale.
            try:
                gain = _literal((p["out_max"] - p["out_min"]) / (p["in_max"] - p["in_min"]))
            except TemcoError:
                pass
            else:
                expression = (
                    f"{_literal(p['out_min'])} + ({a('in')} - {_literal(p['in_min'])}) * {gain}"
                )
                if p["clamp"]:
                    lower, upper = sorted([p["out_min"], p["out_max"]])
                    expression = f"MAX({_literal(lower)}, MIN({_literal(upper)}, {expression}))"
        elif kind == "Convert":
            celsius = (
                f"(({a('in')} - 32) * 5 / 9)"
                if p["from"] == "degF"
                else f"({a('in')} - 273.15)"
                if p["from"] == "K"
                else a("in")
            )
            expression = (
                f"({celsius} * 9 / 5 + 32)"
                if p["to"] == "degF"
                else f"({celsius} + 273.15)"
                if p["to"] == "K"
                else celsius
            )
        elif kind == "Switch":
            lines.append(f"IF {a('select')} THEN {name} = {a('on')} ELSE {name} = {a('off')}")
            continue
        elif kind == "Delay":
            expression = state
        elif kind == "Deadband":
            lines.append(f"{staged} = {state}")
            lines.append(f"IF {a('in')} >= {_literal(p['on'])} THEN {staged} = 1")
            lines.append(f"IF {a('in')} <= {_literal(p['off'])} THEN {staged} = 0")
            # Upper threshold wins when thresholds coincide, as in Engine.
            if p["on"] == p["off"]:
                lines.append(f"IF {a('in')} >= {_literal(p['on'])} THEN {staged} = 1")
            expression = staged
        elif kind in ("TimerOn", "Alarm"):
            active = a("in") if kind == "TimerOn" else f"{a('in')} > {_literal(p['limit'])}"
            duration = _literal(p.get("seconds", p.get("delay")))
            # Saturation preserves timer outputs while avoiding rollover after
            # the fixed-point accumulator has run continuously for many days.
            lines.append(
                f"IF {active} THEN {staged} = MIN({duration}, {state} + {interval}) ELSE {staged} = 0"
            )
            expression = f"({active}) AND ({staged} >= {duration})"
        elif kind == "Slew":
            delta = f"({_literal(p['rate'])} * {interval})"
            expression = f"{state} + MAX(0 - {delta}, MIN({delta}, {a('in')} - {state}))"
            lines.append(f"{staged} = {expression}")
            expression = staged
        elif kind == "PI":
            error, candidate, raw = f"ER{index}", f"CA{index}", f"RA{index}"
            sign = "0 - " if p["reverse"] else ""
            lines.append(f"{error} = {sign}({a('setpoint')} - {a('measured')})")
            lines.append(f"{candidate} = {state} + {_literal(p['ki'])} * {error} * {interval}")
            lines.append(f"{raw} = {_literal(p['kp'])} * {error} + {candidate}")
            lower, upper, gain = _literal(p["min"]), _literal(p["max"]), _literal(p["ki"])
            condition = f"(({raw} >= {lower}) AND ({raw} <= {upper})) OR (({raw} > {upper}) AND ({error} * {gain} < 0)) OR (({raw} < {lower}) AND ({error} * {gain} > 0))"
            lines.append(f"IF {condition} THEN {staged} = {candidate} ELSE {staged} = {state}")
            expression = f"MAX({lower}, MIN({upper}, {_literal(p['kp'])} * {error} + {staged}))"
        elif kind == "Schedule":
            expression = calendars[identifier]["active"]
        else:
            raise TemcoError(f"Unsupported Control Basic block {kind}.")
        if output_type(node) == "boolean":
            lines.append(f"IF {expression} THEN {name} = 1 ELSE {name} = 0")
        else:
            lines.append(f"{name} = {expression}")
    for index, node in enumerate(program.nodes, 1):
        if node.kind == "Delay":
            lines.append(f"U{index} = {names[links[(node.id, 'in')]]}")
    # Publish only after every computation and division guard has succeeded.
    lines += [f"{points[n.id]} = {names[n.id]}" for n in program.nodes if n.kind == "Output"]
    lines += commits
    if initializers:
        lines.append("BMSINIT = 1")
    lines.append("END")
    source = "\r\n".join(f"{(i + 1) * 10} {line}" for i, line in enumerate(lines)) + "\r\n"
    _source_lines(source)
    return source


def _source_lines(source):
    if (
        not isinstance(source, str)
        or len(source.encode()) > 24000
        or not source.isascii()
        or "\0" in source
    ):
        raise TemcoError("Control Basic source must be ASCII text below 24 KB without NUL bytes.")
    rows = source.splitlines()
    if not rows or len(rows) > 180:
        raise TemcoError("Control Basic host accepts 1..180 numbered source lines.")
    result = []
    previous = 0
    for row in rows:
        match = re.fullmatch(r"([1-9][0-9]{0,3})[ \t]+(.{1,240})", row)
        if not match or int(match[1]) <= previous:
            raise TemcoError(
                "Source requires increasing unique line numbers and statements up to 240 characters."
            )
        previous = int(match[1])
        result.append((previous, match[2].strip()))
    return result


class _Reader:
    def __init__(self, booleans):
        self.nodes = []
        self.edges = []
        self.values = {}
        self.booleans = booleans
        self.written = []
        self.last_divisor = None
        self.current_guard = None

    def node(self, kind, sources=(), *, value=None, label="", boolean=False):
        identifier = f"n{len(self.nodes) + 1}"
        params = (
            {"value": value}
            if kind == "Constant"
            else {"default": False if boolean else 0}
            if kind == "Input"
            else {}
        )
        node = Node(
            id=identifier,
            kind=kind,
            label=label,
            params=params,
            value_type="boolean" if boolean else "number",
            x=(len(self.nodes) % 8) * 180,
            y=(len(self.nodes) // 8) * 100,
        )
        self.nodes.append(node)
        for port, source in zip(BLOCKS[kind].inputs, sources, strict=True):
            self.edges.append(
                Edge(
                    id=f"e{len(self.edges) + 1}",
                    source=source.id,
                    target=identifier,
                    target_port=port,
                )
            )
        return node

    def boolean(self, node):
        if output_type(node) == "boolean":
            return node
        zero = self.node("Constant", value=0)
        equal = self.node("Equal", [node, zero], boolean=True)
        return self.node("Not", [equal], boolean=True)

    def expression(self, expression):
        expression = expression.strip()
        if re.search(r"\b\d+-(?:IN|OUT|VAR)\d+\b", expression, flags=re.I):
            raise TemcoError(
                "Panel-prefixed native point references are outside the local point profile."
            )
        tokens = []
        position = 0
        while position < len(expression):
            match = TOKEN.match(expression, position)
            if not match:
                raise TemcoError("Unsupported Control Basic expression token.")
            tokens.append(next(v for v in match.groups() if v is not None).upper())
            position = match.end()
        operand_count = sum(
            bool(re.fullmatch(r"\d+(?:\.\d*)?|\.\d+", token))
            or bool(NAME.fullmatch(token) and token not in RESERVED)
            for token in tokens
        )
        if len(tokens) > 80 or operand_count > 16:
            raise TemcoError("Control Basic expression exceeds the bounded operand profile.")
        cursor = 0
        precedence = {"OR": 1, "AND": 2, "=": 3, "<": 3, ">": 3, "+": 4, "-": 4, "*": 5, "/": 5}
        binary = {
            "OR": "Or",
            "AND": "And",
            "=": "Equal",
            "<": "Less",
            ">": "Greater",
            "+": "Add",
            "-": "Subtract",
            "*": "Multiply",
            "/": "Divide",
        }

        def parse(minimum=0, depth=0):
            nonlocal cursor
            if depth > 8 or cursor >= len(tokens):
                raise TemcoError("Incomplete or overly nested Control Basic expression.")
            token = tokens[cursor]
            cursor += 1
            if token in ("-", "NOT"):
                operand = parse(6, depth + 1)
                left = (
                    self.node("Not", [self.boolean(operand)], boolean=True)
                    if token == "NOT"
                    else self.node("Subtract", [self.node("Constant", value=0), operand])
                )
            elif token == "(":
                left = parse(0, depth + 1)
                if cursor >= len(tokens) or tokens[cursor] != ")":
                    raise TemcoError("Unbalanced Control Basic parentheses.")
                cursor += 1
            elif re.fullmatch(r"\d+(?:\.\d*)?|\.\d+", token):
                value = float(token)
                _literal(value)
                left = self.node("Constant", value=value)
            elif token in ("ABS", "MIN", "MAX"):
                if cursor >= len(tokens) or tokens[cursor] != "(":
                    raise TemcoError("Control Basic functions require parentheses.")
                cursor += 1
                args = [parse(0, depth + 1)]
                if token != "ABS":
                    if cursor >= len(tokens) or tokens[cursor] != ",":
                        raise TemcoError("MIN/MAX require exactly two operands.")
                    cursor += 1
                    args.append(parse(0, depth + 1))
                if cursor >= len(tokens) or tokens[cursor] != ")":
                    raise TemcoError("Control Basic function argument mismatch.")
                cursor += 1
                left = self.node({"ABS": "Abs", "MIN": "Min", "MAX": "Max"}[token], args)
            elif NAME.fullmatch(token) and token not in RESERVED:
                if token not in self.values:
                    if token.startswith(("IN", "OUT", "VAR")) and not POINT.fullmatch(token):
                        raise TemcoError(
                            "Local point number exceeds the supported controller profile."
                        )
                    self.values[token] = self.node(
                        "Input", label=token, boolean=token in self.booleans
                    )
                left = self.values[token]
            else:
                raise TemcoError(f"Unsupported Control Basic expression {token!r}.")
            while (
                cursor < len(tokens)
                and tokens[cursor] in precedence
                and precedence[tokens[cursor]] >= minimum
            ):
                operator = tokens[cursor]
                cursor += 1
                right = parse(precedence[operator] + 1, depth + 1)
                if operator in ("AND", "OR"):
                    left, right = self.boolean(left), self.boolean(right)
                if operator == "/":
                    self.last_divisor = right.id
                left = self.node(
                    binary[operator],
                    [left, right],
                    boolean=operator in ("AND", "OR", "=", "<", ">"),
                )
            return left

        value = parse()
        if cursor != len(tokens):
            raise TemcoError("Unsupported or trailing Control Basic expression syntax.")
        return value

    def assignment(self, text):
        match = re.fullmatch(r"([A-Z][A-Z0-9_]{0,29})\s*=\s*(.+)", text, flags=re.I)
        if not match:
            raise TemcoError("Only assignments and bounded single-line selections are supported.")
        name = match[1].upper()
        if name in RESERVED:
            raise TemcoError("Control Basic native keywords cannot be assigned as local variables.")
        if name.startswith(("IN", "OUT", "VAR")) and not POINT.fullmatch(name):
            raise TemcoError("Invalid local point binding.")
        if name.startswith("IN") and POINT.fullmatch(name):
            raise TemcoError("The conversion profile does not assign to physical inputs.")
        return name, match[2]


def import_source(source: str) -> Program:
    """Parse a bounded native source subset into an executable editable graph.

    Arbitrary jumps, loops, remote I/O, time functions and stateful statements
    are rejected. Assignments use source-order SSA; native comments are retained
    as reference text and never treated as Python or other executable code.
    """
    rows = _source_lines(source)
    annotated = [statement[11:] for _, statement in rows if statement.startswith("REM BMSIR2 ")]
    if annotated:
        try:
            compressed = base64.b64decode("".join(annotated), validate=True)
            inflater = zlib.decompressobj()
            payload = inflater.decompress(compressed, 512001)
            if (
                len(payload) > 512000
                or inflater.unconsumed_tail
                or not inflater.eof
                or inflater.unused_data
            ):
                raise ValueError("Authoring metadata exceeds its bounded profile")
            document = json.loads(payload)
            if (
                set(document) != {"format", "program", "bindings"}
                or document["format"] != "bms-temco-authoring/2"
            ):
                raise ValueError("Unexpected authoring annotation")
            program = Program.model_validate(document["program"])
            expected = _source_lines(export_source(program, bindings=document["bindings"]))
            # Treat source case and newline differences as harmless, while all
            # executable expressions, point mappings and line numbers must match.
            if [(n, text.upper()) for n, text in rows] != [
                (n, text.upper()) for n, text in expected
            ]:
                raise ValueError("Executable source disagrees with its authoring annotations")
            return program
        except (ValueError, TypeError, KeyError, zlib.error) as exc:
            raise TemcoError(f"Invalid Control Basic authoring annotations: {exc}") from exc
    booleans = set()
    for _, statement in rows:
        match = re.fullmatch(r"REM BOOL ([A-Z][A-Z0-9_]{0,29})", statement, flags=re.I)
        if match:
            booleans.add(match[1].upper())
    reader = _Reader(booleans)
    ended = False
    guard = None
    for _, statement in rows:
        upper = statement.upper()
        if upper.startswith("REM ") or upper == "REM":
            continue
        if ended:
            raise TemcoError("Executable statements after END are outside this profile.")
        if upper == "END":
            if guard:
                raise TemcoError("Division guard has no matching calculation.")
            ended = True
            continue
        match = re.fullmatch(r"IF ([A-Z][A-Z0-9_]{0,29}) = 0 THEN END", upper)
        if match:
            if guard or match[1] not in reader.values:
                raise TemcoError("Division guards must immediately precede their calculation.")
            guard = reader.values[match[1]].id
            continue
        reader.last_divisor = None
        match = re.fullmatch(r"IF (.+) THEN (.+) ELSE (.+)", statement, flags=re.I)
        if match:
            name, when_on = reader.assignment(match[2])
            other, when_off = reader.assignment(match[3])
            if name != other:
                raise TemcoError(
                    "A single-line selection must assign the same variable on both branches."
                )
            condition = reader.boolean(reader.expression(match[1]))
            if name in booleans and when_on.strip() == "1" and when_off.strip() == "0":
                result = condition
            else:
                on, off = reader.expression(when_on), reader.expression(when_off)
                result = reader.node(
                    "Switch", [condition, on, off], boolean=output_type(on) == "boolean"
                )
        else:
            name, expression = reader.assignment(statement)
            result = reader.expression(expression)
            if name in booleans:
                result = reader.boolean(result)
        if guard and guard != reader.last_divisor:
            raise TemcoError("Division guard does not match the immediately following divisor.")
        guard = None
        reader.values[name] = result
        reader.written.append(name)
    if not ended or not reader.written:
        raise TemcoError("A Control Basic conversion requires assignments and a final END.")
    outputs = list(
        dict.fromkeys(
            name
            for name in reader.written
            if name.startswith(("OUT", "VAR")) and POINT.fullmatch(name)
        )
    )
    if not outputs:
        outputs = [reader.written[-1]]
    for name in outputs:
        result = reader.values[name]
        reader.node("Output", [result], label=name, boolean=output_type(result) == "boolean")
    program = Program(
        id="temco-import",
        name="Imported Control Basic",
        target=Target(family="temco-control-basic"),
        nodes=reader.nodes,
        edges=reader.edges,
        metadata={
            "conversion": {
                "source_format": "temco-control-basic",
                "profile": 1,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "review_required": True,
                "numeric_resolution": 0.001,
                "notes": capabilities()["limitations"],
            }
        },
    )
    errors = [d.message for d in validate(program) if d.level == "error"]
    if errors:
        raise TemcoError(
            "Source semantics require unsupported implicit coercion: " + "; ".join(errors)
        )
    return program


def _toolchain():
    default = (
        Path(__file__).resolve().parents[3]
        / "Reference_Sources/temcocontrols--T3000/build/bms-host"
    )
    home = Path(os.environ.get("BMS_TEMCO_HOME", default)).expanduser().resolve()
    try:
        manifest = json.loads((home / "manifest.json").read_text())
        if manifest["format"] != "bms-temco-host/1" or manifest["source_commit"] != PIN:
            raise ValueError("Unexpected source revision")
        for name in ("compiler", "vm"):
            if (
                hashlib.sha256((home / f"temco-{name}").read_bytes()).hexdigest()
                != manifest["binary_sha256"][name]
            ):
                raise ValueError("Native binary checksum mismatch")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TemcoError(
            "Native Temco reference is unavailable or unverified. Run scripts/setup_temco.py."
        ) from exc
    return home, manifest


def native_status():
    try:
        _, manifest = _toolchain()
        return {
            "available": True,
            "source_commit": PIN,
            "scope": manifest["scope"],
            "capabilities": capabilities(),
        }
    except TemcoError as exc:
        return {"available": False, "reason": str(exc), "capabilities": capabilities()}


def _compiler_bounds(source):
    """Bound upstream fixed tables before native prescan/code generation.

    local_table is a 4,000-byte region within a larger allocation, so spilling
    into the adjacent timer table is not an ASan allocation-boundary violation.
    Native MAX_OP is ten bytes per operand, including its zero terminator;
    cod_line is 450 bytes. Leave explicit room below both fixed capacities.
    """
    symbols = set()
    precedence = {
        "OR": 1,
        "AND": 2,
        "=": 3,
        "<>": 3,
        "<": 3,
        ">": 3,
        "<=": 3,
        ">=": 3,
        "+": 4,
        "-": 4,
        "*": 5,
        "/": 5,
    }

    def expression(text):
        tokens, position = [], 0
        text = text.strip()
        while position < len(text):
            match = TOKEN.match(text, position)
            if not match:
                raise TemcoError("Unsupported native compiler expression token.")
            tokens.append(next(v for v in match.groups() if v is not None).upper())
            position = match.end()
        cursor = 0

        def parse(minimum=0, depth=0):
            nonlocal cursor
            if cursor >= len(tokens) or depth > 20:
                raise TemcoError("Incomplete or overly nested native compiler expression.")
            token = tokens[cursor]
            cursor += 1
            if token in ("-", "NOT", "ABS"):
                if token == "ABS":
                    if cursor >= len(tokens) or tokens[cursor] != "(":
                        raise TemcoError("Malformed native function.")
                    cursor += 1
                    size, tail, peak, count = parse(0, depth + 1)
                    if cursor >= len(tokens) or tokens[cursor] != ")":
                        raise TemcoError("Malformed native function.")
                    cursor += 1
                else:
                    size, tail, peak, count = parse(6, depth + 1)
                result = size + 1, tail + 1, max(peak, tail + 1), count
            elif token in ("MIN", "MAX"):
                if cursor >= len(tokens) or tokens[cursor] != "(":
                    raise TemcoError("Malformed native function.")
                cursor += 1
                left = parse(0, depth + 1)
                if cursor >= len(tokens) or tokens[cursor] != ",":
                    raise TemcoError("Malformed native function arguments.")
                cursor += 1
                right = parse(0, depth + 1)
                if cursor >= len(tokens) or tokens[cursor] != ")":
                    raise TemcoError("Malformed native function arguments.")
                cursor += 1
                result = (
                    left[0] + right[0] + 2,
                    right[1] + 2,
                    max(left[2], right[2], right[1] + 2),
                    left[3] + right[3],
                )
            elif token == "(":
                result = parse(0, depth + 1)
                if cursor >= len(tokens) or tokens[cursor] != ")":
                    raise TemcoError("Unbalanced native expression parentheses.")
                cursor += 1
            elif NAME.fullmatch(token) and token not in RESERVED:
                result = 3, 0, 0, 1
            elif re.fullmatch(r"\d+(?:\.\d*)?|\.\d+", token):
                result = 5, 0, 0, 1
            else:
                raise TemcoError("Unsupported native expression syntax.")
            while (
                cursor < len(tokens)
                and tokens[cursor] in precedence
                and precedence[tokens[cursor]] >= minimum
            ):
                operator = tokens[cursor]
                cursor += 1
                right = parse(precedence[operator] + 1, depth + 1)
                result = (
                    result[0] + right[0] + 1,
                    right[1] + 1,
                    max(result[2], right[2], right[1] + 1),
                    result[3] + right[3],
                )
            return result

        size, _, peak, count = parse()
        if cursor != len(tokens) or count > 16 or peak > 8:
            raise TemcoError("Native compiler expression exceeds operand/postfix storage bounds.")
        return size

    def assignment(text):
        text = text.strip()
        if text.upper() == "END":
            return 1
        match = re.fullmatch(r"[A-Z][A-Z0-9_]{0,29}\s*=\s*(.+)", text, flags=re.I)
        if not match:
            raise TemcoError("Unsupported native assignment.")
        return 5 + expression(match[1])

    for _, statement in _source_lines(source):
        upper = statement.upper()
        if upper == "REM" or upper.startswith("REM "):
            continue
        for token in re.findall(r"[A-Z][A-Z0-9_]*", upper):
            if token not in RESERVED:
                symbols.add(token)
        if upper == "END":
            size = 4
        elif upper.startswith("IF "):
            parts = re.split(r"\bTHEN\b", upper, maxsplit=1)
            if len(parts) != 2:
                raise TemcoError("Malformed native conditional.")
            branches = re.split(r"\bELSE\b", parts[1], maxsplit=1)
            size = 16 + expression(parts[0][3:]) + sum(assignment(branch) for branch in branches)
        else:
            size = 3 + assignment(upper)
        if size > 400:
            raise TemcoError("Native compiler statement exceeds the 400-byte staging profile.")
    local_bytes = sum(len(name) + 6 for name in symbols if not POINT.fullmatch(name))
    if len(symbols) > 400 or local_bytes > 1800:
        raise TemcoError(
            "Native compiler symbol/local storage exceeds the bounded profile (400 symbols / 1800 local bytes)."
        )


def compile_source(source: str) -> bytes:
    """Use the actual manufacturer compiler after bounded source validation."""
    import_source(source)
    _compiler_bounds(source)
    home, _ = _toolchain()
    # Comments have no executable semantics. Excluding them conserves native
    # memory and prevents optional authoring annotations occupying the 2 KB app.
    normalized = (
        "\r\n".join(
            f"{number} {statement.upper()}"
            for number, statement in _source_lines(source)
            if statement.upper() != "REM" and not statement.upper().startswith("REM ")
        )
        + "\r\n"
    )
    try:
        result = subprocess.run(
            [str(home / "temco-compiler")],
            input=normalized.encode("ascii"),
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TemcoError(
            "Native Control Basic compiler failed or exceeded its time limit."
        ) from exc
    if result.returncode:
        message = result.stderr.decode("ascii", "replace")[:1000].strip()
        raise TemcoError(
            "Manufacturer Control Basic compiler rejected the source: "
            + (message or f"exit {result.returncode}")
        )
    if not 9 <= len(result.stdout) < 2000:
        raise TemcoError("Manufacturer compiler produced an invalid native program size.")
    return result.stdout


def compile_program(program: Program, *, bindings=None):
    source = export_source(program, bindings=bindings)
    bytecode = compile_source(source)
    _, manifest = _toolchain()
    return {
        "source": source,
        "bytecode": bytecode,
        "bindings": _bindings(expand_macros(program), bindings),
        "calendar_bindings": _calendar_bindings(
            expand_macros(program), _bindings(expand_macros(program), bindings)
        ),
        "manifest": manifest,
        "capabilities": capabilities(),
    }


def verify_program(
    program: Program,
    inputs=None,
    *,
    bindings=None,
    scans=1,
    initial_outputs=None,
    clock=None,
    input_sequence=None,
    calendar_valid=True,
):
    """Compile and execute persistent native state with memory-only point frames.

    Calendars are evaluated by the host; active/valid flags are explicit native
    inputs. Every native output at every scan is compared with the separate
    graph engine. Input sequences are bounded local acceptance fixtures.
    """
    if type(scans) is not int or not 1 <= scans <= 1000:
        raise TemcoError("Native verification requires 1..1000 scans.")
    if type(calendar_valid) is not bool:
        raise TemcoError("Calendar validity must be boolean.")
    program = expand_macros(program)
    compiled = compile_program(program, bindings=bindings)
    supplied = {} if inputs is None else dict(inputs)
    input_nodes = {node.id: node for node in program.nodes if node.kind == "Input"}
    output_nodes = {node.id: node for node in program.nodes if node.kind == "Output"}
    if supplied.keys() - input_nodes.keys():
        raise TemcoError("Native verification inputs contain unknown graph identifiers.")
    if input_sequence is not None and (
        not isinstance(input_sequence, list)
        or len(input_sequence) != scans
        or any(not isinstance(frame, dict) for frame in input_sequence)
    ):
        raise TemcoError("Input sequence must have one input mapping per native scan.")
    if clock is None:
        first_clock = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(seconds=program.scan_seconds)
    else:
        try:
            first_clock = (
                datetime.fromisoformat(clock.replace("Z", "+00:00"))
                if isinstance(clock, str)
                else clock
            )
            if not isinstance(first_clock, datetime) or first_clock.utcoffset() is None:
                raise ValueError("Timezone required")
            first_clock = first_clock.astimezone(UTC)
        except (ValueError, TypeError, OverflowError) as exc:
            raise TemcoError("Native scan clock requires an aware ISO-8601 datetime.") from exc
    calendar_nodes = {
        node.id: compile_schedule(node.params) for node in program.nodes if node.kind == "Schedule"
    }
    frame_lines, frame_inputs, clocks = [], [], []
    current = supplied.copy()
    for index in range(scans):
        if input_sequence is not None:
            update = input_sequence[index]
            if update.keys() - input_nodes.keys():
                raise TemcoError("Input sequence contains unknown graph identifiers.")
            current = {**current, **update}
        arguments = []
        checked = {}
        for identifier, node in input_nodes.items():
            value = current.get(
                identifier,
                node.params.get("default", False if output_type(node) == "boolean" else 0),
            )
            if isinstance(value, dict):
                if set(value) - {"value", "quality"} or value.get("quality", "good") != "good":
                    raise TemcoError("Native verification requires good input quality.")
                value = value.get("value")
            if output_type(node) == "boolean" and type(value) is not bool:
                raise TemcoError("Boolean input values must be true or false.")
            if output_type(node) != "boolean" and type(value) not in (int, float):
                raise TemcoError("Numeric input values must be finite numbers.")
            arguments.append(f"{compiled['bindings'][identifier]}={_literal(value)}")
            checked[identifier] = value
        try:
            frame_clock = first_clock + timedelta(seconds=program.scan_seconds * index)
            for identifier, calendar in calendar_nodes.items():
                ports = compiled["calendar_bindings"][identifier]
                arguments += [
                    f"{ports['active']}={int(calendar.active(frame_clock))}",
                    f"{ports['valid']}={int(calendar_valid)}",
                ]
        except (OverflowError, ValueError) as exc:
            raise TemcoError("Native scan clock exceeds the supported calendar range.") from exc
        frame_lines.append("\t".join(arguments))
        frame_inputs.append(checked)
        clocks.append(frame_clock)
    initial_outputs = {} if initial_outputs is None else dict(initial_outputs)
    if initial_outputs.keys() - output_nodes.keys():
        raise TemcoError("Initial output values contain unknown graph identifiers.")
    initial_arguments = []
    for identifier, value in initial_outputs.items():
        node = output_nodes[identifier]
        if output_type(node) == "boolean" and type(value) is not bool:
            raise TemcoError("Boolean output values must be true or false.")
        if output_type(node) != "boolean" and type(value) not in (int, float):
            raise TemcoError("Numeric output values must be finite numbers.")
        initial_arguments.append(f"{compiled['bindings'][identifier]}={_literal(value)}")
    watched = ["--watch=" + compiled["bindings"][identifier] for identifier in output_nodes]
    home, _ = _toolchain()
    with tempfile.TemporaryDirectory(prefix="bms-temco-") as directory:
        path, frames = Path(directory) / "application.bin", Path(directory) / "frames.txt"
        path.write_bytes(compiled["bytecode"])
        frames.write_text("\n".join(frame_lines) + "\n")
        try:
            result = subprocess.run(
                [
                    str(home / "temco-vm"),
                    str(path),
                    str(scans),
                    "--frames=" + str(frames),
                    *watched,
                    *initial_arguments,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TemcoError("Native Control Basic VM failed or exceeded its time limit.") from exc
    if result.returncode:
        raise TemcoError(
            f"Native Control Basic reference execution failed (exit {result.returncode})."
        )
    values = {}
    native_frames = [{} for _ in range(scans)]
    for row in result.stdout.splitlines():
        if row.startswith("@"):
            scan, name, value = row.split("\t", 2)
            native_frames[int(scan[1:]) - 1][name] = float(value)
        else:
            name, value = row.split("\t", 1)
            values[name] = float(value)
    reference = Engine(program)
    reference.outputs = {
        identifier: initial_outputs.get(identifier, False if output_type(node) == "boolean" else 0)
        for identifier, node in output_nodes.items()
    }
    differences, history = [], []
    reference_fault = None
    outputs = {}
    for index, native in enumerate(native_frames):
        reference_fault = None
        try:
            if calendar_nodes and not calendar_valid:
                raise ValueError(
                    "Host calendar is invalid or unbound; scan state and outputs held."
                )
            reference.step(frame_inputs[index], clock=clocks[index])
        except ValueError as exc:
            reference_fault = str(exc)
        outputs = {}
        for identifier, node in output_nodes.items():
            binding = compiled["bindings"][identifier]
            if binding not in native:
                raise TemcoError("Native VM did not return the requested scan output binding.")
            outputs[identifier] = (
                bool(native[binding]) if output_type(node) == "boolean" else native[binding]
            )
        for identifier, expected in reference.outputs.items():
            actual = outputs[identifier]
            matches = (
                actual is expected
                if type(expected) is bool
                else math.isclose(actual, expected, rel_tol=0.00001, abs_tol=0.01)
            )
            if not matches:
                differences.append(
                    {"scan": index + 1, "node": identifier, "native": actual, "reference": expected}
                )
        history.append(
            {
                "scan": index + 1,
                "clock": clocks[index].isoformat(),
                "outputs": outputs.copy(),
                "reference_outputs": reference.outputs.copy(),
                "reference_fault": reference_fault,
            }
        )
    return {
        "outputs": outputs,
        "native_values": values,
        "bytecode_bytes": len(compiled["bytecode"]),
        "source_sha256": hashlib.sha256(compiled["source"].encode()).hexdigest(),
        "source_commit": PIN,
        "scans": scans,
        "scope": "Temco native bytecode, simulated local points, no device connection",
        "numeric_resolution": 0.001,
        "reference_outputs": reference.outputs,
        "reference_fault": reference_fault,
        "differences": differences,
        "matches_reference": not differences,
        "history": history,
        "calendar_bindings": compiled["calendar_bindings"],
        "calendar_scope": "Host-evaluated calendar flags; native interpreter verifies gating and publication"
        if calendar_nodes
        else None,
    }
