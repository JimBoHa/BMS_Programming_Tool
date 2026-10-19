"""Control Basic semantic conversion and independent native compiler/VM checks."""

import hashlib
import json
from pathlib import Path

import pytest
from bms_tool.blocks import BLOCKS
from bms_tool.engine import Engine, input_type, output_type
from bms_tool.models import Edge, Node, Program
from bms_tool.temco import (
    PIN,
    STATELESS,
    SUPPORTED,
    TemcoError,
    capabilities,
    compile_program,
    compile_source,
    export_source,
    import_source,
    native_status,
    verify_program,
)


def graph(kind="Add", *, values=None, params=None):
    node = Node(id="operation", kind=kind, params=params or {})
    values = values or {}
    nodes = []
    edges = []
    for index, port in enumerate(BLOCKS[kind].inputs):
        boolean = input_type(node, port) == "boolean"
        value = values.get(port, True if boolean else 4 if index == 0 else 2)
        nodes.append(
            Node(
                id=port,
                kind="Input",
                value_type="boolean" if boolean else "number",
                params={"default": value},
            )
        )
        edges.append(Edge(id=port, source=port, target=node.id, target_port=port))
    if kind == "Input":
        node.params = {"default": 42}
    if kind == "Constant":
        node.params = {"value": 42}
    nodes.append(node)
    nodes.append(Node(id="result", kind="Output", value_type=output_type(node)))
    edges.append(Edge(id="publish", source=node.id, target="result"))
    if kind == "Convert":
        nodes[0].unit = "degF"
        node.unit = "degC"
        nodes[-1].unit = "degC"
    return Program(id="temco-test", nodes=nodes, edges=edges)


def import_values(program, original):
    if program == original:
        return list(Engine(program).step()["outputs"].values())
    defaults = {
        f"IN{i + 1}": node.params.get("default", 0)
        for i, node in enumerate(n for n in original.nodes if n.kind == "Input")
    }
    inputs = {node.id: defaults[node.label] for node in program.nodes if node.kind == "Input"}
    return list(Engine(program).step(inputs)["outputs"].values())


@pytest.mark.parametrize("kind", sorted(SUPPORTED))
def test_supported_source_roundtrip_preserves_simulated_semantics(kind):
    program = graph(kind)
    expected = list(Engine(program).step()["outputs"].values())
    source = export_source(program)
    assert source.startswith("10 REM BMS STUDIO CONTROL BASIC")
    assert source.endswith(" END\r\n")
    assert not source.startswith("{")
    converted = import_source(source)
    assert import_values(converted, program) == pytest.approx(expected)
    if kind in STATELESS:
        assert converted.metadata["conversion"]["review_required"] is True
    else:
        assert converted == program


@pytest.mark.parametrize("kind", sorted(SUPPORTED))
def test_official_compiler_and_vm_execute_every_supported_block(kind):
    program = graph(kind)
    expected = Engine(program).step()["outputs"]["result"]
    compiled = compile_program(program)
    assert 9 <= len(compiled["bytecode"]) < 2000
    assert compiled["manifest"]["source_commit"] == PIN
    result = verify_program(program)
    assert result["outputs"]["result"] == pytest.approx(expected, abs=0.01)
    assert result["source_commit"] == PIN
    assert result["scope"].endswith("no device connection")
    assert result["matches_reference"] is True


def test_unknown_blocks_are_rejected_instead_of_omitted():
    program = graph()
    program.nodes[2].kind = "UnimplementedVendorOpcode"
    with pytest.raises(TemcoError, match="no execution semantics"):
        export_source(program)


def test_explicit_local_point_bindings_native_execution_and_import():
    program = graph("Add", values={"a": 40, "b": 2})
    bindings = {"a": "VAR4", "b": "IN64", "result": "VAR256"}
    source = export_source(program, bindings=bindings)
    assert "VAR4" in source and "IN64" in source and "VAR256 =" in source
    assert verify_program(program, bindings=bindings)["outputs"] == {"result": 42}
    imported = import_source(source)
    assert next(n.label for n in imported.nodes if n.kind == "Output") == "VAR256"


@pytest.mark.parametrize(
    "bindings",
    [
        {"a": "IN65"},
        {"a": "VAR257"},
        {"a": "1-IN1"},
        {"a": "OUT1"},
        {"a": "in1"},
        {"result": "IN1"},
        {"missing": "IN1"},
        {"a": "IN2", "b": "IN2"},
        {"a": "VAR1", "result": "VAR1"},
    ],
)
def test_bindings_require_supported_local_points_and_single_writer(bindings):
    with pytest.raises(TemcoError):
        export_source(graph(), bindings=bindings)


