"""Synchronous, typed inter-program simulation with explicit one-cycle links.

Programs observe a snapshot of the preceding cycle. All engines commit together;
a failed engine leaves every program at the last successful cycle. This is a
local graph simulator, not a network or vendor-firmware emulator.
"""

from __future__ import annotations

import copy
import math
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import Field, model_validator

from .engine import Engine, output_type
from .models import Edge, Node, Program, StrictModel


class ProgramInstance(StrictModel):
    alias: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    program: Program


class SignalLink(StrictModel):
    source_program: str
    source_output: str
    target_program: str
    target_input: str
    initial: Any = 0


class SimulationWorkspace(StrictModel):
    format: Literal["bms-simulation-workspace/1"] = "bms-simulation-workspace/1"
    name: str = Field(default="Shared-signal simulation", min_length=1, max_length=200)
    programs: list[ProgramInstance] = Field(min_length=2, max_length=16)
    links: list[SignalLink] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def check_links(self):
        instances = {p.alias: p.program for p in self.programs}
        if len(instances) != len(self.programs):
            raise ValueError("Program instance aliases must be unique.")
        if sum(len(p.nodes) for p in instances.values()) > 4000:
            raise ValueError("A simulation workspace supports at most 4,000 total blocks.")
        periods = {p.scan_seconds for p in instances.values()}
        if len(periods) != 1:
            raise ValueError("Shared-signal programs must use the same scan period.")
        nodes = {alias: {n.id: n for n in p.nodes} for alias, p in instances.items()}
        writers = set()
        for link in self.links:
            source = nodes.get(link.source_program, {}).get(link.source_output)
            target = nodes.get(link.target_program, {}).get(link.target_input)
            if source is None or target is None:
                raise ValueError("Shared signal references a missing program or block.")
            if source.kind != "Output" or target.kind != "Input":
                raise ValueError("Shared signals must connect an Output to an Input.")
            typ = output_type(source)
            if typ != output_type(target):
                raise ValueError("Shared signal value types must match.")
            if typ == "number" and source.unit != target.unit:
                raise ValueError("Shared signal engineering units must match; convert explicitly.")
            if (link.target_program, link.target_input) in writers:
                raise ValueError("A shared input can have only one writer.")
            writers.add((link.target_program, link.target_input))
            if typ == "boolean":
                if type(link.initial) is not bool:
                    raise ValueError("Boolean shared signals require a Boolean initial value.")
            else:
                try:
                    finite = type(link.initial) in (int, float) and math.isfinite(link.initial)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError(
                        "Numeric shared signals require a finite numeric initial value."
                    )
        return self


