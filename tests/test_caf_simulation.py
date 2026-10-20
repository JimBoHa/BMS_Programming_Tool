"""Authored archive fixtures and opt-in, read-only private CAF verification."""

import copy
import io
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from bms_tool.caf import NS, CafArchive, Q
from bms_tool.caf_simulation import FORMAT, MAX_PROFILE_BYTES, CafSimulationProfile


def pack(xml):
    stream = io.BytesIO()
    entry = zipfile.ZipInfo("synthetic.caf.xml", date_time=(2020, 2, 3, 4, 5, 6))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.comment = b"preserve entry comment"
    entry.external_attr = 0o600 << 16
    with zipfile.ZipFile(stream, "w") as archive:
        archive.comment = b"preserve archive comment"
        archive.writestr(entry, xml)
    return stream.getvalue()


def make_caf():
    objects = []
    for ref, cid, native in [
        ("8-1/526_1", "526", "<float>70.000</float>"),
        ("8-1/527_2", "527", "<float>25.000</float>"),
        ("8-1/530_3", "530", "<boolean>0</boolean>"),
        ("8-1/528_4", "528", '<enum set="113">1</enum>'),
        ("8-1/999_5", "999", "<future><float>12</float></future>"),
    ]:
        objects.append(
            f'<object ref="{ref}" classid="{cid}" classVersion="1.0">'
            '<property id="2390"><data><string>Authored simulation example</string></data></property>'
            '<property id="3113"><data><float>111.000</float></data></property>'
            f'<simulationProperty id="3113"><data>{native}</data></simulationProperty>'
            '<property id="9999"><data><opaque> untouched </opaque></data></property></object>'
        )
    xml = (
        f'<objects xmlns="{NS}">'
        + "".join(objects)
        + "<jobInfo><string>Opaque root metadata</string></jobInfo></objects>"
    )
    return pack(xml.encode())


def edit(profile, index, value):
    profile["entries"][index]["value"] = value
    return profile


def test_profile_inventory_separates_simulation_records_and_opaque_types():
    adapter = CafSimulationProfile(make_caf())
    summary = adapter.summary()
    assert summary["counts"] == {
        "total": 5,
        "editable": 3,
        "read_only": 2,
        "types": {"float": 2, "boolean": 1, "enum": 1, "opaque": 1},
    }
    assert summary["records"][0]["old"] == "70.000"
    assert summary["records"][3]["attributes"] == {"set": "113"}
    assert "enum domain" in summary["records"][3]["reason"]
    assert summary["records"][4]["old"] is None
    profile = adapter.export_profile()
    assert profile["format"] == FORMAT
    assert profile["version"] == 1
    assert profile["source_sha256"] == summary["sha256"]
    assert profile["entries"] == summary["records"]
    assert adapter.apply(profile) == (adapter.archive.original, [])
    profile["entries"].reverse()
    assert adapter.apply(profile) == (adapter.archive.original, [])


def test_batch_edit_changes_only_existing_simulation_leaves_and_preserves_native_archive():
    adapter = CafSimulationProfile(make_caf())
    original = adapter.archive.xml
    crc, size = adapter.archive.info.CRC, adapter.archive.info.file_size
    profile = adapter.export_profile()
    edit(profile, 0, "+7.25e1")
    edit(profile, 1, "-0.0")
    edit(profile, 2, "true")
    result, report = adapter.apply(profile)
    assert len(report) == 3
    expected = original.replace(b"<float>70.000</float>", b"<float>+7.25e1</float>")
    expected = expected.replace(b"<float>25.000</float>", b"<float>-0.0</float>")
    expected = expected.replace(b"<boolean>0</boolean>", b"<boolean>true</boolean>")
    actual = CafArchive(result)
    assert actual.xml == expected
    assert actual.xml.count(b"<float>111.000</float>") == 5
    assert all(row["kind"] == "simulationProperty" for row in report)
    assert all("unverified" in row["validation"] for row in report)
    assert adapter.archive.xml == original
    assert (adapter.archive.info.CRC, adapter.archive.info.file_size) == (crc, size)
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.comment == b"preserve archive comment"
        info = archive.infolist()[0]
        assert info.date_time == (2020, 2, 3, 4, 5, 6)
        assert info.comment == b"preserve entry comment"
        assert info.external_attr == 0o600 << 16
    with pytest.raises(ValueError, match="source SHA-256"):
        CafSimulationProfile(result).apply(profile)