def test_division_zero_guard_holds_published_outputs_in_actual_vm():
    program = graph("Divide", values={"a": 20, "b": 0})
    source = export_source(program)
    assert "IF T2 = 0 THEN END" in source
    assert source.index("THEN END") < source.index("OUT1 =")
    assert verify_program(program, initial_outputs={"result": 57.25})["outputs"] == {
        "result": 57.25
    }
    with pytest.raises(ValueError, match="zero"):
        Engine(import_source(source)).step()


@pytest.mark.parametrize("value", [0.0001, 2_000_001, 1e30])
def test_export_rejects_unrepresentable_literals(value):
    program = graph("Constant")
    program.nodes[0].params["value"] = value
    with pytest.raises(TemcoError, match="literal"):
        export_source(program)


@pytest.mark.parametrize("value", [0, 0.001, -0.001, 1.234, -123.456, 2000])
def test_native_fixed_point_constants_are_bounded_and_visible(value):
    program = graph("Constant")
    program.nodes[0].params["value"] = value
    result = verify_program(program)["outputs"]["result"]
    assert result == pytest.approx(value, abs=0.00101)


def test_foreign_source_ordered_assignments_and_selection_execute():
    source = (
        "10 REM TEMCO TEST\r\n"
        "20 A = IN1 + 2\r\n"
        "30 A = A * 3\r\n"
        "40 IF A > 100 THEN B = MAX(A, 50) ELSE B = ABS(A - 50)\r\n"
        "50 OUT1 = B\r\n"
        "60 END\r\n"
    )
    program = import_source(source)
    input_id = next(n.id for n in program.nodes if n.kind == "Input")
    assert list(Engine(program).step({input_id: 10})["outputs"].values()) == [14]
    assert list(Engine(program).step({input_id: 40})["outputs"].values()) == [126]
    assert len(compile_source(source)) > 9


def test_source_profile_case_insensitivity_is_normalized_for_vendor_compiler():
    lower = "10 a = in1 + 2\n20 out1 = a\n30 end\n"
    assert compile_source(lower) == compile_source(lower.upper())


def test_native_fixed_point_overflow_is_reported_as_a_reference_difference():
    program = graph("Multiply", values={"a": 2_000_000, "b": 2_000_000})
    result = verify_program(program)
    assert result["matches_reference"] is False
    assert result["differences"][0]["node"] == "result"
    assert result["reference_outputs"] == {"result": 4_000_000_000_000}


def test_division_guard_reports_reference_fault_and_retained_native_output():
    result = verify_program(
        graph("Divide", values={"a": 2, "b": 0}), initial_outputs={"result": 42}
    )
    assert result["matches_reference"] is True
    assert "zero" in result["reference_fault"]
    assert result["outputs"] == result["reference_outputs"] == {"result": 42}


def test_native_boolean_normalization_handles_all_logic_and_numeric_nonzero():
    program = graph("And", values={"a": True, "b": False})
    assert verify_program(program)["outputs"]["result"] is False
    assert verify_program(program, {"a": True, "b": True})["outputs"]["result"] is True
    program = graph("Less", values={"a": 0, "b": 2})
    assert verify_program(program)["outputs"]["result"] is True
    # decode.c comparisons yield raw 1, unlike numeric constants scaled by 1000.
    # Explicit IF normalization must produce physical Boolean value 1.000.
    assert verify_program(program)["native_values"]["OUT1"] == 1
    source = "10 IF IN1 THEN A = 1 ELSE A = 2\n20 OUT1 = A\n30 END\n"
    converted = import_source(source)
    identifier = next(n.id for n in converted.nodes if n.kind == "Input")
    assert list(Engine(converted).step({identifier: -1})["outputs"].values()) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "10 GOTO 10\n20 END\n",
        "10 WAIT 10\n20 END\n",
        "10 A = TIME\n20 END\n",
        "10 A = SQR(IN1)\n20 END\n",
        "10 A = 1-IN1\n20 END\n",
        "10 A = IN65\n20 END\n",
        "10 IN1 = 5\n20 END\n",
        "10 A = 1\n10 END\n",
        "20 A = 1\n10 END\n",
        "10 A = 1\n20 END\n30 OUT1 = A\n",
        "10 IF IN1 THEN A = 1 ELSE B = 2\n20 END\n",
        "10 A = 1\n20 IF A = 0 THEN END\n30 OUT1 = A + 2\n40 END\n",
        "10 A = 1\n20 IF A = 0 THEN END\n30 END\n",
        "10 A = 0.0001\n20 END\n",
        "10 A = 1\n",
        "10 END\n",
        "10 A = __import__('os')\n20 END\n",
        "10 A = 1\x00\n20 END\n",
    ],
)
def test_unsupported_foreign_semantics_and_malformed_sources_are_rejected(source):
    with pytest.raises(TemcoError):
        import_source(source)


