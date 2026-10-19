"""Deterministic scans with typed ports, explicit feedback, and atomic state updates."""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime, timedelta

from .blocks import BLOCKS
from .models import Diagnostic, Program


def validate(program: Program) -> list[Diagnostic]:
    issues = []

    def issue(code, message, node=None, level="error"):
        issues.append(Diagnostic(level=level, code=code, message=message, node=node))

    if "native_sedona" in program.metadata:
        from .native_document import NativeDocument

        try:
            NativeDocument.model_validate(program.metadata["native_sedona"])
            issue(
                "native_extension",
                "Additional native Sedona components require Native sim and native export.",
                level="warning",
            )
        except ValueError as exc:
            issue("native_extension", str(exc))

    nodes = {n.id: n for n in program.nodes}
    if len(nodes) != len(program.nodes):
        issue("duplicate_node", "Node identifiers must be unique.")
    if len(program.nodes) > program.target.max_nodes:
        issue("resources", "Target node limit exceeded.")
    if not program.nodes:
        issue("empty", "Add at least one input and output.")
    incoming = {}
    edge_ids = set()
    for e in program.edges:
        if e.id in edge_ids:
            issue("duplicate_edge", "Edge identifiers must be unique.")
        edge_ids.add(e.id)
        if e.source not in nodes or e.target not in nodes:
            issue("missing_node", "Connection references a missing node.")
            continue
        a, b = nodes[e.source], nodes[e.target]
        if a.kind not in BLOCKS or b.kind not in BLOCKS:
            continue
        if e.source_port != "out" or e.target_port not in BLOCKS[b.kind].inputs:
            issue("port", "Connection references an undefined port.", b.id)
            continue
        key = (b.id, e.target_port)
        if key in incoming:
            issue("multiple_writers", "An input port can have only one writer.", b.id)
        incoming[key] = a
        actual = output_type(a)
        expected = input_type(b, e.target_port)
        if actual != expected:
            issue("type", f"{e.target_port} requires {expected}, received {actual}.", b.id)
        if expected == "number" and b.kind not in (
            "Scale",
            "Convert",
            "PI",
            "Multiply",
            "Divide",
        ):
            if a.unit != b.unit and b.kind not in ("Greater", "Less", "Equal"):
                issue(
                    "unit",
                    f"Unit mismatch ({a.unit or 'dimensionless'} to {b.unit or 'dimensionless'}); add a scale/conversion block.",
                    b.id,
                )
    for n in program.nodes:
        if n.kind not in BLOCKS:
            issue("unknown_block", f"Block {n.kind!r} has no execution semantics.", n.id)
            continue
        for port in BLOCKS[n.kind].inputs:
            if (n.id, port) not in incoming:
                issue("unwired", f"Connect required input {port}.", n.id)
        defaults = BLOCKS[n.kind].parameters
        extra = n.params.keys() - defaults.keys()
        if extra:
            issue("parameter", f"Unknown parameters: {', '.join(sorted(extra))}.", n.id)
        p = {**defaults, **n.params}
        try:
            numeric = {
                k
                for k, v in defaults.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            if n.value_type == "boolean" and n.kind in ("Input", "Constant", "Delay"):
                numeric.difference_update({"value", "default", "initial"})
            for key in numeric:
                if type(p[key]) not in (int, float) or not math.isfinite(p[key]):
                    raise ValueError(f"{key} must be a finite number")
            for key, v in defaults.items():
                if isinstance(v, bool) and type(p[key]) is not bool:
                    raise ValueError(f"{key} must be boolean")
            if n.kind in ("PI", "Clamp") and p["min"] > p["max"]:
                raise ValueError("minimum exceeds maximum")
            if n.kind == "Scale" and p["in_min"] == p["in_max"]:
                raise ValueError("scale input range is zero")
            if (
                n.kind in ("TimerOn", "Alarm", "Slew")
                and p.get("seconds", p.get("delay", p.get("rate", 0))) < 0
            ):
                raise ValueError("time/rate must be nonnegative")
            if n.kind == "Deadband" and p["off"] > p["on"]:
                raise ValueError("off threshold exceeds on threshold")
            if n.kind == "Convert" and (
                p["from"] not in ("degF", "degC", "K")
                or p["to"] not in ("degF", "degC", "K")
                or n.unit != p["to"]
            ):
                raise ValueError("use degF, degC or K; output unit must equal 'to'")
            if n.kind == "Schedule":
                for k in ("start", "end"):
                    datetime.strptime(p[k], "%H:%M")
                if not isinstance(p["days"], list) or any(
                    type(d) is not int or not 0 <= d <= 6 for d in p["days"]
                ):
                    raise ValueError("days must be integers 0..6")
            if n.kind in ("Input", "Constant", "Delay"):
                val = p.get("default", p.get("value", p.get("initial")))
                if n.value_type == "boolean" and type(val) is not bool:
                    raise ValueError("boolean block requires a boolean default/value/initial")
            if n.kind in (
                "Greater",
                "Less",
                "Equal",
                "PI",
                "Add",
                "Subtract",
                "Min",
                "Max",
            ):
                sources = [
                    incoming[(n.id, k)] for k in BLOCKS[n.kind].inputs if (n.id, k) in incoming
                ]
                if len({x.unit for x in sources}) > 1:
                    raise ValueError("input engineering units must match")
            if (
                n.kind == "Convert"
                and (n.id, "in") in incoming
                and incoming[(n.id, "in")].unit != p["from"]
            ):
                raise ValueError("input unit does not match conversion 'from'")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            issue("parameter", str(exc), n.id)
    for kind, limit in (
        ("Input", program.target.physical_inputs),
        ("Output", program.target.physical_outputs),
    ):
        terminals = [
            n.params.get("terminal")
            for n in program.nodes
            if n.kind == kind and n.params.get("terminal")
        ]
        if len(terminals) != len(set(terminals)):
            issue("terminal", f"{kind} terminal assigned more than once.")
        if limit is not None and len(terminals) > limit:
            issue("resources", f"{kind} terminal capacity exceeded.")
    try:
        execution_order(program)
    except ValueError as exc:
        issue("cycle", str(exc))
    if program.target.family != "universal-runtime":
        issue(
            "native_deployment",
            "This target requires its native compiler and a verified download adapter. BACnet access alone does not supply either.",
            level="warning",
        )
    if not any(n.kind == "Output" for n in program.nodes):
        issue("no_output", "Program has no published outputs.", level="warning")
    return issues


def output_type(n):
    spec = BLOCKS.get(n.kind)
    if not spec or spec.output in ("same",) or n.kind in ("Input", "Constant"):
        return n.value_type
    return spec.output


def input_type(n, port):
    if n.kind in ("And", "Or", "Not", "TimerOn") or (n.kind == "Switch" and port == "select"):
        return "boolean"
    if n.kind in ("Output", "Switch", "Delay"):
        return n.value_type
    return "number"


def execution_order(program):
    ids = {n.id for n in program.nodes}
    kinds = {n.id: n.kind for n in program.nodes}
    dependencies = {n: set() for n in ids}
    for e in program.edges:
        if e.target in ids and e.source in ids and kinds[e.target] != "Delay":
            dependencies[e.target].add(e.source)
    result = []
    while dependencies:
        ready = sorted(n for n, d in dependencies.items() if not d)
        if not ready:
            raise ValueError("Combinational cycle detected; insert a one-scan memory block.")
        result.extend(ready)
        for n in ready:
            del dependencies[n]
        for d in dependencies.values():
            d.difference_update(ready)
    return result


class ScanError(ValueError):
    pass


class Engine:
    def __init__(self, program: Program, *, allow_native_extension=False):
        if "native_sedona" in program.metadata and not allow_native_extension:
            raise ValueError(
                "This project contains native Sedona components. Use Native sim; portable execution would omit them."
            )
        self.program = program.model_copy(deep=True)
        issues = validate(self.program)
        errors = [d.message for d in issues if d.level == "error"]
        if errors:
            raise ValueError("; ".join(errors))
        self.order = execution_order(self.program)
        self.nodes = {n.id: n for n in self.program.nodes}
        self.links = {(e.target, e.target_port): e.source for e in self.program.edges}
        self.state = {}
        self.values = {}
        self.outputs = {}
        self.forces = {}
        self.time = 0.0
        self.history = []
        self.history_limit = min(10000, max(20, 100000 // max(1, len(program.nodes))))
        self.clock = datetime(2026, 1, 5, tzinfo=UTC)

    def step(self, inputs=None, dt=None, clock=None, *, forces=None):
        inputs = inputs or {}
        unknown = set(inputs) - {n.id for n in self.program.nodes if n.kind == "Input"}
        if unknown:
            raise ScanError("Unknown input identifiers: " + ", ".join(sorted(unknown)))
        held = self.forces.copy() if forces is None else copy.deepcopy(forces)
        if not isinstance(held, dict) or held.keys() - self.nodes.keys():
            raise ScanError("Simulation forces must name existing blocks.")
        for identifier, value in held.items():
            typ = output_type(self.nodes[identifier])
            if typ == "boolean":
                valid = type(value) is bool
            else:
                try:
                    valid = type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    valid = False
            if not valid:
                raise ScanError(f"{identifier}: force requires a finite {typ} value.")
        dt = self.program.scan_seconds if dt is None else dt
        if type(dt) not in (int, float) or not 0 < dt <= 60:
            raise ScanError("Scan duration must be finite and in (0,60] seconds.")
        current_clock = clock or (self.clock + timedelta(seconds=dt))
        values = {}
        computed = {}
        state = copy.deepcopy(self.state)
        alarms = []
        try:
            for node_id in self.order:
                n = self.nodes[node_id]
                k = n.kind
                p = {**BLOCKS[k].parameters, **n.params}

                def arg(port, current_node=node_id):
                    return values[self.links[(current_node, port)]]

                s = state.setdefault(node_id, {})
                if k == "Input":
                    v = inputs.get(node_id, p["default"])
                    if isinstance(v, dict):
                        if v.get("quality", "good") != "good":
                            raise ScanError(
                                f"{n.label or node_id}: {v.get('quality')} input quality"
                            )
                        v = v.get("value")
                elif k == "Constant":
                    v = p["value"]
                elif k == "Output":
                    v = arg("in")
                elif k == "Delay":
                    v = s.get("previous", p["initial"])
                elif k == "Add":
                    v = arg("a") + arg("b")
                elif k == "Subtract":
                    v = arg("a") - arg("b")
                elif k == "Multiply":
                    v = arg("a") * arg("b")
                elif k == "Divide":
                    v = arg("a") / arg("b")
                elif k == "Min":
                    v = min(arg("a"), arg("b"))
                elif k == "Max":
                    v = max(arg("a"), arg("b"))
                elif k == "Abs":
                    v = abs(arg("in"))
                elif k == "Clamp":
                    v = max(p["min"], min(p["max"], arg("in")))
                elif k == "Scale":
                    fraction = (arg("in") - p["in_min"]) / (p["in_max"] - p["in_min"])
                    if p["clamp"]:
                        fraction = max(0, min(1, fraction))
                    v = p["out_min"] + fraction * (p["out_max"] - p["out_min"])
                elif k == "Convert":
                    c = (
                        (arg("in") - 32) * 5 / 9
                        if p["from"] == "degF"
                        else arg("in") - 273.15
                        if p["from"] == "K"
                        else arg("in")
                    )
                    v = c * 9 / 5 + 32 if p["to"] == "degF" else c + 273.15 if p["to"] == "K" else c
                elif k == "Greater":
                    v = arg("a") > arg("b")
                elif k == "Less":
                    v = arg("a") < arg("b")
                elif k == "Equal":
                    v = arg("a") == arg("b")
                elif k == "And":
                    v = arg("a") and arg("b")
                elif k == "Or":
                    v = arg("a") or arg("b")
                elif k == "Not":
                    v = not arg("in")
                elif k == "Switch":
                    v = arg("on") if arg("select") else arg("off")
                elif k == "Deadband":
                    v = s.get("on", p["initial"])
                    if arg("in") >= p["on"]:
                        v = True
                    elif arg("in") <= p["off"]:
                        v = False
                    s["on"] = v
                elif k in ("TimerOn", "Alarm"):
                    active = arg("in") if k == "TimerOn" else arg("in") > p["limit"]
                    s["elapsed"] = s.get("elapsed", 0) + dt if active else 0
                    v = bool(active and s["elapsed"] >= p.get("seconds", p.get("delay")))
                elif k == "Slew":
                    old = s.get("previous", p["initial"])
                    delta = p["rate"] * dt
                    v = old + max(-delta, min(delta, arg("in") - old))
                    s["previous"] = v
                elif k == "PI":
                    error = (arg("setpoint") - arg("measured")) * (-1 if p["reverse"] else 1)
                    integral = s.get("integral", 0)
                    candidate = integral + p["ki"] * error * dt
                    raw = p["kp"] * error + candidate
                    if (
                        p["min"] <= raw <= p["max"]
                        or (raw > p["max"] and error * p["ki"] < 0)
                        or (raw < p["min"] and error * p["ki"] > 0)
                    ):
                        integral = candidate
                    s["integral"] = integral
                    v = max(p["min"], min(p["max"], p["kp"] * error + integral))
                elif k == "Schedule":
                    minute = current_clock.hour * 60 + current_clock.minute
                    start = sum(
                        int(x) * m for x, m in zip(p["start"].split(":"), (60, 1), strict=True)
                    )
                    end = sum(int(x) * m for x, m in zip(p["end"].split(":"), (60, 1), strict=True))
                    day = current_clock.weekday()
                    v = (
                        (day in p["days"] and start <= minute < end)
                        if start <= end
                        else (
                            (day in p["days"] and minute >= start)
                            or ((day - 1) % 7 in p["days"] and minute < end)
                        )
                    )
                else:
                    raise ScanError(f"No semantics for {k}")
                expected = output_type(n)
                if expected == "boolean" and type(v) is not bool:
                    raise ScanError(f"{node_id}: expected boolean")
                if expected == "number" and (type(v) not in (int, float) or not math.isfinite(v)):
                    raise ScanError(f"{node_id}: expected finite number")
                if node_id in held:
                    computed[node_id] = v
                    v = held[node_id]
                values[node_id] = v
                if k == "Alarm" and v:
                    alarms.append({"node": node_id, "message": n.label or "High alarm"})
            for n in self.program.nodes:
                if n.kind == "Delay":
                    state[n.id]["previous"] = values[self.links[(n.id, "in")]]
        except (ZeroDivisionError, OverflowError, TypeError, KeyError) as exc:
            raise ScanError(f"{node_id}: {exc}") from exc
        outputs = {n.id: values[n.id] for n in self.program.nodes if n.kind == "Output"}
        self.state = state
        self.values = values
        self.outputs = outputs
        self.forces = held
        self.time += dt
        self.clock = current_clock
        row = {
            "time": self.time,
            "clock": current_clock.isoformat(),
            "values": values.copy(),
            "outputs": outputs.copy(),
            "alarms": alarms,
            "forces": held.copy(),
            "computed": computed,
        }
        self.history.append(row)
        if len(self.history) > self.history_limit:
            self.history = self.history[-self.history_limit :]
        return row

    def snapshot(self):
        return {
            "program_hash": self.program.digest(),
            "time": self.time,
            "clock": self.clock.isoformat(),
            "state": copy.deepcopy(self.state),
            "values": self.values.copy(),
            "outputs": self.outputs.copy(),
            "forces": self.forces.copy(),
        }


def run_scenario(program, events, duration, dt=None, *, forces=None):
    if type(duration) not in (int, float) or not 0 < duration <= 86400:
        raise ValueError("Scenario duration must be in (0,86400].")
    engine = Engine(program)
    dt = program.scan_seconds if dt is None else dt
    if type(dt) not in (int, float) or not 0 < dt <= 60:
        raise ValueError("Scenario timestep must be finite and in (0,60].")
    if duration / dt > engine.history_limit:
        raise ValueError(
            "Scenario exceeds 10,000 scans or bounded trace capacity; shorten duration or increase the timestep."
        )
    i = 0
    inputs = {}
    held = forces
    if len(events) > 10000:
        raise ValueError("A scenario supports at most 10,000 events.")
    for e in events:
        if not isinstance(e, dict) or "time" not in e:
            raise ValueError("Every scenario event requires a time.")
        if e.keys() - {"time", "inputs", "forces"} or not isinstance(e.get("inputs", {}), dict):
            raise ValueError("Scenario events contain time and optional inputs/forces objects.")
        if "forces" in e and not isinstance(e["forces"], dict):
            raise ValueError(
                "Scenario forces must be a complete override map; use {} to release all."
            )
        try:
            finite = type(e["time"]) in (int, float) and math.isfinite(e["time"])
        except OverflowError:
            finite = False
        if not finite or e["time"] < 0:
            raise ValueError("Event times must be finite and nonnegative.")
    ordered = sorted(events, key=lambda e: e["time"])
    while engine.time < duration - 1e-9:
        while i < len(ordered) and ordered[i]["time"] <= engine.time:
            inputs.update(ordered[i].get("inputs", {}))
            if "forces" in ordered[i]:
                held = ordered[i]["forces"]
            i += 1
        engine.step(inputs, min(dt, duration - engine.time), forces=held)
    return engine.history
