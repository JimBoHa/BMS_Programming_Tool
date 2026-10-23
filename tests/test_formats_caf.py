import io
import os
import zipfile
from pathlib import Path

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.formats import ConversionError, export_program, export_st, import_program
from bms_tool.iec_symbols import SymbolTable
from bms_tool.templates import all_templates


@pytest.mark.parametrize("format", ["json", "st", "plcopen", "graphml"])
@pytest.mark.parametrize("program", all_templates()[:3], ids=lambda p: p.id)
def test_interchange_keeps_graph_and_metadata(program, format):
    program.metadata["unknown_extension"] = {"nested": ["must survive", 42]}
    content, _, ext = export_program(program, format)
    restored = import_program(content, "project." + ext)
    assert restored.model_dump() == program.model_dump()


def test_outside_edits_are_not_ignored_in_embedded_graph_import():
    p = all_templates()[0]
    name = SymbolTable(p).role("zone").encode()
    raw = export_st(p)
    declaration = name + b" : REAL := 74.0;"
    assert raw.count(declaration) == 1
    text = raw.replace(declaration, name + b" : REAL := 99.0;")
    with pytest.raises(ConversionError, match="edited"):
        import_program(text, "program.st")


def test_unsupported_export_never_masquerades_as_vendor_binary():
    for format in ["caf", "gfb", "sab", "spyder", "whatever"]:
        with pytest.raises(ConversionError, match="no verified encoder"):
            export_program(all_templates()[0], format)


def make_caf(xml=None, name="sample.caf.xml"):
    if xml is None:
        xml = (
            f'<objects xmlns="{NS}"><object classid="194" ref="8-1" objectid="1" classVersion="1.0">'
            '<property id="12"><data><string>10.2</string></data></property>'
            '<property id="70"><data><string>MS-VMA1630-0</string></data></property>'
            '<property id="2390"><data><string>Example</string></data></property>'
            '<property id="28"><data><string /></data></property>'
            '<property id="3113"><data><float>72.000000</float></data></property>'
            '<property id="9999"><data><struct><structElement><unsignedShort>999</unsignedShort></structElement></struct></data></property>'
            "</object></objects>"
        ).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, xml)
        z.comment = b"keep me"
    return out.getvalue()


def test_caf_unchanged_export_is_byte_exact():
    data = make_caf()
    caf = CafArchive(data)
    assert caf.patch([]) == (data, [])
    assert caf.summary()["model"] == "MS-VMA1630-0"


def test_caf_patch_changes_only_target_text_and_preserves_unknown_data():
    caf = CafArchive(make_caf())
    output, report = caf.patch(
        [{"ref": "8-1", "property": "3113", "old": "72.000000", "value": "73.5"}]
    )
    edited = CafArchive(output)
    assert edited.xml == caf.xml.replace(b"<float>72.000000</float>", b"<float>73.5</float>")
    with zipfile.ZipFile(io.BytesIO(output)) as z:
        assert z.comment == b"keep me"
    assert report[0]["type"] == "float"


def test_empty_caf_string_can_be_edited_without_rewriting_other_properties():
    caf = CafArchive(make_caf())
    data, _ = caf.patch([{"ref": "8-1", "property": "28", "old": "", "value": "A < B & C"}])
    assert b"A &lt; B &amp; C" in CafArchive(data).xml


def test_caf_patch_checks_original_value_and_refuses_identity_changes():
    caf = CafArchive(make_caf())
    with pytest.raises(ValueError, match="conflict"):
        caf.patch([{"ref": "8-1", "property": "3113", "old": "99", "value": "75"}])
    with pytest.raises(ValueError, match="Identity"):
        caf.patch(
            [
                {
                    "ref": "8-1",
                    "property": "70",
                    "old": "MS-VMA1630-0",
                    "value": "FX-PCV1630-0",
                }
            ]
        )
    with pytest.raises(ValueError, match="finite"):
        caf.patch([{"ref": "8-1", "property": "3113", "old": "72.000000", "value": "NaN"}])


@pytest.mark.parametrize("value", [1e100, 1e-100])
def test_caf_float_patch_rejects_nonrepresentable_values(value):
    with pytest.raises(ValueError, match="32-bit"):
        CafArchive(make_caf()).patch(
            [{"ref": "8-1", "property": "3113", "old": "72.000000", "value": str(value)}]
        )


@pytest.mark.parametrize("value", [1e100, 1e-100])
def test_st_export_rejects_nonrepresentable_real_literals(value):
    p = all_templates()[0]
    p.nodes[0].params["default"] = value
    with pytest.raises(ConversionError, match="32-bit"):
        export_st(p)


def test_caf_parser_rejects_entities_and_ambiguous_archives():
    with pytest.raises(ValueError, match="entities"):
        CafArchive(make_caf(b'<!DOCTYPE x [<!ENTITY evil SYSTEM "file:///etc/passwd">]><objects/>'))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("a.xml", "<x/>")
        z.writestr("b.xml", "<x/>")
    with pytest.raises(ValueError, match="single-XML"):
        CafArchive(out.getvalue())


def test_caf_keeps_job_metadata_and_distinct_simulation_values():
    original = CafArchive(make_caf()).xml
    original = original.replace(
        b"</object>",
        b'<simulationProperty id="3113"><data><float>900</float></data></simulationProperty></object>',
    )
    original = original.replace(
        b"</objects>",
        b"<jobInfo><description>Keep this opaque metadata</description></jobInfo></objects>",
    )
    caf = CafArchive(make_caf(original))
    same_id = [p for p in caf.properties("8-1") if p["id"] == "3113"]
    assert len(same_id) == 2 and sum(p["editable"] for p in same_id) == 1
    edited, _ = caf.patch([{"ref": "8-1", "property": "3113", "old": "72.000000", "value": "73"}])
    assert CafArchive(edited).xml == original.replace(
        b"<float>72.000000</float>", b"<float>73</float>"
    )
    assert caf.summary()["preserved_root_metadata"] == ["jobInfo"]


def test_local_authorized_cafs_if_available():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip(
            "Set BMS_TEST_CAF_DIR to the authorized local sample directory. Building programs are not distributed."
        )
    files = list(Path(directory).rglob("*.caf"))
    assert files
    for p in files:
        data = p.read_bytes()
        caf = CafArchive(data)
        assert caf.patch([])[0] == data
        assert caf.summary()["objects"] > 0
        for obj in caf.inventory():
            scalar = next(
                (
                    p
                    for p in caf.properties(obj["ref"])
                    if p["id"] == "3113" and p["editable"] and p["scalar"]["type"] == "float"
                ),
                None,
            )
            if scalar:
                original = scalar["scalar"]["text"]
                new = str(float(original) + 0.125)
                patched, _ = caf.patch(
                    [
                        {
                            "ref": obj["ref"],
                            "property": "3113",
                            "old": original,
                            "value": new,
                        }
                    ]
                )
                assert CafArchive(patched).summary()["objects"] == caf.summary()["objects"]
                break