def test_source_size_depth_line_and_operand_limits_precede_native_invocation():
    with pytest.raises(TemcoError):
        import_source("\n".join(f"{i + 1} REM X" for i in range(181)))
    with pytest.raises(TemcoError):
        import_source("10 REM " + "X" * 241)
    with pytest.raises(TemcoError):
        import_source("10 A = " + "(" * 15 + "1" + ")" * 15 + "\n20 END")
    with pytest.raises(TemcoError):
        import_source("10 A = " + "+".join("1" for _ in range(60)) + "\n20 END")


def test_host_native_status_and_binary_provenance_can_be_checked():
    status = native_status()
    assert status["available"] is True
    assert status["source_commit"] == PIN
    assert status["capabilities"]["supported_blocks"] == sorted(SUPPORTED)
    compiled = compile_program(graph())
    assert len(compiled["manifest"]["source_sha256"]) == 5
    assert compiled["manifest"]["license"] == "MIT"
    for digest in compiled["manifest"]["source_sha256"].values():
        assert len(digest) == 64


def test_unavailable_native_reference_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("BMS_TEMCO_HOME", str(tmp_path))
    assert native_status()["available"] is False
    with pytest.raises(TemcoError, match="setup_temco"):
        compile_program(graph())


def test_native_binary_hash_mismatch_is_rejected(monkeypatch, tmp_path):
    manifest = {
        "format": "bms-temco-host/1",
        "source_commit": PIN,
        "binary_sha256": {"compiler": hashlib.sha256(b"original").hexdigest(), "vm": "0" * 64},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "temco-compiler").write_bytes(b"changed")
    monkeypatch.setenv("BMS_TEMCO_HOME", str(tmp_path))
    assert native_status()["available"] is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e50, 10**1000, 0.00001, "5", None])
def test_native_input_validation_prevents_invalid_or_unrepresentable_values(value):
    with pytest.raises(TemcoError):
        verify_program(graph("Add"), {"a": value})


@pytest.mark.parametrize("scans", [0, 1001, True, 1.5])
def test_native_scan_count_is_bounded(scans):
    with pytest.raises(TemcoError):
        verify_program(graph(), scans=scans)


def test_quality_unknown_inputs_and_output_seed_types_are_checked():
    with pytest.raises(TemcoError, match="quality"):
        verify_program(graph(), {"a": {"value": 2, "quality": "open-circuit"}})
    with pytest.raises(TemcoError, match="unknown"):
        verify_program(graph(), {"unknown": 2})
    with pytest.raises(TemcoError, match="unknown"):
        verify_program(graph(), initial_outputs={"unknown": 2})
    with pytest.raises(TemcoError, match="Boolean"):
        verify_program(graph("And"), {"a": 1})
    with pytest.raises(TemcoError, match="Boolean"):
        verify_program(graph("And"), initial_outputs={"result": 1})


def test_native_extension_and_invalid_graph_are_not_silently_dropped():
    program = graph()
    program.metadata["native_sedona"] = {}
    with pytest.raises(TemcoError, match="Sedona"):
        export_source(program)
    program = graph()
    program.edges.pop()
    with pytest.raises(TemcoError, match="Connect"):
        export_source(program)


def test_resource_limit_is_actual_manufacturer_bytecode_limit():
    program = graph()
    for index in range(110):
        program.nodes.insert(0, Node(id=f"constant{index}", kind="Constant", params={"value": 42}))
    with pytest.raises(TemcoError, match="compiler rejected"):
        compile_program(program)


def test_setup_provenance_retains_original_manufacturer_license():
    sdk = Path(__file__).resolve().parents[2] / "Reference_Sources/temcocontrols--T3000"
    license_text = (sdk / "build/bms-host/LICENSE.txt").read_text()
    assert "Copyright (c) 2017 Temco Controls" in license_text
    assert "MIT License" in license_text
    assert capabilities()["source_url"].startswith("https://github.com/temcocontrols/")


