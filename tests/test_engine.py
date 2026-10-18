from datetime import UTC, datetime

import pytest
from bms_tool.engine import Engine, ScanError, run_scenario, validate
from bms_tool.models import Edge, Node, Program
from bms_tool.templates import all_templates


def graph(kind, a=2, b=3, params=None, boolean=False):
    from bms_tool.blocks import BLOCKS

    spec = BLOCKS[kind]
    is_bool = spec.output == "boolean"
    sources = [
        Node(
            id="a",
            kind="Input",
            params={"default": a},
            value_type="boolean" if type(a) is bool else "number",
        ),
        Node(
            id="b",
            kind="Input",
            params={"default": b},
            value_type="boolean" if type(b) is bool else "number",
        ),
    ]
    node = Node(
        id="block",
        kind=kind,
        params=params or {},
        value_type="boolean" if boolean else "number",
    )
    output = Node(
        id="result",
        kind="Output",
        value_type="boolean" if is_bool or boolean else "number",
    )
    edges = [
        Edge(id=str(i), source="a" if i == 0 else "b", target="block", target_port=port)
        for i, port in enumerate(spec.inputs)
    ]
    return Program(
        nodes=sources + [node, output],
        edges=edges + [Edge(id="out", source="block", target="result")],
    )


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("Add", 5),
        ("Subtract", -1),
        ("Multiply", 6),
        ("Divide", 2 / 3),
        ("Min", 2),
        ("Max", 3),
        ("Abs", 2),
        ("Greater", False),
        ("Less", True),
        ("Equal", False),
    ],
)
def test_arithmetic_and_comparison(kind, expected):
    assert Engine(graph(kind)).step()["outputs"]["result"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "kind,a,b,expected",
    [
        ("And", True, False, False),
        ("Or", True, False, True),
        ("Not", True, False, False),
    ],
)
def test_boolean_blocks(kind, a, b, expected):
    assert Engine(graph(kind, a, b)).step()["outputs"]["result"] is expected


def test_feedback_requires_explicit_memory():
    p = graph("Add")
    p.edges[0].source = "block"
    assert "cycle" in [d.code for d in validate(p)]
    with pytest.raises(ValueError, match="cycle"):
        Engine(p)


def test_delay_closes_feedback_deterministically():
    p = Program(
        nodes=[
            Node(id="one", kind="Constant", params={"value": 1}),
            Node(id="memory", kind="Delay"),
            Node(id="sum", kind="Add"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="1", source="one", target="sum", target_port="a"),
            Edge(id="2", source="memory", target="sum", target_port="b"),
            Edge(id="3", source="sum", target="memory"),
            Edge(id="4", source="sum", target="out"),
        ],
    )
    engine = Engine(p)
    assert [engine.step()["outputs"]["out"] for _ in range(4)] == [1, 2, 3, 4]


def test_scan_failure_is_atomic():
    engine = Engine(graph("Divide", 6, 2))
    engine.step()
    before = engine.snapshot()
    with pytest.raises(ScanError):
        engine.step({"b": 0})
    assert engine.snapshot() == before
    assert engine.step({"b": 3})["outputs"]["result"] == 2


@pytest.mark.parametrize("quality", ["open-circuit", "stale", "missing"])
def test_bad_input_quality_never_becomes_a_plausible_value(quality):
    engine = Engine(graph("Add"))
    engine.step()
    before = engine.snapshot()
    with pytest.raises(ScanError, match=quality):
        engine.step({"a": {"value": 999, "quality": quality}})
    assert engine.snapshot() == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, None, "12"])
def test_numeric_input_type_is_strict(value):
    with pytest.raises(ScanError):
        Engine(graph("Add")).step({"a": value})


def test_unknown_input_is_not_silently_ignored():
    with pytest.raises(ScanError, match="Unknown input"):
        Engine(graph("Add")).step({"wrong_name": 3})


def test_unit_and_type_mismatches_are_reported():
    p = graph("Add")
    p.nodes[0].unit = "degF"
    p.nodes[1].value_type = "boolean"
    p.nodes[1].params = {"default": True}
    codes = [i.code for i in validate(p)]
    assert "unit" in codes and "type" in codes


def test_multiple_writers_and_undefined_ports():
    p = graph("Add")
    p.edges.append(Edge(id="duplicate", source="b", target="block", target_port="a"))
    p.edges.append(Edge(id="bad", source="a", target="block", target_port="nothing"))
    codes = [i.code for i in validate(p)]
    assert "multiple_writers" in codes and "port" in codes


