import pytest
from bms_tool.app import create_app
from bms_tool.engine import Engine, run_scenario
from bms_tool.models import Edge, Node, Program
from fastapi.testclient import TestClient


def rate_program():
    return Program(
        nodes=[
            Node(id="input", kind="Input", params={"default": 100}),
            Node(id="rate", kind="Slew", params={"rate": 1, "initial": 0}),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="input", target="rate"),
            Edge(id="b", source="rate", target="out"),
        ],
    )


def test_internal_force_keeps_underlying_state_and_releases_without_a_jump():
    engine = Engine(rate_program())
    first = engine.step(forces={"rate": 50})
    assert first["outputs"] == {"out": 50}
    assert first["computed"] == {"rate": 1}
    second = engine.step()
    assert second["values"]["rate"] == 50 and second["computed"] == {"rate": 2}
    released = engine.step(forces={})
    assert released["outputs"] == {"out": 3} and released["forces"] == {}


def test_forces_do_not_bypass_sensor_faults_or_commit_new_overrides_after_failure():
    engine = Engine(rate_program())
    engine.step(forces={"rate": 50})
    before = engine.snapshot()
    with pytest.raises(ValueError, match="open-circuit"):
        engine.step(
            {"input": {"value": None, "quality": "open-circuit"}}, forces={"input": 100, "rate": 90}
        )
    assert engine.snapshot() == before
    assert engine.step()["forces"] == {"rate": 50}


def test_releasing_one_force_keeps_other_requested_holds():
    engine = Engine(rate_program())
    engine.step(forces={"rate": 50, "out": 20})
    row = engine.step(forces={"rate": 60})
    assert row["forces"] == {"rate": 60}
    assert row["outputs"] == {"out": 60} and row["computed"]["rate"] == 2


@pytest.mark.parametrize(
    "forces",
    [{"missing": 1}, {"rate": True}, {"rate": "1"}, {"rate": float("nan")}, {"rate": 10**1000}],
)
def test_invalid_force_values_leave_simulation_unchanged(forces):
    engine = Engine(rate_program())
    before = engine.snapshot()
    with pytest.raises(ValueError, match="force|forces"):
        engine.step(forces=forces)
    assert engine.snapshot() == before


def test_alarm_force_trace_and_alarm_list_agree():
    program = rate_program()
    program.nodes[1] = Node(id="rate", kind="Alarm", params={"limit": 0, "delay": 0})
    program.nodes[2].value_type = "boolean"
    row = Engine(program).step(forces={"rate": False})
    assert row["computed"] == {"rate": True}
    assert row["outputs"] == {"out": False} and row["alarms"] == []


def test_scenario_force_events_hold_and_release_at_repeatable_scan_boundaries():
    rows = run_scenario(
        rate_program(), [{"time": 0, "forces": {"rate": 50}}, {"time": 2, "forces": {}}], duration=4
    )
    assert [r["outputs"]["out"] for r in rows] == [50, 50, 3, 4]
    assert [r["forces"] for r in rows] == [{"rate": 50}, {"rate": 50}, {}, {}]
    with pytest.raises(ValueError, match="requires a time"):
        run_scenario(rate_program(), [{"forces": {}}], 4)


def test_simulation_api_retains_and_releases_forces_without_editing_program(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        program = rate_program().model_dump()
        forced = client.post(
            "/api/simulation/step",
            json={"program": program, "forces": {"rate": 50}},
            headers=headers,
        ).json()
        assert forced["last"]["outputs"] == {"out": 50}
        released = client.post(
            "/api/simulation/step",
            json={"program": program, "session": forced["session"], "forces": {}},
            headers=headers,
        ).json()
        assert released["last"]["outputs"] == {"out": 2}
        assert rate_program().model_dump() == program