@pytest.mark.parametrize("kind", ["Delay", "Slew", "PI", "Deadband", "TimerOn", "Alarm"])
def test_native_retained_state_survives_multiple_changing_input_frames(kind):
    program = graph(kind)
    if kind in ("Delay", "Slew"):
        program.nodes[-2].params = {"initial": 7, **({"rate": 1} if kind == "Slew" else {})}
        frames = [{"in": 10}, {"in": 20}, {"in": -10}, {"in": 30}]
    elif kind == "PI":
        program.nodes[-2].params = {"kp": 2, "ki": 0.5, "min": 0, "max": 10}
        frames = [
            {"setpoint": 10, "measured": 0},
            {"setpoint": 2},
            {"measured": 10},
            {"setpoint": 10},
        ]
    elif kind == "Deadband":
        program.nodes[-2].params = {"initial": True, "on": 10, "off": 5}
        frames = [{"in": 7}, {"in": 4}, {"in": 7}, {"in": 12}]
    elif kind == "TimerOn":
        program.nodes[-2].params = {"seconds": 2}
        frames = [{"in": True}, {"in": True}, {"in": False}, {"in": True}]
    else:
        program.nodes[-2].params = {"limit": 100, "delay": 2}
        frames = [{"in": 110}, {"in": 110}, {"in": 90}, {"in": 110}]
    result = verify_program(program, scans=4, input_sequence=frames)
    assert result["matches_reference"], result["differences"]
    assert len(result["history"]) == 4
    if kind == "Delay":
        assert [row["outputs"]["result"] for row in result["history"]] == [7, 10, 20, -10]
    if kind == "Slew":
        assert [row["outputs"]["result"] for row in result["history"]] == [8, 9, 8, 9]
    if kind in ("TimerOn", "Alarm"):
        assert [row["outputs"]["result"] for row in result["history"]] == [
            False,
            True,
            False,
            False,
        ]


def test_native_state_is_not_committed_when_later_division_fails():
    program = graph("Delay", params={"initial": 7})
    program.nodes += [
        Node(id="denominator", kind="Input", params={"default": 1}),
        Node(id="numerator", kind="Constant", params={"value": 10}),
        Node(id="divide", kind="Divide"),
        Node(id="division_out", kind="Output"),
    ]
    program.edges += [
        Edge(id="num_div", source="numerator", target="divide", target_port="a"),
        Edge(id="den_div", source="denominator", target="divide", target_port="b"),
        Edge(id="div_publish", source="divide", target="division_out"),
    ]
    result = verify_program(
        program,
        scans=3,
        input_sequence=[{"in": 10}, {"in": 20, "denominator": 0}, {"in": 30, "denominator": 1}],
    )
    assert result["matches_reference"], result["differences"]
    assert [row["outputs"]["result"] for row in result["history"]] == [7, 7, 10]
    assert "zero" in result["history"][1]["reference_fault"]


def test_delayed_feedback_native_scans_are_ordered_and_persistent():
    program = Program(
        nodes=[
            Node(id="previous", kind="Delay", params={"initial": 10}),
            Node(id="increment", kind="Constant", params={"value": 2}),
            Node(id="sum", kind="Add"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="prev_sum", source="previous", target="sum", target_port="a"),
            Edge(id="inc_sum", source="increment", target="sum", target_port="b"),
            Edge(id="feedback", source="sum", target="previous"),
            Edge(id="pub", source="sum", target="out"),
        ],
    )
    result = verify_program(program, scans=4)
    assert result["matches_reference"], result["differences"]
    assert [row["outputs"]["out"] for row in result["history"]] == [12, 14, 16, 18]


@pytest.mark.parametrize("reverse", [False, True])
def test_native_pi_antiwindup_and_reversal_match_all_scans(reverse):
    program = graph("PI", params={"kp": 2, "ki": 0.5, "min": 0, "max": 10, "reverse": reverse})
    frames = (
        [{"setpoint": 10, "measured": 0}] * 20
        + [{"setpoint": 2}] * 3
        + [{"setpoint": -10}] * 3
        + [{"setpoint": 0, "measured": 0}]
    )
    result = verify_program(program, scans=len(frames), input_sequence=frames)
    assert result["matches_reference"], result["differences"]


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("2026-11-01T08:30:00Z", True),
        ("2026-11-01T09:30:00Z", True),
        ("2026-03-08T10:30:00Z", False),
    ],
)
def test_host_calendar_dst_flags_are_consumed_by_actual_native_program(clock, expected):
    program = graph(
        "Schedule",
        params={"start": "01:00", "end": "02:00", "days": [6], "timezone": "America/Los_Angeles"},
    )
    result = verify_program(program, clock=clock)
    assert result["outputs"]["result"] is expected
    assert result["matches_reference"]
    assert result["calendar_bindings"] == {"operation": {"active": "VAR256", "valid": "VAR255"}}
    assert "Host-evaluated" in result["calendar_scope"]


