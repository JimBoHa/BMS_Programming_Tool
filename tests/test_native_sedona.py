"""Integration tests compile real kits/SAB and communicate with the native SVM."""

import io
import json
import re
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime

import pytest
from bms_tool.blocks import BLOCKS
from bms_tool.engine import input_type, output_type
from bms_tool.formats import export_program, import_program
from bms_tool.models import Edge, Node, Program
from bms_tool.native_simulator import NativeSimulator
from bms_tool.sedona import compiler, toolchain
from bms_tool.storage import Store
from bms_tool.temperature import TEMPERATURE_BLOCKS, input_units
from bms_tool.templates import all_templates


def has_sdk():
    try:
        sdk, _ = toolchain()
        return (sdk / "bin/svm-bms64").is_file()
    except ValueError:
        return False


pytestmark = pytest.mark.skipif(
    not has_sdk(), reason="Build optional pinned native toolchain first"
)


@pytest.fixture
def native(tmp_path):
    simulator = NativeSimulator(Store(tmp_path))
    yield simulator
    simulator.stop()


def block_program(kind):
    node = Node(id="block", kind=kind, unit=BLOCKS[kind].unit)
    if kind == "Input":
        node.params = {"default": 2.5}
    if kind == "Constant":
        node.params = {"value": -3.25}
    if kind == "Convert":
        node.unit = "degC"
    if kind == "Alarm":
        node.params = {"limit": 1, "delay": 2}
    if kind == "TimerOn":
        node.params = {"seconds": 2}
    nodes, edges = [node], []
    for i, port in enumerate(BLOCKS[kind].inputs):
        boolean = input_type(node, port) == "boolean"
        source = Node(
            id=f"input{i}",
            kind="Input",
            value_type="boolean" if boolean else "number",
            params={"default": True if boolean else 4 if i == 0 else 2},
        )
        if kind == "Convert":
            source.unit = "degF"
        if kind in TEMPERATURE_BLOCKS:
            source.unit = input_units(kind, BLOCKS[kind].parameters, node.unit)[port]
        nodes.append(source)
        edges.append(Edge(id=f"edge{i}", source=source.id, target=node.id, target_port=port))
    nodes.append(Node(id="out", kind="Output", value_type=output_type(node), unit=node.unit))
    edges.append(Edge(id="result", source=node.id, target="out"))
    return Program(id="native-" + kind, nodes=nodes, edges=edges)


@pytest.mark.parametrize("kind", list(BLOCKS))
def test_every_block_compiles_and_executes_in_the_native_vm(native, kind):
    native.start(block_program(kind))
    for scan in range(3):
        row = native.step()
        assert row["execution"] == "compiled Sedona SCode via native SVM"
        assert row["successful_scans"] == scan + 1
        assert row["matches_reference"] and not row["fault"], row


@pytest.mark.parametrize("index", range(9))
def test_vav_examples_execute_as_sedona_without_claiming_jci_deployment(native, index):
    native.start(all_templates()[index])
    for zone in (80, 60, 73):
        assert native.step({"zone": zone})["matches_reference"]


def test_native_fault_does_not_advance_state_or_publish_partial_outputs(native):
    native.start(all_templates()[1])
    before = native.step({"zone": 80})
    failed = native.step({"zone": {"value": None, "quality": "open-circuit"}})
    assert failed["fault"] and failed["matches_reference"]
    assert failed["outputs"] == before["outputs"]
    assert failed["successful_scans"] == before["successful_scans"]
    recovered = native.step({"zone": 60})
    assert recovered["matches_reference"] and not recovered["fault"]
    assert recovered["successful_scans"] == 2


def test_native_calendar_uses_explicit_host_binding_and_unbound_calendar_holds_output(native):
    from tests.test_calendar_integration import calendar_program

    native.start(calendar_program())
    occupied = native.step(clock=datetime(2026, 1, 5, 17, tzinfo=UTC))
    assert occupied["outputs"]["out"] and occupied["matches_reference"]
    holiday = native.step(clock=datetime(2026, 1, 6, 17, tzinfo=UTC))
    assert not holiday["outputs"]["out"] and holiday["matches_reference"]
    native._request(
        [
            {
                "op": "write",
                "path": "/logic/graph",
                "slot": "n_occupied_calendar_valid",
                "value": "false",
            },
            {"op": "invoke", "path": "/logic/graph", "slot": "step"},
        ]
    )
    result = native._request(
        [
            {"op": "read", "path": "/logic/graph", "slot": "StudioFault"},
            {"op": "read", "path": "/logic/graph", "slot": "successfulScans"},
            {"op": "read", "path": "/logic/graph", "slot": "n_out"},
        ]
    )
    values = {r.get("slot"): r.get("value") for r in result.findall("read")}
    assert values == {"StudioFault": "true", "successfulScans": "2", "n_out": "false"}


