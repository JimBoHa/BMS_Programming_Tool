"""Actual unchanged MatIEC compilation and native series-fan lifecycle matrix."""

import hashlib
import json
import os
import shutil
import struct
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.series_fan_vav import generate

from tests.test_series_fan_vav import COMPOSITIONS, StartupOracle, choices, temperature


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("unit,flow,control,scan", COMPOSITIONS)
def test_actual_compiled_series_fan_elapsed_proof_primary_feedback_latch_units_and_quality(
    unit, flow, control, scan
):
    value = choices(unit=unit, flow=flow, control=control, scan=scan)
    program = generate(value)
    root = os.environ.get("BMS_SERIES_VAV_NATIVE_EVIDENCE")
    destination = (
        Path(root) / f"{unit}-{flow.replace('/', '')}-{control}-scan{scan}" if root else None
    )
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    native = iec.NativeIEC(program)
    process, rows = native.process, []
    oracle = StartupOracle(value)
    try:
        first = native.step({"zone_temperature": {"quality": "unreliable"}, "unit_enable": False})
        expected_initial = {
            node.id: False if node.value_type == "boolean" else 0
            for node in program.nodes
            if node.kind == "Output"
        }
        rows.append(
            {
                "submitted_inputs": {
                    "zone_temperature": {"quality": "unreliable"},
                    "unit_enable": False,
                },
                "native_step_observation": first,
                "independent_expected_outputs": expected_initial,
            }
        )
        assert first["matches_reference"] and first["fault"]
        assert first["successful_scans"] == 0 and first["outputs"] == expected_initial
        assert not any(first["native_state"].values())

        def run(zone=74, *, request=True, admitted=True, proof=True, reset=False, **inputs):
            supplied = {
                "zone_temperature": temperature(zone, unit),
                "unit_enable": request,
                "fan_proven": proof,
                "fan_reset": reset,
                **inputs,
            }
            observed = native.step(supplied)
            expected = oracle.step(request=request, admitted=admitted, proof=proof, reset=reset)
            rows.append(
                {
                    "submitted_inputs": supplied,
                    "native_step_observation": observed,
                    "independent_expected_lifecycle": expected,
                }
            )
            assert observed["matches_reference"] and not observed["fault"], observed
            outputs = observed["outputs"]
            assert {key: outputs[key] for key in expected} == expected
            assert not (outputs["heating_active"] and outputs["cooling_active"])
            assert all(
                0 <= outputs[key] <= 100
                for key in (
                    "primary_damper",
                    "reheat_valve",
                    "zone_heating_demand",
                    "zone_cooling_demand",
                )
            )
            if not outputs["fan_ready"]:
                assert (
                    outputs["primary_damper"]
                    == outputs["reheat_valve"]
                    == outputs["primary_flow_target"]
                    == 0
                )
            return outputs

        # True status throughout close cannot count early; exact startup deadline wins.
        sequence = [run(proof=flag) for flag in (True, True, False, True, True)]
        assert [row["series_state"] for row in sequence] == [1, 1, 2, 2, 3]
        assert sequence[-1]["startup_deadline_reached"] and not sequence[-1]["fan_fault"]
        assert sequence[-1]["primary_flow_target"] > value.primary_flow_min
        if control == "P":
            # Independent IEEE REAL oracle: the native host rounds the input,
            # setpoint, subtraction and gain before computing the P command.
            # An ideal8% is not the converted Celsius worker's exact value.
            def real(number):
                return struct.unpack("f", struct.pack("f", number))[0]

            parameters = {node.id: node.params for node in program.nodes}
            error = real(
                real(real(parameters["cooling_setpoint"]["default"]) - real(temperature(74, unit)))
                * real(-1)
            )
            expected_demand = real(
                real(real(parameters["zone_cooling_loop"]["kp"]) * error) + real(0)
            )
            mapping = parameters["mapped_primary_target"]
            expected_flow = real(
                real(mapping["out_min"])
                + real(
                    real(expected_demand / real(100))
                    * real(real(mapping["out_max"]) - real(mapping["out_min"]))
                )
            )
            rows[-1]["independent_expected_p_control"] = {
                "zone_cooling_demand": expected_demand,
                "primary_flow_target": expected_flow,
            }
            assert sequence[-1]["zone_cooling_demand"] == pytest.approx(expected_demand)
            assert sequence[-1]["primary_flow_target"] == pytest.approx(expected_flow)
        integral = rows[-1]["native_step_observation"]["native_state"][
            "n_zone_cooling_loop_integral"
        ]
        held = run(72)
        if control == "PI":
            assert held["cooling_active"] and held["zone_cooling_demand"] > 0
            assert (
                rows[-1]["native_step_observation"]["native_state"]["n_zone_cooling_loop_integral"]
                == integral
            )
        heating = run(60, primary_airflow=0)
        assert heating["heating_active"] and heating["reheat_valve"] > 0
        assert heating["primary_flow_target"] == pytest.approx(value.primary_flow_min)
        before = rows[-1]["native_step_observation"]
        for node in (node for node in program.nodes if node.kind == "Input"):
            supplied = {"unit_enable": False, node.id: {"quality": "unreliable"}}
            failed = native.step(supplied)
            rows.append(
                {
                    "submitted_inputs": supplied,
                    "native_step_observation": failed,
                    "independent_expected_outputs": before["outputs"],
                }
            )
            assert failed["matches_reference"] and failed["fault"]
            assert (
                failed["outputs"] == before["outputs"]
                and failed["native_state"] == before["native_state"]
            )
            assert failed["successful_scans"] == before["successful_scans"]
        lost = run(proof=False)
        assert lost["fan_fault"] and lost["primary_damper"] == lost["reheat_valve"] == 0
        assert run(admitted=False, reset=True, primary_airflow=-1)["fan_fault"]
        assert run(request=False, reset=True)["fan_fault"]
        assert run(request=False, reset=False)["fan_fault"]
        assert not run(request=False, reset=True)["fan_fault"]
        assert [run()["series_state"] for _ in range(4)] == [1, 1, 2, 3]
        invalid = run(
            admitted=False,
            heating_setpoint=temperature(90, unit),
            cooling_setpoint=temperature(80, unit),
        )
        assert invalid["raw_run_request"] and not invalid["fan_fault"] and not invalid["fan_ready"]
        assert [run()["series_state"] for _ in range(4)] == [1, 1, 2, 3]
        off = run(request=False)
        assert not off["fan_enable"]
        chatter = [run(proof=flag) for flag in (True, True, True, False, True)]
        assert chatter[-1]["fan_fault"] and not chatter[-1]["fan_enable"]
    finally:
        if destination:
            (destination / "program.json").write_bytes(program.model_dump_json().encode())
            (destination / "worker-observations.json").write_text(
                json.dumps(rows, indent=2, allow_nan=False) + "\n"
            )
            (destination / "compiler-profile.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n"
            )
            for file in native.directory.iterdir():
                if file.is_file():
                    shutil.copyfile(file, destination / file.name)
        native.close()
        if destination:
            manifest = {
                file.name: {
                    "bytes": file.stat().st_size,
                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                }
                for file in sorted(destination.iterdir())
                if file.is_file()
            }
            receipt = {
                "unit": unit,
                "flow_unit": flow,
                "control": control,
                "scan_seconds": scan,
                "attempted_scans": len(rows),
                "faulted_scans": sum(bool(row["native_step_observation"]["fault"]) for row in rows),
                "all_matches_reference": all(
                    row["native_step_observation"]["matches_reference"] for row in rows
                ),
                "worker_pid": process.pid,
                "worker_reaped": process.poll() is not None,
                "worker_returncode": process.poll(),
                "program_sha256": program.digest(),
                "files": manifest,
                "qualification": "Original Program/ST/C/compiler/executable artifacts copied before ordinary worker cleanup. Worker observations are unchanged decoded NativeIEC.step values plus actual supplied inputs, not raw stdout wire-line capture. Normal compiler/SDK/flags/deadlines/tolerances unchanged. Physical controllers/native JCI deployment unverified; negative close returncodes record cleanup/reap, not executable success.",
            }
            (destination / "EVIDENCE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    assert process.poll() is not None