def test_pi_saturation_does_not_wind_up_integral():
    p = graph("PI", 100, 0, {"kp": 1, "ki": 1, "min": 0, "max": 10})
    engine = Engine(p)
    for _ in range(100):
        assert engine.step()["outputs"]["result"] == 10
    assert engine.state["block"]["integral"] == 0
    assert engine.step({"a": 1})["outputs"]["result"] == 2


def test_timer_resets_after_false():
    engine = Engine(graph("TimerOn", True, False, {"seconds": 3}))
    assert [engine.step()["outputs"]["result"] for _ in range(3)] == [
        False,
        False,
        True,
    ]
    assert engine.step({"a": False})["outputs"]["result"] is False
    assert engine.step()["outputs"]["result"] is False


def test_hysteresis_retains_between_thresholds():
    engine = Engine(graph("Deadband", 0, 0, {"on": 10, "off": 5}))
    assert [engine.step({"a": v})["outputs"]["result"] for v in [0, 11, 7, 4, 7]] == [
        False,
        True,
        True,
        False,
        False,
    ]


def test_overnight_schedule_uses_previous_weekday():
    p = graph("Schedule", params={"start": "22:00", "end": "06:00", "days": [0]})
    e = Engine(p)
    assert e.step(clock=datetime(2026, 1, 6, 1, tzinfo=UTC))["outputs"]["result"] is True
    assert e.step(clock=datetime(2026, 1, 7, 1, tzinfo=UTC))["outputs"]["result"] is False


def test_scenario_events_and_limits():
    rows = run_scenario(graph("Add"), [{"time": 2, "inputs": {"a": 10}}], 4)
    assert [r["outputs"]["result"] for r in rows] == [5, 5, 13, 13]
    with pytest.raises(ValueError, match="10,000"):
        run_scenario(graph("Add"), [], 20000)


def test_scale_and_clamp_bound_outputs():
    assert Engine(graph("Clamp", 200)).step()["outputs"]["result"] == 100
    assert (
        Engine(
            graph(
                "Scale",
                5,
                params={"in_min": 0, "in_max": 10, "out_min": 0, "out_max": 100},
            )
        ).step()["outputs"]["result"]
        == 50
    )


def test_temperature_conversion_requires_matching_units():
    p = graph("Convert", 32)
    p.nodes[0].unit = "degF"
    p.nodes[2].unit = "degC"
    p.nodes[3].unit = "degC"
    assert Engine(p).step()["outputs"]["result"] == 0
    p.nodes[0].unit = "degC"
    with pytest.raises(ValueError, match="input unit"):
        Engine(p)


def test_slew_uses_scan_duration():
    engine = Engine(graph("Slew", 100, params={"rate": 2, "initial": 0}))
    assert engine.step(dt=0.5)["outputs"]["result"] == 1
    assert engine.step(dt=0.5)["outputs"]["result"] == 2


def test_alarm_delay_and_return_to_normal():
    engine = Engine(graph("Alarm", 11, params={"limit": 10, "delay": 2}))
    assert engine.step()["outputs"]["result"] is False
    row = engine.step()
    assert row["outputs"]["result"] is True and row["alarms"][0]["node"] == "block"
    row = engine.step({"a": 9})
    assert row["outputs"]["result"] is False and not row["alarms"]


def test_boolean_constant_and_selector():
    p = Program(
        nodes=[
            Node(
                id="select",
                kind="Constant",
                params={"value": True},
                value_type="boolean",
            ),
            Node(id="high", kind="Constant", params={"value": 10}),
            Node(id="low", kind="Constant", params={"value": 2}),
            Node(id="switch", kind="Switch"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="1", source="select", target="switch", target_port="select"),
            Edge(id="2", source="high", target="switch", target_port="on"),
            Edge(id="3", source="low", target="switch", target_port="off"),
            Edge(id="4", source="switch", target="out"),
        ],
    )
    assert Engine(p).step()["outputs"]["out"] == 10
    p.nodes[0].params = {"value": False}
    assert Engine(p).step()["outputs"]["out"] == 2


@pytest.mark.parametrize("program", all_templates(), ids=lambda p: p.id)
def test_vav_examples_exercise_cooling_and_heating(program):
    engine = Engine(program)
    cool = engine.step({"zone": 80})["outputs"]
    assert 20 <= cool["damper"] <= 100
    warm = engine.step({"zone": 60})["outputs"]
    if "reheat" in warm:
        assert warm["reheat"] > 0 and cool["reheat"] == 0
    if "fan" in warm:
        assert warm["fan"] is True and cool["fan"] is False
