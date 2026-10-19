import pytest
from bms_tool.analysis import dependencies
from bms_tool.app import create_app
from bms_tool.models import Edge, Node, Program
from bms_tool.simulation_group import (
    SimulationGroup,
    SimulationGroups,
    SimulationWorkspace,
    demo_workspace,
)
from fastapi.testclient import TestClient


def accumulator(name):
    return Program(
        id=name,
        nodes=[
            Node(id="one", kind="Constant", params={"value": 1}),
            Node(id="memory", kind="Delay"),
            Node(id="sum", kind="Add"),
            Node(id="divisor", kind="Input", params={"default": 1}),
            Node(id="divide", kind="Divide"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="one", target="sum", target_port="a"),
            Edge(id="b", source="memory", target="sum", target_port="b"),
            Edge(id="c", source="sum", target="memory"),
            Edge(id="d", source="sum", target="divide", target_port="a"),
            Edge(id="e", source="divisor", target="divide", target_port="b"),
            Edge(id="f", source="divide", target="out"),
        ],
    )


def test_linked_programs_use_the_previous_cycle_and_external_inputs_persist():
    group = SimulationGroup(demo_workspace())
    first = group.step()
    assert first["programs"]["producer"]["outputs"] == {"signal": 42}
    assert first["programs"]["consumer"]["outputs"] == {"scaled": 0}
    assert group.step()["programs"]["consumer"]["outputs"] == {"scaled": 84}
    changed = group.step({"producer": {"value": 50}})
    assert changed["programs"]["producer"]["outputs"] == {"signal": 52}
    assert changed["programs"]["consumer"]["outputs"] == {"scaled": 84}
    assert group.step()["programs"]["consumer"]["outputs"] == {"scaled": 104}
    with pytest.raises(ValueError, match="linked input"):
        group.step({"consumer": {"incoming": 999}})


def test_failed_program_cannot_advance_another_programs_feedback_state():
    group = SimulationGroup(
        SimulationWorkspace(
            programs=[
                {"alias": "first", "program": accumulator("first")},
                {"alias": "second", "program": accumulator("second")},
            ]
        )
    )
    group.step()
    before = group.status()["programs"]
    with pytest.raises(ValueError, match="all programs remain"):
        group.step({"second": {"divisor": 0}})
    assert group.status()["programs"] == before
    assert group.time == 1
    recovered = group.step()
    assert [p["outputs"]["out"] for p in recovered["programs"].values()] == [2, 2]
    assert group.status()["last_fault"] is None


def test_shared_signal_feedback_does_not_depend_on_program_evaluation_order():
    definition = demo_workspace().model_dump()
    for item in definition["programs"]:
        item["program"] = Program(
            nodes=[
                Node(id="in", kind="Input"),
                Node(id="one", kind="Constant", params={"value": 1}),
                Node(id="add", kind="Add"),
                Node(id="out", kind="Output"),
            ],
            edges=[
                Edge(id="a", source="in", target="add", target_port="a"),
                Edge(id="b", source="one", target="add", target_port="b"),
                Edge(id="c", source="add", target="out"),
            ],
        ).model_dump()
    definition["links"] = [
        {
            "source_program": "producer",
            "source_output": "out",
            "target_program": "consumer",
            "target_input": "in",
            "initial": 0,
        },
        {
            "source_program": "consumer",
            "source_output": "out",
            "target_program": "producer",
            "target_input": "in",
            "initial": 0,
        },
    ]
    original = SimulationGroup(SimulationWorkspace.model_validate(definition))
    definition["programs"].reverse()
    reversed = SimulationGroup(SimulationWorkspace.model_validate(definition))
    for expected in range(1, 5):
        a, b = original.step(), reversed.step()
        assert {k: v["outputs"] for k, v in a["programs"].items()} == {
            k: v["outputs"] for k, v in b["programs"].items()
        }
        assert all(p["outputs"]["out"] == expected for p in a["programs"].values())


@pytest.mark.parametrize("failure", ["unit", "type", "writers", "period", "initial"])
def test_shared_signal_contracts_reject_incompatible_definitions(failure):
    definition = demo_workspace().model_dump()
    if failure == "unit":
        definition["programs"][1]["program"]["nodes"][0]["unit"] = "degF"
    elif failure == "type":
        definition["programs"][1]["program"]["nodes"][0]["value_type"] = "boolean"
    elif failure == "writers":
        definition["links"] *= 2
    elif failure == "period":
        definition["programs"][1]["program"]["scan_seconds"] = 2
    else:
        definition["links"][0]["initial"] = 10**1000
    with pytest.raises(ValueError):
        SimulationWorkspace.model_validate(definition)


def test_group_sessions_export_restore_expire_and_enforce_capacity():
    groups = SimulationGroups()
    sessions = [groups.start(demo_workspace())["session"] for _ in range(8)]
    with pytest.raises(ValueError, match="Close an existing"):
        groups.start(demo_workspace())
    exported = groups.export(sessions[0])
    groups.close(sessions[0])
    restored = groups.import_file(exported)
    assert restored["time"] == 0 and len(restored["definition"]["programs"]) == 2
    groups.sessions[restored["session"]]["touched"] -= 3601
    with pytest.raises(ValueError, match="expired"):
        groups.status(restored["session"])


def test_dependency_trace_handles_feedback_and_exposes_affected_outputs():
    program = accumulator("trace")
    result = dependencies(program, "sum")
    assert [n["id"] for n in result["affected_outputs"]] == ["out"]
    assert any(
        w["target"] == "memory" and w["previous_scan"] for w in result["feedback_boundaries"]
    )
    assert set(n["id"] for n in result["upstream"]) == {"one", "memory"}
    assert result["scan_index"] is not None and result["broken_links"] == 0
    with pytest.raises(ValueError, match="existing block"):
        dependencies(program, "missing")


def test_group_api_faults_hold_state_and_export_complete_definitions(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        definition = client.get("/api/groups/demo").json()
        result = client.post("/api/groups/start", json={"definition": definition}, headers=headers)
        assert result.status_code == 200, result.text
        token = result.json()["session"]
        stepped = client.post(
            "/api/groups/step", json={"session": token, "steps": 2}, headers=headers
        ).json()
        assert stepped["programs"]["consumer"]["outputs"] == {"scaled": 84}
        fault = client.post(
            "/api/groups/step",
            json={
                "session": token,
                "inputs": {"producer": {"value": {"value": None, "quality": "open-circuit"}}},
            },
            headers=headers,
        )
        assert fault.status_code == 422
        assert client.get("/api/groups/" + token).json()["time"] == 2
        exported = client.post("/api/groups/export", json={"session": token}, headers=headers)
        assert exported.json() == definition
        restored = client.post(
            "/api/groups/import",
            files={"file": ("workspace.bms-workspace.json", exported.content)},
            headers=headers,
        )
        assert restored.status_code == 200 and restored.json()["time"] == 0
        response = client.post(
            "/api/dependencies",
            json={"program": definition["programs"][0]["program"], "node": "value"},
            headers=headers,
        )
        assert response.json()["affected_outputs"][0]["id"] == "signal"
