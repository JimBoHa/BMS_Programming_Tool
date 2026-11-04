"""All edited CAF copy paths retain original ZIP entry attributes, including zero."""

import copy
import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_hardware import CafHardwareBindings
from bms_tool.caf_scenarios import CafInputScenarios
from bms_tool.caf_simulation import CafSimulationProfile

from .test_caf_enum_defaults import enum_caf
from .test_caf_graph import change, connection, make_graph
from .test_caf_hardware import fixture as hardware_fixture
from .test_caf_hardware import move
from .test_caf_instance import exported as instance_export
from .test_caf_simulation import make_caf

FAMILIES = (
    "scalar",
    "enum",
    "wire",
    "connection",
    "hardware",
    "instance",
    "simulation1",
    "simulation2",
    "scenario",
)


def original(family):
    if family == "enum":
        return enum_caf()[0]
    if family == "wire":
        return make_graph()
    if family == "connection":
        return make_graph(wires=[(0, 663, 2, 513)])
    if family in ("simulation1", "simulation2", "scenario"):
        return make_caf()
    return hardware_fixture().original


def repack(raw, attributes=0, origin=0, compression=zipfile.ZIP_DEFLATED):
    source = CafArchive(raw)
    entry = copy.copy(source.info)
    entry.external_attr = attributes
    entry.create_system = origin
    entry.compress_type = compression
    entry.internal_attr = 1
    entry.comment = b"preserved member comment"
    entry.extra = b"\xfe\xca\x00\x00"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.comment = b"preserved archive comment"
        z.writestr(entry, source.xml)
        # Author the actual zero instead of zipfile's automatic Unix permissions.
        entry.external_attr = attributes
    return output.getvalue()


def changed(family, caf):
    if family == "scalar":
        return caf.patch(
            [
                {
                    "ref": "8-1/0_10",
                    "property": "2390",
                    "old": "Authored temperature",
                    "value": "Edited temperature",
                }
            ]
        )[0]
    if family == "enum":
        return caf.patch(
            [{"ref": "controller/enum", "property": "3113", "old": "1", "value": "256"}]
        )[0]
    if family == "wire":
        return CafGraph(caf).rewire_sources([change()])[0]
    if family == "connection":
        return CafGraph(caf).add_connections([connection()])[0]
    if family == "hardware":
        service = CafHardwareBindings(caf)
        request = move(caf)
        plan = service.preview(request)
        return service.export(request | {"plan_sha256": plan["plan_sha256"]})[0]
    if family == "instance":
        return instance_export(caf)[0]
    if family == "scenario":
        service = CafInputScenarios(caf)
        scenario = service.template()
        scenario["events"] = [
            {
                "time": 0,
                "values": {scenario["inputs"][0]["id"]: {"value": "73.25", "quality": "good"}},
            }
        ]
        profile = service.startup_profile(scenario, 0)
    else:
        service = CafSimulationProfile(caf, profile_version=1 if family == "simulation1" else 2)
        profile = service.export_profile()
        profile["entries"][0]["value"] = "73.25"
        if family == "simulation2":
            profile["entries"][3]["value"] = "256"
    return CafSimulationProfile(caf).apply(profile)[0]


