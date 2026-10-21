"""Authored native CAF hardware fixtures, without building application data."""

import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_hardware import CafHardwareBindings, HardwareMoveRequest
from fastapi.testclient import TestClient
from pydantic import ValidationError


def fixture_xml(model="MS-VMA1630-0", extra=""):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<objects xmlns="{NS}">
<!-- Preserve unrelated native comments and opaque payload exactly. -->
<object classid="194" classVersion="1.0" ref="8-1" objectid="99">
<property id="70"><data><string>{model}</string></data></property>
<property id="12"><data><string>10.2</string></data></property>
<property id="75"><data><BACoid id="8">99</BACoid></data></property>
<property id="32527"><data><string>8-1</string></data></property>
</object>
<object classid="240" classVersion="1.0" ref="8-1/0_10" objectid="10">
<property id="75"><data><BACoid id="0">10</BACoid></data></property>
<property id="32527"><data><string>8-1/0_10</string></data></property>
<property id="31"><data><string>UI IN1</string></data></property>
<property id="519"><data><unsignedByte>1</unsignedByte></data></property>
<property id="518"><data><enum set="360">3</enum></data></property>
<property id="2390"><data><string>Authored temperature</string></data></property>
<property id="1293"><data><float>-40.000</float></data></property>
<property id="909090"><data><opaque preserve="yes"> raw &amp; unknown </opaque></data></property>
</object>
<object classid="242" classVersion="1.0" ref="8-1/3_20" objectid="20">
<property id="75"><data><BACoid id="3">20</BACoid></data></property>
<property id="32527"><data><string>8-1/3_20</string></data></property>
<property id="31"><data><string>UI IN2</string></data></property>
<property id="519"><data><unsignedByte>2</unsignedByte></data></property>
<property id="2390"><data><string>Authored dry contact</string></data></property>
<property id="931"><data><unsignedByte>0</unsignedByte></data></property>
</object>
<object classid="240" classVersion="1.0" ref="8-1/0_30" objectid="30">
<property id="75"><data><BACoid id="0">30</BACoid></data></property>
<property id="32527"><data><string>8-1/0_30</string></data></property>
<property id="31"><data><string>AI1-Int</string></data></property>
<property id="519"><data><unsignedByte>4</unsignedByte></data></property>
<property id="518"><data><enum set="360">9</enum></data></property>
</object>
{extra}<jobInfo><opaque untouched="true">not a program compiler</opaque></jobInfo>
</objects>'''.encode()


def fixture(xml=None, **kwargs):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.comment = b"Authored fixture comment"
        info = zipfile.ZipInfo("authored-native.xml", (2020, 1, 2, 3, 4, 6))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        info.comment = b"member comment"
        info.extra = b"\xfe\xca\x00\x00"
        archive.writestr(info, xml or fixture_xml(**kwargs))
    return CafArchive(stream.getvalue())


def move(caf, ref="8-1/0_10", old=1, destination=3):
    return {"source_sha256": caf.hash, "ref": ref, "old_slot": old, "destination_slot": destination}


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCV1630-0", "FX-PCV1615-0"])
def test_real_native_scalar_edit_preserves_xml_identity_signal_and_zip_metadata(model):
    caf = fixture(model=model)
    bindings = CafHardwareBindings(caf)
    summary = bindings.summary()
    assert summary["supported"] and summary["unassigned_slots"] == [3]
    assert not summary["inputs"][2]["movable"]
    request = move(caf)
    plan = bindings.preview(request)
    output, receipt = bindings.export(request | {"plan_sha256": plan["plan_sha256"]})
    edited = CafArchive(output)
    expected = caf.xml.replace(b">UI IN1<", b">UI IN3<").replace(
        b"<unsignedByte>1</unsignedByte>", b"<unsignedByte>3</unsignedByte>"
    )
    assert edited.xml == expected
    assert list(edited.objects) == list(caf.objects)
    assert edited.properties("8-1/3_20") == caf.properties("8-1/3_20")
    assert edited.properties("8-1/0_30") == caf.properties("8-1/0_30")
    assert receipt["output_sha256"] == hashlib.sha256(output).hexdigest()
    assert receipt["native_validation"] == "pending" and receipt["native_download"] is False
    for key in [
        "filename",
        "date_time",
        "compress_type",
        "external_attr",
        "comment",
        "extra",
        "create_system",
    ]:
        assert getattr(edited.info, key) == getattr(caf.info, key)
    assert edited.comment == caf.comment


def test_binary_on_ui_moves_without_changing_external_identity_or_alarm_configuration():
    caf = fixture()
    request = move(caf, "8-1/3_20", 2, 3)
    bindings = CafHardwareBindings(caf)
    plan = bindings.preview(request)
    output, _ = bindings.export(request | {"plan_sha256": plan["plan_sha256"]})
    assert CafArchive(output).xml == caf.xml.replace(b">UI IN2<", b">UI IN3<").replace(
        b"<unsignedByte>2</unsignedByte>", b"<unsignedByte>3</unsignedByte>"
    )


def test_noop_is_byte_exact_and_plans_require_both_source_and_review_hash():
    caf = fixture()
    bindings = CafHardwareBindings(caf)
    request = move(caf, destination=1)
    plan = bindings.preview(request)
    assert not plan["changes"]
    assert bindings.export(request | {"plan_sha256": plan["plan_sha256"]})[0] == caf.original
    with pytest.raises(ValueError, match="source hash"):
        bindings.preview(request | {"source_sha256": "0" * 64})
    with pytest.raises(ValueError, match="plan changed"):
        bindings.export(move(caf) | {"plan_sha256": plan["plan_sha256"]})
    with pytest.raises(ValueError, match="Original terminal"):
        bindings.preview(request | {"old_slot": 2})


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_terminal_numbers_require_explicit_integers(value):
    with pytest.raises(ValidationError):
        HardwareMoveRequest.model_validate(move(fixture()) | {"old_slot": value})


@pytest.mark.parametrize("replacement", [b"<![CDATA[UI IN1]]>", b"UI<!-- note --> IN1"])
def test_opaque_leaf_serialization_is_refused_before_reviewing_an_edit(replacement):
    caf = fixture(fixture_xml().replace(b">UI IN1<", b">" + replacement + b"<"))
    bindings = CafHardwareBindings(caf)
    assert bindings.summary()["supported"]
    with pytest.raises(ValueError, match="opaque leaf markup"):
        bindings.preview(move(caf))
    # An unchanged request still preserves an otherwise readable archive exactly.
    request = move(caf, destination=1)
    plan = bindings.preview(request)
    assert bindings.export(request | {"plan_sha256": plan["plan_sha256"]})[0] == caf.original


@pytest.mark.parametrize(
    "change",
    [
        {"ref": "8-1/0_30", "old_slot": 4, "destination_slot": 3},
        {"ref": "8-1/0_10", "old_slot": 1, "destination_slot": 2},
        {"ref": "8-1/0_10", "old_slot": 1, "destination_slot": 4},
    ],
)
def test_internal_dpt_occupied_and_nonphysical_destination_are_rejected(change):
    caf = fixture()
    with pytest.raises(ValueError):
        CafHardwareBindings(caf).preview({"source_sha256": caf.hash, **change})


@pytest.mark.parametrize(
    "before,after",
    [
        (b"MS-VMA1630-0", b"MS-VMA1630-1"),
        (b"<unsignedByte>2</unsignedByte>", b"<unsignedByte>1</unsignedByte>"),
        (b">UI IN2<", b">UI IN3<"),
        (b'objectid="20"', b'objectid="21"'),
        (b'<BACoid id="3">20', b'<BACoid id="0">20'),
        (b"<string>8-1/3_20</string>", b"<string>another/3_20</string>"),
        (b"UI IN2</string>", b"UI IN2</string>"),
    ],
)
def test_unknown_model_conflicting_labels_identity_and_host_metadata_block(before, after):
    xml = fixture_xml().replace(before, after)
    if before == after:
        xml = xml.replace(
            b"</object>",
            b'<property id="3645"><data><unsignedByte>4</unsignedByte></data></property></object>',
            1,
        )
        # Root SA metadata alone is not a point binding; add it to a physical input too.
        xml = xml.replace(
            b'<property id="931">',
            b'<property id="3645"><data><unsignedByte>4</unsignedByte></data></property><property id="931">',
        )
    summary = CafHardwareBindings(fixture(xml)).summary()
    assert not summary["supported"] and summary["errors"]


@pytest.mark.parametrize("class_id", ["598", "0598", "910", "0910", "243", "671", "673"])
def test_sa_module_and_new_hardware_schema_never_enter_local_edit_profile(class_id):
    caf = fixture(
        extra=f'<object classid="{class_id}" classVersion="1.0" ref="8-1/307_1.598_1" objectid="1"/>'
    )
    assert not CafHardwareBindings(caf).summary()["supported"]


@pytest.mark.parametrize("pid", ["3645", "03645", "2577", "02577"])
def test_padded_host_binding_property_identifiers_cannot_bypass_local_profile(pid):
    xml = fixture_xml().replace(
        b'<property id="931">',
        f'<property id="{pid}"><data><unsignedByte>4</unsignedByte></data></property><property id="931">'.encode(),
    )
    summary = CafHardwareBindings(fixture(xml)).summary()
    assert not summary["supported"]
    assert "SA/device-host bindings" in summary["errors"][0]


@pytest.mark.parametrize(
    "property_xml",
    [
        '<property id="519"><data><unsignedByte>3</unsignedByte></data></property>',
        '<property id="0519"><data><unsignedByte>3</unsignedByte></data></property>',
        '<property id="31"><data><string>UI IN3</string></data></property>',
        '<property id="0031"><data><string>UI IN3</string></data></property>',
    ],
)
def test_unknown_physical_record_cannot_hide_destination_occupancy(property_xml):
    caf = fixture(
        extra=f'<object classid="999" classVersion="1.0" ref="8-1/999_88" objectid="88">{property_xml}</object>'
    )
    summary = CafHardwareBindings(caf).summary()
    assert not summary["supported"] and "conceal terminal occupancy" in summary["errors"][0]
    caf = fixture(
        fixture_xml().replace(
            b'classid="242" classVersion="1.0"', b'classid="242" classVersion="2.0"'
        )
    )
    assert not CafHardwareBindings(caf).summary()["supported"]


def test_http_preview_and_export_require_session_and_return_real_caf_without_field_interface(
    tmp_path,
):
    caf = fixture()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post(
            "/api/caf", files={"file": ("authored.caf", caf.original)}, headers=headers
        ).json()
        endpoint = f"/api/caf/{opened['sha256']}/hardware"
        assert client.get(endpoint).json()["supported"]
        assert client.post(endpoint + "/preview", json=move(caf)).status_code == 403
        response = client.post(endpoint + "/preview", json=move(caf), headers=headers)
        assert response.status_code == 200, response.text
        plan = response.json()
        refused = client.post(
            endpoint + "/export",
            json=move(caf) | {"plan_sha256": "0" * 64},
            headers=headers,
        )
        assert refused.status_code == 422
        assert "plan changed" in refused.json()["detail"]
        exported = client.post(
            endpoint + "/export",
            json=move(caf) | {"plan_sha256": plan["plan_sha256"]},
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        assert CafHardwareBindings(CafArchive(exported.content)).summary()["inputs"][0]["slot"] == 3
        assert client.get("/api/session").json()["field_network_open"] is False


def test_optional_private_corpus_edits_in_memory_only():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR for authorized offline CAF compatibility.")
    paths = sorted(Path(directory).rglob("*.caf"))
    assert paths
    for path in paths:
        original = path.read_bytes()
        caf = CafArchive(original)
        bindings = CafHardwareBindings(caf)
        summary = bindings.summary()
        assert summary["supported"], summary["errors"]
        for source in [p for p in summary["inputs"] if p["movable"]]:
            request = move(caf, source["ref"], source["slot"], summary["unassigned_slots"][0])
            plan = bindings.preview(request)
            output, _ = bindings.export(request | {"plan_sha256": plan["plan_sha256"]})
            assert CafHardwareBindings(CafArchive(output)).summary()["supported"]
        assert path.read_bytes() == original
