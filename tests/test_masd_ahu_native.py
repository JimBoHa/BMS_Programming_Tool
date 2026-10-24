"""Actual unchanged MatIEC/native-worker AHU state/proof/PI/unit/time matrix."""

import hashlib
import itertools
import json
import os
import shutil
import struct
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.masd_ahu import generate

from tests.test_masd_ahu import choices, temperature

NATIVE_COMPOSITIONS = list(
    itertools.product(
        ("constant-speed", "variable-speed"),
        ("off", "fixed-drybulb", "differential-drybulb"),
        ("P", "PI"),
        ("degF", "degC"),
        (1, 2),
    )
)


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("fan,economizer,control,unit,scan", NATIVE_COMPOSITIONS)
def test_actual_compiled_ahu_proof_deadlines_pi_holds_economizer_priorities_and_rollback(
    fan, economizer, control, unit, scan
):
    value = choices(
        fan=fan,
        economizer=economizer,
        control=control,
        unit=unit,
        scan_seconds=scan,
        proof_seconds=2 * scan,
        stabilize_seconds=2 * scan,
        startup_timeout_seconds=5 * scan,
        recovery_timeout_seconds=5 * scan,
        release_seconds=2 * scan,
    )
    if value.economizer_control:
        value.economizer_control.assist_seconds = 2 * scan
    program = generate(value)
    evidence_root = os.environ.get("BMS_MASD_NATIVE_EVIDENCE")
    destination = (
        Path(evidence_root) / f"{fan}-{economizer}-{control}-{unit}-scan{scan}"
        if evidence_root
        else None
    )
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    rows = []
    native = iec.NativeIEC(program)
    process = native.process
    try:

        def run(sat=58, **inputs):
            supplied = {"sat": temperature(sat, unit), **inputs}
            result = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": result})
            assert result["matches_reference"], result
            assert not result["fault"], result
            return result["outputs"]

        initial = [run() for _ in range(4)]
        assert [r["fan_ready"] for r in initial] == [False, False, False, True]
        assert all(
            r["heating_valve"] == r["cooling_valve"] == r["mixing_damper"] == 0 for r in initial[:3]
        )
        assert initial[-1]["ahu_state"] == (2 if economizer != "off" else 4)
        assert not initial[-1]["fan_fault"]
        integral_name = (
            "n_economizer_loop_integral" if economizer != "off" else "n_cooling_loop_integral"
        )
        expected_integral = scan if control == "PI" else 0
        assert rows[-1]["native_step_observation"]["native_state"][integral_name] == pytest.approx(
            expected_integral
        )
        for _ in range(2):
            held = run(56)
            assert held["ahu_state"] == (2 if economizer != "off" else 4)
            assert rows[-1]["native_step_observation"]["native_state"][
                integral_name
            ] == pytest.approx(expected_integral)
            if economizer == "off":
                assert held["cooling_valve"] == pytest.approx(expected_integral)
        if economizer != "off":
            hot = [run(90) for _ in range(3)]
            assert (
                hot[-1]["ahu_state"] == 3
                and hot[-1]["mixing_damper"] == 100
                and hot[-1]["cooling_valve"] > 0
            )
            released = [run(55) for _ in range(5)]
            assert [r["ahu_state"] for r in released] == [3, 3, 2, 2, 0]
            assert released[-1]["mixing_damper"] == 10
            unavailable = run(58, outdoor_temperature=temperature(70, unit))
            assert unavailable["ahu_state"] == 4 and unavailable["mixing_damper"] == 10
            available = run(58, outdoor_temperature=temperature(50, unit))
            assert available["ahu_state"] == 3 and available["mixing_damper"] == 100
        heating = run(50)
        assert (
            heating["ahu_state"] == 1
            and heating["heating_valve"] > 0
            and heating["cooling_valve"] == 0
        )
        held_heat = run(54)
        assert held_heat["ahu_state"] == 1 and held_heat["heating_valve"] == (
            pytest.approx(2 * scan) if control == "PI" else 0
        )
        inhibited = run(54, energy_holdoff=True)
        assert (
            not inhibited["fan_enable"]
            and inhibited["mixing_damper"]
            == inhibited["heating_valve"]
            == inhibited["cooling_valve"]
            == 0
        )
        if fan == "variable-speed":
            assert inhibited["fan_speed"] == 0
        restored = [run() for _ in range(4)]
        assert restored[-1]["fan_ready"]
        before = rows[-1]["native_step_observation"]
        required = (
            ["sat"]
            + (["duct_pressure"] if fan == "variable-speed" else [])
            + (["outdoor_temperature"] if economizer != "off" else [])
            + (["return_temperature"] if economizer == "differential-drybulb" else [])
        )
        for sensor in required:
            supplied = {
                "sat": temperature(58, unit),
                "unit_enable": False,
                sensor: {"quality": "unreliable"},
            }
            fault = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": fault})
            assert fault["matches_reference"] and fault["fault"]
            assert (
                fault["outputs"] == before["outputs"]
                and fault["native_state"] == before["native_state"]
            )
            assert fault["successful_scans"] == before["successful_scans"]
        lost = run(fan_proven=False)
        assert (
            not lost["fan_ready"]
            and lost["fan_enable"]
            and lost["mixing_damper"] == lost["cooling_valve"] == lost["heating_valve"] == 0
        )
        recovered = [run(fan_proven=True) for _ in range(4)]
        assert recovered[-1]["fan_ready"] and not recovered[-1]["fan_fault"]
        chatter = [run(fan_proven=flag) for flag in (False, True, False, True, False)]
        assert chatter[-1]["fan_fault"] and not chatter[-1]["fan_enable"]
        assert run(fan_reset=True)["fan_fault"]
        assert run(unit_enable=False, fan_reset=True)["fan_fault"]
        assert run(unit_enable=False, fan_reset=False)["fan_fault"]
        reset = run(unit_enable=False, fan_reset=True)
        assert not reset["fan_fault"] and not reset["fan_enable"]
        start = [run(fan_proven=False)] + [run(fan_proven=True) for _ in range(4)]
        assert (
            not any(r["fan_ready"] for r in start[:4])
            and start[-1]["fan_ready"]
            and not start[-1]["fan_fault"]
        )
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
            files = {
                p.name: {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in sorted(destination.iterdir())
                if p.is_file()
            }
            record = {
                "fan": fan,
                "economizer": economizer,
                "control": control,
                "temperature_unit": unit,
                "scan_seconds": scan,
                "attempted_scans": len(rows),
                "faulted_scans": sum(bool(r["native_step_observation"]["fault"]) for r in rows),
                "all_matches_reference": all(
                    r["native_step_observation"]["matches_reference"] for r in rows
                ),
                "worker_pid": process.pid,
                "worker_reaped": process.poll() is not None,
                "worker_returncode": process.poll(),
                "program_sha256": program.digest(),
                "files": files,
                "qualification": "Program/ST/C/binary files copied from original actual native session before cleanup. Worker observations are unchanged decoded NativeIEC.step return values plus submitted test inputs, serialized for private evidence; not original stdout wire-line capture. Ordinary compiler/SDK/flags/deadlines/comparison tolerances unchanged.",
            }
            (destination / "EVIDENCE.json").write_text(json.dumps(record, indent=2) + "\n")
    assert process.poll() is not None


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_actual_native_floor100_admits_assist_from_selected_command_and_holds_at_setpoint(unit):
    value = choices(economizer="fixed-drybulb", unit=unit, minimum_oa_percent=100)
    program = generate(value)

    # Independent IEEE REAL oracle from original Program literals and submitted
    # inputs. Actual POUS.c rounds each REAL operation and uses f-suffixed gains;
    # an ideal binary64 half-percent is not the Celsius worker's expected value.
    def real(number):
        return struct.unpack("f", struct.pack("f", number))[0]

    parameters = {node.id: node.params for node in program.nodes}
    native_sat = real(temperature(57, unit))
    native_center = real(parameters["sat_setpoint"]["default"])
    native_half_band = real(parameters["positive_half_band"]["value"])
    native_setpoint = real(native_center + native_half_band)
    native_error = real(real(native_setpoint - native_sat) * real(-1))
    expected_integral = real(
        real(real(parameters["economizer_loop"]["ki"]) * native_error) * real(1)
    )
    expected_command = real(
        real(real(parameters["economizer_loop"]["kp"]) * native_error) + expected_integral
    )
    oracle = {
        "ideal_integral": 0.5,
        "ideal_command": 4.5,
        "float32_sat": native_sat,
        "float32_center": native_center,
        "float32_half_band": native_half_band,
        "float32_setpoint": native_setpoint,
        "float32_error": native_error,
        "float32_expected_integral": expected_integral,
        "float32_expected_command": expected_command,
        "native_or_pytest_tolerances_changed": False,
    }
    evidence = os.environ.get("BMS_MASD_NATIVE_EVIDENCE")
    destination = Path(evidence) / ("floor100-" + unit) if evidence else None
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    rows = []
    native = iec.NativeIEC(program)
    process = native.process
    try:

        def run(sat):
            inputs = {"sat": temperature(sat, unit)}
            result = native.step(inputs)
            rows.append({"submitted_inputs": inputs, "native_step_observation": result})
            assert not result["fault"] and result["matches_reference"], result
            return result["outputs"]

        for _ in range(4):
            out = run(57)
        assert out["ahu_state"] == 2 and out["mixing_damper"] == 100
        assert rows[-1]["native_step_observation"]["native_state"][
            "n_economizer_loop_integral"
        ] == pytest.approx(expected_integral)
        assert run(57)["ahu_state"] == 2
        admitted = run(57)
        assert (
            admitted["ahu_state"] == 3
            and admitted["mixing_damper"] == 100
            and admitted["cooling_valve"] == pytest.approx(expected_command)
        )
        held = run(56)
        assert held["ahu_state"] == 3 and held["cooling_valve"] == pytest.approx(expected_integral)
        assert rows[-1]["native_step_observation"]["native_state"][
            "n_cooling_loop_integral"
        ] == pytest.approx(expected_integral)
    finally:
        if destination:
            (destination / "independent-float32-oracle.json").write_text(
                json.dumps(oracle, indent=2) + "\n"
            )
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
            files = {
                p.name: {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in sorted(destination.iterdir())
                if p.is_file()
            }
            (destination / "EVIDENCE.json").write_text(
                json.dumps(
                    {
                        "fan": "constant-speed",
                        "economizer": "fixed-drybulb",
                        "control": "PI",
                        "temperature_unit": unit,
                        "scan_seconds": 1,
                        "minimum_oa_percent": 100,
                        "attempted_scans": len(rows),
                        "faulted_scans": 0,
                        "all_matches_reference": all(
                            r["native_step_observation"]["matches_reference"] for r in rows
                        ),
                        "worker_pid": process.pid,
                        "worker_reaped": process.poll() is not None,
                        "worker_returncode": process.poll(),
                        "program_sha256": program.digest(),
                        "files": files,
                        "qualification": "Original actual-session compiler artifacts and decoded NativeIEC.step observations retained; not raw stdout wire-line capture. No SDK/compiler/deadline/tolerance changes.",
                    },
                    indent=2,
                )
                + "\n"
            )
    assert process.poll() is not None
