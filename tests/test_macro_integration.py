"""Source hierarchy survives execution, interchange, online edits, and native builds."""

import io
import json
import zipfile
from datetime import UTC, datetime

import pytest
from bms_tool.app import create_app
from bms_tool.deployment import Runtime
from bms_tool.engine import Engine, validate
from bms_tool.formats import export_program, import_program
from bms_tool.models import Edge, Node, Program
from bms_tool.native_simulator import NativeSimulator
from bms_tool.sedona import toolchain
from bms_tool.simulation_group import ProgramInstance, SimulationGroup, SimulationWorkspace
from bms_tool.storage import Store
from fastapi.testclient import TestClient


def nested_rate_program():
    inner = Program(
        nodes=[
            Node(id="demand", kind="Input"),
            Node(id="limit", kind="Slew", params={"rate": 1, "initial": 0}),
            Node(id="result", kind="Output"),
        ],
        edges=[
            Edge(id="in", source="demand", target="limit"),
            Edge(id="out", source="limit", target="result"),
        ],
    )
    outer = Program(
        nodes=[
            Node(id="demand", kind="Input"),
            Node(id="nested", kind="Macro", params={"definition": "limiter"}),
            Node(id="result", kind="Output"),
        ],
        edges=[
            Edge(id="in", source="demand", target="nested", target_port="demand"),
            Edge(id="out", source="nested", target="result"),
        ],
    )
    return Program(
        id="nested-rate-integration",
        nodes=[
            Node(id="a", kind="Input", params={"default": 100}),
            Node(id="b", kind="Input", params={"default": -100}),
            Node(id="first", kind="Macro", params={"definition": "outer"}),
            Node(id="second", kind="Macro", params={"definition": "outer"}),
            Node(id="out_a", kind="Output"),
            Node(id="out_b", kind="Output"),
        ],
        edges=[
            Edge(id="a", source="a", target="first", target_port="demand"),
            Edge(id="b", source="b", target="second", target_port="demand"),
            Edge(id="ao", source="first", target="out_a"),
            Edge(id="bo", source="second", target="out_b"),
        ],
        metadata={
            "macros": {
                "version": 1,
                "definitions": [
                    {"id": "limiter", "name": "Limiter", "program": inner.model_dump(mode="json")},
                    {
                        "id": "outer",
                        "name": "Nested limiter",
                        "program": outer.model_dump(mode="json"),
                    },
                ],
            },
            "notes": "Hierarchy remains editable",
        },
    )


def has_sdk():
    try:
        sdk, _ = toolchain()
        return (sdk / "bin/svm-bms64").is_file()
    except ValueError:
        return False


def test_engine_retains_source_hash_hierarchy_and_independent_instance_state():
    program = nested_rate_program()
    digest = program.digest()
    engine = Engine(program)
    assert not [item for item in validate(program) if item.level == "error"]
    assert engine.program == program
    assert engine.graph != program
    assert not any(node.kind == "Macro" for node in engine.graph.nodes)
    assert engine.snapshot()["program_hash"] == digest
    assert engine.step()["outputs"] == {"out_a": 1, "out_b": -1}
    assert engine.step()["outputs"] == {"out_a": 2, "out_b": -2}
    assert len([node for node in engine.nodes.values() if node.kind == "Slew"]) == 2
    assert engine.program.digest() == digest == program.digest()
    assert len(engine.program.metadata["macros"]["definitions"]) == 2


@pytest.mark.parametrize(
    "format,suffix",
    [("json", "bms.json"), ("st", "st"), ("plcopen", "xml"), ("graphml", "graphml")],
)
def test_interchange_keeps_editable_macro_library_and_compiles_semantics(format, suffix):
    source = nested_rate_program()
    data, _, _ = export_program(source, format)
    restored = import_program(data, "nested." + suffix)
    assert restored == source
    assert restored.digest() == source.digest()
    assert Engine(restored).step()["outputs"] == {"out_a": 1, "out_b": -1}
    assert [node.kind for node in restored.nodes].count("Macro") == 2
    if format == "st":
        body = data.split(b"(* BMS_STUDIO_IR_V1", 1)[0]
        assert b"mn_" in body and b"Slew" not in body


def test_runtime_preserves_compatible_internal_state_and_resets_changed_control(tmp_path):
    source = nested_rate_program()
    runtime = Runtime(Store(tmp_path))
    runtime.apply(runtime.plan(source)["token"])
    runtime.engine.step()
    assert runtime.engine.outputs == {"out_a": 2, "out_b": -2}
    before = runtime.engine.snapshot()
    changed_label = source.model_copy(deep=True)
    changed_label.nodes[2].label = "Renamed existing instance"
    plan = runtime.plan(changed_label)
    assert not plan["diff"]["macro_definitions_changed"]
    runtime.apply(plan["token"])
    assert runtime.engine.outputs == {"out_a": 3, "out_b": -3}
    runtime.rollback(runtime.backups[-1]["id"], runtime.generation)
    assert runtime.engine.snapshot() == before
    changed_control = source.model_copy(deep=True)
    changed_control.metadata["macros"]["definitions"][0]["program"]["nodes"][1]["params"][
        "rate"
    ] = 10
    plan = runtime.plan(changed_control)
    assert plan["diff"]["macro_definitions_changed"]
    runtime.apply(plan["token"])
    assert runtime.engine.outputs == {"out_a": 10, "out_b": -10}
    assert runtime.engine.program == changed_control


