"""Authored adversarial CAFs verify guarded edits without distributing building data."""

import copy
import io
import struct
import zipfile

import pytest
from bms_tool import caf as module
from bms_tool.app import create_app
from bms_tool.caf import NS, CafArchive, Q
from fastapi.testclient import TestClient

from tests.test_formats_caf import make_caf


def edit(pid="3113", old="72.000000", value="73", ref="8-1"):
    return {"ref": ref, "property": pid, "old": old, "value": value}


def original_xml():
    return CafArchive(make_caf()).xml


@pytest.mark.parametrize("kind", ["element", "attribute", "namespace_uri", "namespace_prefix"])
def test_expanded_xml_names_and_namespace_declarations_have_explicit_resource_bounds(kind):
    long_name = "x" * 4097
    if kind == "element":
        body, declarations = f"<{long_name}/>", ""
    elif kind == "attribute":
        body, declarations = f'<extra {long_name}="keep"/>', ""
    elif kind == "namespace_uri":
        body, declarations = "<extra/>", f' xmlns:unused="urn:{long_name}"'
    else:
        body, declarations = "<extra/>", f' xmlns:{long_name}="urn:unused"'
    raw = make_caf(f'<objects xmlns="{NS}"{declarations}>{body}</objects>'.encode())
    with pytest.raises(ValueError, match="4096-character resource profile"):
        CafArchive(raw)


def test_corrupted_deflate_is_a_value_error_and_api_rejects_it_without_opening_transports(tmp_path):
    broken = bytearray(make_caf())
    with zipfile.ZipFile(io.BytesIO(broken)) as archive:
        info = archive.infolist()[0]
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    broken[offset : offset + 8] = b"\xff" * 8
    with pytest.raises(ValueError, match="valid ZIP/XML"):
        CafArchive(bytes(broken))
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/caf", files={"file": ("corrupt.caf", bytes(broken))}, headers=headers
        )
        assert response.status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False


def test_unknown_zip_compression_is_an_explicit_value_error():
    broken = bytearray(make_caf())
    central = broken.index(b"PK\x01\x02")
    struct.pack_into("<H", broken, 8, 99)
    struct.pack_into("<H", broken, central + 10, 99)
    with pytest.raises(ValueError, match="valid ZIP/XML"):
        CafArchive(bytes(broken))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize(
    "declaration", ["<!DOCTYPE objects>", '<!DOCTYPE objects [<!ENTITY value "unsafe">]>']
)
def test_dtd_rejection_covers_unicode_encodings_even_without_an_entity_use(encoding, declaration):
    raw = (
        f'<?xml version="1.0" encoding="{encoding}"?>{declaration}<objects xmlns="{NS}"/>'
    ).encode(encoding)
    with pytest.raises(ValueError, match="entities and DTDs"):
        CafArchive(make_caf(raw))


def test_xml_limits_abort_parser_allocation_before_deep_or_excessive_trees(monkeypatch):
    deep = (
        f'<objects xmlns="{NS}">'
        + "<opaque>" * module.MAX_DEPTH
        + "</opaque>" * module.MAX_DEPTH
        + "</objects>"
    )
    with pytest.raises(ValueError, match="depth/element"):
        CafArchive(make_caf(deep.encode()))
    monkeypatch.setattr(module, "MAX_ELEMENTS", 30)
    large = f'<objects xmlns="{NS}">' + "<opaque/>" * 30 + "</objects>"
    with pytest.raises(ValueError, match="depth/element"):
        CafArchive(make_caf(large.encode()))


@pytest.mark.parametrize("kind", ["property", "simulationProperty"])
def test_duplicate_native_property_ids_are_rejected_per_record_kind_including_numeric_aliases(kind):
    raw = original_xml()
    extra = f'<{kind} id="3113"><data><float>1</float></data></{kind}><{kind} id="03113"><data><float>2</float></data></{kind}>'
    raw = raw.replace(b"</object>", extra.encode() + b"</object>")
    with pytest.raises(ValueError, match="duplicate property identifiers"):
        CafArchive(make_caf(raw))


@pytest.mark.parametrize("replacement", [b"", b"-1", b"nonnumeric", b"4294967296"])
def test_invalid_native_property_identifiers_cannot_enter_a_change_baseline(replacement):
    raw = original_xml().replace(b'id="3113"', b'id="' + replacement + b'"')
    with pytest.raises(ValueError, match="invalid native identifier"):
        CafArchive(make_caf(raw))