@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "Infinity",
        "1e400",
        "3.5e38",
        "1e-50",
        "1e-999",
        "1_000",
        "١",
        "",
        ".",
        "1,5",
        10,
        True,
        None,
    ],
)
def test_float_values_require_finite_native_float32_text(value):
    adapter = CafSimulationProfile(make_caf())
    with pytest.raises(ValueError, match="Simulation"):
        adapter.apply(edit(adapter.export_profile(), 0, value))


@pytest.mark.parametrize("value", ["1", "false", "true"])
def test_observed_boolean_native_spellings(value):
    adapter = CafSimulationProfile(make_caf())
    result, _ = adapter.apply(edit(adapter.export_profile(), 2, value))
    assert CafSimulationProfile(result).summary()["records"][2]["old"] == value


@pytest.mark.parametrize("value", ["True", "FALSE", "2", " 1 ", True])
def test_boolean_values_do_not_use_python_truthiness(value):
    adapter = CafSimulationProfile(make_caf())
    with pytest.raises(ValueError, match="Simulation"):
        adapter.apply(edit(adapter.export_profile(), 2, value))


def test_float_xml_whitespace_and_carriage_returns_have_exact_readback():
    adapter = CafSimulationProfile(make_caf())
    spelling = " \t-2.50E+1\r\n"
    result, _ = adapter.apply(edit(adapter.export_profile(), 0, spelling))
    assert CafSimulationProfile(result).summary()["records"][0]["old"] == spelling
    assert b" \t-2.50E+1&#13;\n" in CafArchive(result).xml


@pytest.mark.parametrize("index,value", [(3, "2"), (4, "12")])
def test_enums_and_unknown_native_structures_remain_read_only(index, value):
    adapter = CafSimulationProfile(make_caf())
    with pytest.raises(ValueError, match="read-only"):
        adapter.apply(edit(adapter.export_profile(), index, value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("old", "70"),
        ("native_type", "boolean"),
        ("class_id", "527"),
        ("class_version", "2.0"),
        ("kind", "property"),
        ("attributes", {"unknown": "1"}),
        ("editable", 1),
        ("name", "Spoofed display name"),
        ("reason", "unchecked"),
    ],
)
def test_all_profile_record_guards_are_checked(field, value):
    adapter = CafSimulationProfile(make_caf())
    profile = edit(adapter.export_profile(), 0, "71")
    profile["entries"][0][field] = value
    with pytest.raises(ValueError, match="guard changed"):
        adapter.apply(profile)


@pytest.mark.parametrize(
    "field,value", [("format", "other"), ("version", True), ("source_sha256", "0" * 64)]
)
def test_profile_is_bound_to_exact_source_and_version(field, value):
    adapter = CafSimulationProfile(make_caf())
    profile = adapter.export_profile()
    profile[field] = value
    with pytest.raises(ValueError, match="format, version or source SHA-256"):
        adapter.apply(profile)


def test_missing_duplicate_unknown_and_extra_profile_fields_are_rejected():
    adapter = CafSimulationProfile(make_caf())
    profile = adapter.export_profile()
    mutations = []
    missing = copy.deepcopy(profile)
    missing["entries"].pop()
    mutations.append(missing)
    duplicate = copy.deepcopy(profile)
    duplicate["entries"][1] = duplicate["entries"][0]
    mutations.append(duplicate)
    unknown = copy.deepcopy(profile)
    unknown["entries"][0]["ref"] = "missing"
    mutations.append(unknown)
    extra = copy.deepcopy(profile)
    extra["entries"][0]["unexpected"] = True
    mutations.append(extra)
    extra_header = copy.deepcopy(profile)
    extra_header["unexpected"] = True
    mutations.append(extra_header)
    mutations.extend([None, [], {**profile, "entries": {}}, {**profile, "entries": [None] * 5}])
    for malformed in mutations:
        with pytest.raises(ValueError):
            adapter.apply(malformed)
    assert adapter.archive.original == make_caf()