def test_host_calendar_exception_and_boundary_are_checked_each_scan():
    program = graph(
        "Schedule",
        params={
            "start": "08:00",
            "end": "18:00",
            "days": [0],
            "timezone": "America/Los_Angeles",
            "exceptions": [
                {"date": "2026-10-19", "start": "10:00", "end": "10:01", "enabled": True}
            ],
        },
    )
    program.scan_seconds = 60
    result = verify_program(program, scans=3, clock="2026-10-19T16:59:00Z")
    assert [row["outputs"]["result"] for row in result["history"]] == [False, True, False]
    assert result["matches_reference"]
    held = verify_program(
        program,
        clock="2026-10-19T17:00:00Z",
        initial_outputs={"result": True},
        calendar_valid=False,
    )
    assert held["outputs"] == {"result": True}
    assert held["matches_reference"]
    assert "unbound" in held["reference_fault"]


def test_calendar_bindings_avoid_user_var_points():
    program = graph("Schedule")
    result = compile_program(program, bindings={"result": "VAR256"})
    assert result["calendar_bindings"] == {"operation": {"active": "VAR255", "valid": "VAR254"}}


def test_authoring_annotations_are_checked_against_actual_executable_source():
    program = graph("Slew", params={"rate": 2, "initial": 7})
    source = export_source(program)
    assert "REM BMSIR2 " in source
    assert "S2 = U2" in source
    assert import_source(source) == program
    changed = source.replace("S2 + MAX", "S2 - MAX")
    with pytest.raises(TemcoError, match="disagrees"):
        import_source(changed)
    assert b"BMSIR2" not in compile_source(source)
    assert compile_source(source) != source.encode()


def test_authoring_annotation_decompression_is_bounded():
    import base64
    import zlib

    encoded = base64.b64encode(zlib.compress(b" " * 600000)).decode()
    lines = ["REM BMSIR2 " + encoded[i : i + 160] for i in range(0, len(encoded), 160)] + [
        "A = 1",
        "END",
    ]
    source = "\n".join(f"{(i + 1) * 10} {line}" for i, line in enumerate(lines))
    with pytest.raises(TemcoError, match="bounded"):
        import_source(source)


@pytest.mark.parametrize(
    "name",
    sorted(
        path.name for path in (Path(__file__).resolve().parents[1] / "examples").glob("*.bms.json")
    ),
)
def test_all_nine_illustrative_vav_profiles_execute_as_native_temco_programs(name):
    program = Program.model_validate_json(
        (Path(__file__).resolve().parents[1] / "examples" / name).read_text()
    )
    result = verify_program(program, scans=60, clock="2026-10-19T17:00:00Z")
    assert result["matches_reference"], result["differences"]
    assert result["bytecode_bytes"] < 2000
    assert len(result["history"]) == 60


@pytest.mark.parametrize("clock", ["2026-01-01", "nonsense", 123])
def test_native_clock_requires_an_aware_timestamp(clock):
    with pytest.raises(TemcoError, match="clock"):
        verify_program(graph("Schedule"), clock=clock)


@pytest.mark.parametrize("sequence", [[], [1], [{"unknown": 5}]])
def test_native_input_frames_are_strictly_bounded(sequence):
    with pytest.raises(TemcoError):
        verify_program(graph(), input_sequence=sequence)


def test_nonrepresentable_scale_gain_is_reported_instead_of_labeled_equivalent():
    program = graph(
        "Scale", values={"in": 1}, params={"in_min": 0, "in_max": 3, "out_min": 0, "out_max": 1000}
    )
    result = verify_program(program)
    assert result["matches_reference"] is False
    assert result["outputs"] == {"result": 333}
    assert result["reference_outputs"]["result"] == pytest.approx(1000 / 3)