def test_empty_native_object_reference_is_rejected():
    with pytest.raises(ValueError, match="missing object references"):
        CafArchive(make_caf(original_xml().replace(b'ref="8-1"', b'ref=""')))


@pytest.mark.parametrize(
    "descriptor",
    [
        b'<property id="3113"><data><float>72.000000</float></data><data><float>99</float></data></property>',
        b'<property id="3113"><data><float>72.000000</float></data><opaque>keep</opaque></property>',
        b'<property id="3113"><data>unmodeled<float>72.000000</float></data></property>',
        b'<property id="3113"><data><float>72.000000</float>unmodeled</data></property>',
        b'<property id="3113" nativeOption="opaque"><data><float>72.000000</float></data></property>',
        b'<property id="3113"><data nativeOption="opaque"><float>72.000000</float></data></property>',
    ],
)
def test_ambiguous_or_unknown_scalar_wrappers_stay_visible_as_opaque_and_cannot_be_patched(
    descriptor,
):
    old = b'<property id="3113"><data><float>72.000000</float></data></property>'
    source = make_caf(original_xml().replace(old, descriptor))
    archive = CafArchive(source)
    prop = next(p for p in archive.properties("8-1") if p["id"] == "3113")
    assert prop["scalar"] is None and prop["xml"] and prop["editable"] is False
    assert archive.patch([]) == (source, [])
    with pytest.raises(ValueError, match="not an editable scalar"):
        archive.patch([edit()])


def test_actual_xml_tokens_prevent_comment_and_cdata_lookalikes_from_becoming_edit_targets():
    fake = b'<object ref="8-1"><property id="3113"><data><float>72.000000</float></data></property></object>'
    actual = original_xml().replace(b'ref="8-1"', b"ref='8-1'").replace(b'id="3113"', b"id='3113'")
    raw = actual.replace(
        b"</objects>", b"<jobInfo><![CDATA[" + fake + b"]]><!--" + fake + b"--></jobInfo></objects>"
    )
    archive = CafArchive(make_caf(raw))
    edited, report = archive.patch([edit(value="73.125")])
    # Only the actual parsed property's leaf changes. Both deceptive copies stay exact.
    expected = raw.replace(b"<float>72.000000</float>", b"<float>73.125</float>", 1)
    assert CafArchive(edited).xml == expected and report[0]["value"] == "73.125"
    assert archive.xml == raw


def test_native_namespace_prefixes_alternate_quotes_and_quoted_angle_brackets_are_preserved():
    raw = (
        f'<j:objects xmlns:j="{NS}"><j:object ref="8&gt;1" classid="194" objectid="1" classVersion="1.0">'
        "<j:property id='28'><j:data><j:string /></j:data></j:property>"
        "<j:property id='3113'><j:data><j:float>72.000000</j:float></j:data></j:property>"
        "</j:object></j:objects>"
    ).encode()
    archive = CafArchive(make_caf(raw))
    edited, _ = archive.patch(
        [edit(ref="8>1"), edit(pid="28", old="", value="Keep > and <", ref="8>1")]
    )
    expected = raw.replace(b"<j:float>72.000000</j:float>", b"<j:float>73</j:float>").replace(
        b"<j:string />", b"<j:string >Keep &gt; and &lt;</j:string>"
    )
    assert CafArchive(edited).xml == expected


@pytest.mark.parametrize("markup", [b"<!--opaque-->", b"<![CDATA[72.000000]]>"])
def test_opaque_markup_inside_leaf_values_is_not_silently_deleted(markup):
    content = b"72.000000" + markup if markup.startswith(b"<!--") else markup
    raw = original_xml().replace(b"<float>72.000000</float>", b"<float>" + content + b"</float>")
    archive = CafArchive(make_caf(raw))
    with pytest.raises(ValueError, match="opaque leaf markup"):
        archive.patch([edit()])
    assert archive.xml == raw


@pytest.mark.parametrize("encoding", ["utf-16", "iso-8859-1"])
def test_non_utf8_native_xml_is_inspectable_and_byte_exact_but_edits_are_refused(encoding):
    raw = (
        '<?xml version="1.0" encoding="'
        + encoding
        + '"?>'
        + original_xml().decode().replace("Example", "Caf\N{LATIN SMALL LETTER E WITH ACUTE}")
    ).encode(encoding)
    source = make_caf(raw)
    archive = CafArchive(source)
    assert archive.inventory()[0]["name"] == "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"
    assert archive.summary()["capabilities"]["scalar_patch"] is False
    assert all(not prop["editable"] for prop in archive.properties("8-1"))
    assert archive.patch([]) == (source, [])
    with pytest.raises(ValueError, match="UTF-8/ASCII"):
        archive.patch([edit()])


