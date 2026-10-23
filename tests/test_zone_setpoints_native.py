"""Actual unchanged MatIEC worker target/clock/quality composition matrix."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.zone_setpoints import Population, Window, generate

from tests.test_zone_setpoints import COMPOSITIONS, Oracle, choices, frames


def exercise(value, supplied_rows, name, *, faults=True, initial_fault=False):
    program = generate(value)
    evidence = os.environ.get("BMS_ZONE_SP_NATIVE_EVIDENCE")
    destination = Path(evidence) / name if evidence else None
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    native = iec.NativeIEC(program)
    process, observations = native.process, []
    oracle = Oracle(value)
    try:
        if initial_fault:
            supplied = {"populated": {"quality": "unreliable"}}
            result = native.step(supplied)
            expected = {
                n.id: False if n.value_type == "boolean" else 0
                for n in program.nodes
                if n.kind == "Output"
            }
            observations.append(
                {
                    "submitted_inputs": supplied,
                    "native_step_observation": result,
                    "independent_expected_outputs": expected,
                }
            )
            assert result["fault"] and result["matches_reference"]
            assert result["successful_scans"] == 0 and result["outputs"] == expected
            assert not any(result["native_state"].values())
        for supplied in supplied_rows:
            result = native.step(supplied)
            expected = oracle.step(supplied)
            observations.append(
                {
                    "submitted_inputs": supplied,
                    "native_step_observation": result,
                    "independent_expected_outputs": expected,
                }
            )
            assert result["matches_reference"] and not result["fault"], result
            assert result["outputs"] == pytest.approx(expected)
            assert (
                result["outputs"]["effective_heating_setpoint"]
                < result["outputs"]["effective_cooling_setpoint"]
            )
        if faults:
            before = observations[-1]["native_step_observation"]
            for node in (n for n in program.nodes if n.kind == "Input"):
                supplied = {
                    "scheduled_occupied": False,
                    **({"window_open": True} if value.window_control else {}),
                    node.id: {"quality": "unreliable"},
                }
                result = native.step(supplied)
                observations.append(
                    {
                        "submitted_inputs": supplied,
                        "native_step_observation": result,
                        "independent_expected_outputs": before["outputs"],
                    }
                )
                assert result["fault"] and result["matches_reference"]
                assert (
                    result["outputs"] == before["outputs"]
                    and result["native_state"] == before["native_state"]
                )
                assert result["successful_scans"] == before["successful_scans"]
    finally:
        if destination:
            (destination / "program.json").write_bytes(program.model_dump_json().encode())
            (destination / "worker-observations.json").write_text(
                json.dumps(observations, indent=2, allow_nan=False) + "\n"
            )
            (destination / "compiler-profile.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n"
            )
            for file in native.directory.iterdir():
                if file.is_file():
                    shutil.copyfile(file, destination / file.name)
        native.close()
        if destination:
            files = {
                p.name: {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in sorted(destination.iterdir())
                if p.is_file()
            }
            record = {
                "name": name,
                "population": value.population,
                "window": value.window,
                "temperature_unit": value.temperature_unit,
                "scan_seconds": value.scan_seconds,
                "attempted_scans": len(observations),
                "faulted_scans": sum(
                    bool(r["native_step_observation"]["fault"]) for r in observations
                ),
                "all_matches_reference": all(
                    r["native_step_observation"]["matches_reference"] for r in observations
                ),
                "worker_pid": process.pid,
                "worker_reaped": process.poll() is not None,
                "worker_returncode": process.poll(),
                "program_sha256": program.digest(),
                "files": files,
                "qualification": "Original Program/ST/C/compiler artifacts copied before ordinary cleanup. Observations are decoded NativeIEC.step returns and submitted inputs, not raw stdout. Existing compiler/SDK/flags/deadlines/tolerances unchanged; negative worker-close returncodes describe cleanup/reap, not executable success.",
            }
            (destination / "EVIDENCE.json").write_text(json.dumps(record, indent=2) + "\n")
    assert process.poll() is not None
    return observations


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("population,window,unit,scan", COMPOSITIONS)
def test_actual_compiled_compositions_match_independent_timing_window_units_and_rollback(
    population, window, unit, scan
):
    value = choices(population=population, window=window, unit=unit, scan=scan)
    rows = list(frames(population, window))
    # Finish with latent population timing under window before quality faults.
    rows += [
        {
            "scheduled_occupied": True,
            **({"populated": False} if population else {}),
            **({"window_open": True} if window else {}),
        }
    ] * 3
    observed = exercise(
        value, rows, f"population{int(population)}-window{int(window)}-{unit}-scan{scan}"
    )
    assert len(observed) == 16 + 1 + int(population) + int(window)


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
def test_actual_compiled_reference_population_entry300_release60_not_one_scan_short():
    value = choices(population_control=Population().model_dump())
    supplied = [{"scheduled_occupied": True, "populated": False}] * 300 + [
        {"scheduled_occupied": True, "populated": True}
    ] * 60
    rows = exercise(value, supplied, "reference-entry300-release60", faults=False)
    assert not any(
        r["native_step_observation"]["outputs"]["population_setback_ready"] for r in rows[:299]
    )
    assert rows[299]["native_step_observation"]["outputs"]["population_offset_applied"]
    assert all(
        r["native_step_observation"]["outputs"]["population_setback_ready"] for r in rows[300:359]
    )
    assert not rows[359]["native_step_observation"]["outputs"]["population_setback_ready"]


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
def test_actual_native_first_fault_retains_zero_initialized_host_outputs_then_good_window_targets():
    value = choices(window_control=Window(open_default=True).model_dump())
    rows = exercise(value, [{}], "first-fault-before-targets", faults=False, initial_fault=True)
    assert rows[0]["native_step_observation"]["fault"]
    out = rows[1]["native_step_observation"]["outputs"]
    assert out["effective_heating_setpoint"] == 40 and out["effective_cooling_setpoint"] == 120
    assert (
        out["setpoint_profile"] == 3 and rows[1]["native_step_observation"]["successful_scans"] == 1
    )