def metadata(caf):
    return {
        k: getattr(caf.info, k)
        for k in (
            "filename",
            "date_time",
            "compress_type",
            "external_attr",
            "internal_attr",
            "create_system",
            "create_version",
            "extract_version",
            "comment",
            "extra",
            "volume",
        )
    }


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param(0, id="zero"),
        pytest.param(0x20, id="DOS-archive-bit"),
        pytest.param(0o640 << 16, id="Unix-permissions"),
    ],
)
@pytest.mark.parametrize("origin", [pytest.param(0, id="DOS"), pytest.param(3, id="Unix")])
@pytest.mark.parametrize(
    "compression",
    [
        pytest.param(zipfile.ZIP_STORED, id="stored"),
        pytest.param(zipfile.ZIP_DEFLATED, id="deflate"),
    ],
)
def test_all_copy_families_preserve_recorded_zip_metadata(family, attributes, origin, compression):
    raw = repack(original(family), attributes, origin, compression)
    caf = CafArchive(raw)
    before = {name: getattr(caf.info, name, "<unset>") for name in type(caf.info).__slots__}
    xml = caf.xml
    output = changed(family, caf)
    actual = CafArchive(output)
    assert actual.xml != xml and output != raw
    assert metadata(actual) == metadata(caf)
    assert actual.comment == caf.comment
    assert actual.info.CRC == zipfile.crc32(actual.xml) and actual.info.file_size == len(actual.xml)
    assert (
        caf.original == raw
        and caf.xml == xml
        and {name: getattr(caf.info, name, "<unset>") for name in type(caf.info).__slots__}
        == before
    )
    if family == "scalar":
        assert b"Edited temperature" in actual.xml and b"Authored dry contact" in actual.xml
    if family == "enum":
        assert (
            next(p for p in actual.properties("controller/enum") if p["id"] == "3113")["scalar"][
                "text"
            ]
            == "256"
        )
    if family == "wire":
        assert (
            CafGraph(actual).diagram("8-1/575_1")["connections"][0]["source_ref"]
            == "8-1/575_1.2_11"
        )
    if family == "connection":
        assert len(CafGraph(actual).diagram("8-1/575_1")["connections"]) == 2
    if family == "hardware":
        assert b">UI IN3<" in actual.xml and b">UI IN2<" in actual.xml
    if family == "instance":
        assert b'objectid="5336"' in actual.xml and b'<BACoid id="8">5336</BACoid>' in actual.xml
    if family in ("simulation1", "simulation2", "scenario"):
        rows = CafSimulationProfile(actual, profile_version=2).export_profile()["entries"]
        assert rows[0]["old"] == "73.25"
        assert rows[1]["old"] == "25.000" and rows[2]["old"] == "0"
        assert (
            rows[3]["old"] == ("256" if family == "simulation2" else "1") and rows[4]["old"] is None
        )
        assert actual.xml.count(b"<float>111.000</float>") == 5


def test_existing_noop_paths_retain_exact_original_zero_attribute_container():
    for family in FAMILIES:
        raw = repack(original(family))
        a = CafArchive(raw)
        assert a.patch([])[0] == raw
        if family in ("wire", "connection"):
            assert CafGraph(a).rewire_sources([])[0] == raw
            assert CafGraph(a).add_connections([])[0] == raw
        if family == "instance":
            assert instance_export(a, new_instance=99)[0] == raw
        if family in ("simulation1", "simulation2", "scenario"):
            for version in (1, 2):
                p = CafSimulationProfile(a, profile_version=version)
                assert p.apply(p.export_profile()) == (raw, [])
        assert a.info.external_attr == 0


def test_private_originals_keep_recorded_attributes_in_all_supported_in_memory_scalar_copies():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR to authorized undistributed CAF originals.")
    paths = sorted(
        p for p in Path(directory).rglob("*") if p.is_file() and p.suffix.lower() == ".caf"
    )
    assert paths
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        a = CafArchive(raw)
        assert a.patch([])[0] == raw
        target = next(
            (
                (ref, p)
                for ref in a.objects
                for p in a.properties(ref)
                if p["editable"]
                and p.get("scalar", {}).get("type") == "string"
                and p["kind"] == "property"
            ),
            None,
        )
        if target:
            ref, p = target
            output, _ = a.patch(
                [
                    {
                        "ref": ref,
                        "property": p["id"],
                        "old": p["scalar"]["text"],
                        "value": "Authored private-copy verification",
                    }
                ]
            )
            actual = CafArchive(output)
            assert metadata(actual) == metadata(a) and actual.comment == a.comment
        for version in (1, 2):
            service = CafSimulationProfile(a, profile_version=version)
            profile = service.export_profile()
            assert service.apply(profile) == (raw, [])
            row = next(
                (r for r in profile["entries"] if r["editable"] and r["native_type"] == "float"),
                None,
            )
            if row:
                row["value"] = "0" if row["old"] != "0" else "1"
                output, _ = service.apply(profile)
                actual = CafArchive(output)
                assert metadata(actual) == metadata(a) and actual.comment == a.comment
        assert path.read_bytes() == raw and hashlib.sha256(path.read_bytes()).hexdigest() == digest
