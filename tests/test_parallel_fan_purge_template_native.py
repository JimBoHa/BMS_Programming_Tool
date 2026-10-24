"""Actual unchanged IEC thermal purge, live duration and qualified REAL boundaries."""

import copy
import hashlib
import json
import math
import os
import shutil
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.activities import resolve
from bms_tool.formats import export_st
from bms_tool.models import canonical
from bms_tool.parallel_fan_purge_template import PROFILE_SHA, Choices

from tests.test_parallel_fan_purge_template import PORTS, caller


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize(
    "case", ["raw-heat-inband-purge", "live-duration-h60", "coalesced-thresholds"]
)
def test_actual_shared_request_elapsed_raw_reset_quality_and_real_boundary(case):
    choices = Choices(
        scan_seconds=60
        if case == "live-duration-h60"
        else 2
        if case == "coalesced-thresholds"
        else 1,
        heating_purge_duration_default=0
        if case == "live-duration-h60"
        else 6
        if case == "coalesced-thresholds"
        else 3,
    )
    program = caller(choices)
    original = canonical(program)
    root = os.environ.get("BMS_PARALLEL_FAN_PURGE_NATIVE_EVIDENCE")
    folder = Path(root) / case if root else None
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "program.original.json").write_bytes(original)
        (folder / "bindings.original.json").write_text(
            json.dumps(resolve(program), indent=2) + "\n", encoding="utf-8"
        )
        (folder / "pregenerated-program.st").write_bytes(
            export_st(program, embedded=False) + iec._CONFIGURATION.encode()
        )
    native, process, failure, rows, cleanup, refusals = None, None, None, [], [], []
    try:
        native = iec.NativeIEC(program)
        process = native.process
        compilation = native.compilation()
        assert compilation["activity_bindings"] == resolve(program)
        assert compilation["symbol_table"] == native.symbols.evidence()
        assert compilation["program_sha256"] == program.digest()
        assert (
            program.metadata["macros"]["definitions"][0]["program"]["metadata"][
                "parallel_fan_purge_template"
            ]["profile_sha256"]
            == PROFILE_SHA
        )
        memory = {
            r["roles"]["memory"]["type"]: r["roles"]["memory"]["state_label"]
            for r in compilation["symbol_table"]["nodes"]
            if r["kind"] == "Delay"
        }
        assert set(memory) == {"BOOL", "REAL"}
        if folder:
            (folder / "compilation.returned.original.json").write_text(
                json.dumps(compilation, indent=2) + "\n", encoding="utf-8"
            )
            (folder / "symbol-table.returned.original.json").write_text(
                json.dumps(compilation["symbol_table"], indent=2) + "\n", encoding="utf-8"
            )
            (folder / "expanded.original.json").write_bytes(canonical(native.graph))
            before = folder / "compiler-before-scans"
            before.mkdir()
            for file in native.directory.iterdir():
                if file.is_file():
                    shutil.copyfile(file, before / file.name)
            assert (folder / "pregenerated-program.st").read_bytes() == (
                native.directory / "program.st"
            ).read_bytes()

        def run(inputs, request, elapsed, valid=True, matches=True):
            observed = native.step(inputs)
            rows.append(
                {
                    "inputs": inputs,
                    "independent_outputs": {"request0": request, "valid0": valid},
                    "independent_elapsed": elapsed,
                    "expected_matches_reference": matches,
                    "native_step_observation": observed,
                }
            )
            assert not observed["fault"] and observed["outputs"] == {
                "request0": request,
                "valid0": valid,
            }
            assert observed["native_state"] == {memory["BOOL"]: request, memory["REAL"]: elapsed}
            assert observed["matches_reference"] is matches
            assert "activity_bindings" not in observed and "symbol_table" not in observed
            return observed

        if case == "raw-heat-inband-purge":
            first = native.step({"heating_percent_command": {"quality": "open-circuit"}})
            rows.append(
                {
                    "inputs": {"heating_percent_command": {"quality": "open-circuit"}},
                    "independent_outputs": None,
                    "native_step_observation": first,
                }
            )
            assert first["fault"] and first["matches_reference"]
            assert first["outputs"] == {"request0": False, "valid0": False}
            assert first["native_state"] == {memory["BOOL"]: False, memory["REAL"]: 0}
            assert first["successful_scans"] == first["time"] == 0
            run({"heating_percent_command": 6}, True, 0)
            run({}, True, 1)
            run({}, True, 2)
            run({"heating_percent_command": 1}, True, 0)
            run({}, True, 1)
            run({}, True, 2)
            run({}, False, 3)
            run({"cooling_percent_command": 6}, True, 4)
            run({"cooling_percent_command": 0.1}, True, 5)
            run({"heating_percent_command": 0.1}, True, 0)
            run({}, True, 1)
            run({"heating_purge_duration": 1}, False, 2)
        elif case == "live-duration-h60":
            run({}, False, 60)
            run({}, False, 120)
            run({}, False, 180)
            run({"cooling_percent_command": 6, "heating_purge_duration": 400}, True, 240)
            run({"heating_purge_duration": 400}, True, 300)
            run({"heating_purge_duration": 240}, False, 360)
            run({"heating_percent_command": 6}, True, 0)
            run({"heating_purge_duration": 86400}, True, 60)
            run({"fan_off_threshold": 0}, True, 0, valid=False)
            run({"heating_purge_duration": 90}, True, 60)
            run({"heating_purge_duration": 90}, False, 120)
        else:
            run({"heating_percent_command": 6}, True, 0)
            run({}, True, 2)
            different = run(
                {"fan_on_threshold": 1, "fan_off_threshold": math.nextafter(1.0, 0.0)},
                True,
                0,
                valid=False,
                matches=False,
            )
            assert (
                different["reference_outputs"] == {"request0": True, "valid0": True}
                and different["reference_fault"] is None
            )
            run({"heating_percent_command": 6}, True, 0)
            run({}, True, 2)
            run({}, True, 4)
            run({}, False, 6)
        previous = rows[-1]["native_step_observation"]
        for name in PORTS:
            inputs = {name: {"quality": "unreliable"}}
            observed = native.step(inputs)
            rows.append(
                {"inputs": inputs, "independent_outputs": None, "native_step_observation": observed}
            )
            assert observed["fault"] and observed["matches_reference"]
            for key in ("outputs", "native_state", "successful_scans", "time"):
                assert observed[key] == previous[key]
        history = copy.deepcopy(native.history)
        for value, reason in ((1e308, "within"), (5e-324, "underflows")):
            with pytest.raises(ValueError, match=reason) as error:
                native.step({"fan_off_threshold": value})
            refusals.append(
                {
                    "inputs": {"fan_off_threshold": value},
                    "actual_host_error": str(error.value),
                    "native_exchange_submitted": False,
                }
            )
            assert native.history == history
        assert canonical(program) == original
    except BaseException as exc:
        failure = exc
    finally:
        try:
            if native is not None and folder:
                for file in native.directory.iterdir():
                    if file.is_file():
                        shutil.copyfile(file, folder / file.name)
        except BaseException as exc:
            cleanup.append(exc)
        finally:
            if native is not None:
                try:
                    native.close()
                except BaseException as exc:
                    cleanup.append(exc)
        if folder:
            (folder / "frames.original.json").write_text(
                json.dumps(rows, indent=2) + "\n", encoding="utf-8"
            )
            (folder / "host-refusals.original.json").write_text(
                json.dumps(refusals, indent=2) + "\n", encoding="utf-8"
            )
            (folder / "compiler-profile.original.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n", encoding="utf-8"
            )
            (folder / "EVIDENCE.json").write_text(
                json.dumps(
                    {
                        "case": case,
                        "pid": process.pid if process else None,
                        "reaped": process is not None and process.poll() is not None,
                        "returncode": process.poll() if process else None,
                        "failure": repr(failure) if failure else None,
                        "cleanup_errors": [repr(e) for e in cleanup],
                        "qualification": "Decoded original IEC frames and returned tables. One deliberate coalesced-threshold reference difference, not raw stdout/native JCI/physical purge proof. Counter-cap crossing86400 is covered by portable core and static bound; normal generated native fixtures are not state-injected to bypass the1000scan host limit. Host refusals submit no scans.",
                        "files": {
                            str(p.relative_to(folder)): {
                                "bytes": p.stat().st_size,
                                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                            }
                            for p in sorted(folder.rglob("*"))
                            if p.is_file()
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if failure:
            raise failure
        if cleanup:
            raise cleanup[0]
        assert process is not None and process.poll() is not None
