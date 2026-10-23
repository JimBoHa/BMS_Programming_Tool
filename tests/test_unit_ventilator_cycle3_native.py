"""Actual unchanged MatIEC/REAL execution, independent lifecycle and control oracles."""

import hashlib
import json
import os
import shutil
import struct
from contextlib import contextmanager
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.formats import export_st
from bms_tool.unit_ventilator_cycle3 import generate

from tests.test_unit_ventilator_cycle3 import COMPOSITIONS, FanOracle, choices, temperature

pytestmark = pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC host unavailable"
)


@contextmanager
def compiled_case(program, name):
    root = os.environ.get("BMS_UV_NATIVE_EVIDENCE")
    dest = Path(root) / name if root else None
    rows = []
    native = None
    process = None
    failure = None
    errors = []
    if dest:
        dest.mkdir(parents=True, exist_ok=False)
        (dest / "program.json").write_bytes(program.model_dump_json().encode())
        # Generated before compilation. On success it must equal the actual compiler input.
        (dest / "pregenerated-input.st").write_bytes(
            export_st(program, embedded=False) + iec._CONFIGURATION.encode()
        )
    try:
        native = iec.NativeIEC(program)
        process = native.process
        if dest:
            assert (dest / "pregenerated-input.st").read_bytes() == (
                native.directory / "program.st"
            ).read_bytes()
        yield native, rows
    except BaseException as exc:
        failure = exc
    finally:
        if native is not None:
            try:
                if dest:
                    for file in native.directory.iterdir():
                        if file.is_file():
                            shutil.copyfile(file, dest / file.name)
            except BaseException as exc:
                errors.append(exc)
            finally:
                try:
                    native.close()
                except BaseException as exc:
                    errors.append(exc)
        if process is not None and process.poll() is None:
            errors.append(AssertionError("Owned native worker is not reaped"))
        if dest:
            (dest / "worker-observations.json").write_text(
                json.dumps(rows, indent=2, allow_nan=False) + "\n"
            )
            (dest / "compiler-profile.json").write_text(json.dumps(iec.profile(), indent=2) + "\n")
            files = {
                p.name: {
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
                for p in sorted(dest.iterdir())
                if p.is_file()
            }
            result = {
                "status": "passed" if failure is None and not errors else "failed",
                "error": None if failure is None else repr(failure),
                "cleanup_errors": [repr(x) for x in errors],
                "program_sha256": program.digest(),
                "attempted_scans": len(rows),
                "faulted_scans": sum(bool(x["native_step_observation"]["fault"]) for x in rows),
                "worker_pid": None if process is None else process.pid,
                "worker_reaped": None if process is None else process.poll() is not None,
                "worker_returncode": None if process is None else process.poll(),
                "files": files,
                "qualification": "Original Program, pre-generated candidate text, actual successful compiler input/ST/C/host/executable artifacts and unchanged decoded NativeIEC.step observations. Not raw stdout capture. Failed constructor files may be unavailable; pre-generated text is labelled separately. Original compiler/SDK/flags/deadlines/tolerances unchanged. Cleanup returncode is not executable success. No native JCI/physical acceptance.",
            }
            (dest / "EVIDENCE.json").write_text(json.dumps(result, indent=2) + "\n")
    if failure is not None:
        if errors:
            raise BaseExceptionGroup("Native case and cleanup failures", [failure, *errors])
        raise failure
    if errors:
        raise BaseExceptionGroup("Native cleanup failures", errors)


def real(n):
    return struct.unpack("f", struct.pack("f", n))[0]


def encoded(n):
    return float(format(n, ".9g"))


@pytest.mark.parametrize("unit,control,scan", COMPOSITIONS)
@pytest.mark.parametrize("policy", ["disable-cooling", "shutdown-unit"])
def test_actual_native_cycle3_lifecycle_coils_mat_limiter_units_and_full_fault_rollback(
    unit, control, scan, policy
):
    v = choices(unit=unit, control=control, scan=scan, condensate_policy=policy)
    p = generate(v)
    with compiled_case(p, f"{unit}-{control}-scan{scan}-{policy}") as (native, rows):
        initial_inputs = {"mixed_air_temperature": {"quality": "unreliable"}, "unit_enable": False}
        initial = native.step(initial_inputs)
        expected_zero = {
            n.id: False if n.value_type == "boolean" else 0 for n in p.nodes if n.kind == "Output"
        }
        rows.append(
            {
                "submitted_inputs": initial_inputs,
                "native_step_observation": initial,
                "independent_initial_outputs": expected_zero,
            }
        )
        assert (
            initial["fault"] and initial["matches_reference"] and initial["successful_scans"] == 0
        )
        assert initial["outputs"] == expected_zero and not any(initial["native_state"].values())
        oracle = FanOracle(v)

        def run(
            zone=80,
            mat=65,
            *,
            request=True,
            admitted=True,
            proof=True,
            reset=False,
            alarm=False,
            **extra,
        ):
            supplied = {
                "zone_temperature": temperature(zone, unit),
                "mixed_air_temperature": temperature(mat, unit),
                "unit_enable": request,
                "airflow_proven": proof,
                "fan_reset": reset,
                "condensate_alarm": alarm,
                **extra,
            }
            observed = native.step(supplied)
            expected = oracle.step(
                request=request,
                admitted=admitted,
                proof=proof,
                reset=reset,
                shutdown=alarm and policy == "shutdown-unit",
            )
            rows.append(
                {
                    "submitted_inputs": supplied,
                    "native_step_observation": observed,
                    "independent_lifecycle": expected,
                }
            )
            assert observed["matches_reference"] and not observed["fault"], observed
            out = observed["outputs"]
            assert {k: out[k] for k in expected} == expected
            assert not (out["heating_active"] and out["cooling_active"])
            if not out["fan_ready"]:
                assert out["heating_valve"] == out["cooling_valve"] == out["outdoor_damper"] == 0
            assert all(
                0 <= out[k] <= 100 for k in ("outdoor_damper", "heating_valve", "cooling_valve")
            )
            return out

        sequence = [run(proof=x) for x in (False, True, True)]
        assert [x["unit_state"] for x in sequence] == [1, 1, 2]
        out = sequence[-1]
        assert out["startup_deadline_reached"] and not out["fan_fault"] and out["cooling_valve"] > 0
        if control == "P":
            params = {n.id: n.params for n in p.nodes}
            sp = real(params["cooling_setpoint"]["default"])
            pv = real(temperature(80, unit))
            error = real(real(sp - pv) * real(-1))
            expected = real(real(params["uv_cooling_loop"]["kp"]) * error)
            expected = max(real(0), min(real(100), expected))
            assert out["cooling_valve"] == encoded(expected)
            sp = real(params["mixed_air_setpoint"]["default"])
            pv = real(temperature(65, unit))
            error = real(real(sp - pv) * real(-1))
            raw = max(
                real(0), min(real(100), real(real(params["uv_mixed_air_loop"]["kp"]) * error))
            )
            mapping = params["uv_mixed_air_mapped"]
            mapped = real(
                real(mapping["out_min"])
                + real(
                    real(raw / real(100))
                    * real(real(mapping["out_max"]) - real(mapping["out_min"]))
                )
            )
            rows[-1]["independent_REAL_P_expected"] = {
                "cooling_valve": encoded(expected),
                "outdoor_damper": encoded(mapped),
            }
            assert out["outdoor_damper"] == encoded(mapped)
        out = run(cooling_available=False)
        assert (
            out["cooling_requested"]
            and not out["cooling_active"]
            and out["cooling_valve"] == 0
            and out["fan_ready"]
            and out["outdoor_damper"] >= 10
        )
        out = run(alarm=True)
        assert out["cooling_valve"] == 0 and out["condensate_inhibits_cooling"]
        if policy == "shutdown-unit":
            assert not out["fan_enable"]
            assert [run()["unit_state"] for _ in range(2)] == [1, 2]
        else:
            assert out["fan_ready"] and out["outdoor_damper"] >= 10
        run(zone=40, mat=80)
        out = run(zone=40, mat=80)
        assert (
            out["heating_valve"] == 100
            and out["zone_limit_active"]
            and out["zone_limit_restricting"]
        )
        assert (
            out["zone_limit_correction"] == 100
            and out["zone_limit_allowed"] == 0
            and out["outdoor_damper"] == 10
        )
        positive = rows[-1]["native_step_observation"]
        fields = [
            "occupied",
            "unit_enable",
            "energy_holdoff",
            "airflow_proven",
            "fan_reset",
            "condensate_alarm",
            "heating_available",
            "cooling_available",
            "zone_temperature",
            "mixed_air_temperature",
            "heating_setpoint",
            "cooling_setpoint",
            "mixed_air_setpoint",
        ]
        for field in fields:
            supplied = {"unit_enable": False, field: {"quality": "stale"}}
            failed = native.step(supplied)
            rows.append(
                {
                    "submitted_inputs": supplied,
                    "native_step_observation": failed,
                    "expected_rollback_to_observation": len(rows) - 1,
                }
            )
            assert failed["fault"] and failed["matches_reference"]
            assert (
                failed["outputs"] == positive["outputs"]
                and failed["native_state"] == positive["native_state"]
                and failed["successful_scans"] == positive["successful_scans"]
            )
        lost = run(proof=False)
        assert lost["fan_fault"] and not lost["fan_enable"]
        assert run(admitted=False, reset=True, heating_setpoint=temperature(90, unit))["fan_fault"]
        assert run(request=False, reset=True)["fan_fault"]
        assert run(request=False, reset=False)["fan_fault"]
        assert not run(request=False, reset=True)["fan_fault"]
        assert [run()["unit_state"] for _ in range(2)] == [1, 2]
        invalid = run(admitted=False, mixed_air_temperature=temperature(-100, unit))
        assert (
            invalid["raw_run_request"]
            and not invalid["temperature_range_valid"]
            and not invalid["fan_fault"]
        )
        assert [run()["unit_state"] for _ in range(2)] == [1, 2]
        run(request=False)
        chatter = [run(proof=x) for x in (True, False, True)]
        assert chatter[-1]["fan_fault"] and not chatter[-1]["fan_enable"]


@pytest.mark.parametrize("scan", [1, 3])
def test_actual_native_independent_integral_trace_selected_release_and_minimum100(scan):
    v = choices(control="P", scan=scan, cooling_kp=0, cooling_ki=1, minimum_outdoor_position=100)
    p = generate(v)
    with compiled_case(p, f"analytic-integral-F-scan{scan}-minimum100") as (native, rows):

        def run(zone=76, **inputs):
            supplied = {"zone_temperature": zone, "mixed_air_temperature": 80, **inputs}
            observed = native.step(supplied)
            rows.append({"submitted_inputs": supplied, "native_step_observation": observed})
            assert observed["matches_reference"] and not observed["fault"]
            return observed

        run()
        a = run()
        assert a["outputs"]["cooling_valve"] == 2 * scan and a["outputs"]["outdoor_damper"] == 100
        a = run(74)
        assert a["outputs"]["cooling_requested"] and a["outputs"]["cooling_valve"] == 2 * scan
        a = run(74, cooling_available=False)
        assert a["outputs"]["cooling_requested"] and a["outputs"]["cooling_valve"] == 0
        a = run(72, cooling_available=False)
        assert not a["outputs"]["cooling_requested"]
        assert a["native_state"]["n_uv_cooling_loop_integral"] == 2 * scan
        a = run(76)
        assert a["outputs"]["cooling_valve"] == 4 * scan
        a = run(40, heating_available=False)
        assert a["outputs"]["zone_limit_active"] and a["outputs"]["zone_limit_allowed"] == 0
        assert a["outputs"]["outdoor_damper"] == 100 and not a["outputs"]["zone_limit_restricting"]