def test_macro_api_catalog_portable_roundtrip_inspect_delete_and_instantiation(tmp_path):
    source = nested_rate_program().model_dump(mode="json")
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}

        def post(path, payload):
            response = client.post("/api/macros/" + path, json=payload, headers=headers)
            assert response.status_code == 200, response.text
            return response.json()

        catalog = post("catalog", {"program": source})
        assert {item["id"] for item in catalog["definitions"]} == {"limiter", "outer"}
        bundle = post("export", {"program": source, "definition": "outer"})
        imported = post("import", {"program": Program().model_dump(mode="json"), "bundle": bundle})
        inspected = post("definition", {"program": imported, "definition": "outer"})
        assert any(node["kind"] == "Macro" for node in inspected["nodes"])
        added = post(
            "instantiate", {"program": imported, "definition": "outer", "x": 120, "y": 200}
        )
        assert added["nodes"][-1]["kind"] == "Macro"
        denied = client.post(
            "/api/macros/delete", json={"program": added, "definition": "limiter"}, headers=headers
        )
        assert denied.status_code == 422
        removed = post("delete", {"program": imported, "definition": "outer"})
        assert [item["id"] for item in post("catalog", {"program": removed})["definitions"]] == [
            "limiter"
        ]


def test_shared_simulation_counts_expanded_blocks_not_only_compact_instances():
    inner = Program(
        nodes=[
            *[Node(id=f"value{index}", kind="Constant") for index in range(1495)],
            Node(id="out", kind="Output"),
        ],
        edges=[Edge(id="publish", source="value0", target="out")],
    )
    source = Program(
        nodes=[
            Node(id="macro", kind="Macro", params={"definition": "large"}),
            Node(id="out", kind="Output"),
        ],
        edges=[Edge(id="publish", source="macro", target="out")],
        metadata={
            "macros": {
                "version": 1,
                "definitions": [
                    {"id": "large", "name": "Large graph", "program": inner.model_dump(mode="json")}
                ],
            }
        },
    )
    workspace = SimulationWorkspace(
        programs=[ProgramInstance(alias=f"copy{index}", program=source) for index in range(3)]
    )
    assert sum(len(item.program.nodes) for item in workspace.programs) == 6
    with pytest.raises(ValueError, match="4,000 expanded blocks"):
        SimulationGroup(workspace)


@pytest.mark.skipif(not has_sdk(), reason="Build optional pinned native toolchain first")
def test_native_nested_macros_execute_save_and_reimport_original_library(tmp_path):
    native = NativeSimulator(Store(tmp_path))
    source = nested_rate_program()
    try:
        started = native.start(source)
        assert (
            started["program"]["metadata"]["macros"]
            == source.model_dump(mode="json")["metadata"]["macros"]
        )
        for number in (1, 2):
            row = native.step()
            assert row["matches_reference"] and not row["fault"], row
            assert row["outputs"] == {"out_a": number, "out_b": -number}
        saved = native.save(0)
        assert saved.revision == 1
        assert saved.metadata["macros"] == source.metadata["macros"]
        bundle, _, _ = export_program(native.snapshot_program(), "sedona")
        restored = import_program(bundle, "nested.sedona.zip")
        assert restored == saved
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert (
                json.loads(archive.read("program.bms.json"))["metadata"]["macros"]
                == source.model_dump(mode="json")["metadata"]["macros"]
            )
            assert b"mn_" in archive.read("Graph.sedona")
            assert archive.read("app.sab") != archive.read("program.bms.json")
    finally:
        native.stop()


@pytest.mark.skipif(not has_sdk(), reason="Build optional pinned native toolchain first")
def test_native_nested_boolean_calendar_uses_expanded_host_binding(tmp_path):
    inner = Program(
        nodes=[
            Node(
                id="occupied",
                kind="Schedule",
                params={
                    "timezone": "America/Los_Angeles",
                    "exceptions": [{"date": "2026-01-06", "enabled": False}],
                },
            ),
            Node(id="out", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="publish", source="occupied", target="out")],
    )
    outer = Program(
        nodes=[
            Node(
                id="calendar", kind="Macro", params={"definition": "calendar"}, value_type="boolean"
            ),
            Node(id="out", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="publish", source="calendar", target="out")],
    )
    source = Program(
        nodes=[
            Node(id="outer", kind="Macro", params={"definition": "outer"}, value_type="boolean"),
            Node(id="out", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="publish", source="outer", target="out")],
        metadata={
            "macros": {
                "version": 1,
                "definitions": [
                    {
                        "id": "calendar",
                        "name": "Calendar",
                        "program": inner.model_dump(mode="json"),
                    },
                    {
                        "id": "outer",
                        "name": "Nested calendar",
                        "program": outer.model_dump(mode="json"),
                    },
                ],
            }
        },
    )
    native = NativeSimulator(Store(tmp_path))
    try:
        native.start(source)
        occupied = native.step(clock=datetime(2026, 1, 5, 17, tzinfo=UTC))
        closed = native.step(clock=datetime(2026, 1, 6, 17, tzinfo=UTC))
        assert occupied["outputs"]["out"] is True and occupied["matches_reference"]
        assert closed["outputs"]["out"] is False and closed["matches_reference"]
    finally:
        native.stop()
