"""Native-record change review is independent from hypothetical compiler semantics."""

import io
import os
import zipfile
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_compare import compare_cafs
from bms_tool.caf_graph import CafGraph
from fastapi.testclient import TestClient

from tests.test_caf_graph import change, make_graph
from tests.test_formats_caf import make_caf


def with_xml(source, old, new):
    return make_caf(CafArchive(source).xml.replace(old, new))


def test_exact_original_and_equivalent_archive_format_are_distinguished_without_edits():
    original = make_caf()
    same = compare_cafs(original, original)
    assert same["byte_identical"] and same["native_records_equal"]
    assert same["target_metadata_equal"] and same["total"] == 0
    assert same["can_apply"] is False
    archive = CafArchive(original)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as package:
        package.writestr("another-entry.xml", archive.xml)
    repacked = compare_cafs(original, output.getvalue())
    assert not repacked["byte_identical"] and repacked["xml_identical"]
    assert repacked["native_records_equal"] and repacked["total"] == 0
    assert archive.patch([])[0] == original


def test_namespace_prefix_attribute_order_and_indentation_do_not_invent_record_changes():
    original = make_caf()
    archive = CafArchive(original)
    from xml.etree import ElementTree

    tree = ElementTree.fromstring(archive.xml)
    for element in tree.iter():
        element.attrib = dict(reversed(list(element.attrib.items())))
    ElementTree.indent(tree)
    candidate = make_caf(ElementTree.tostring(tree))
    result = compare_cafs(original, candidate)
    assert not result["xml_identical"] and result["native_records_equal"]
    assert not result["changes"]


def test_empty_native_container_indentation_is_normalized_consistently():
    original = make_caf(
        b'<objects xmlns="http://johnsoncontrols.com/MetasysIII/2002/3/Core"><object ref="a" classid="526"/></objects>'
    )
    candidate = with_xml(original, b'classid="526"/>', b'classid="526"> </object>')
    result = compare_cafs(original, candidate)
    assert result["native_records_equal"] and result["total"] == 0


def test_native_application_and_saved_simulation_values_are_separate_changes():
    original = with_xml(
        make_caf(),
        b"</object>",
        b'<simulationProperty id="3113"><data><float>900</float></data></simulationProperty></object>',
    )
    candidate = with_xml(original, b"72.000000", b"73.5")
    candidate = with_xml(candidate, b"<float>900</float>", b"<float>901</float>")
    result = compare_cafs(original, candidate)
    assert result["counts"] == {"application_value": 1, "simulation_value": 1}
    ordinary = next(row for row in result["changes"] if row["record_kind"] == "property")
    assert ordinary["before"]["scalar"]["text"] == "72.000000"
    assert ordinary["after"]["scalar"]["text"] == "73.5"
    saved = next(row for row in result["changes"] if row["record_kind"] == "simulationProperty")
    assert saved["before"]["scalar"]["text"] == "900"


def test_numeric_lexemes_remain_visible_and_string_whitespace_remains_significant():
    original = make_caf()
    candidate = with_xml(original, b"72.000000", b"72.0")
    result = compare_cafs(original, candidate)
    assert not result["native_records_equal"] and result["total"] == 1
    assert result["changes"][0]["numeric_lexeme_only"] is True
    candidate = with_xml(original, b"<string>Example</string>", b"<string> Example </string>")
    result = compare_cafs(original, candidate)
    assert result["total"] == 1 and not result["changes"][0]["numeric_lexeme_only"]


def test_unknown_record_attributes_cannot_be_hidden_as_numeric_representation_changes():
    original = make_caf()
    candidate = with_xml(
        original, b'<property id="3113">', b'<property id="3113" unknown="changed">'
    )
    row = compare_cafs(original, candidate)["changes"][0]
    assert not row["numeric_lexeme_only"]
    assert row["after"]["attributes"]["unknown"] == "changed"