def test_native_nan_guard_uses_sedona_null_semantics(native):
    native.start(all_templates()[0])
    native._request(
        [
            {"op": "write", "path": "/logic/graph", "slot": "n_zone", "value": "null"},
            {"op": "invoke", "path": "/logic/graph", "slot": "step"},
        ]
    )
    result = native._request(
        [
            {"op": "read", "path": "/logic/graph", "slot": "StudioFault"},
            {"op": "read", "path": "/logic/graph", "slot": "successfulScans"},
        ]
    )
    assert [r.get("value") for r in result.findall("read")] == ["true", "0"]


def test_native_late_scan_fault_holds_all_outputs_and_feedback_state(native):
    program = Program(
        nodes=[
            Node(id="denominator", kind="Input", params={"default": 1}),
            Node(id="one", kind="Constant", params={"value": 1}),
            Node(id="memory", kind="Delay"),
            Node(id="sum", kind="Add"),
            Node(id="ratio", kind="Divide"),
            Node(id="early", kind="Output"),
            Node(id="late", kind="Output"),
        ],
        edges=[
            Edge(id="1", source="one", target="sum", target_port="a"),
            Edge(id="2", source="memory", target="sum", target_port="b"),
            Edge(id="3", source="sum", target="memory"),
            Edge(id="4", source="sum", target="ratio", target_port="a"),
            Edge(id="5", source="denominator", target="ratio", target_port="b"),
            Edge(id="6", source="sum", target="early"),
            Edge(id="7", source="ratio", target="late"),
        ],
    )
    native.start(program)
    assert native.step()["outputs"] == {"early": 1, "late": 1}
    failed = native.step({"denominator": 0})
    assert failed["fault"] and failed["matches_reference"]
    assert failed["outputs"] == {"early": 1, "late": 1}
    recovered = native.step()
    assert recovered["matches_reference"] and recovered["successful_scans"] == 2
    assert recovered["outputs"] == {"early": 2, "late": 2}


def test_native_feedback_and_explicit_calendar(native):
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
    native.start(p)
    assert [native.step()["outputs"]["out"] for _ in range(4)] == [1, 2, 3, 4]
    native.start(block_program("Schedule"))
    on = native.step(clock=datetime(2026, 1, 5, 9, tzinfo=UTC))
    off = native.step(clock=datetime(2026, 1, 10, 9, tzinfo=UTC))
    assert on["outputs"]["out"] is True and off["outputs"]["out"] is False
    assert on["matches_reference"] and off["matches_reference"]


def test_native_bundle_contains_real_binary_and_is_independently_decoded(tmp_path):
    p = all_templates()[2]
    bundle, mime, extension = export_program(p, "sedona")
    assert (mime, extension) == ("application/zip", "sedona.zip")
    assert import_program(bundle, "application.sedona.zip").model_dump() == p.model_dump()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read("app.sab") != archive.read("program.bms.json")
        assert b"AFL" in archive.read("Sedona-LICENSE.md")
        assert b"SoxService" not in archive.read("app.sax")
        assert b'<prop name="autoScan" val="true"' in archive.read("app.sax")
        binary = tmp_path / "native.sab"
        binary.write_bytes(archive.read("app.sab"))
        sdk, java = toolchain()
        compiler(sdk, java, binary, "-outDir", tmp_path)
        decoded = (tmp_path / "native.sax").read_text()
        assert manifest["kit"] + "::Graph" in decoded
        assert "BMS_STUDIO_IR" not in decoded


