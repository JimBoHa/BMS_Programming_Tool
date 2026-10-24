"""Authored CAFs exercise identity edits independently of controller models."""

import hashlib
import io
import zipfile

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_instance import CafInstanceChange, CafInstanceEditor
from fastapi.testclient import TestClient
from pydantic import ValidationError

from .test_caf_hardware import fixture, fixture_xml


def proposal(caf, **updates):
    return {"source_sha256": caf.hash, "expected_instance": 99, "new_instance": 5336, **updates}


def exported(caf, **updates):
    editor = CafInstanceEditor(caf)
    request = proposal(caf, **updates)
    plan = editor.preview(request)
    return editor.export({**request, "plan_sha256": plan["plan_sha256"]})


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCG2611-0", "Authored future controller"])
def test_instance_and_root_id_change_together_without_changing_application(model):
    caf = fixture(model=model)
    original = caf.original
    output, receipt = exported(caf)
    edited = CafArchive(output)
    expected = caf.xml.replace(b'objectid="99"', b'objectid="5336"').replace(
        b'<BACoid id="8">99</BACoid>', b'<BACoid id="8">5336</BACoid>'
    )
    assert edited.xml == expected
    assert CafInstanceEditor(edited).summary()["instance"] == 5336
    assert CafInstanceEditor(edited).ref == "8-1"
    assert list(caf.objects) == list(edited.objects)
    for ref in caf.objects:
        if ref != "8-1":
            assert caf.properties(ref) == edited.properties(ref)
    assert len(receipt["changes"]) == 2 and receipt["controller_write"] is False
    assert receipt["transfer_required"]
    assert receipt["output_sha256"] == hashlib.sha256(output).hexdigest()
    assert caf.original == original and caf.xml != edited.xml
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


def test_no_change_returns_original_archive_bytes_exactly():
    caf = fixture()
    output, receipt = exported(caf, new_instance=99)
    assert output == caf.original
    assert receipt["changes"] == [] and receipt["output_sha256"] == caf.hash
    assert receipt["transfer_required"] is False


def test_expansion_device_and_peer_reference_data_remain_exact():
    expansion = """<object classid="196" classVersion="9.9" ref="8-1/8_99" objectid="99">
    <property id="75"><data><BACoid id="8">99</BACoid></data></property>
    <property id="90000"><data><string>Peer controller device,99; MAC 99</string></data></property>
    </object>"""
    caf = fixture(extra=expansion)
    output, _ = exported(caf)
    edited = CafArchive(output)
    assert edited.properties("8-1/8_99") == caf.properties("8-1/8_99")
    assert b'ref="8-1/8_99" objectid="99"' in edited.xml


def test_only_real_attribute_is_edited_not_quoted_or_comment_lookalikes():
    xml = (
        fixture_xml()
        .replace(
            b'ref="8-1" objectid="99"',
            b"""ref="8-1" note=" objectid='99' &gt; do not edit " objectid = '99' """,
        )
        .replace(b"<!-- Preserve", b'<!-- objectid="99" <BACoid id="8">99</BACoid> Preserve')
    )
    caf = fixture(xml=xml)
    output, _ = exported(caf)
    expected = xml.replace(b"objectid = '99'", b"objectid = '5336'").replace(
        b'<property id="75"><data><BACoid id="8">99</BACoid>',
        b'<property id="75"><data><BACoid id="8">5336</BACoid>',
    )
    assert CafArchive(output).xml == expected


@pytest.mark.parametrize("change", [{"expected_instance": 98}, {"source_sha256": "0" * 64}])
def test_source_and_old_instance_guards(change):
    caf = fixture()
    with pytest.raises(ValueError, match="source or current"):
        CafInstanceEditor(caf).preview(proposal(caf, **change))


