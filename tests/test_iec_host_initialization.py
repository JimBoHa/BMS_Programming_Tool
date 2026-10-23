"""Actual compiled host controls under deterministic automatic-storage poison."""

import copy

import pytest
from bms_tool import iec
from bms_tool.equipment_wizard import Choices, generate
from bms_tool.models import Edge, Node, Program


def seeded_state_graph():
    nodes = [
        Node(id="value", kind="Input", params={"default": 2}),
        Node(id="setpoint", kind="Constant", params={"value": 5}),
        Node(id="controller", kind="PI", params={"kp": 2, "ki": 0.5, "min": -100, "max": 100}),
        Node(id="memory", kind="Delay", params={"initial": 7.25}),
        Node(id="middle", kind="Constant", params={"value": 0.5}),
        Node(
            id="hysteresis",
            kind="Deadband",
            value_type="boolean",
            params={"on": 1, "off": 0, "initial": True},
        ),
        Node(id="request", kind="Constant", value_type="boolean", params={"value": True}),
        Node(id="timer", kind="TimerOn", value_type="boolean", params={"seconds": 2}),
        Node(id="ramp", kind="Slew", params={"rate": 1, "initial": 3}),
    ]
    links = [
        ("setpoint", "controller", "setpoint"),
        ("value", "controller", "measured"),
        ("value", "memory", "in"),
        ("middle", "hysteresis", "in"),
        ("request", "timer", "in"),
        ("setpoint", "ramp", "in"),
    ]
    for source, boolean in (
        ("controller", False),
        ("memory", False),
        ("hysteresis", True),
        ("timer", True),
        ("ramp", False),
    ):
        nodes.append(
            Node(id=source + "_out", kind="Output", value_type="boolean" if boolean else "number")
        )
        links.append((source, source + "_out", "in"))
    return Program(
        id="defined-initial-values",
        nodes=nodes,
        edges=[
            Edge(id=f"edge{i}", source=a, target=b, target_port=c)
            for i, (a, b, c) in enumerate(links)
        ],
    )


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang toolchain unavailable"
)
@pytest.mark.parametrize("case", ["dual-feedback", "dual-position", "declared-initial-state"])
def test_explicit_initialization_survives_actual_clang_automatic_storage_poison(monkeypatch, case):
    original = iec._run
    compiler_calls = []

    def compile_with_poison(args, **kwargs):
        args = list(args)
        if args[0] == "clang":
            # Define formerly indeterminate automatic bytes as 0xAA: includes
            # MatIEC FORCE flag 0x02. Explicit initializers must override it.
            args.insert(1, "-ftrivial-auto-var-init=pattern")
            compiler_calls.append(args)
        return original(args, **kwargs)

    monkeypatch.setattr(iec, "_run", compile_with_poison)
    program = (
        seeded_state_graph()
        if case == "declared-initial-state"
        else generate(
            Choices(
                project_id=case,
                name=case,
                equipment="dual-duct",
                control="position" if case == "dual-position" else "flow-feedback",
                dual_duct={"layout": "none" if case == "dual-position" else "hot-cold"},
            )
        )
    )
    with iec.NativeIEC(program) as native:
        process = native.process
        first = native.step()
        assert not first["fault"] and first["matches_reference"], first
        if case == "declared-initial-state":
            assert first["outputs"] == {
                "controller_out": 7.5,
                "memory_out": 7.25,
                "hysteresis_out": True,
                "timer_out": False,
                "ramp_out": 4,
            }
        else:
            assert first["outputs"]["cold_damper"] == pytest.approx(
                52.16 if case == "dual-position" else 12.2816, abs=0.0002
            )
        second = native.step()
        assert not second["fault"] and second["matches_reference"], second
        before = copy.deepcopy(second)
        key = "value" if case == "declared-initial-state" else "zone"
        fault = native.step({key: {"value": 0.0, "quality": "open-circuit"}})
        assert fault["fault"] and fault["matches_reference"]
        assert (
            fault["outputs"] == before["outputs"]
            and fault["native_state"] == before["native_state"]
        )
        resumed = native.step()
        assert not resumed["fault"] and resumed["matches_reference"], resumed
    assert process.poll() is not None
    assert len(compiler_calls) == 1