@pytest.mark.parametrize("markup", [b"<!--operator note A-->", b"<?tool note-A?>"])
def test_comments_and_processing_instructions_are_visible_without_inventing_program_semantics(
    markup,
):
    original = with_xml(make_caf(), b"</objects>", markup + b"</objects>")
    candidate = (
        with_xml(original, b"note A", b"note B")
        if b"<!--" in markup
        else with_xml(original, b"note-A", b"note-B")
    )
    result = compare_cafs(original, candidate)
    assert not result["native_records_equal"] and result["total"] == 1
    row = result["changes"][0]
    assert row["change"] == "xml_annotations_changed"
    assert row["before_evidence"]["events"] == 1
    assert row["before_evidence"]["sha256"] != row["after_evidence"]["sha256"]
    assert row["before"] is None and row["after"] is None


def test_annotations_before_and_after_root_have_distinct_locations():
    xml = CafArchive(make_caf()).xml
    original = make_caf(b"<!--same-->" + xml)
    candidate = make_caf(xml + b"<!--same-->")
    assert compare_cafs(original, candidate)["total"] == 1


@pytest.mark.parametrize(
    "content",
    [
        b'<unknown type="t:Analog"/>',
        b"<unknown>t:Analog</unknown>",
        b"<unknown>t:<!--keep-->Analog</unknown>",
    ],
)
def test_qname_binding_changes_cannot_be_hidden_by_equal_literal_values(content):
    original = with_xml(make_caf(), b"<objects ", b'<objects xmlns:t="urn:before" ')
    original = with_xml(original, b"</objects>", content + b"</objects>")
    candidate = with_xml(original, b"urn:before", b"urn:after")
    result = compare_cafs(original, candidate)
    assert not result["native_records_equal"] and result["total"] == 1
    assert result["changes"][0]["change"] == "xml_qname_bindings_changed"


def test_qname_bindings_follow_nested_scope_and_ignore_unused_declarations():
    original = with_xml(make_caf(), b"<objects ", b'<objects xmlns:t="urn:unused" ')
    original = with_xml(
        original, b"</objects>", b'<unknown xmlns:t="urn:used" type="t:Analog"/></objects>'
    )
    candidate = with_xml(original, b"urn:unused", b"urn:still-unused")
    assert compare_cafs(original, candidate)["native_records_equal"]
    candidate = with_xml(original, b"urn:used", b"urn:changed")
    assert not compare_cafs(original, candidate)["native_records_equal"]


@pytest.mark.parametrize("after_namespace", [b"urn:after", b""])
def test_unprefixed_xsi_type_resolves_through_default_namespace(after_namespace):
    original = make_caf(
        b'<j:objects xmlns:j="http://johnsoncontrols.com/MetasysIII/2002/3/Core" xmlns="urn:before" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><j:object ref="a" classid="526"><j:value xsi:type="Analog"/></j:object></j:objects>'
    )
    candidate = with_xml(original, b"urn:before", after_namespace)
    result = compare_cafs(original, candidate)
    assert not result["native_records_equal"] and result["total"] == 1
    assert result["changes"][0]["change"] == "xml_qname_bindings_changed"


def test_attribute_and_annotation_previews_are_bounded_with_full_content_hashes():
    original = with_xml(
        make_caf(), b'<property id="3113">', b'<property id="3113" note="' + b"x" * 30000 + b'">'
    )
    candidate = with_xml(original, b"x" * 30000, b"y" * 30000)
    row = compare_cafs(original, candidate)["changes"][0]
    assert row["after"]["attributes_truncated"]
    assert len(row["after"]["attributes"]["note"]) == 512
    assert row["before"]["sha256"] != row["after"]["sha256"]
    original = with_xml(make_caf(), b"</objects>", b"<!--" + b"a" * 30000 + b"--></objects>")
    candidate = with_xml(original, b"a" * 30000, b"b" * 30000)
    row = compare_cafs(original, candidate)["changes"][0]
    assert row["after_evidence"]["preview"][0]["truncated"]
    assert len(row["after_evidence"]["preview"][0]["event"]) == 2048


