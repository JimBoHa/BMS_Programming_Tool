"""Representative exact-friendly native timelines; not physical stroke proof."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.activities import resolve
from bms_tool.cw_isolation_output_template import PROFILE_SHA
from bms_tool.formats import export_st
from bms_tool.models import canonical

from tests.test_cw_isolation_output_template import caller

CASES = {
    "rise-down-disable-restart": (20.0, 4, 1, 1),
    "target-floor-and-clipping": (75.0, 4, 1, 1),
    "two-independent-instances": (20.0, 4, 1, 2),
    "aligned-three-second-scan": (-0.0, 6, 3, 1),
}


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize("case", list(CASES))
def test_actual_fixed_scan_cw_two_output_state_disable_quality_and_returned_compiler_table(case):
    minimum, stroke, scan, instances = CASES[case]
    program = caller(minimum, stroke, scan, instances)
    original = canonical(program)
    root = os.environ.get("BMS_CW_OUTPUT_NATIVE_EVIDENCE")
    folder = Path(root) / case if root else None
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "program.original.json").write_bytes(original)
        (folder / "bindings.original.json").write_text(
            json.dumps(resolve(program), indent=2) + "\n"
        )
        (folder / "pregenerated-program.st").write_bytes(
            export_st(program, embedded=False) + iec._CONFIGURATION.encode()
        )
    native, process, failure, rows, cleanup = None, None, None, [], []
    try:
        native = iec.NativeIEC(program)
        process = native.process
        compilation = native.compilation()
        if folder:
            (folder / "compilation.returned.original.json").write_text(
                json.dumps(compilation, indent=2) + "\n"
            )
            (folder / "symbol-table.returned.original.json").write_text(
                json.dumps(compilation["symbol_table"], indent=2) + "\n"
            )
            (folder / "expanded.original.json").write_bytes(canonical(native.graph))
        assert compilation["activity_bindings"] == resolve(program)
        assert compilation["symbol_table"] == native.symbols.evidence()
        assert compilation["program_sha256"] == program.digest()
        assert len(native.symbols.state_rows()) == instances
        assert (
            program.metadata["macros"]["definitions"][0]["program"]["metadata"][
                "cw_isolation_output_template"
            ]["profile_sha256"]
            == PROFILE_SHA
        )
        if folder:
            assert (folder / "pregenerated-program.st").read_bytes() == (
                native.directory / "program.st"
            ).read_bytes()

        def run(inputs, expected=None):
            observed = native.step(inputs)
            rows.append(
                {
                    "inputs": inputs,
                    "independent_outputs": expected,
                    "native_step_observation": observed,
                }
            )
            assert observed["matches_reference"], observed
            assert "activity_bindings" not in observed and "symbol_table" not in observed
            if expected is not None:
                assert not observed["fault"] and observed["outputs"] == expected
            return observed

        if case == "rise-down-disable-restart":
            vector = [
                (False, 100, 0),
                (True, 100, 25),
                (True, 100, 50),
                (True, 100, 75),
                (True, 10, 50),
                (True, 10, 25),
                (True, 10, 20),
                (False, 100, 0),
                (True, 80, 25),
            ]
        elif case == "target-floor-and-clipping":
            vector = [
                (True, 0, 25),
                (True, 0, 50),
                (True, 0, 75),
                (True, 250, 100),
                (False, -20, 0),
                (True, -20, 25),
            ]
        elif case == "aligned-three-second-scan":
            vector = [
                (True, 100, 50),
                (True, 100, 100),
                (True, 40, 50),
                (True, 40, 40),
                (False, 100, 0),
                (True, 100, 50),
            ]
        else:
            vector = []
            for one, two, enabled2, command2 in [
                (25, 20, True, 20),
                (50, 40, True, 40),
                (75, 0, False, 40),
            ]:
                run(
                    {"enable": True, "requested": 100, "enable1": enabled2, "requested1": command2},
                    {"on0": True, "effective0": one, "on1": enabled2, "effective1": two},
                )
        for enabled, command, expected in vector:
            run({"enable": enabled, "requested": command}, {"on0": enabled, "effective0": expected})
        previous = rows[-1]["native_step_observation"]
        for name in ("enable", "requested"):
            observed = run({"enable": False, "requested": 100, name: {"quality": "unreliable"}})
            assert observed["fault"] and observed["outputs"] == previous["outputs"]
            assert observed["native_state"] == previous["native_state"]
            assert (
                observed["successful_scans"] == previous["successful_scans"]
                and observed["time"] == previous["time"]
            )
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
            (folder / "frames.original.json").write_text(json.dumps(rows, indent=2) + "\n")
            (folder / "compiler-profile.original.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n"
            )
            (folder / "EVIDENCE.json").write_text(
                json.dumps(
                    {
                        "case": case,
                        "pid": process.pid if process else None,
                        "reaped": process is not None and process.poll() is not None,
                        "returncode": process.poll() if process else None,
                        "failure": repr(failure) if failure else None,
                        "cleanup_errors": [repr(x) for x in cleanup],
                        "files": {
                            p.name: {
                                "bytes": p.stat().st_size,
                                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                            }
                            for p in sorted(folder.iterdir())
                            if p.is_file()
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
        if failure:
            raise failure
        if cleanup:
            raise cleanup[0]
        assert process is not None and process.poll() is not None