class SimulationGroup:
    def __init__(self, definition: SimulationWorkspace):
        self.definition = definition.model_copy(deep=True)
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.engines = {p.alias: Engine(p.program) for p in self.definition.programs}
            self.external_inputs = {alias: {} for alias in self.engines}
            self.time = 0.0
            self.clock = datetime(2026, 1, 5, tzinfo=UTC)
            self.history = []
            self.last_fault = None
            self.failures = []
            self.history_limit = min(
                1000, max(20, 100000 // sum(len(e.nodes) for e in self.engines.values()))
            )

    def status(self):
        with self.lock:
            return {
                "definition": self.definition.model_dump(),
                "time": self.time,
                "clock": self.clock.isoformat(),
                "programs": {alias: e.snapshot() for alias, e in self.engines.items()},
                "history": self.history[:],
                "last_fault": self.last_fault,
                "failures": self.failures[:],
                "external_inputs": copy.deepcopy(self.external_inputs),
                "link_delay_cycles": 1,
                "execution": "Local synchronous BMS graph simulation; no field interfaces",
            }

    def step(self, inputs=None, *, clock=None):
        with self.lock:
            inputs = inputs or {}
            if inputs.keys() - self.engines.keys():
                raise ValueError("Unknown program instance in simulation inputs.")
            proposed = copy.deepcopy(self.external_inputs)
            for alias, values in inputs.items():
                if not isinstance(values, dict):
                    raise ValueError("Each program's simulation inputs must be an object.")
                if values.keys() - {
                    n.id for n in self.engines[alias].program.nodes if n.kind == "Input"
                }:
                    raise ValueError("Unknown simulation input block.")
                for value in values.values():
                    if isinstance(value, dict) and (
                        value.keys() - {"value", "quality"}
                        or not isinstance(value.get("quality", "good"), str)
                        or len(value.get("quality", "good")) > 80
                    ):
                        raise ValueError(
                            "Signal values contain only value and bounded quality fields."
                        )
                proposed[alias].update(values)
            effective = copy.deepcopy(proposed)
            for link in self.definition.links:
                if link.target_input in proposed[link.target_program]:
                    raise ValueError("A linked input cannot also have an external override.")
                effective[link.target_program][link.target_input] = self.engines[
                    link.source_program
                ].outputs.get(link.source_output, link.initial)
            dt = self.definition.programs[0].program.scan_seconds
            current_clock = clock or (self.clock + timedelta(seconds=dt))
            candidates, rows = {}, {}
            try:
                for alias, engine in self.engines.items():
                    # Engine.step stages new state/values rather than mutating the
                    # old dictionaries. Give each candidate its own history list.
                    candidate = copy.copy(engine)
                    candidate.history = []
                    rows[alias] = candidate.step(effective[alias], dt, current_clock)
                    candidates[alias] = candidate
            except ValueError as exc:
                self.last_fault = {"program": alias, "detail": str(exc), "time": self.time}
                self.failures.append({**self.last_fault, "inputs": effective})
                self.failures = self.failures[-50:]
                raise ValueError(
                    f"{alias}: {exc}; all programs remain at the previous cycle."
                ) from exc
            self.engines = candidates
            self.external_inputs = proposed
            self.time += dt
            self.clock = current_clock
            self.last_fault = None
            row = {
                "time": self.time,
                "clock": self.clock.isoformat(),
                "programs": rows,
                "inputs": effective,
            }
            self.history.append(row)
            self.history = self.history[-self.history_limit :]
            return row


class SimulationGroups:
    """Bounded in-memory sessions. Exported definitions are portable data only."""

    def __init__(self):
        self.lock = threading.RLock()
        self.sessions = {}

    def start(self, definition, replace=None):
        candidate = SimulationGroup(definition)
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: v for k, v in self.sessions.items() if now - v["touched"] < 3600}
            if len(self.sessions) >= 8 and replace not in self.sessions:
                raise ValueError(
                    "Close an existing shared-signal simulation before starting another."
                )
            token = secrets.token_urlsafe(24)
            self.sessions[token] = {"group": candidate, "touched": now}
            self.sessions.pop(replace, None)
        return self.status(token)

    def list(self):
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: v for k, v in self.sessions.items() if now - v["touched"] < 3600}
            result = []
            for token, record in sorted(
                self.sessions.items(), key=lambda item: -item[1]["touched"]
            ):
                group = record["group"]
                with group.lock:
                    result.append(
                        {"session": token, "name": group.definition.name, "time": group.time}
                    )
            return result

    def get(self, token):
        with self.lock:
            record = self.sessions.get(token)
            if record is None or time.monotonic() - record["touched"] >= 3600:
                self.sessions.pop(token, None)
                raise ValueError(
                    "Shared-signal simulation expired. Start it again from its definition."
                )
            record["touched"] = time.monotonic()
            return record["group"]

    def status(self, token):
        return {"session": token, **self.get(token).status()}

    def close(self, token):
        with self.lock:
            self.sessions.pop(token, None)

    def export(self, token):
        return self.get(token).definition.model_dump_json(indent=2).encode()

    def import_file(self, content, replace=None):
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("Simulation workspace exceeds 8 MiB.")
        return self.start(SimulationWorkspace.model_validate_json(content), replace)


def demo_workspace():
    def edge(id, source, target, port="in"):
        return Edge(id=id, source=source, target=target, target_port=port)

    producer = Program(
        id="signal-producer",
        name="Producer: value + 2",
        nodes=[
            Node(id="value", kind="Input", params={"default": 40}),
            Node(id="offset", kind="Constant", params={"value": 2}),
            Node(id="add", kind="Add"),
            Node(id="signal", kind="Output"),
        ],
        edges=[
            edge("a", "value", "add", "a"),
            edge("b", "offset", "add", "b"),
            edge("c", "add", "signal"),
        ],
    )
    consumer = Program(
        id="signal-consumer",
        name="Consumer: incoming × 2",
        nodes=[
            Node(id="incoming", kind="Input"),
            Node(
                id="double",
                kind="Scale",
                params={"in_min": 0, "in_max": 1, "out_min": 0, "out_max": 2, "clamp": False},
            ),
            Node(id="scaled", kind="Output"),
        ],
        edges=[edge("a", "incoming", "double"), edge("b", "double", "scaled")],
    )
    return SimulationWorkspace(
        name="Shared-signal math example",
        programs=[
            ProgramInstance(alias="producer", program=producer),
            ProgramInstance(alias="consumer", program=consumer),
        ],
        links=[
            SignalLink(
                source_program="producer",
                source_output="signal",
                target_program="consumer",
                target_input="incoming",
                initial=0,
            )
        ],
    )
