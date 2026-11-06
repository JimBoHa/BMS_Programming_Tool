"""Independent lexical and occurrence tests using only authored CAF containers.

Expected output is assembled from the fixture's literal records, without using
the production span finder or removal encoder to locate or calculate changes.
These checks establish local archive preservation, not vendor or field support.
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from hashlib import sha256

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_connection_removal import CafConnectionRemoval
from bms_tool.caf_graph import CafGraph

from tests.test_caf_graph import REF, make_graph, pack, prop, record, shorts

Q = "{" + NS + "}"
TUPLE = (0, 663, 2, 513)
PREVIEW_KEYS = (
    "source_sha256",
    "diagram_ref",
    "wire_index",
    "selection_sha256",
    "diagram_sha256",
    "connection_property_sha256",
    "continuation_property_sha256",
    "connection_record_sha256",
    "continuation_record_sha256",
    "connection_count",
    "old",
    "continuation",
)


def preview(selection):
    return {key: selection[key] for key in PREVIEW_KEYS}


def duplicate_fixture(index, *, decoys=False, escaped_reference=False):
    """Three identical tuples, individually marked tails and distinct paired text."""
    source_xml = CafArchive(make_graph(wires=[TUPLE] * 3)).xml
    wire = record(*shorts(*TUPLE))
    wires = [wire] * 3
    continuations = [
        record("<boolean>true</boolean>", "<string>First &amp; kept</string>"),
        record("<boolean>1</boolean>", "<string>Middle &#38; removed</string>"),
        record("<boolean>false</boolean>", "<string>Last &lt;kept&gt;</string>"),
    ]
    old_wire_property = prop("3118", "<array>" + wire * 3 + "</array>").encode()
    old_continuation_property = prop(
        "3384",
        "<listof>"
        + record("<boolean>1</boolean>", "<string>Opaque &amp; retained</string>") * 3
        + "</listof>",
    ).encode()

    def collection(pid, tag, rows, removed=None):
        # These comments are outside record spans. Deleting an earlier identical
        # row instead of the selected occurrence changes this literal byte oracle.
        body = "".join(
            f"\n<!--before-{pid}-{i}-->\r\n" + ("" if i == removed else row)
            for i, row in enumerate(rows)
        )
        return prop(pid, f"<{tag}>" + body + f"\n</{tag}>").encode()

    wire_property = collection("3118", "array", wires)
    continuation_property = collection("3384", "listof", continuations)
    source_xml = source_xml.replace(old_wire_property, wire_property, 1).replace(
        old_continuation_property, continuation_property, 1
    )
    expected_xml = source_xml.replace(
        wire_property, collection("3118", "array", wires, index), 1
    ).replace(continuation_property, collection("3384", "listof", continuations, index), 1)

    if decoys:
        # A text-based matcher sees convincing earlier object/property/row copies.
        # Neither the comment, CDATA string, nor nested opaque property is a graph.
        shadow = (
            f'<object classid="575" classVersion="1.0" ref="{REF}" objectid="1">'
            + prop("3118", "<array>" + wire * 3 + "</array>")
            + prop("3384", "<listof>" + "".join(continuations) + "</listof>")
            + "</object>"
        ).encode()
        root_open = f'<objects xmlns="{NS}">'.encode()
        prefix = (
            root_open
            + b"\n<!--"
            + shadow
            + b"-->\n<jobInfo><string><![CDATA["
            + shadow
            + b"]]></string></jobInfo>\n"
        )
        opaque = prop("9997", "<opaque>" + shadow.decode() + "</opaque>").encode()
        for old, new in (
            (root_open, prefix),
            (b'<property id="9999">', opaque + b'<property id="9999">'),
        ):
            source_xml = source_xml.replace(old, new, 1)
            expected_xml = expected_xml.replace(old, new, 1)

    selected_ref = REF
    if escaped_reference:
        encoded = REF + "&gt;&amp;&quot;&apos;"
        selected_ref += ">&\"'"
        source_xml = source_xml.replace(REF.encode(), encoded.encode())
        expected_xml = expected_xml.replace(REF.encode(), encoded.encode())
    return pack(source_xml), source_xml, expected_xml, selected_ref, continuations


def assert_independent_output(original, output, expected_xml, diagram_ref, remaining):
    """Read ZIP and XML directly, independently of CafArchive/CafGraph offsets."""
    with (
        zipfile.ZipFile(io.BytesIO(original)) as before,
        zipfile.ZipFile(io.BytesIO(output)) as after,
    ):
        assert before.namelist() == after.namelist()
        assert before.comment == after.comment
        original_info, info = before.infolist()[0], after.infolist()[0]
        for attribute in (
            "filename",
            "date_time",
            "compress_type",
            "comment",
            "extra",
            "create_system",
            "create_version",
            "extract_version",
            "reserved",
            "flag_bits",
            "volume",
            "internal_attr",
            "external_attr",
        ):
            assert getattr(info, attribute) == getattr(original_info, attribute), attribute
        assert after.read(info) == expected_xml
        assert after.testzip() is None

    root = ET.fromstring(expected_xml)
    diagram = next(e for e in root.findall(Q + "object") if e.get("ref") == diagram_ref)
    properties = {e.get("id"): e for e in diagram.findall(Q + "property")}
    wires = list(properties["3118"][0][0])
    continuations = list(properties["3384"][0][0])
    assert len(wires) == len(continuations) == remaining
    assert [[int(field[0].text) for field in row] for row in wires] == [list(TUPLE)] * remaining


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("decoys,escaped_reference", [(False, False), (True, False), (True, True)])
def test_duplicate_tuple_removes_only_selected_pair_despite_earlier_lexical_decoys(
    index, decoys, escaped_reference
):
    original, xml, expected, ref, continuation_rows = duplicate_fixture(
        index, decoys=decoys, escaped_reference=escaped_reference
    )
    original_hash = sha256(original).hexdigest()
    editor = CafConnectionRemoval(original)
    selection = editor.inspect(ref, index)
    assert selection["old"] == list(TUPLE)
    assert selection["target_remaining_writer_count"] == 2
    assert (
        selection["continuation_record_sha256"]
        == sha256(continuation_rows[index].encode()).hexdigest()
    )
    output, report = editor.compile(**preview(selection))
    assert_independent_output(original, output, expected, ref, 2)
    assert report["output_sha256"] == sha256(output).hexdigest()
    assert report["output_xml_sha256"] == sha256(expected).hexdigest()
    assert CafArchive(original).xml == xml
    assert sha256(original).hexdigest() == original_hash


@pytest.mark.parametrize(
    "marker",
    [
        b"<!--must not silently discard this annotation-->",
        b"<?review must-stay?>",
        b"<![CDATA[unrecognized-row-text]]>",
        b"unrecognized-row-text",
    ],
)
@pytest.mark.parametrize("pid", ["3118", "3384"])
def test_selected_row_rejects_unknown_interior_content_instead_of_discarding_it(pid, marker):
    original, xml, _, _, _ = duplicate_fixture(1)
    before = f"<!--before-{pid}-1-->\r\n<struct>".encode()
    modified = xml.replace(before, before + marker, 1)
    assert modified != xml
    source = pack(modified)
    # CafGraph's structural reader ignores comments/PI and non-value text. The
    # stronger deletion admission must account for bytes it would actually erase.
    assert len(CafGraph(source).diagram(REF)["connections"]) == 3
    with pytest.raises(ValueError):
        CafConnectionRemoval(source).inspect(REF, 1)
    assert CafArchive(source).xml == modified
    assert CafArchive(original).xml == xml


@pytest.mark.parametrize(
    "replacement", [b"<boolean>true</boolean>", b"<boolean><![CDATA[1]]></boolean>"]
)
def test_paired_continuation_lexical_change_cannot_reuse_original_selection(replacement):
    original, xml, _, _, _ = duplicate_fixture(1)
    selected = CafConnectionRemoval(original).inspect(REF, 1)
    assert xml.count(b"<boolean>1</boolean>") == 1
    changed = pack(xml.replace(b"<boolean>1</boolean>", replacement, 1))
    # It remains the same decoded source, tuple and Boolean; exact recorded bytes
    # are different and are not authorized by the former source/selection proof.
    assert (
        CafGraph(changed).diagram(REF)["connections"]
        == CafGraph(original).diagram(REF)["connections"]
    )
    request = preview(selected)
    request["source_sha256"] = sha256(changed).hexdigest()
    with pytest.raises(ValueError):
        CafConnectionRemoval(changed).compile(**request)


def test_comment_on_unselected_record_is_preserved_while_selected_record_is_removed():
    original, xml, expected, ref, _ = duplicate_fixture(1)
    before = b"<!--before-3384-0-->\r\n<struct>"
    annotation = b"<!--opaque unselected record annotation-->"
    xml = xml.replace(before, before + annotation, 1)
    expected = expected.replace(before, before + annotation, 1)
    original = pack(xml)
    editor = CafConnectionRemoval(original)
    output, _ = editor.compile(**preview(editor.inspect(ref, 1)))
    assert_independent_output(original, output, expected, ref, 2)
    assert annotation in expected
