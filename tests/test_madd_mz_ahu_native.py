"""Actual ordinary MatIEC/worker two-deck concurrency and timing matrix."""

import hashlib
import json
import os
import shutil
import struct
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.madd_mz_ahu import generate

from tests.test_madd_mz_ahu import COMPOSITIONS, choices, temperature


def real(value):
    return struct.unpack("f", struct.pack("f", value))[0]


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("economizer,control,unit,scan", COMPOSITIONS)
def test_actual_compiled_independent_decks_concurrency_holds_proof_runtime_range_and_rollback(
    economizer, control, unit, scan
):
    value = choices(economizer=economizer, control=control, unit=unit, scan=scan)
    program = generate(value)
    root = os.environ.get("BMS_MADD_MZ_NATIVE_EVIDENCE")
    destination = Path(root) / f"{economizer}-{control}-{unit}-scan{scan}" if root else None
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    rows = []
    native = iec.NativeIEC(program)
    process = native.process
    try:

        def run(hot=83, cold=57, **inputs):
            supplied = {
                "hot_deck_temperature": temperature(hot, unit),
                "cold_deck_temperature": temperature(cold, unit),
                **inputs,
            }
            result = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": result})
            assert result["matches_reference"] and not result["fault"], result
            return result["outputs"]

        def expected_first(sp, pv, kp, ki, reverse=False):
            error = real(real(real(sp) - real(pv)) * real(-1 if reverse else 1))
            integral = real(real(real(ki) * error) * real(scan))
            command = real(real(real(kp) * error) + integral)
            return integral, command

        first = [run() for _ in range(4)]
        assert [r["fan_ready"] for r in first] == [False, False, False, True]
        assert all(
            r["hot_heating_valve"] == r["cold_cooling_valve"] == r["mixing_damper"] == 0
            for r in first[:3]
        )
        assert first[-1]["hot_heating_active"] and first[-1]["cold_deck_state"] == (
            3 if economizer == "off" else 1
        )
        hot_integral, hot_command = expected_first(
            value.hot_deck_setpoint, temperature(83, unit), value.hot_kp, value.hot_ki
        )
        assert first[-1]["hot_heating_valve"] == pytest.approx(hot_command)
        assert rows[-1]["native_step_observation"]["native_state"][
            "n_hot_loop_integral"
        ] == pytest.approx(hot_integral)
        if economizer == "off":
            cold_integral, cold_command = expected_first(
                value.cold_deck_setpoint, temperature(57, unit), value.cold_kp, value.cold_ki, True
            )
            assert first[-1]["cold_cooling_valve"] == pytest.approx(cold_command)
            loop = "n_cold_loop_integral"
        else:
            e = value.economizer_control
            cold_integral, _ = expected_first(
                value.cold_deck_setpoint, temperature(57, unit), e.kp, e.ki, True
            )
            assert first[-1]["cold_cooling_valve"] == 0 and first[-1]["cold_economizer_active"]
            loop = "n_economizer_loop_integral"
        assert rows[-1]["native_step_observation"]["native_state"][loop] == pytest.approx(
            cold_integral
        )
        for _ in range(2):
            held = run(hot=85, cold=55)
            assert held["hot_heating_active"] and held["hot_heating_valve"] == pytest.approx(
                hot_integral
            )
            assert held["cold_deck_state"] == (3 if economizer == "off" else 1)
            assert rows[-1]["native_step_observation"]["native_state"][loop] == pytest.approx(
                cold_integral
            )
            if economizer == "off":
                assert held["cold_cooling_valve"] == pytest.approx(cold_integral)
        if economizer != "off":
            hot_cold = [run(hot=85, cold=90) for _ in range(3)]
            assert (
                hot_cold[-1]["cold_deck_state"] == 2
                and hot_cold[-1]["mixing_damper"] == 100
                and hot_cold[-1]["cold_cooling_valve"] > 0
            )
            assert hot_cold[-1]["hot_heating_valve"] == pytest.approx(hot_integral)
            released = [run(hot=85, cold=50) for _ in range(5)]
            assert [r["cold_deck_state"] for r in released] == [2, 2, 1, 1, 0]
            assert all(
                r["hot_heating_active"] and r["hot_heating_valve"] == pytest.approx(hot_integral)
                for r in released
            )
            mechanical = run(hot=85, outdoor_temperature=temperature(70, unit))
            assert mechanical["cold_deck_state"] == 3 and mechanical["cold_cooling_valve"] > 0
            integrated = run(hot=85, outdoor_temperature=temperature(50, unit))
            assert integrated["cold_deck_state"] == 2 and integrated["mixing_damper"] == 100
        hot_release = [run(hot=95, cold=57) for _ in range(3)]
        # P-only already commanded zero during the preceding at-setpoint
        # holds, so its release timer admits the first warm scan. PI still
        # held a positive command and needs one scan to commit zero first.
        assert [r["hot_heating_active"] for r in hot_release] == (
            [True, False, False] if control == "P" else [True, True, False]
        )
        assert all(r["cold_deck_state"] != 0 for r in hot_release)
        inhibited = run(energy_holdoff=True)
        assert (
            not inhibited["fan_enable"]
            and inhibited["hot_heating_valve"]
            == inhibited["cold_cooling_valve"]
            == inhibited["mixing_damper"]
            == 0
        )
        assert [run() for _ in range(4)][-1]["fan_ready"]
        before = rows[-1]["native_step_observation"]
        required = (
            [
                "hot_deck_temperature",
                "cold_deck_temperature",
                "hot_deck_setpoint",
                "cold_deck_setpoint",
            ]
            + (["outdoor_temperature"] if economizer != "off" else [])
            + (["return_temperature"] if economizer == "differential-drybulb" else [])
        )
        for sensor in required:
            supplied = {"unit_enable": False, sensor: {"quality": "unreliable"}}
            result = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": result})
            assert result["matches_reference"] and result["fault"], result
            assert (
                result["outputs"] == before["outputs"]
                and result["native_state"] == before["native_state"]
            )
            assert result["successful_scans"] == before["successful_scans"]
        range_inhibited = run(hot_deck_setpoint=temperature(393, unit))
        assert (
            not range_inhibited["setpoints_valid"]
            and not range_inhibited["fan_enable"]
            and not range_inhibited["fan_fault"]
        )
        assert (
            range_inhibited["hot_heating_valve"]
            == range_inhibited["cold_cooling_valve"]
            == range_inhibited["mixing_damper"]
            == 0
        )
        assert [run() for _ in range(4)][-1]["fan_ready"]
        lost = run(fan_proven=False)
        assert (
            not lost["fan_ready"]
            and lost["fan_enable"]
            and lost["hot_heating_valve"]
            == lost["cold_cooling_valve"]
            == lost["mixing_damper"]
            == 0
        )
        recovery = [run() for _ in range(4)]
        assert recovery[-1]["fan_ready"] and not recovery[-1]["fan_fault"]
        chatter = [run(fan_proven=flag) for flag in (False, True, False, True, False)]
        assert chatter[-1]["fan_fault"] and not chatter[-1]["fan_enable"]
        # Invalid configuration cannot masquerade as operator-off for latch reset.
        assert run(hot_deck_setpoint=temperature(393, unit), fan_reset=True)["fan_fault"]
        assert run(unit_enable=False, fan_reset=True)["fan_fault"]
        assert run(unit_enable=False, fan_reset=False)["fan_fault"]
        assert not run(unit_enable=False, fan_reset=True)["fan_fault"]
        deadline = [run(fan_proven=False)] + [run() for _ in range(4)]
        assert (
            not any(r["fan_ready"] for r in deadline[:4])
            and deadline[-1]["fan_ready"]
            and not deadline[-1]["fan_fault"]
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
            for path in native.directory.iterdir():
                if path.is_file():
                    shutil.copyfile(path, destination / path.name)
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
                "qualification": "Original Program/ST/C/compiler outputs copied before ordinary NativeIEC cleanup. Observations are unchanged decoded NativeIEC.step values plus submitted inputs, not original raw stdout. Ordinary compiler/SDK/flags/deadlines/comparison tolerances unchanged; worker close SIGTERM/reap is cleanup, not a successful program-exit assertion.",
            }
            (destination / "EVIDENCE.json").write_text(json.dumps(record, indent=2) + "\n")
    assert process.poll() is not None