def test_long_repeated_native_identities_are_clipped_without_changing_exact_matching():
    import hashlib
    import json

    native_ref = "reference" * 1250
    properties = "".join(
        f'<property id="{10000 + i}"><data><float>0</float></data></property>' for i in range(100)
    )
    original = make_caf(
        f'<objects xmlns="http://johnsoncontrols.com/MetasysIII/2002/3/Core"><object ref="{native_ref}" classid="526">{properties}</object></objects>'.encode()
    )
    candidate = with_xml(original, b"<float>0</float>", b"<float>1</float>")
    result = compare_cafs(original, candidate)
    assert result["total"] == 100 and len(json.dumps(result)) < 300000
    row = result["changes"][0]
    assert row["ref"] == native_ref[:256]
    assert row["object"]["ref"] == native_ref[:256]
    assert (
        row["truncated_identity_fields"]["ref"]["sha256"]
        == hashlib.sha256(native_ref.encode()).hexdigest()
    )
    renamed = with_xml(original, native_ref.encode(), (native_ref + "x").encode())
    assert compare_cafs(original, renamed)["counts"]["object_membership"] == 2


def test_native_rewire_is_identified_by_observed_connection_record_not_block_label():
    original = make_graph()
    candidate, _ = CafGraph(original).rewire_sources([change()])
    result = compare_cafs(original, candidate)
    assert result["counts"] == {"wiring": 1}
    assert result["changes"][0]["property_id"] == "3118"
    assert result["target_metadata_equal"] is None


def test_execution_order_object_identity_and_opaque_job_metadata_stay_visible():
    original = make_graph()
    candidate = with_xml(
        original,
        b"<array><unsignedShort>0</unsignedShort><unsignedShort>1</unsignedShort>",
        b"<array><unsignedShort>1</unsignedShort><unsignedShort>0</unsignedShort>",
    )
    candidate = with_xml(candidate, b'classVersion="1.0"', b'classVersion="2.0"')
    candidate = with_xml(candidate, b"Preserve job", b"Different job")
    result = compare_cafs(original, candidate)
    assert result["counts"]["execution_order"] == 1
    assert result["counts"]["object_identity"] == 5
    assert result["counts"]["opaque_metadata"] == 1


def test_same_name_never_remaps_a_changed_object_reference():
    original = make_caf()
    candidate = with_xml(original, b'ref="8-1"', b'ref="8-2"')
    result = compare_cafs(original, candidate)
    assert result["counts"]["object_membership"] == 2
    assert {
        row["change"] for row in result["changes"] if row["category"] == "object_membership"
    } == {"object_added", "object_removed"}


@pytest.mark.parametrize("old,new", [(b"MS-VMA1630-0", b"FX-PCV1630-0"), (b">10.2<", b">10.1<")])
def test_controller_metadata_changes_do_not_become_compatibility_approval(old, new):
    original = make_caf()
    result = compare_cafs(original, with_xml(original, old, new))
    assert result["counts"] == {"controller_identity": 1}
    assert result["target_metadata_equal"] is False and result["can_apply"] is False


def test_mixed_unknown_text_and_metadata_order_do_not_escape_review():
    original = with_xml(
        make_caf(), b"</objects>", b"<extra>A</extra><another>B</another></objects>"
    )
    candidate = with_xml(
        original, b"<extra>A</extra><another>B</another>", b"<another>B</another><extra>A</extra>"
    )
    assert compare_cafs(original, candidate)["counts"]["record_order"] == 1
    row = next(
        row
        for row in compare_cafs(original, candidate)["changes"]
        if row["category"] == "record_order"
    )
    assert row["before_evidence"]["sha256"] != row["after_evidence"]["sha256"]
    assert row["before_evidence"]["events"] == row["after_evidence"]["events"]
    candidate = with_xml(original, b"<object classid=", b" <object classid=")
    assert compare_cafs(original, candidate)["total"] == 0
    candidate = with_xml(
        original,
        b"<data><float>72.000000</float></data>",
        b"<data><float>72.000000</float></data>meaningful",
    )
    result = compare_cafs(original, candidate)
    assert result["total"] == 1 and not result["native_records_equal"]
    assert result["changes"][0]["after"]["mixed_content"][0]["text"] == "meaningful"
    assert not result["changes"][0]["numeric_lexeme_only"]


def test_native_property_reorder_has_order_preview_and_full_order_hashes():
    original = make_caf()
    candidate = with_xml(
        original, b'<property id="3113"><data><float>72.000000</float></data></property>', b""
    )
    candidate = with_xml(
        candidate,
        b'<property id="2390">',
        b'<property id="3113"><data><float>72.000000</float></data></property><property id="2390">',
    )
    result = compare_cafs(original, candidate)
    assert result["counts"] == {"record_order": 1}
    row = result["changes"][0]
    assert row["before_evidence"]["sha256"] != row["after_evidence"]["sha256"]
    assert row["before_evidence"]["preview"] != row["after_evidence"]["preview"]


