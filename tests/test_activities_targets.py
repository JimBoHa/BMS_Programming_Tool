"""Existing target profiles consume one ordinary expansion, not native activities."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from bms_tool import activities as a
from bms_tool import iec, temco
from bms_tool.formats import export_program, import_program
from bms_tool.models import canonical
from bms_tool.native_simulator import NativeSimulator
from bms_tool.sedona import kit_source, toolchain
from bms_tool.storage import Store

from tests.test_activities import caller


def location(name):
    root = os.environ.get("BMS_ACTIVITY_TARGET_EVIDENCE")
    if root:
        folder = Path(root) / name
        folder.mkdir(parents=True, exist_ok=False)
        return folder


def record(folder, name, value):
    if folder:
        (folder / name).write_text(json.dumps(value, indent=2) + "\n")


def sedona_available():
    try:
        sdk, _ = toolchain()
        return (sdk / "bin/svm-bms64").is_file()
    except ValueError:
        return False


@pytest.mark.skipif(not sedona_available(), reason="Optional pinned Sedona SVM unavailable")
def test_existing_sedona_compiler_svm_root_outputs_quality_and_full_hierarchy_bundle(tmp_path):
    program = caller(nested=True)
    original, folder = canonical(program), location("sedona")
    native = NativeSimulator(Store(tmp_path))
    process, rows, failure = None, [], None
    try:
        started = native.start(program)
        process = native.process
        record(folder, "start.original.json", started)
        for inputs in ({}, {}, {"request0": {"quality": "unreliable"}}, {"request0": 10}):
            result = native.step(inputs)
            rows.append({"inputs": inputs, "observed": result})
            assert result["matches_reference"], result
        assert rows[0]["observed"]["outputs"] == {"value0": 2, "active0": True}
        assert (
            rows[1]["observed"]["outputs"]
            == rows[2]["observed"]["outputs"]
            == {"value0": 4, "active0": True}
        )
        assert rows[2]["observed"]["fault"] and rows[3]["observed"]["outputs"]["value0"] == 6
        bundle, _, _ = export_program(program, "sedona")
        assert canonical(import_program(bundle, "original.sedona.zip")) == original
        if folder:
            (folder / "program.original.json").write_bytes(original)
            (folder / "Graph.pregenerated.sedona").write_bytes(kit_source(program))
            (folder / "bundle.original.sedona.zip").write_bytes(bundle)
            for path in native.folder.iterdir():
                if path.is_file():
                    shutil.copyfile(path, folder / path.name)
        assert canonical(program) == original
    except BaseException as exc:
        failure = exc
    finally:
        native.stop()
        record(folder, "frames.original.json", rows)
        record(
            folder,
            "EVIDENCE.json",
            {
                "pid": process.pid if process else None,
                "reaped": process is not None and process.poll() is not None,
                "returncode": process.poll() if process else None,
                "failure": repr(failure) if failure else None,
                "scope": "Actual pinned Sedona compiler/owned loopback SVM/root slots; no private native Activity output probes or forces, no field device",
            },
        )
    if failure:
        raise failure
    assert process is not None and process.poll() is not None


@pytest.mark.skipif(
    not temco.native_status()["available"], reason="Optional native Temco host unavailable"
)
def test_existing_temco_source_compiler_interpreter_and_original_hierarchy_annotation():
    program = caller()
    original, folder = canonical(program), location("temco")
    source = temco.export_source(program)
    if folder:
        (folder / "program.original.json").write_bytes(original)
        (folder / "source.original.bas").write_text(source)
    assert canonical(temco.import_source(source)) == original
    compiled = temco.compile_program(program)
    assert compiled["source"] == source and len(compiled["bytecode"]) < 2000
    result = temco.verify_program(program, scans=2)
    record(folder, "verify.original.json", result)
    if folder:
        (folder / "bytecode.original.bin").write_bytes(compiled["bytecode"])
        record(
            folder, "compiler.original.json", {k: v for k, v in compiled.items() if k != "bytecode"}
        )
    assert result["matches_reference"], result
    assert result["outputs"] == {"value0": 4, "active0": True}
    assert canonical(program) == original


@pytest.mark.skipif(not iec.profile()["available"], reason="Optional pinned IEC host unavailable")
def test_actual_iec_verification_and_scenario_carry_one_source_bound_alias_table():
    program, folder = caller(), location("iec-reports")
    for name, result in (
        ("verify", iec.verify_program(program, scans=2)),
        (
            "scenario",
            iec.verify_scenario(program.model_dump(), [{"time": 0, "inputs": {"request0": 10}}], 2),
        ),
    ):
        record(folder, name + ".original.json", result)
        assert result["activity_bindings"] == a.resolve(program)
        assert result["matches_reference"] and result["native_runtime_verified"]
        assert len(result["rows"]) == 2
        assert all(
            "activity_bindings" not in row and "symbol_table" not in row for row in result["rows"]
        )
        assert result["rows"][-1]["outputs"] == {"value0": 4, "active0": True}
        table = result["symbol_table"]
        assert (
            table["sha256"]
            == hashlib.sha256(
                a.canonical({k: v for k, v in table.items() if k != "sha256"})
            ).hexdigest()
        )
