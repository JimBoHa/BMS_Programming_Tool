"""Explicit numeric saved-Enum copies preserve legacy simulation and execution scopes."""

import copy
import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive, Q
from bms_tool.caf_scenarios import CafInputScenarios
from bms_tool.caf_simulation import CafSimulationProfile
from fastapi.testclient import TestClient

from .test_caf_simulation import make_caf, pack


def source(*, cid=528, code="1", attributes='set="113"', version="1.0", cdata=False):
    xml = CafArchive(make_caf()).xml.replace(
        b'classid="528" classVersion="1.0"', f'classid="{cid}" classVersion="{version}"'.encode()
    )
    value = f"<![CDATA[{code}]]>" if cdata else code
    xml = xml.replace(b'<enum set="113">1</enum>', f"<enum {attributes}>{value}</enum>".encode())
    return pack(xml)


def enum_profile(raw):
    adapter = CafSimulationProfile(raw, profile_version=2)
    profile = adapter.export_profile()
    row = next(r for r in profile["entries"] if r["native_type"] == "enum")
    return adapter, profile, row


@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("cdata", [False, True])
@pytest.mark.parametrize("value", ["0", "255", "65535", "65536", "4294967295"])
def test_explicit_v2_numeric_enum_changes_only_its_existing_simulation_leaf(cid, cdata, value):
    raw = source(cid=cid, cdata=cdata)
    adapter, profile, row = enum_profile(raw)
    assert row["editable"] and row["maximum_code"] == 4294967295
    assert row["enum_semantics_verified"] is False and row["attributes"] == {"set": "113"}
    row["value"] = value
    output, changes = adapter.apply(profile)
    before = b"<![CDATA[1]]>" if cdata else b">1</enum>"
    after = f"<![CDATA[{value}]]>".encode() if cdata else f">{value}</enum>".encode()
    assert CafArchive(output).xml == adapter.archive.xml.replace(before, after)
    assert CafArchive(output).xml.count(b"<float>111.000</float>") == 5
    assert len(changes) == 1 and changes[0]["kind"] == "simulationProperty"
    assert changes[0]["enum_semantics_verified"] is False
    assert CafSimulationProfile(output, profile_version=2).summary()["records"][3]["old"] == value
    with (
        zipfile.ZipFile(io.BytesIO(output)) as copied,
        zipfile.ZipFile(io.BytesIO(raw)) as original,
    ):
        a, b = copied.infolist()[0], original.infolist()[0]
        assert copied.comment == original.comment
        assert (a.filename, a.date_time, a.comment, a.external_attr, a.compress_type) == (
            b.filename,
            b.date_time,
            b.comment,
            b.external_attr,
            b.compress_type,
        )
    assert adapter.archive.original == raw


def test_mixed_v2_values_and_noop_keep_all_v1_metadata_and_execution_contracts():
    raw = source()
    legacy = CafSimulationProfile(raw)
    adapter, profile, row = enum_profile(raw)
    baseline = legacy.export_profile()
    assert baseline["version"] == 1 and baseline["entries"][3]["editable"] is False
    assert adapter.apply(profile) == (raw, [])
    assert adapter.apply(baseline) == (raw, [])
    row["value"] = "4294967295"
    profile["entries"][0]["value"] = "+7.25e1"
    profile["entries"][2]["value"] = "true"
    output, changes = legacy.apply(profile)
    assert len(changes) == 3 and all(r["kind"] == "simulationProperty" for r in changes)
    assert legacy.export_profile() == baseline
    bad_legacy = copy.deepcopy(baseline)
    bad_legacy["entries"][3]["value"] = "2"
    with pytest.raises(ValueError, match="read-only"):
        adapter.apply(bad_legacy)
    before = CafInputScenarios(CafArchive(raw)).contract()
    after = CafInputScenarios(CafArchive(output)).contract()
    assert [r["class_id"] for r in before["inputs"]] == ["526", "530"]
    assert [r["class_id"] for r in after["inputs"]] == ["526", "530"]


def test_v2_preserves_recorded_zero_zip_permissions_without_changing_legacy_rules():
    original = CafArchive(source())
    stream = io.BytesIO()
    info = copy.copy(original.info)
    info.create_system = 0
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(info, original.xml)
        info.external_attr = 0
    raw = stream.getvalue()
    adapter, profile, row = enum_profile(raw)
    assert adapter.archive.info.external_attr == 0
    assert adapter.apply(profile) == (raw, [])
    row["value"] = "256"
    output, _ = adapter.apply(profile)
    assert CafArchive(output).info.external_attr == 0
    assert CafArchive(output).info.create_system == 0
    assert adapter.archive.info.external_attr == 0


@pytest.mark.parametrize(
    "value",
    ["-1", "+1", "01", "1.0", "1e2", " 1 ", "١", "4294967296", "", "On", True, 2, 2.0, None],
)
def test_enum_representation_does_not_coerce_labels_signed_decimal_or_boolean_values(value):
    adapter, profile, row = enum_profile(source())
    row["value"] = value
    with pytest.raises(ValueError, match="Simulation"):
        adapter.apply(profile)


