"""Compile exported ST with upstream MatIEC and execute actual native machine code."""

import json
import os
import shutil
import signal
import time
from datetime import UTC, datetime

import pytest
from bms_tool.blocks import BLOCKS
from bms_tool.engine import input_type, output_type
from bms_tool.formats import ConversionError, export_st
from bms_tool.iec import (
    NativeIEC,
    _tool_lock,
    compile_program,
    profile,
    toolchain,
    verify_program,
    verify_scenario,
)
from bms_tool.models import Edge, Node, Program
from bms_tool.templates import all_templates

requires_compiler = pytest.mark.skipif(
    not profile()["available"], reason="Run scripts/setup_iec.py for optional pinned IEC compiler"
)


def block_program(kind):
    node = Node(id="block", kind=kind)
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
    for index, port in enumerate(BLOCKS[kind].inputs):
        boolean = input_type(node, port) == "boolean"
        source = Node(
            id=f"input{index}",
            kind="Input",
            value_type="boolean" if boolean else "number",
            params={"default": True if boolean else 4 if index == 0 else 2},
            unit="degF" if kind == "Convert" else "",
        )
        nodes.append(source)
        edges.append(Edge(id=f"edge{index}", source=source.id, target=node.id, target_port=port))
    nodes.append(Node(id="out", kind="Output", value_type=output_type(node), unit=node.unit))
    edges.append(Edge(id="result", source=node.id, target="out"))
    return Program(id="iec-" + kind, nodes=nodes, edges=edges)


@requires_compiler
@pytest.mark.parametrize("kind", list(BLOCKS))
def test_all_27_blocks_compile_to_native_machine_code_and_match_graph_reference(kind):
    with NativeIEC(block_program(kind)) as native:
        for index in range(3):
            row = native.step(clock=datetime(2026, 1, 5, 12, 0, index, tzinfo=UTC))
            assert row["execution"] == "compiled IEC Structured Text via MatIEC/native C"
            assert row["successful_scans"] == index + 1
            assert not row["fault"] and row["matches_reference"], row


@requires_compiler
@pytest.mark.parametrize("index", range(9))
def test_all_nine_vav_graphs_execute_as_iec_without_claiming_jci_download(index):
    with NativeIEC(all_templates()[index]) as native:
        for zone in (80, 60, 73):
            row = native.step({"zone": zone})
            assert row["matches_reference"] and not row["fault"], row


@requires_compiler
def test_late_scan_divide_fault_holds_every_output_and_feedback_state_until_recovery():
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
    with NativeIEC(program) as native:
        before = native.step()
        assert before["outputs"] == {"early": 1, "late": 1}
        failed = native.step({"denominator": 0})
        assert failed["fault"] and failed["matches_reference"]
        assert failed["outputs"] == before["outputs"]
        assert failed["native_state"] == before["native_state"]
        assert failed["successful_scans"] == 1
        recovered = native.step()
        assert recovered["matches_reference"] and not recovered["fault"]
        assert recovered["outputs"] == {"early": 2, "late": 2}


@requires_compiler
def test_open_sensor_quality_fails_in_native_st_and_holds_state_then_recovers():
    with NativeIEC(all_templates()[1]) as native:
        before = native.step({"zone": 73})
        failed = native.step({"zone": {"value": None, "quality": "open-circuit"}})
        assert failed["fault"] and failed["matches_reference"]
        assert failed["outputs"] == before["outputs"]
        assert failed["native_state"] == before["native_state"]
        assert failed["successful_scans"] == 1
        assert native.step({"zone": 60})["matches_reference"]


@requires_compiler
def test_float32_overflow_fault_is_exposed_as_difference_from_float64_reference():
    with NativeIEC(block_program("Multiply")) as native:
        before = native.step()
        failed = native.step({"input0": 3e38, "input1": 2})
        assert failed["fault"] and not failed["matches_reference"]
        assert failed["reference_fault"] is None
        assert failed["outputs"] == before["outputs"]
        assert failed["native_state"] == before["native_state"]
        assert failed["successful_scans"] == 1
        assert native.step()["matches_reference"]


@requires_compiler
@pytest.mark.parametrize("kind", ["Input", "Constant"])
@pytest.mark.parametrize("value", [1e30, 1e-30, -1e-30])
def test_scientific_literals_compile_in_actual_iec_and_keep_finite_nonzero_values(kind, value):
    program = block_program(kind)
    program.nodes[0].params = {"default" if kind == "Input" else "value": value}
    with NativeIEC(program) as native:
        row = native.step()
        assert row["matches_reference"] and not row["fault"], row
        assert row["outputs"]["out"] != 0
        assert row["outputs"]["out"] == pytest.approx(value, rel=1e-6, abs=0)
        assert "1.0E" in native.source_st