def test_native_automatic_scanning_runs_without_manual_step(native):
    native.start(all_templates()[0])
    native._request(
        [
            {"op": "write", "path": "/logic/graph", "slot": "n_zone", "value": "80"},
            {"op": "write", "path": "/logic/graph", "slot": "autoScan", "value": "true"},
        ]
    )
    result = native._request(
        [
            {"op": "read", "path": "/logic/graph", "slot": "successfulScans"},
            {"op": "read", "path": "/logic/graph", "slot": "n_damper"},
            {"op": "write", "path": "/logic/graph", "slot": "autoScan", "value": "false"},
        ]
    )
    assert int(result.findall("read")[0].get("value")) > 0
    assert float(result.findall("read")[1].get("value")) == 100
    first = (
        native._request([{"op": "read", "path": "/logic/graph", "slot": "successfulScans"}])
        .find("read")
        .get("value")
    )
    second = (
        native._request([{"op": "read", "path": "/logic/graph", "slot": "successfulScans"}])
        .find("read")
        .get("value")
    )
    assert first == second  # Explicit pause leaves no background scan advancing state.


def test_native_structural_changes_are_preflighted_applied_and_rolled_back(native):
    native.start(all_templates()[0])
    native.step({"zone": 80})
    plan = native.plan(
        [
            {"op": "add", "path": "/online", "name": "sensor", "type": "types::WriteFloat"},
            {"op": "write", "path": "/online/sensor", "slot": "in", "value": "null"},
        ]
    )
    assert not any(c["path"] == "/online/sensor" for c in native.inspect()["components"])
    applied = native.apply(plan["token"])
    sensor = next(c for c in applied["inventory"]["components"] if c["path"] == "/online/sensor")
    assert next(p for p in sensor["properties"] if p["name"] == "in")["value"] == "null"
    assert (
        native.step({"zone": 80})["successful_scans"] == 2
    )  # Unchanged application state retained.
    with pytest.raises(ValueError, match="consumed"):
        native.apply(plan["token"])
    restored = native.rollback(applied["backup_id"], native.generation)
    assert not any(c["path"] == "/online/sensor" for c in restored["inventory"]["components"])
    assert native.step({"zone": 80})["successful_scans"] == 3


def test_bad_native_plan_never_changes_the_active_controller(native):
    native.start(all_templates()[0])
    with pytest.raises(ValueError):
        native.plan(
            [
                {"op": "add", "path": "/online", "type": "types::WriteFloat", "name": "sensor"},
                {"op": "write", "path": "/online/sensor", "slot": "nonexistent", "value": "10"},
            ]
        )
    assert not any(c["path"] == "/online/sensor" for c in native.inspect()["components"])
    with pytest.raises(ValueError, match="confined"):
        native.plan([{"op": "delete", "path": "/service"}])


def test_native_links_run_in_the_vm_and_rollback_restores_linked_configuration(native):
    native.start(all_templates()[0])
    operations = [
        {"op": "add", "path": "/online", "type": "types::WriteFloat", "name": "a"},
        {"op": "write", "path": "/online/a", "slot": "in", "value": "40"},
        {"op": "add", "path": "/online", "type": "types::ConstFloat", "name": "b"},
        {"op": "write", "path": "/online/b", "slot": "out", "value": "2"},
        {"op": "add", "path": "/online", "type": "math::Add2", "name": "sum"},
        {
            "op": "link",
            "path": "/online/a",
            "slot": "out",
            "target": "/online/sum",
            "target_slot": "in1",
        },
        {
            "op": "link",
            "path": "/online/b",
            "slot": "out",
            "target": "/online/sum",
            "target_slot": "in2",
        },
    ]
    native.apply(native.plan(operations)["token"])
    time.sleep(0.1)
    result = native._request([{"op": "read", "path": "/online/sum", "slot": "out"}])
    assert float(result.find("read").get("value")) == 42
    changed = native.apply(
        native.plan([{"op": "write", "path": "/online/a", "slot": "in", "value": "90"}])["token"]
    )
    restored = native.rollback(changed["backup_id"], native.generation)
    a = next(c for c in restored["inventory"]["components"] if c["path"] == "/online/a")
    assert next(p for p in a["properties"] if p["name"] == "in")["value"] == "40.0"
    result = native._request([{"op": "read", "path": "/online/sum", "slot": "out"}])
    assert float(result.find("read").get("value")) == 42


