"""Three actual host IEC cases, including a declared binary64/REAL boundary."""

import hashlib
import json
import math
import os
import shutil
import struct
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.formats import export_st

from tests.test_sum8_macro_template import caller, fold

pytestmark = pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned IEC unavailable"
)


def real(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def real_fold(values):
    result = real(values[0])
    for value in values[1:]:
        result = real(result + real(value))
    return float(format(result, ".9g"))


@pytest.mark.parametrize("case", ["ordinary-and-quality", "width-boundary", "negative-zero"])
def test_actual_existing_macro_lowering_real_order_quality_and_signed_zero(case):
    program = caller("cfm" if case == "ordinary-and-quality" else "")
    location = os.environ.get("BMS_SUM8_NATIVE_EVIDENCE")
    folder = Path(location) / case if location else None
    rows, native, process, failure, cleanup_errors = [], None, None, None, []
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "program.json").write_bytes(program.model_dump_json().encode())
        (folder / "pregenerated-input.st").write_bytes(
            export_st(program, embedded=False) + iec._CONFIGURATION.encode()
        )
    try:
        native = iec.NativeIEC(program)
        process = native.process
        if folder:
            assert (folder / "pregenerated-input.st").read_bytes() == (
                native.directory / "program.st"
            ).read_bytes()

        def run(values):
            inputs = {f"v{i}": value for i, value in enumerate(values, 1)}
            actual = native.step(inputs)
            expected = real_fold(values)
            rows.append(
                {
                    "inputs": inputs,
                    "native_step_observation": actual,
                    "independent_REAL_expected": expected,
                    "independent_binary64_expected": fold(values),
                }
            )
            assert not actual["fault"] and actual["outputs"] == {"total": expected}
            return actual

        if case == "ordinary-and-quality":
            previous = run(list(range(1, 9)))
            assert previous["matches_reference"] and previous["outputs"]["total"] == 36
            for index in range(1, 9):
                inputs = {f"v{index}": {"quality": "stale"}}
                actual = native.step(inputs)
                rows.append({"inputs": inputs, "native_step_observation": actual})
                assert actual["fault"] and actual["matches_reference"]
                assert actual["outputs"] == previous["outputs"] and actual["successful_scans"] == 1
            assert run([0.25, -0.5, 1, 2, -4, 8, 0, 0])["matches_reference"]
        elif case == "width-boundary":
            values = [16777216.0, 1.0, -16777216.0, 0, 0, 0, 0, 0]
            actual = run(values)
            assert real_fold(values) == 0 and fold(values) == 1
            assert not actual["matches_reference"] and actual["reference_outputs"]["total"] == 1
        else:
            actual = run([-0.0] * 8)
            assert actual["matches_reference"] and math.copysign(1, actual["outputs"]["total"]) < 0
    except BaseException as exc:
        failure = exc
    finally:
        try:
            if native is not None and folder:
                for file in native.directory.iterdir():
                    if file.is_file():
                        shutil.copyfile(file, folder / file.name)
        except BaseException as exc:
            cleanup_errors.append(exc)
        finally:
            if native is not None:
                try:
                    native.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        reaped = process is not None and process.poll() is not None
        if folder:
            (folder / "worker-observations.json").write_text(
                json.dumps(rows, indent=2, allow_nan=False) + "\n"
            )
            (folder / "compiler-profile.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n"
            )
            files = {
                path.name: {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(folder.iterdir())
                if path.is_file()
            }
            (folder / "EVIDENCE.json").write_text(
                json.dumps(
                    {
                        "status": "passed"
                        if failure is None and not cleanup_errors and reaped
                        else "failed",
                        "error": None if failure is None else repr(failure),
                        "cleanup_errors": [repr(error) for error in cleanup_errors],
                        "program_sha256": program.digest(),
                        "worker_pid": None if process is None else process.pid,
                        "worker_reaped": reaped,
                        "worker_returncode": None if process is None else process.poll(),
                        "submitted_scans": len(rows),
                        "files": files,
                        "qualification": "Original Program/pregenerated ST equals actual compiler ST; original C/host/executable plus decoded NativeIEC.step observations, not raw stdout. One width-boundary case explicitly expects REAL0 versus binary64reference1 and matches_reference=false; no tolerance/source/compiler changes or native JCI equivalence.",
                    },
                    indent=2,
                )
                + "\n"
            )
        if process is not None and not reaped:
            cleanup_errors.append(AssertionError("Owned worker not reaped"))
    if failure is not None:
        if cleanup_errors:
            raise BaseExceptionGroup("Native case and cleanup failures", [failure, *cleanup_errors])
        raise failure
    if cleanup_errors:
        raise BaseExceptionGroup("Native cleanup failures", cleanup_errors)