@requires_compiler
def test_scientific_defaults_compile_before_native_overflow_is_reported():
    program = block_program("Multiply")
    for node in program.nodes:
        if node.kind == "Input":
            node.params = {"default": 1e30}
    report = verify_program(program)
    assert report["native_runtime_verified"] and not report["matches_reference"]
    row = report["rows"][0]
    assert row["fault"] and row["reference_fault"] is None
    assert row["outputs"] == {"out": 0}
    assert row["reference_outputs"]["out"] == pytest.approx(1e60)
    assert row["successful_scans"] == 0


@requires_compiler
def test_calendar_timezone_holiday_and_missing_host_binding_have_explicit_native_guards():
    from tests.test_calendar_integration import calendar_program

    with NativeIEC(calendar_program()) as native:
        occupied = native.step(clock=datetime(2026, 1, 5, 17, tzinfo=UTC))
        assert occupied["outputs"]["out"] and occupied["matches_reference"]
        failed = native.step(clock=datetime(2026, 1, 6, 17, tzinfo=UTC), calendar_bindings={})
        assert failed["fault"] and failed["matches_reference"]
        assert failed["host_calendar_fault"]
        assert failed["outputs"] == occupied["outputs"]
        assert failed["successful_scans"] == 1
        holiday = native.step(clock=datetime(2026, 1, 6, 17, tzinfo=UTC))
        assert not holiday["outputs"]["out"] and holiday["matches_reference"]


@requires_compiler
def test_nested_macros_compile_to_independent_native_state():
    from tests.test_macro_integration import nested_rate_program

    program = nested_rate_program()
    digest = program.digest()
    with NativeIEC(program) as native:
        first = native.step()
        second = native.step()
        assert first["outputs"] == {"out_a": 1, "out_b": -1}
        assert second["outputs"] == {"out_a": 2, "out_b": -2}
        assert first["matches_reference"] and second["matches_reference"]
        assert len(second["native_state"]) == 2
    assert program.digest() == digest


@requires_compiler
@pytest.mark.parametrize("kind", ["TimerOn", "Alarm"])
def test_timer_and_alarm_native_state_reset_after_false_then_require_full_delay(kind):
    with NativeIEC(block_program(kind)) as native:
        off = False if kind == "TimerOn" else 0
        on = True if kind == "TimerOn" else 4
        rows = [native.step({"input0": value}) for value in (on, on, off, on, on)]
        assert [row["outputs"]["out"] for row in rows] == [False, True, False, False, True]
        assert all(row["matches_reference"] and not row["fault"] for row in rows)


@requires_compiler
def test_boolean_memory_and_stateful_pi_antiwindup_survive_actual_native_scans():
    delay = block_program("Delay")
    for node in delay.nodes:
        node.value_type = "boolean"
    delay.nodes[0].params = {"initial": False}
    delay.nodes[1].params = {"default": True}
    with NativeIEC(delay) as native:
        assert native.step()["outputs"]["out"] is False
        row = native.step()
        assert row["outputs"]["out"] is True and row["matches_reference"]
    pi = block_program("PI")
    pi.nodes[0].params = {"kp": 1, "ki": 1, "min": 0, "max": 10}
    with NativeIEC(pi) as native:
        saturated = native.step({"input0": 100, "input1": 0})
        assert saturated["outputs"]["out"] == 10
        assert saturated["native_state"]["n_block_integral"] == 0
        recovered = native.step({"input0": 1, "input1": 0})
        assert recovered["outputs"]["out"] == 2 and recovered["matches_reference"]


@requires_compiler
def test_invalid_input_bounds_and_types_do_not_advance_the_native_process():
    with NativeIEC(block_program("Slew")) as native:
        for value in ("4", True, None, float("nan"), float("inf"), 10**1000, 1e-50):
            with pytest.raises(ValueError):
                native.step({"input0": value})
        for dt in (0, -1, 61, float("nan"), True, 10**1000, 1e-50):
            with pytest.raises(ValueError):
                native.step(dt=dt)
        for inputs in ({"not_a_point": 1}, {"input0": {"value": 1, "extra": 2}}):
            with pytest.raises(ValueError):
                native.step(inputs)
        with pytest.raises(ValueError, match="timezone-aware"):
            native.step(clock=datetime(2026, 1, 5))
        with pytest.raises(ValueError, match="timezone-aware"):
            native.step(clock=False)
        assert native.attempts == 0
        assert native.step()["successful_scans"] == 1
    with NativeIEC(block_program("Not")) as native:
        with pytest.raises(ValueError, match="Boolean"):
            native.step({"input0": 1})


@requires_compiler
def test_compilation_reports_real_c_source_without_claiming_execution_verification():
    program = block_program("Add")
    report = compile_program(program)
    assert report["compiled"] and not report["native_runtime_verified"]
    assert report["source_st"].encode() == export_st(program, embedded=False)
    assert "MAIN_body__" in report["generated_c"]
    assert report["program_sha256"] == program.digest()
    assert report["profile"]["provenance"]["library_sha256"]
    assert not report["profile"]["physical_io"]
    assert not report["profile"]["controller_download"]
    assert report["warnings"]["count"] >= 1
    assert "varargs" in report["warnings"]["categories"]


