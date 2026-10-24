"""Opaque legacy metadata never becomes new activity execution authority."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from bms_tool import iec
from bms_tool.iec import _activity_evidence
from bms_tool.macros import expand_macros
from bms_tool.models import Edge, Node, Program, canonical


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2},
        {"version": 2, "outputs": [{"alias_node_id": "untrusted", "output_id": "fake"}]},
    ],
    ids=["missing-outputs", "forged-outputs"],
)
def test_opaque_activity_expansion_metadata_never_enables_native_binding_evidence(legacy, payload):
    if legacy:
        from tests.test_macros import caller

        program = caller()
    else:
        program = Program(
            nodes=[
                Node(id="input", kind="Input", params={"default": 3}),
                Node(id="out", kind="Output"),
            ],
            edges=[Edge(id="wire", source="input", target="out")],
        )
    program.metadata["activity_expansion"] = payload
    original = canonical(program)
    native = SimpleNamespace(program=program, graph=expand_macros(program))
    assert _activity_evidence(native) == {}
    assert canonical(program) == original


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize("case", ["ordinary", "v1"])
def test_actual_legacy_opaque_program_retains_original_native_report_shape(case):
    fixture = Path(__file__).parent / "fixtures/activity-legacy-opaque"
    raw = (fixture / (case + ".json")).read_bytes()
    program = Program.model_validate_json(raw)
    root = os.environ.get("BMS_ACTIVITY_OPAQUE_NATIVE_EVIDENCE")
    folder = Path(root) / case if root else None
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "program.original.json").write_bytes(raw)
    native, process, failure, rows = None, None, None, []
    try:
        native = iec.NativeIEC(program)
        process = native.process
        report = native.compilation()
        assert set(report) == set(json.loads((fixture / "report-keys.json").read_text()))
        assert "activity_bindings" not in report
        assert report["program_sha256"] == program.digest()
        if folder:
            (folder / "compilation.original.json").write_text(json.dumps(report, indent=2) + "\n")
        previous = native.step()
        rows.append(previous)
        assert not previous["fault"] and previous["outputs"] == {
            "out": 3 if case == "ordinary" else 5
        }
        name = next(n.id for n in program.nodes if n.kind == "Input")
        fault = native.step({name: {"quality": "unreliable"}})
        rows.append(fault)
        assert fault["fault"] and fault["outputs"] == previous["outputs"]
        baseline = os.environ.get("BMS_ACTIVITY_OPAQUE_BASELINE")
        if baseline:
            original = json.loads(
                (Path(baseline) / case / "compilation.original.json").read_bytes()
            )
            for key in (
                "source_st",
                "generated_c",
                "program_sha256",
                "symbol_table",
                "source_generator",
                "profile",
            ):
                assert report[key] == original[key], key
            assert (
                previous
                == json.loads((Path(baseline) / case / "frames.original.json").read_bytes())[0]
            )
        assert canonical(program) == raw
    except BaseException as exc:
        failure = exc
    finally:
        try:
            if native is not None and folder:
                for path in native.directory.iterdir():
                    if path.is_file():
                        shutil.copyfile(path, folder / path.name)
        finally:
            if native is not None:
                native.close()
        if folder:
            (folder / "frames.original.json").write_text(json.dumps(rows, indent=2) + "\n")
            (folder / "EVIDENCE.json").write_text(
                json.dumps(
                    {
                        "pid": process.pid if process else None,
                        "reaped": process is not None and process.poll() is not None,
                        "returncode": process.poll() if process else None,
                        "failure": repr(failure) if failure else None,
                        "files": {
                            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in folder.iterdir()
                            if p.is_file()
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
    if failure:
        raise failure
    assert process is not None and process.poll() is not None
