"""Actual unchanged IEC curve/hold and explicitly qualified REAL boundary evidence."""

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
from bms_tool.co2_minimum_flow_template import PROFILE_SHA
from bms_tool.formats import export_st
from bms_tool.models import canonical

from tests.test_co2_minimum_flow_template import PORTS, caller


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize(
    "case", ["curve-hold-repair", "coalesced-endpoints", "near-min-normal-span"]
)
def test_actual_shared_state_reset_curve_quality_and_real_width_boundaries(case):
    program = caller(scan=0.5 if case == "curve-hold-repair" else 3.0)
    original = canonical(program)
    root = os.environ.get("BMS_CO2_MIN_FLOW_NATIVE_EVIDENCE")
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
    native, process, failure, rows, cleanup, refused = None, None, None, [], [], []
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
        assert (
            compilation["program_sha256"] == program.digest()
            and len(native.symbols.state_rows()) == 1
        )
        assert (
            program.metadata["macros"]["definitions"][0]["program"]["metadata"][
                "co2_minimum_flow_template"
            ]["profile_sha256"]
            == PROFILE_SHA
        )
        if folder:
            assert (folder / "pregenerated-program.st").read_bytes() == (
                native.directory / "program.st"
            ).read_bytes()

        def run(inputs, expected=None, matches=True):
            observed = native.step(inputs)
            rows.append(
                {
                    "inputs": inputs,
                    "independent_outputs": expected,
                    "expected_matches_reference": matches,
                    "native_step_observation": observed,
                }
            )
            assert observed["matches_reference"] is matches, observed
            assert "activity_bindings" not in observed and "symbol_table" not in observed
            if expected is not None:
                assert not observed["fault"] and observed["outputs"] == expected
            return observed

        if case == "curve-hold-repair":
            first = run({"co2": {"quality": "open-circuit"}})
            assert first["fault"] and first["outputs"] == {"flow0": 0, "valid0": False}
            assert first["successful_scans"] == 0 and first["time"] == 0
            for sample, flow in [(700, 425), (800, 425), (900, 625), (1000, 825), (1200, 825)]:
                run({"co2": sample}, {"flow0": flow, "valid0": True})
            for values in (
                {"co2_reset_b": 800},
                {"co2_reset_a": 1200},
                {"flow_low": 900, "flow_high": 100},
                {"flow_high": 1e30},
            ):
                run({"co2": 3e38, **values}, {"flow0": 825, "valid0": False})
            run(
                {
                    "co2": 500,
                    "co2_reset_a": 400,
                    "co2_reset_b": 800,
                    "flow_low": 100,
                    "flow_high": 300,
                },
                {"flow0": 150, "valid0": True},
            )
            run({"co2": 900, "flow_low": 77, "flow_high": 77}, {"flow0": 77, "valid0": True})
            run({"co2": 1000}, {"flow0": 825, "valid0": True})
        elif case == "coalesced-endpoints":
            run({"co2": 900}, {"flow0": 625, "valid0": True})
            narrow_b = math.nextafter(800.0, math.inf)
            different = run(
                {"co2": 800, "co2_reset_a": 800, "co2_reset_b": narrow_b},
                {"flow0": 625, "valid0": False},
                matches=False,
            )
            assert different["reference_outputs"] == {"flow0": 425, "valid0": True}
            assert different["successful_scans"] == 2 and different["reference_fault"] is None
            run({"co2": 1000}, {"flow0": 825, "valid0": True})
        else:
            a = 2**-126
            b = a + 2**-149
            run({"co2": a, "co2_reset_a": a, "co2_reset_b": b}, {"flow0": 425, "valid0": True})
            run({"co2": b, "co2_reset_a": a, "co2_reset_b": b}, {"flow0": 825, "valid0": True})
            run({"co2": b, "co2_reset_a": a, "co2_reset_b": a}, {"flow0": 825, "valid0": False})
            run({"co2": 900}, {"flow0": 625, "valid0": True})
        previous = rows[-1]["native_step_observation"]
        for name in PORTS:
            observed = run({"co2_reset_b": 800, name: {"quality": "unreliable"}})
            assert observed["fault"] and observed["outputs"] == previous["outputs"]
            assert observed["native_state"] == previous["native_state"]
            assert (
                observed["successful_scans"] == previous["successful_scans"]
                and observed["time"] == previous["time"]
            )
        before = copy.deepcopy(native.history)
        for sample, reason in ((1e308, "within"), (5e-324, "underflows")):
            with pytest.raises(ValueError, match=reason) as error:
                native.step({"co2": sample})
            refused.append(
                {
                    "inputs": {"co2": sample},
                    "actual_host_error": str(error.value),
                    "native_exchange_submitted": False,
                }
            )
            assert native.history == before
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
            (folder / "host-refusals.original.json").write_text(
                json.dumps(refused, indent=2) + "\n"
            )
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
                        "qualification": "Decoded actual IEC frames, including explicitly expected coalesced-endpoint reference mismatch; not raw stdout or native JCI/physical/ventilation proof. Host range/underflow refusals do not submit scans.",
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