def test_significant_record_tail_is_included_in_before_after_evidence_hash():
    original = make_caf()
    candidate = with_xml(original, b"</property>", b"</property>operator-text")
    result = compare_cafs(original, candidate)
    assert result["total"] > 0
    assert all(row["before"]["sha256"] != row["after"]["sha256"] for row in result["changes"])
    assert all(row["after"]["tail_text"] == "operator-text" for row in result["changes"])


def test_filtered_pagination_is_deterministic_and_large_scalar_previews_are_explicitly_clipped():
    original = make_caf()
    candidate = with_xml(original, b">Example<", (">" + "N" * 5000 + "<").encode())
    candidate = with_xml(candidate, b"72.000000", b"77")
    first = compare_cafs(original, candidate, limit=1)
    second = compare_cafs(original, candidate, offset=1, limit=1)
    assert first["total"] == second["total"] == 2
    assert first["changes"][0]["index"] == 0 and second["changes"][0]["index"] == 1
    rows = first["changes"] + second["changes"]
    name = next(row for row in rows if row["property_id"] == "2390")
    assert name["after"]["scalar"]["text_truncated"]
    assert len(name["after"]["scalar"]["text"]) == 2048
    filtered = compare_cafs(original, candidate, category="application_value", query="3113")
    assert filtered["filtered_total"] == 1 and filtered["total"] == 2


@pytest.mark.parametrize(
    "options",
    [
        {"offset": -1},
        {"offset": True},
        {"limit": 0},
        {"limit": 501},
        {"category": "guess"},
        {"query": "x" * 201},
    ],
)
def test_request_bounds_are_explicit(options):
    with pytest.raises(ValueError):
        compare_cafs(make_caf(), make_caf(), **options)


def test_real_api_upload_compare_and_original_export_are_local_and_lossless(tmp_path):
    original = make_caf()
    candidate = with_xml(original, b"72.000000", b"78.5")
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        ids = []
        for raw in (original, candidate):
            response = client.post(
                "/api/caf", files={"file": ("example.caf", raw)}, headers=headers
            )
            assert response.status_code == 200
            ids.append(response.json()["sha256"])
        body = {"before_sha": ids[0], "after_sha": ids[1]}
        assert client.post("/api/caf/compare", json=body).status_code == 403
        result = client.post("/api/caf/compare", json=body, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["changes"][0]["after"]["scalar"]["text"] == "78.5"
        assert (
            client.post(
                "/api/caf/compare", json={**body, "limit": True}, headers=headers
            ).status_code
            == 422
        )
        missing = client.post(
            "/api/caf/compare", json={**body, "after_sha": "0" * 64}, headers=headers
        )
        assert missing.status_code == 422
        for id, expected in zip(ids, (original, candidate), strict=True):
            assert (
                client.post(f"/api/caf/{id}/export", json={"changes": []}, headers=headers).content
                == expected
            )
        assert not client.get("/api/session").json()["field_network_open"]


def test_all_authorized_local_archives_compare_to_their_actual_edited_copies():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR to undistributed authorized CAFs.")
    files = list(Path(directory).rglob("*.caf"))
    assert files
    for path in files:
        original = path.read_bytes()
        archive = CafArchive(original)
        assert compare_cafs(archive, archive)["total"] == 0
        chosen = next(
            (row, prop)
            for row in archive.inventory()
            for prop in archive.properties(row["ref"])
            if prop["id"] == "3113" and prop["editable"] and prop["scalar"]["type"] == "float"
        )
        row, prop = chosen
        edited, _ = archive.patch(
            [
                {
                    "ref": row["ref"],
                    "property": "3113",
                    "old": prop["scalar"]["text"],
                    "value": str(float(prop["scalar"]["text"]) + 0.125),
                }
            ]
        )
        result = compare_cafs(original, edited)
        assert result["total"] == 1 and result["counts"] == {"application_value": 1}
        assert result["changes"][0]["ref"] == row["ref"]
        assert path.read_bytes() == original
