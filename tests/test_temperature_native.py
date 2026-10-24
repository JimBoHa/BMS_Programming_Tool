"""Execute quantity arithmetic in independent compiler/interpreter backends."""

import io
import xml.etree.ElementTree as XML
import zipfile

import pytest
from bms_tool.formats import export_program, import_program
from bms_tool.iec import NativeIEC, profile
from bms_tool.native_simulator import NativeSimulator
from bms_tool.niagara import SOURCE, NiagaraArchive, export_bog, import_bog
from bms_tool.storage import Store
from bms_tool.temco import native_status, verify_program

from .test_native_sedona import has_sdk
from .test_niagara_sdk import DescriptorRegistry
from .test_niagara_sdk import sdk as genuine_sdk
from .test_temperature_quantities import operation, temperature_chain

FRAMES = [
    ({"a": 86, "b": 68, "base": 20}, {"absolute": 30, "change": 10}),
    ({"a": 32, "b": 50, "base": -10}, {"absolute": -20, "change": -10}),
    ({"a": 0, "b": 0, "base": -273.15}, {"absolute": -273.15, "change": 0}),
]


@pytest.mark.skipif(not profile()["available"], reason="Optional MatIEC toolchain unavailable")
def test_independent_iec_executes_temperature_chain_and_holds_after_bad_quality():
    with NativeIEC(temperature_chain()) as native:
        for values, expected in FRAMES:
            row = native.step(values)
            assert row["outputs"] == pytest.approx(expected, abs=0.0001)
            assert not row["fault"] and row["matches_reference"]
        before = row
        failed = native.step({"a": {"value": None, "quality": "open-circuit"}})
        assert failed["fault"] and failed["outputs"] == before["outputs"]
        assert failed["successful_scans"] == before["successful_scans"]
        assert failed["native_state"] == before["native_state"]
        assert native.step(FRAMES[0][0])["outputs"] == pytest.approx(FRAMES[0][1])


@pytest.mark.skipif(not has_sdk(), reason="Optional native Sedona toolchain unavailable")
def test_independent_sedona_executes_temperature_chain_and_holds_after_bad_quality(tmp_path):
    native = NativeSimulator(Store(tmp_path))
    try:
        native.start(temperature_chain())
        for values, expected in FRAMES:
            row = native.step(values)
            assert row["outputs"] == pytest.approx(expected, abs=0.0001)
            assert not row["fault"] and row["matches_reference"]
        before = row
        failed = native.step({"a": {"value": None, "quality": "open-circuit"}})
        assert failed["fault"] and failed["outputs"] == before["outputs"]
        assert failed["successful_scans"] == before["successful_scans"]
        assert native.step(FRAMES[0][0])["outputs"] == pytest.approx(FRAMES[0][1])
    finally:
        native.stop()


@pytest.mark.skipif(
    not native_status()["available"], reason="Optional native Temco compiler unavailable"
)
def test_independent_temco_bytecode_executes_all_temperature_chain_scans():
    result = verify_program(temperature_chain(), scans=3, input_sequence=[v for v, _ in FRAMES])
    assert result["matches_reference"] and result["bytecode_bytes"] > 9
    for row, (_, expected) in zip(result["history"], FRAMES, strict=True):
        assert row["outputs"] == pytest.approx(expected, abs=0.005)


@pytest.mark.parametrize("backend", ["iec", "sedona", "temco"])
def test_cross_unit_offset_runs_in_independent_targets(backend, tmp_path):
    p = operation(
        "TemperatureOffset",
        {"base": "degF", "difference": "delta-degC"},
        unit="degF",
        params={"unit": "degF", "difference_unit": "delta-degC"},
        defaults={"base": 32, "difference": -10},
    )
    if backend == "iec":
        if not profile()["available"]:
            pytest.skip("Optional MatIEC unavailable")
        with NativeIEC(p) as native:
            row = native.step()
    elif backend == "sedona":
        if not has_sdk():
            pytest.skip("Optional Sedona unavailable")
        native = NativeSimulator(Store(tmp_path))
        try:
            native.start(p)
            row = native.step()
        finally:
            native.stop()
    else:
        if not native_status()["available"]:
            pytest.skip("Optional Temco unavailable")
        row = verify_program(p)
    assert row["outputs"]["out"] == pytest.approx(14, abs=0.005)
    assert row["matches_reference"]


def test_temperature_bog_composites_and_facets_match_genuine_niagara_metadata():
    directory = genuine_sdk.__wrapped__()
    registry = DescriptorRegistry(directory)
    try:
        for p in [
            temperature_chain(),
            operation(
                "TemperatureOffset",
                {"base": "degF", "difference": "delta-degC"},
                unit="degF",
                params={"unit": "degF", "difference_unit": "delta-degC"},
            ),
        ]:
            data = export_bog(p)
            document = XML.fromstring(SOURCE.sub(b"", NiagaraArchive(data).xml))
            registry.check(document)
            assert import_bog(data) == p
    finally:
        registry.docs.close()


@pytest.mark.skipif(not has_sdk(), reason="Optional native Sedona toolchain unavailable")
@pytest.mark.parametrize("format", ["sedona", "sedona-sax", "sedona-sab"])
def test_native_sedona_exports_keep_exact_temperature_quantity_graph(format):
    program = temperature_chain()
    data, _, extension = export_program(program, format)
    assert len(data) > 100
    if format == "sedona":
        assert import_program(data, "quantity." + extension) == program
    else:
        bundle, _, _ = export_program(program, "sedona")
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert data == archive.read("app." + extension)
        # Standalone native applications reference their generated kit. They do
        # not carry the bundle's checked editable authoring metadata.
        with pytest.raises(ValueError, match="Generated Studio graphs use their"):
            import_program(data, "quantity." + extension)