def test_ascii_and_carriage_return_string_edits_have_exact_unicode_readback():
    raw = b'<?xml version="1.0" encoding="US-ASCII"?>' + original_xml()
    archive = CafArchive(make_caf(raw))
    value = "Caf\N{LATIN SMALL LETTER E WITH ACUTE}\r\n\tvalue"
    edited, report = archive.patch([edit(pid="28", old="", value=value)])
    actual = CafArchive(edited)
    assert b"&#233;&#13;\n\tvalue" in actual.xml
    prop = next(p for p in actual.properties("8-1") if p["id"] == "28")
    assert prop["scalar"]["text"] == report[0]["value"] == value


def test_utf8_bom_multibyte_prefix_and_xml_character_references_use_real_byte_positions():
    raw = b"\xef\xbb\xbf" + original_xml().replace(
        b"<object ",
        "<jobInfo>\N{LATIN SMALL LETTER E WITH ACUTE}\N{CJK UNIFIED IDEOGRAPH-8A9E}</jobInfo><object ".encode(),
        1,
    ).replace(b"Example", "A&#13;B&#x80;\N{LATIN SMALL LETTER E WITH ACUTE}".encode())
    archive = CafArchive(make_caf(raw))
    old = archive.inventory()[0]["name"]
    assert old == "A\rB\x80\N{LATIN SMALL LETTER E WITH ACUTE}"
    edited, _ = archive.patch([edit(pid="2390", old=old, value="New name"), edit(value="73.25")])
    expected = raw.replace(
        "A&#13;B&#x80;\N{LATIN SMALL LETTER E WITH ACUTE}".encode(), b"New name"
    ).replace(b"72.000000", b"73.25")
    assert CafArchive(edited).xml == expected


@pytest.mark.parametrize(
    "value", ["bad\x00value", "bad\ud800value", "bad\ufffevalue", "bad\uffffvalue"]
)
def test_invalid_xml_characters_cannot_become_native_strings(value):
    with pytest.raises(ValueError, match="Invalid CAF string"):
        CafArchive(make_caf()).patch([edit(pid="28", old="", value=value)])


def test_batch_splices_and_repeated_edits_preserve_original_archive_metadata_and_bytes():
    source = make_caf()
    archive = CafArchive(source)
    original_info = copy.copy(archive.info)
    changes = [
        edit(pid="28", old="", value="Longer description"),
        edit(value="75.5"),
        edit(pid="2390", old="Example", value="X"),
    ]
    first, report = archive.patch(changes)
    second, again = archive.patch(changes)
    expected = (
        archive.xml.replace(b"<string />", b"<string >Longer description</string>")
        .replace(b"72.000000", b"75.5")
        .replace(b"Example", b"X")
    )
    assert CafArchive(first).xml == expected and first == second and report == again
    assert archive.info.CRC == original_info.CRC
    assert archive.info.file_size == original_info.file_size
    assert archive.info.compress_size == original_info.compress_size
    assert archive.info.header_offset == original_info.header_offset
    assert archive.original == source and archive.patch([]) == (source, [])
    assert archive.patch([edit(value="72.000000")]) == (source, [])


@pytest.mark.parametrize(
    "changes", [{}, "not a list", [None], [edit(ref=[])], [edit(old=72)], [edit(value={})]]
)
def test_guarded_edit_request_shape_failures_are_value_errors(changes):
    with pytest.raises(ValueError):
        CafArchive(make_caf()).patch(changes)


def test_simulation_metadata_does_not_override_native_model_summary_or_normal_property_edits():
    raw = original_xml().replace(
        b"</object>",
        b'<simulationProperty id="12"><data><string>simulation-only</string></data></simulationProperty></object>',
    )
    archive = CafArchive(make_caf(raw))
    assert archive.summary()["release_mode"] == "10.2"
    edited, _ = archive.patch([edit()])
    assert (
        CafArchive(edited).root.find("./" + Q + "object/" + Q + "simulationProperty")[0][0].text
        == "simulation-only"
    )
