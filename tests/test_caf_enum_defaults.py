"""Literal CAF Enum leaves: class/type scope, other-byte preservation and HTTP evidence."""

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.caf import NS, CafArchive, Q
from fastapi.testclient import TestClient

REF = "controller/enum"


def enum_caf(
    *,
    cid="528",
    kind="enum",
    attributes=" set='state&amp;set'",
    text="1",
    pid="3113",
    simulation=False,
):
    prop = "simulationProperty" if simulation else "property"
    before = (
        f'<?xml version="1.0" encoding="UTF-8"?><j:objects xmlns:j="{NS}">'
        "<!-- <j:enum set='state&amp;set'>1</j:enum> is only a comment. -->"
        "<j:jobInfo><j:string>Keep opaque job metadata</j:string></j:jobInfo>"
        "<j:object classid='194' ref='controller' objectid='5136' classVersion='1.0'>"
        "<j:property id='75'><j:data><j:BACoid id='8'>5136</j:BACoid></j:data></j:property>"
        "<j:property id='2390'><j:data><j:string>Authored CAF</j:string></j:data></j:property>"
        "<j:property id='70'><j:data><j:string>UNLISTED-MODEL</j:string></j:data></j:property></j:object>"
        f"<j:object classid='{cid}' ref='{REF}' objectid='1' classVersion='1.0'>"
        "<j:property id='2390'><j:data><j:string>ENUM_CMD</j:string></j:data></j:property>"
        f"<j:{prop} id='{pid}'><j:data><j:{kind}{attributes}>"
    ).encode()
    after = (
        f"</j:{kind}></j:data></j:{prop}>"
        "<j:property id='65000'><j:data><j:struct><j:opaque value='unchanged'>42</j:opaque></j:struct></j:data></j:property></j:object>"
        "<j:object classid='526' ref='controller/real' objectid='2' classVersion='1.0'>"
        "<j:property id='2390'><j:data><j:string>FLOAT_CMD</j:string></j:data></j:property>"
        "<j:property id='3113'><j:data><j:float>23.5</j:float></j:data></j:property>"
        "<j:property id='28'><j:data><j:string>blue</j:string></j:data></j:property></j:object></j:objects>"
    ).encode()
    xml = before + text.encode() + after
    info = zipfile.ZipInfo("authored.caf.xml", (2026, 11, 2, 10, 4, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.extra = b"\xca\xfe\x04\x00KEEP"
    info.comment = b"original entry comment"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.comment = b"original CAF comment"
        archive.writestr(info, xml)
    return output.getvalue(), before, after


def change(value, old="1"):
    return {"ref": REF, "property": "3113", "old": old, "value": value}


@pytest.mark.parametrize("cid", ["528", "529"])
@pytest.mark.parametrize("attributes", ["", " set='state&amp;set'"])
@pytest.mark.parametrize("value", [0, 256, 4294967295])
def test_typed_enum_copy_preserves_exact_other_xml_and_container_metadata(cid, attributes, value):
    source, before, after = enum_caf(cid=cid, attributes=attributes)
    caf = CafArchive(source)
    prop = next(p for p in caf.properties(REF) if p["id"] == "3113")
    meta = prop["enum_code_copy"]
    assert prop["editable"] and meta["profile"] == "caf-enum-default-code-copy/1"
    assert (
        meta["source_sha256"] == caf.hash and meta["record_ref"] == REF and meta["class_id"] == cid
    )
    assert (
        meta["original_code"] == 1
        and not meta["enum_semantics_verified"]
        and not meta["controller_write"]
    )
    output, report = caf.patch([change(value)])
    actual = CafArchive(output)
    assert actual.xml == before + str(value).encode() + after
    assert caf.original == source and caf.xml == before + b"1" + after
    assert actual.scalar(next(p for p in actual.objects[REF] if p.get("id") == "3113"))[
        "attributes"
    ] == ({"set": "state&set"} if attributes else {})
    assert report[0]["type"] == "enum" and report[0]["enum_semantics_verified"] is False
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        info = archive.infolist()[0]
        assert archive.comment == caf.comment and info.filename == caf.info.filename
        assert info.extra == caf.info.extra and info.comment == caf.info.comment
        assert info.date_time == caf.info.date_time and info.compress_type == caf.info.compress_type


@pytest.mark.parametrize("value", [1, "1", " 0001 "])
def test_equivalent_enum_codes_return_the_entire_original_archive(value):
    source, _, _ = enum_caf()
    assert CafArchive(source).patch([change(value)]) == (source, [])


@pytest.mark.parametrize(
    "value", [True, False, 1.0, "1.0", -1, "-1", "1e2", "0x10", "", "4294967296", "1" * 129]
)
def test_non_uint32_proposals_never_rewrite_the_source(value):
    source, _, _ = enum_caf()
    caf = CafArchive(source)
    with pytest.raises(ValueError, match="Enum codes"):
        caf.patch([change(value)])
    assert caf.original == source


@pytest.mark.parametrize(
    "options",
    [
        {"cid": "530"},
        {"kind": "unsignedLong", "attributes": ""},
        {"attributes": " set='states' flags='unknown'"},
        {"pid": "931"},
        {"simulation": True},
        {"text": "-1"},
        {"text": "01"},
        {"text": "4294967296"},
        {"text": "<![CDATA[1]]>"},
    ],
)
def test_unsupported_enum_encodings_keep_their_previous_editability(options):
    source, _, _ = enum_caf(**options)
    caf = CafArchive(source)
    prop = next(p for p in caf.properties(REF) if p["id"] == options.get("pid", "3113"))
    assert "enum_code_copy" not in prop
    if options.get("kind") == "unsignedLong":
        # This numeric scalar was already supported by the general CAF adapter.
        # It must not acquire an Enum profile or lose its previous editability.
        assert prop["editable"]
        output, report = caf.patch([change(2)])
        assert report[0]["type"] == "unsignedLong" and "enum_semantics_verified" not in report[0]
        assert (
            CafArchive(output).scalar(
                next(p for p in CafArchive(output).objects[REF] if p.get("id") == "3113")
            )["type"]
            == "unsignedLong"
        )
        return
    assert not prop["editable"]
    with pytest.raises(ValueError):
        caf.patch([change(2, options.get("text", "1")) | {"property": options.get("pid", "3113")}])
    assert caf.original == source


def test_owner_class_is_required_to_add_enum_editability():
    source, _, _ = enum_caf()
    caf = CafArchive(source)
    prop = next(p for p in caf.objects[REF] if p.get("id") == "3113")
    assert not caf._editable(prop)
    assert caf._editable(prop, class_id="528")
    assert not caf._editable(prop, class_id="530")


def test_character_reference_code_changes_only_the_actual_parsed_leaf():
    source, before, after = enum_caf(text="&#49;")
    caf = CafArchive(source)
    assert caf.patch([change(1)])[0] == source
    output, _ = caf.patch([change(2)])
    assert CafArchive(output).xml == before + b"2" + after


def test_utf16_enum_xml_remains_readable_without_granting_a_text_splice():
    from .test_formats_caf import make_caf

    source, _, _ = enum_caf()
    xml = CafArchive(source).xml.decode().replace('encoding="UTF-8"', 'encoding="UTF-16"')
    original = make_caf(xml.encode("utf-16"))
    caf = CafArchive(original)
    prop = next(p for p in caf.properties(REF) if p["id"] == "3113")
    assert prop["scalar"]["text"] == "1" and not prop["editable"] and "enum_code_copy" not in prop
    assert caf.patch([])[0] == original
    with pytest.raises(ValueError, match="UTF-8/ASCII"):
        caf.patch([change(2)])


def test_mixed_enum_real_and_unicode_string_changes_share_one_exact_copy():
    source, before, after = enum_caf()
    caf = CafArchive(source)
    changes = [
        change(" 000256 "),
        {"ref": "controller/real", "property": "3113", "old": "23.5", "value": "24.25"},
        {"ref": "controller/real", "property": "28", "old": "blue", "value": "é🙂"},
    ]
    output, report = caf.patch(changes)
    expected = (
        before + b"256" + after.replace(b">23.5<", b">24.25<").replace(b">blue<", ">é🙂<".encode())
    )
    assert CafArchive(output).xml == expected and len(report) == 3
    assert caf.original == source
    for bad in ([change(2, "other")], [change(2), change(3)]):
        with pytest.raises(ValueError):
            caf.patch(bad)


def test_real_http_exports_bind_source_request_and_artifact_without_field_access(
    tmp_path, monkeypatch
):
    source, before, after = enum_caf()
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local CAF editing attempted field access")

    for method in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, method, forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post("/api/caf", files={"file": ("enum.caf", source)}).status_code == 403
        upload = client.post("/api/caf", files={"file": ("enum.caf", source)}, headers=headers)
        assert upload.status_code == 200, upload.text
        identity = upload.json()["sha256"]
        props = client.get(f"/api/caf/{identity}/properties", params={"ref": REF}).json()
        assert (
            next(p for p in props if p["id"] == "3113")["enum_code_copy"]["source_sha256"]
            == identity
        )
        body = {
            "changes": [
                change("256"),
                {"ref": "controller/real", "property": "28", "old": "blue", "value": "é🙂"},
            ]
        }
        response = client.post(f"/api/caf/{identity}/export", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert (
            response.headers["X-CAF-Source-SHA256"]
            == identity
            == hashlib.sha256(source).hexdigest()
        )
        assert (
            response.headers["X-CAF-Output-SHA256"] == hashlib.sha256(response.content).hexdigest()
        )
        canonical = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        assert response.headers["X-CAF-Request-SHA256"] == hashlib.sha256(canonical).hexdigest()
        assert CafArchive(response.content).xml == before + b"256" + after.replace(
            b">blue<", ">é🙂<".encode()
        )
        assert not client.get("/api/session").json()["field_network_open"]


def test_authorized_local_enum_examples_keep_every_original_and_other_xml_byte():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR to authorized local, undistributed CAFs.")
    files = [p for p in Path(directory).rglob("*") if p.is_file() and p.suffix.lower() == ".caf"]
    assert files
    eligible = 0
    for path in files:
        source = path.read_bytes()
        caf = CafArchive(source)
        selected = []
        for ref, obj in caf.objects.items():
            for prop in caf.properties(ref):
                if "enum_code_copy" in prop:
                    eligible += 1
                    if not any(cid == obj.get("classid") for cid, _, _ in selected):
                        selected.append((obj.get("classid"), ref, prop))
        for _, ref, prop in selected:
            raw_prop = next(
                p for p in caf.objects[ref] if p.tag == Q + "property" and p.get("id") == "3113"
            )
            a, b, prefix, suffix = caf._scalar_span(raw_prop[0][0])
            value = (int(prop["scalar"]["text"]) + 1) % 4294967296
            output, _ = caf.patch(
                [
                    {
                        "ref": ref,
                        "property": "3113",
                        "old": prop["scalar"]["text"],
                        "value": str(value),
                    }
                ]
            )
            assert (
                CafArchive(output).xml
                == caf.xml[:a] + prefix + str(value).encode() + suffix + caf.xml[b:]
            )
        assert path.read_bytes() == source
    assert eligible > 0
