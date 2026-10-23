"""Actual pinned MatIEC/C host bindings for formerly colliding identifiers."""

import copy
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.iec_symbols import digest, symbol_profile
from bms_tool.models import canonical

from tests.test_iec_symbols import (
    alias_graph,
    boolean_graph,
    calendar_graph,
    nested_graph,
    original_series_graph,
    state_graph,
    unicode_host_graph,
)

CASES = {
    "aliases": alias_graph,
    "boolean": boolean_graph,
    "state": state_graph,
    "calendar": calendar_graph,
    "nested-macro": nested_graph,
    "original-series": original_series_graph,
    "unicode-host": unicode_host_graph,
}


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional unchanged pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize("case", list(CASES))
def test_actual_native_private_symbols_values_quality_calendars_state_and_original_outputs(case):
    program = CASES[case]()
    original = canonical(program)
    root = os.environ.get("BMS_IEC_SYMBOL_EVIDENCE")
    destination = Path(root) / case if root else None
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    native = iec.NativeIEC(program)
    process, rows = native.process, []
    try:
        table = native.symbols.evidence()
        assert table["profile"] == symbol_profile()
        assert table["sha256"] == digest({k: v for k, v in table.items() if k != "sha256"})
        assert native.compilation()["symbol_table"] == table
        assert native.compilation()["program_sha256"] == program.digest()

        def run(supplied=None, **options):
            observed = native.step(supplied, **options)
            rows.append(
                {
                    "submitted_inputs": supplied or {},
                    "host_options": {
                        k: str(v) if isinstance(v, datetime) else v for k, v in options.items()
                    },
                    "native_step_observation": observed,
                }
            )
            assert observed["matches_reference"], observed
            assert "symbol_table" not in observed and "symbol_generator" not in observed
            assert set(observed["outputs"]) == {
                node.id for node in program.nodes if node.kind == "Output"
            }
            return observed

        first = run()
        assert not first["fault"]
        if case == "aliases":
            assert first["outputs"] == {
                "x_valid": 1,
                "X_valid": 2,
                "a-b_valid": 3,
                "a_b_valid": 4,
                "bms000000_valid": 5,
                "StudioFault_valid": 6,
                "long_valid": 7,
            }
            changed = run({"a-b": 19, "a_b": 23, "x": 29, "X": 31})
            assert [
                changed["outputs"][key] for key in ["a-b_valid", "a_b_valid", "x_valid", "X_valid"]
            ] == [19, 23, 29, 31]
        elif case == "boolean":
            assert first["outputs"] == {"switch_valid": True, "Switch_valid": False}
            assert run({"switch": False, "Switch": True})["outputs"] == {
                "switch_valid": False,
                "Switch_valid": True,
            }
        elif case == "state":
            assert (
                first["outputs"]["controller_out"] == 7.5 and first["outputs"]["memory_out"] == 7.25
            )
            assert first["outputs"]["controller_integral_published"] == 50
            assert first["native_state"]["n_controller_integral"] == 1.5
            assert first["native_state"]["n_memory_memory"] == 2
            assert first["native_state"]["n_hysteresis_memory"] is True
            assert not first["outputs"]["timer_out"]
            assert run()["outputs"]["timer_out"]
            assert {row["state_label"] for row in native.symbols.state_rows()} == set(
                rows[-1]["native_step_observation"]["native_state"]
            )
        elif case == "calendar":
            assert first["outputs"] == {"cal_calendar_valid": False, "actual_calendar": True}
            clock = datetime(2026, 1, 5, 9, tzinfo=UTC)
            previous = copy.deepcopy(first)
            invalid = run(
                {"cal_calendar": True},
                clock=clock,
                calendar_bindings={"cal": {"value": False, "valid": False}},
            )
            assert invalid["fault"] and invalid["outputs"] == previous["outputs"]
            assert invalid["native_state"] == previous["native_state"]
            valid = run({"cal_calendar": True}, clock=clock)
            assert valid["outputs"] == {"cal_calendar_valid": True, "actual_calendar": True}
        elif case == "nested-macro":
            assert first["outputs"] == {"out": 5}
            assert run({"a-b": 11, "a_b": 13})["outputs"] == {"out": 24}
            assert {row["id"] for row in table["nodes"]} == {node.id for node in native.graph.nodes}
            assert any(
                row["id"] not in {node.id for node in program.nodes} for row in table["nodes"]
            )
        elif case == "original-series":
            assert any(
                n.id == "zone_temperature_valid" and n.kind == "Output" for n in program.nodes
            )
            ready = [first] + [run() for _ in range(3)]
            assert [r["outputs"]["series_state"] for r in ready] == [1, 1, 2, 3]
            assert ready[-1]["outputs"]["primary_damper"] > 0
            assert ready[-1]["outputs"]["zone_temperature_valid"] is True
            lost = run({"fan_proven": False})
            assert lost["outputs"]["fan_fault"] and not lost["outputs"]["fan_enable"]
        elif case == "unicode-host":
            assert first["outputs"] == {"温度": 3}
            assert first["native_state"] == {"n_记忆_memory": 2}
            assert run({"é": 7})["outputs"] == {"温度": 2}
        # Every original Input name addresses its own validity role; one bad
        # source must roll back the whole prior committed host transaction.
        before = rows[-1]["native_step_observation"]
        for node in (node for node in program.nodes if node.kind == "Input"):
            observed = run({node.id: {"quality": "unreliable"}})
            assert observed["fault"]
            assert (
                observed["outputs"] == before["outputs"]
                and observed["native_state"] == before["native_state"]
            )
            assert observed["successful_scans"] == before["successful_scans"]
        assert canonical(program) == original
    finally:
        if destination:
            (destination / "program.json").write_bytes(original)
            (destination / "symbol-table.json").write_text(
                json.dumps(native.symbols.evidence(), indent=2, ensure_ascii=False) + "\n"
            )
            (destination / "worker-observations.json").write_text(
                json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
            )
            (destination / "compiler-profile.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n"
            )
            for path in native.directory.iterdir():
                if path.is_file():
                    shutil.copyfile(path, destination / path.name)
        native.close()
        if destination:
            files = {
                str(p.name): {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in destination.iterdir()
                if p.is_file()
            }
            receipt = {
                "case": case,
                "worker_pid": process.pid,
                "worker_reaped": process.poll() is not None,
                "worker_returncode": process.poll(),
                "attempted_scans": len(rows),
                "faulted_scans": sum(bool(r["native_step_observation"]["fault"]) for r in rows),
                "all_matches_reference": all(
                    r["native_step_observation"]["matches_reference"] for r in rows
                ),
                "program_sha256": program.digest(),
                "symbol_table_sha256": native.symbols.sha256,
                "files": files,
                "qualification": "Original Program/ST/C/host/executable artifacts copied before ordinary cleanup; submitted inputs/observations are decoded NativeIEC values, not raw stdout. Compiler/SDK/flags/zero-init/deadlines/limits/tolerances unchanged. Unicode-host case exercises low-level Engine/host graph allocation without widening existing serialized HTTP/IR ID validators. No physical/JCI acceptance.",
            }
            (destination / "EVIDENCE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    assert process.poll() is not None