def preserve_focused(native, program, rows, destination, identity):
    """Keep original session files before ordinary cleanup, including failures."""
    process = native.process
    if destination:
        (destination / "program.json").write_bytes(program.model_dump_json().encode())
        (destination / "worker-observations.json").write_text(
            json.dumps(rows, indent=2, allow_nan=False) + "\n"
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
                    **identity,
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
                    "qualification": "Original native files copied before cleanup. Observations are decoded NativeIEC.step values, not raw stdout. Compiler/SDK/flags/deadlines/tolerances unchanged; close returncode is cleanup, not program success.",
                },
                indent=2,
            )
            + "\n"
        )
    assert process.poll() is not None


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_actual_floor100_small_econ_demand_admits_assist_and_both_integrals_hold(unit):
    value = choices(economizer="fixed-drybulb", unit=unit, minimum_oa_percent=100)
    program = generate(value)
    root = os.environ.get("BMS_MADD_MZ_NATIVE_EVIDENCE")
    destination = Path(root) / ("floor100-" + unit) if root else None
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    rows = []
    native = iec.NativeIEC(program)
    try:

        def run(hot=83, cold=56):
            supplied = {
                "hot_deck_temperature": temperature(hot, unit),
                "cold_deck_temperature": temperature(cold, unit),
            }
            result = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": result})
            assert not result["fault"] and result["matches_reference"], result
            return result["outputs"]

        initial = [run() for _ in range(4)][-1]
        assert (
            initial["cold_deck_state"] == 1
            and initial["mixing_damper"] == 100
            and initial["hot_heating_valve"] > 0
        )
        assert (
            rows[-1]["native_step_observation"]["native_state"][
                "n_previous_economizer_demand_memory"
            ]
            < 99
        )
        assert run()["cold_deck_state"] == 1
        integrated = run()
        assert (
            integrated["cold_deck_state"] == 2
            and integrated["cold_cooling_valve"] > 0
            and integrated["hot_heating_valve"] > 0
        )
        error = real(real(real(value.cold_deck_setpoint) - real(temperature(56, unit))) * real(-1))
        expected_cold_integral = real(real(real(value.cold_ki) * error) * real(1))
        hot_error = real(real(value.hot_deck_setpoint) - real(temperature(83, unit)))
        hot_increment = real(real(value.hot_ki) * hot_error)
        expected_hot_integral = real(real(hot_increment + hot_increment) + hot_increment)
        held = run(hot=85, cold=55)
        assert held["cold_deck_state"] == 2 and held["hot_heating_active"]
        assert held["cold_cooling_valve"] == pytest.approx(expected_cold_integral)
        assert held["hot_heating_valve"] == pytest.approx(expected_hot_integral)
    finally:
        preserve_focused(
            native, program, rows, destination, {"case": "floor100", "temperature_unit": unit}
        )


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Build the optional pinned MatIEC compiler first"
)
@pytest.mark.parametrize("unit", ["degF", "degC"])
def test_actual_reversed_deck_targets_still_control_both_feedback_loops(unit):
    value = choices(unit=unit, hot_deck_setpoint=55, cold_deck_setpoint=85)
    program = generate(value)
    root = os.environ.get("BMS_MADD_MZ_NATIVE_EVIDENCE")
    destination = Path(root) / ("reversed-targets-" + unit) if root else None
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
    rows = []
    native = iec.NativeIEC(program)
    try:
        for _ in range(4):
            supplied = {
                "hot_deck_temperature": temperature(53, unit),
                "cold_deck_temperature": temperature(87, unit),
            }
            result = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": result})
            assert not result["fault"] and result["matches_reference"], result
        out = rows[-1]["native_step_observation"]["outputs"]
        assert out["setpoints_valid"] and out["fan_ready"] and not out["hot_target_above_cold"]
        assert out["hot_heating_valve"] > 0 and out["cold_cooling_valve"] > 0
        assert out["nominal_deck_spread"] < 0 and out["measured_deck_spread"] < 0
    finally:
        preserve_focused(
            native,
            program,
            rows,
            destination,
            {"case": "reversed-targets", "temperature_unit": unit},
        )