@pytest.mark.parametrize(
    "options",
    [
        {"cid": 530},
        {"cid": 999},
        {"version": "2.0"},
        {"attributes": 'set="113" future="x"'},
        {"code": "01"},
        {"code": "-1"},
        {"code": "4294967296"},
    ],
)
def test_unknown_class_version_attributes_or_original_encoding_remain_readonly(options):
    adapter, profile, row = enum_profile(source(**options))
    assert not row["editable"] and not row["enum_semantics_verified"]
    assert adapter.apply(profile) == (adapter.archive.original, [])
    row["value"] = "2"
    with pytest.raises(ValueError, match="read-only"):
        adapter.apply(profile)


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "version",
        "boolean-version",
        "class",
        "kind",
        "set",
        "old",
        "editable",
        "meaning",
        "maximum",
        "duplicate",
        "missing",
    ],
)
def test_source_metadata_and_complete_record_guards_remain_required(fault):
    adapter, profile, row = enum_profile(source())
    row["value"] = "2"
    if fault == "source":
        profile["source_sha256"] = "0" * 64
    elif fault == "version":
        profile["version"] = 3
    elif fault == "boolean-version":
        profile["version"] = True
    elif fault == "class":
        row["class_id"] = "529"
    elif fault == "kind":
        row["kind"] = "property"
    elif fault == "set":
        row["attributes"] = {"set": "114"}
    elif fault == "old":
        row["old"] = "0"
    elif fault == "editable":
        row["editable"] = 1
    elif fault == "meaning":
        row["enum_semantics_verified"] = True
    elif fault == "maximum":
        row["maximum_code"] = 65535
    elif fault == "duplicate":
        profile["entries"][0] = copy.deepcopy(row)
    else:
        profile["entries"].pop()
    with pytest.raises(ValueError):
        adapter.apply(profile)


def test_get_version_is_canonical_and_post_remains_local_token_admitted(tmp_path):
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved simulation copy attempted a field operation")

    for name in ("require", "connect", "disconnect", "_read", "release"):
        setattr(app.state.bacnet, name, forbidden)
    raw = source()
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post("/api/caf", headers=headers, files={"file": ("authored.caf", raw)})
        assert opened.status_code == 200
        base = f"/api/caf/{opened.json()['sha256']}/simulation"
        legacy = client.get(base + "/profile").json()
        assert legacy == CafSimulationProfile(raw).export_profile()
        summary = client.get(base + "?profile_version=2").json()
        assert summary["profile_version"] == 2 and summary["counts"]["editable"] == 4
        profile = client.get(base + "/profile?profile_version=2").json()
        profile["entries"][3]["value"] = "4294967295"
        assert client.post(base, json={"profile": profile}).status_code == 403
        copied = client.post(base, headers=headers, json={"profile": profile})
        assert copied.status_code == 200, copied.text
        assert copied.headers["X-Studio-Source-Sha256"] == opened.json()["sha256"]
        assert copied.headers["X-Studio-Simulation-Version"] == "2"
        assert (
            copied.headers["X-Studio-Artifact-Sha256"] == hashlib.sha256(copied.content).hexdigest()
        )
        legacy_copy = client.post(base, headers=headers, json={"profile": legacy})
        assert legacy_copy.content == raw
        assert legacy_copy.headers["X-Studio-Simulation-Version"] == "1"
        assert (
            CafSimulationProfile(copied.content, profile_version=2).summary()["records"][3]["old"]
            == "4294967295"
        )
        assert client.get(base + "/profile").json() == legacy
        assert not client.get("/api/session").json()["field_network_open"]
        for value in ("0", "3", "true", "2.0", "02", ""):
            assert client.get(base + "/profile?profile_version=" + value).status_code == 422


def test_private_examples_v2_preserve_all_ordinary_records_and_original_files(tmp_path):
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR to authorized local, undistributed CAFs.")
    paths = sorted(
        p for p in Path(directory).rglob("*") if p.is_file() and p.suffix.lower() == ".caf"
    )
    assert paths
    total = 0
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        adapter = CafSimulationProfile(raw, profile_version=2)
        baseline = adapter.export_profile()
        assert adapter.apply(baseline) == (raw, [])
        for entry in baseline["entries"]:
            if entry["native_type"] != "enum" or not entry["editable"]:
                continue
            profile = copy.deepcopy(baseline)
            changed = next(
                r
                for r in profile["entries"]
                if (r["ref"], r["property_id"]) == (entry["ref"], entry["property_id"])
            )
            changed["value"] = "0" if entry["old"] != "0" else "4294967295"
            result, report = adapter.apply(profile)
            original_props = [
                (ref, [p for p in obj if p.tag == Q + "property"])
                for ref, obj in adapter.archive.objects.items()
            ]
            actual = CafArchive(result)
            for ref, props in original_props:
                from xml.etree import ElementTree as ET

                assert [ET.tostring(p) for p in props] == [
                    ET.tostring(p) for p in actual.objects[ref] if p.tag == Q + "property"
                ]
            assert len(report) == 1 and report[0]["native_type"] == "enum"
            (tmp_path / f"private-simulation-{total}.caf").write_bytes(result)
            total += 1
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert total > 0


@pytest.mark.parametrize(
    "body",
    ["<![CDATA[1]]><![CDATA[]]>", "<![CDATA[1]]><!--retain-->", "<!--retain-->1", "1<future/>"],
)
def test_opaque_markup_is_not_admitted_as_a_single_enum_code_span(body):
    raw = source(code=body)
    adapter = CafSimulationProfile(raw, profile_version=2)
    profile = adapter.export_profile()
    row = profile["entries"][3]
    assert not row["editable"]
    assert row["native_type"] == (None if "<future/>" in body else "enum")
    assert adapter.apply(profile) == (raw, [])
    row["value"] = "2"
    with pytest.raises(ValueError, match="read-only"):
        adapter.apply(profile)