@pytest.mark.parametrize("value,expected", [(-10, 100), (0, 100), (51, 59.2), (110, 20)])
def test_reversed_exact_gain_scale_keeps_clamping_and_native_precision(value, expected):
    program = graph(
        "Scale",
        values={"in": value},
        params={"in_min": 0, "in_max": 100, "out_min": 100, "out_max": 20},
    )
    result = verify_program(program)
    assert result["matches_reference"]
    assert result["outputs"]["result"] == pytest.approx(expected, abs=0.001)


def test_nested_stateful_macros_lower_and_roundtrip_through_real_native_source():
    from tests.test_macro_integration import nested_rate_program

    program = nested_rate_program()
    source = export_source(program)
    assert import_source(source) == program
    result = verify_program(program, scans=10)
    assert result["matches_reference"], result["differences"]


def test_clock_range_error_is_reported_before_native_execution():
    with pytest.raises(TemcoError, match="clock"):
        verify_program(graph("Schedule"), scans=2, clock="9999-12-31T23:59:59Z")


def test_timer_accumulator_saturates_without_changing_future_alarm_outputs():
    program = graph("TimerOn", params={"seconds": 2}, values={"in": True})
    result = verify_program(program, scans=1000)
    assert result["matches_reference"]
    assert result["native_values"]["S2"] == 2
    assert all(row["outputs"]["result"] for row in result["history"][1:])


def test_first_scan_fault_preserves_nonzero_initial_state_until_first_valid_scan():
    program = graph("Delay", params={"initial": 7})
    program.nodes += [
        Node(id="denominator", kind="Input", params={"default": 0}),
        Node(id="numerator", kind="Constant", params={"value": 10}),
        Node(id="divide", kind="Divide"),
        Node(id="division_out", kind="Output"),
    ]
    program.edges += [
        Edge(id="num_div", source="numerator", target="divide", target_port="a"),
        Edge(id="den_div", source="denominator", target="divide", target_port="b"),
        Edge(id="div_publish", source="divide", target="division_out"),
    ]
    result = verify_program(
        program,
        scans=3,
        input_sequence=[{"in": 10}, {"in": 20, "denominator": 1}, {"in": 30}],
        initial_outputs={"result": 55, "division_out": 66},
    )
    assert result["matches_reference"], result["differences"]
    assert [row["outputs"]["result"] for row in result["history"]] == [55, 7, 20]


def test_native_local_name_storage_is_checked_before_compiler_prescan(monkeypatch):
    lines = []
    for index in range(70):
        names = ["V" + str(index * 5 + offset).zfill(4) + "X" * 25 for offset in range(5)]
        lines.append(f"{(index + 1) * 10} A{index} = " + " + ".join(names))
    source = "\n".join(lines) + "\n800 OUT1 = A0\n810 END\n"
    assert len(source) < 24000
    assert max(map(len, source.splitlines())) < 240
    assert import_source(source).nodes  # Grammatically accepted foreign source.
    monkeypatch.setattr(
        "bms_tool.temco.subprocess.run",
        lambda *args, **kwargs: pytest.fail(
            "Native compiler must not run after a local-table bound violation"
        ),
    )
    with pytest.raises(TemcoError, match="symbol/local storage"):
        compile_source(source)


def test_native_postfix_storage_is_checked_before_compiler_invocation(monkeypatch):
    expression = "1"
    for _ in range(8):
        expression = "MIN(1," + expression + ")"
    source = f"10 A = {expression}\n20 OUT1 = A\n30 END\n"
    assert import_source(source).nodes
    monkeypatch.setattr(
        "bms_tool.temco.subprocess.run",
        lambda *args, **kwargs: pytest.fail(
            "Native compiler must not run after a postfix bound violation"
        ),
    )
    with pytest.raises(TemcoError, match="postfix storage"):
        compile_source(source)


def test_safe_postfix_boundary_remains_accepted_by_actual_native_compiler():
    expression = "1"
    for _ in range(4):
        expression = "MIN(1," + expression + ")"
    assert len(compile_source(f"10 A = {expression}\n20 OUT1 = A\n30 END\n")) > 9


def test_local_names_starting_with_rem_are_executable_assignments(tmp_path):
    import subprocess

    from bms_tool.temco import _toolchain

    source = "10 REMARK = 42\n20 OUT1 = REMARK\n30 END\n"
    bytecode = compile_source(source)
    assert b"REMARK" in bytecode
    binary = tmp_path / "program.bin"
    binary.write_bytes(bytecode)
    host, _ = _toolchain()
    result = subprocess.run(
        [host / "temco-vm", binary, "1", "--watch=OUT1"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert "@1\tOUT1\t42.000000" in result.stdout