def test_proposal_change_requires_a_new_review():
    caf = fixture()
    editor = CafInstanceEditor(caf)
    request = proposal(caf)
    plan = editor.preview(request)
    with pytest.raises(ValueError, match="plan changed"):
        editor.export({**request, "new_instance": 5337, "plan_sha256": plan["plan_sha256"]})


@pytest.mark.parametrize("bad", [True, False, "5336", 5336.0, -1, 4194303])
def test_instance_values_are_strict_and_bounded(bad):
    with pytest.raises(ValidationError):
        CafInstanceChange(**proposal(fixture(), new_instance=bad))


@pytest.mark.parametrize(
    "alter",
    [
        lambda s: s.replace(b'objectid="99"', b'objectid="100"'),
        lambda s: s.replace(b'<BACoid id="8">99</BACoid>', b'<BACoid id="8">4194303</BACoid>'),
        lambda s: s.replace(b'<BACoid id="8">99</BACoid>', b'<BACoid id="8">099</BACoid>'),
        lambda s: s.replace(b'<BACoid id="8">99</BACoid>', b'<BACoid id="0">99</BACoid>'),
    ],
)
def test_inconsistent_or_unsupported_root_identity_is_refused(alter):
    with pytest.raises(ValueError):
        CafInstanceEditor(fixture(xml=alter(fixture_xml())))


def test_another_root_controller_is_ambiguous():
    extra = """<object classid="999" ref="8-2" objectid="100">
    <property id="75"><data><BACoid id="8">100</BACoid></data></property></object>"""
    with pytest.raises(ValueError, match="unambiguous"):
        CafInstanceEditor(fixture(extra=extra))


@pytest.mark.parametrize(
    "alter",
    [
        lambda s: s.replace(b'objectid="99"', b'objectid="&#57;&#57;"'),
        lambda s: s.replace(
            b'<BACoid id="8">99</BACoid>', b'<BACoid id="8"><![CDATA[99]]></BACoid>'
        ),
    ],
)
def test_opaque_source_serializations_are_not_rewritten(alter):
    caf = fixture(xml=alter(fixture_xml()))
    with pytest.raises(ValueError):
        CafInstanceEditor(caf).preview(proposal(caf))


def test_utf16_archive_can_be_inspected_but_not_spliced_as_utf8():
    xml = fixture_xml().decode().replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("authored.xml", xml)
    caf = CafArchive(stream.getvalue())
    assert CafInstanceEditor(caf).summary()["instance"] == 99
    with pytest.raises(ValueError, match="UTF-8"):
        CafInstanceEditor(caf).preview(proposal(caf))


def test_real_api_exports_a_guarded_caf_copy_without_a_field_connection(tmp_path):
    caf = fixture()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post(
            "/api/caf", files={"file": ("authored.caf", caf.original)}, headers=headers
        )
        assert opened.status_code == 200
        base = f"/api/caf/{opened.json()['sha256']}/device-instance"
        identity = client.get(base).json()
        assert identity["instance"] == 99 and identity["offline_only"]
        assert client.post(base + "/preview", json=proposal(caf)).status_code == 403
        response = client.post(base + "/preview", json=proposal(caf), headers=headers)
        assert response.status_code == 200, response.text
        plan = response.json()
        body = {**proposal(caf), "plan_sha256": plan["plan_sha256"]}
        assert (
            client.post(
                base + "/export", json={**body, "new_instance": 5337}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/export", json={**body, "apply_to_controller": True}, headers=headers
            ).status_code
            == 422
        )
        result = client.post(base + "/export", json=body, headers=headers)
        assert result.status_code == 200, result.text
        assert result.headers["content-disposition"].endswith('controller-instance-5336.caf"')
        assert result.headers["x-caf-source-sha256"] == caf.hash
        assert result.headers["x-caf-output-sha256"] == hashlib.sha256(result.content).hexdigest()
        assert CafInstanceEditor(CafArchive(result.content)).current == 5336
        assert client.get(base).json() == identity
        assert client.get("/api/session").json()["field_network_open"] is False