@requires_compiler
def test_timed_scenario_runs_native_steps_and_exposes_scan_aligned_event_application():
    report = verify_scenario(
        block_program("Slew").model_dump(),
        [{"time": 0, "inputs": {"input0": 10}}, {"time": 2, "inputs": {"input0": -10}}],
        duration=4,
        dt=1,
    )
    assert report["native_runtime_verified"] and report["matches_reference"]
    assert [row["outputs"]["out"] for row in report["rows"]] == [1, 2, 1, 0]
    assert [row["successful_scans"] for row in report["rows"]] == [1, 2, 3, 4]
    single = verify_program(block_program("Add"), scans=2)
    assert single["matches_reference"] and len(single["rows"]) == 2


@pytest.mark.parametrize(
    "events,duration,dt",
    [
        ([], 1001, 1),
        ([], 10**1000, 1),
        ([], 1, 10**1000),
        ([{"time": 10**1000, "inputs": {}}], 4, 1),
        ([{"time": 1, "inputs": {}, "forces": {"out": 10}}], 4, 1),
    ],
)
def test_scenario_bounds_reject_before_compiling(events, duration, dt):
    with pytest.raises(ValueError):
        verify_scenario(block_program("Slew"), events, duration, dt)


@requires_compiler
def test_scenario_quality_fault_is_recorded_and_recovery_resumes_retained_native_state():
    report = verify_scenario(
        block_program("Slew"),
        [
            {"time": 0, "inputs": {"input0": 10}},
            {"time": 1, "inputs": {"input0": {"quality": "open-circuit"}}},
            {"time": 2, "inputs": {"input0": 10}},
        ],
        3,
    )
    assert report["matches_reference"]
    assert [row["fault"] for row in report["rows"]] == [False, True, False]
    assert [row["outputs"]["out"] for row in report["rows"]] == [1, 1, 2]
    assert [row["successful_scans"] for row in report["rows"]] == [1, 1, 2]


def test_compiler_lock_wait_has_a_deadline_and_releases_thread_ownership(monkeypatch, tmp_path):
    import bms_tool.file_access as access
    import bms_tool.iec as iec

    times = iter((0, 46, 46, 92))
    monkeypatch.setattr(iec.time, "monotonic", lambda: next(times))

    def busy(*args):
        raise BlockingIOError("held by another process")

    monkeypatch.setattr(access, "try_lock", busy)
    with pytest.raises(ConversionError, match="busy rebuilding"):
        with _tool_lock(tmp_path):
            pytest.fail("Entered compiler critical section while already locked")
    assert iec._LOCK.acquire(blocking=False)
    iec._LOCK.release()


@requires_compiler
def test_scan_cap_stopped_worker_and_close_cleanup_fail_closed():
    native = NativeIEC(block_program("Add"))
    directory, process = native.directory, native.process
    native.attempts = 1000
    with pytest.raises(ValueError, match="scan limit"):
        native.step()
    native.attempts = 0
    process.terminate()
    process.wait(timeout=3)
    with pytest.raises(ValueError, match="stopped"):
        native.step()
    native.close()
    native.close()
    assert not directory.exists()
    assert process.poll() is not None


@requires_compiler
def test_unresponsive_actual_native_process_times_out_then_is_killed_and_cleaned():
    native = NativeIEC(block_program("Add"))
    directory, process = native.directory, native.process
    os.kill(process.pid, signal.SIGSTOP)
    started = time.monotonic()
    try:
        with pytest.raises(ConversionError, match="scan failed"):
            native.step()
        assert time.monotonic() - started < 6
        assert native.process is None and process.poll() is not None
        assert not directory.exists()
    finally:
        native.close()


def test_missing_toolchain_profile_is_explicit_and_does_not_fallback_to_graph_engine(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("BMS_IEC_HOME", str(tmp_path))
    assert not profile()["available"]
    with pytest.raises(ConversionError, match="unavailable"):
        NativeIEC(block_program("Add"))


def test_malformed_manifest_is_reported_as_unavailable_instead_of_crashing(monkeypatch, tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/iec2c").write_bytes(b"not used")
    (tmp_path / "manifest.json").write_text("[]")
    monkeypatch.setenv("BMS_IEC_HOME", str(tmp_path))
    assert not profile()["available"]
    assert "pinned compiler profile" in profile()["error"]


@requires_compiler
def test_corrupted_binary_and_runtime_library_manifests_are_rejected(monkeypatch, tmp_path):
    home, manifest = toolchain()
    (tmp_path / "bin").mkdir()
    shutil.copy2(home / "bin/iec2c", tmp_path / "bin/iec2c")
    (tmp_path / "source").mkdir()
    shutil.copytree(home / "source/lib", tmp_path / "source/lib")
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "binary_sha256": "bad"}))
    monkeypatch.setenv("BMS_IEC_HOME", str(tmp_path))
    assert "compiler checksum" in profile()["error"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with (tmp_path / "source/lib/C/iec_std_lib.h").open("a") as handle:
        handle.write("\n/* changed */\n")
    assert "library checksum" in profile()["error"]