def test_native_readback_mismatch_compensates_the_partial_change(native, monkeypatch):
    native.start(all_templates()[0])
    plan = native.plan(
        [
            {"op": "add", "path": "/online", "name": "sensor", "type": "types::WriteFloat"},
            {"op": "write", "path": "/online/sensor", "slot": "in", "value": "null"},
        ]
    )
    request = native._request

    def dropped_write(operations):
        return request(
            [
                op
                for op in operations
                if not (op["op"] == "write" and op["path"] == "/online/sensor")
            ]
        )

    monkeypatch.setattr(native, "_request", dropped_write)
    with pytest.raises(ValueError, match="readback differs"):
        native.apply(plan["token"])
    assert not any(c["path"] == "/online/sensor" for c in native.inspect()["components"])
    assert native.step({"zone": 80})["matches_reference"]
    assert any(row["operation"] == "native.online.compensated" for row in native.store.audit())


def test_upstream_vm_core_value_semantics_pass():
    sdk, _ = toolchain()
    # Avoid upstream's external-host timeout tests and AppTest's documented
    # dangling-pointer callback assertions. No test here contacts a field network.
    for prefix in (
        "sys::BoolTest",
        "sys::FloatTest",
        "sys::IntTest",
        "sys::LongTest",
        "sys::DoubleTest",
    ):
        result = subprocess.run(
            [str(sdk / "bin/svm-bms64"), str(sdk / "build/test-bms64.scode"), "-utest", prefix],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Assert Failures  = 0" in result.stdout
        assert int(re.search(r"Assert Successes = (\d+)", result.stdout)[1]) > 0


def test_native_compiler_database_is_safe_across_independent_processes(tmp_path):
    script = """from pathlib import Path
from bms_tool.formats import export_program
from bms_tool.templates import all_templates
import sys
Path(sys.argv[1]).write_bytes(export_program(all_templates()[0], 'sedona')[0])
"""
    outputs = [tmp_path / f"build-{i}.zip" for i in range(2)]
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(output)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for output in outputs
    ]
    for process in processes:
        stdout, stderr = process.communicate(timeout=45)
        assert process.returncode == 0, stdout + stderr
    for path in outputs:
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert archive.read("app.sab").startswith(b"sapp")


def test_saved_native_application_retains_added_inputs_links_and_null_after_reload(native):
    native.start(all_templates()[0])
    operations = [
        {"op": "add", "path": "/online", "name": "sensor", "type": "types::WriteFloat"},
        {"op": "write", "path": "/online/sensor", "slot": "in", "value": "null"},
        {"op": "add", "path": "/online", "name": "a", "type": "types::ConstFloat"},
        {"op": "write", "path": "/online/a", "slot": "out", "value": "40"},
        {"op": "add", "path": "/online", "name": "b", "type": "types::ConstFloat"},
        {"op": "write", "path": "/online/b", "slot": "out", "value": "2"},
        {"op": "add", "path": "/online", "name": "sum", "type": "math::Add2"},
        {
            "op": "link",
            "path": "/online/a",
            "slot": "out",
            "target": "/online/sum",
            "target_slot": "in1",
        },
        {
            "op": "link",
            "path": "/online/b",
            "slot": "out",
            "target": "/online/sum",
            "target_slot": "in2",
        },
    ]
    native.apply(native.plan(operations)["token"])
    native.step()
    saved = native.save(0)
    assert native.step()["successful_scans"] == 2  # Saving does not restart the controller.
    document = saved.metadata["native_sedona"]
    assert len(document["components"]) == 4 and len(document["links"]) == 2
    restored = native.store.load(saved.id, 1)
    bundle = export_program(restored, "sedona")[0]
    imported = import_program(bundle, "saved.sedona.zip")
    native.start(imported)
    result = native._request(
        [
            {"op": "read", "path": "/online/sum", "slot": "out"},
            {"op": "read", "path": "/online/sensor", "slot": "in"},
        ]
    )
    assert [r.get("value") for r in result.findall("read")] == ["42.0", "null"]
    assert native.step()["matches_reference"]
    from bms_tool.engine import Engine

    with pytest.raises(ValueError, match="Native sim"):
        Engine(imported)
    for format in ("st", "plcopen", "graphml"):
        with pytest.raises(ValueError, match="native Sedona"):
            export_program(imported, format)


def test_native_runtime_only_writes_are_not_misrepresented_as_saved_configuration(native):
    native.start(all_templates()[0])
    with pytest.raises(ValueError, match="runtime-only"):
        native.plan(
            [
                {"op": "add", "path": "/online", "name": "sum", "type": "math::Add2"},
                {"op": "write", "path": "/online/sum", "slot": "in1", "value": "42"},
            ]
        )
    assert not any(c["path"] == "/online/sum" for c in native.inspect()["components"])