@pytest.mark.parametrize(
    "old,new",
    [
        (b'classVersion="1.0"', b'classVersion="2.0"'),
        (b'classid="526"', b'classid="999"'),
        (b"<float>70.000</float>", b'<float units="unknown">70.000</float>'),
        (b"<float>70.000</float>", b"<float>70<!--opaque comment-->.000</float>"),
        (b"<float>70.000</float>", b"<float>NaN</float>"),
        (b'<simulationProperty id="3113">', b'<simulationProperty id="3114">'),
    ],
)
def test_unobserved_records_are_inspectable_but_not_editable(old, new):
    xml = CafArchive(make_caf()).xml.replace(old, new, 1)
    adapter = CafSimulationProfile(pack(xml))
    row = adapter.summary()["records"][0]
    assert not row["editable"]
    assert adapter.apply(adapter.export_profile()) == (adapter.archive.original, [])


def test_prefixed_xml_and_comment_lookalikes_do_not_redirect_the_native_edit():
    xml = CafArchive(make_caf()).xml
    xml = xml.replace(b'<objects xmlns="', b'<objects xmlns:c="')
    # Keep the original default namespace and prefix only the first real leaf.
    xml = xml.replace(b'<objects xmlns:c="', b'<objects xmlns="' + NS.encode() + b'" xmlns:c="')
    xml = xml.replace(
        b"<float>70.000</float>",
        b'<!-- <simulationProperty id="3113"><data><float>70.000</float></data></simulationProperty> -->'
        b"<c:float>70.000</c:float>",
        1,
    )
    adapter = CafSimulationProfile(pack(xml))
    result, _ = adapter.apply(edit(adapter.export_profile(), 0, "72.5"))
    actual = CafArchive(result).xml
    assert actual == xml.replace(b"<c:float>70.000</c:float>", b"<c:float>72.5</c:float>", 1)


def test_empty_native_simulation_profile_is_a_byte_exact_no_op():
    xml = f'<objects xmlns="{NS}"><object ref="8-1/575_1"/></objects>'.encode()
    adapter = CafSimulationProfile(pack(xml))
    assert adapter.summary()["counts"]["total"] == 0
    assert adapter.apply(adapter.export_profile()) == (adapter.archive.original, [])


def test_oversized_opaque_simulation_metadata_is_rejected_without_clipping_guards():
    xml = CafArchive(make_caf()).xml.replace(
        b"<future><float>12</float></future>",
        b"<string>" + b"x" * (MAX_PROFILE_BYTES // 2) + b"</string>",
    )
    adapter = CafSimulationProfile(pack(xml))
    assert adapter.archive.xml == xml
    with pytest.raises(ValueError, match="2 MiB serialized limit"):
        adapter.summary()
    with pytest.raises(ValueError, match="2 MiB serialized limit"):
        adapter.export_profile()
    normal = CafSimulationProfile(make_caf())
    profile = normal.export_profile()
    profile["entries"][4]["value"] = "x" * MAX_PROFILE_BYTES
    with pytest.raises(ValueError, match="2 MiB serialized limit"):
        normal.apply(profile)


def test_private_native_simulation_profiles_preserve_all_ordinary_properties_and_original_files():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR to authorized local, undistributed CAFs.")
    files = sorted(Path(directory).rglob("*.caf"))
    assert files
    totals = {"records": 0, "editable": 0, "float": 0, "boolean": 0, "enum": 0}
    for path in files:
        original = path.read_bytes()
        adapter = CafSimulationProfile(original)
        profile = adapter.export_profile()
        rows = profile["entries"]
        totals["records"] += len(rows)
        for row in rows:
            if row["native_type"] in totals:
                totals[row["native_type"]] += 1
            if row["editable"]:
                totals["editable"] += 1
                row["value"] = (
                    ("0" if row["old"] in {"1", "true"} else "1")
                    if row["native_type"] == "boolean"
                    else ("12.75" if row["old"] != "12.75" else "13.25")
                )
        result, report = adapter.apply(profile)
        assert len(report) == sum(row["editable"] for row in rows)
        parsed = CafArchive(result)
        for ref, obj in adapter.archive.objects.items():
            old_props = [ET.tostring(p) for p in obj if p.tag != Q + "simulationProperty"]
            new_props = [
                ET.tostring(p) for p in parsed.objects[ref] if p.tag != Q + "simulationProperty"
            ]
            assert old_props == new_props
        assert path.read_bytes() == original
    # The known seven-file corpus has saved simulation values in four CAFs.
    if len(files) == 7:
        assert totals == {"records": 72, "editable": 50, "float": 39, "boolean": 11, "enum": 22}
