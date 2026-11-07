"""Independent literal CAF execution-order oracles; no site or vendor fixtures."""

import itertools

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_execution_order import FLAGS, CafExecutionOrder, OrderPreview
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from .test_caf_graph import REF, make_graph, pack, prop, record, shorts
from .test_caf_zip_attributes import repack


def order_request(editor, proposed=None, ref=REF):
    selected = editor.inspect(ref)
    return {
        **{k: selected[k] for k in OrderPreview.model_fields if k != "proposed_order"},
        "proposed_order": proposed if proposed is not None else [1, 0, 2, 3],
    }


def many_members(count):
    original = CafArchive(make_graph(wires=[]))
    xml = original.xml
    old_list = (
        "<array>" + "".join(f'<BACoid id="2">{i}</BACoid>' for i in range(10, 14)) + "</array>"
    )
    new_list = (
        "<array>"
        + "".join(f'<BACoid id="2">{i}</BACoid>' for i in range(10, 10 + count))
        + "</array>"
    )
    xml = xml.replace(old_list.encode(), new_list.encode(), 1)
    old_order = "<array>" + "".join(shorts(0, 1, 2, 3)) + "</array>"
    new_order = "<array>" + "".join(shorts(*range(count))) + "</array>"
    xml = xml.replace(old_order.encode(), new_order.encode(), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>0</unsignedShort>"
    )
    xml = xml.replace(
        ("<listof>" + position * 4 + "</listof>").encode(),
        ("<listof>" + position * count + "</listof>").encode(),
        1,
    )
    # Literal authored child records; no cloning/allocation implementation is used.
    start = xml.index(b'<object classid="526"')
    end = xml.index(b"<jobInfo>")
    children = "".join(
        f'<object classid="526" classVersion="1.0" ref="{REF}.2_{i}" objectid="{i}">'
        + prop("75", f'<BACoid id="2">{i}</BACoid>')
        + prop("2390", f"<string>Authored member {i}</string>")
        + "</object>"
        for i in range(10, 10 + count)
    )
    return pack(xml[:start] + children.encode() + xml[end:])


@pytest.mark.parametrize("count", [1, 512])
def test_exact_member_boundaries_have_independent_full_order_readback(count):
    editor = CafExecutionOrder(many_members(count))
    proposed = list(reversed(range(count)))
    output, result = editor.compile(**order_request(editor, proposed))
    assert CafGraph(output).diagram(REF)["execution_order"] == proposed
    assert result["preserved"]["original_object_count"] == count + 1
    if count == 1:
        assert output == editor.archive.original


@pytest.mark.parametrize("count", [0, 513])
def test_outside_member_boundaries_refuse_original_source(count):
    with pytest.raises(ValueError, match="1–512"):
        CafExecutionOrder(many_members(count)).inspect(REF)


@pytest.mark.parametrize("count", [6000, 6001])
def test_recorded_wire_boundaries_are_bounded_without_changing_originals(count):
    editor = CafExecutionOrder(make_graph(wires=[(0, 663, 0, 513)] * count))
    if count == 6001:
        with pytest.raises(ValueError, match="6,000"):
            editor.inspect(REF)
    else:
        assert len(editor.inspect(REF)["edge_relationships"]) == count


def test_single_quoted_xml_is_patched_without_normalizing_attribute_spelling():
    xml = CafArchive(make_graph()).xml.replace(b'"', b"'")
    editor = CafExecutionOrder(pack(xml))
    output, _ = editor.compile(**order_request(editor))
    old = "<array>" + "".join(shorts(0, 1, 2, 3)) + "</array>"
    new = "<array>" + "".join(shorts(1, 0, 2, 3)) + "</array>"
    assert CafArchive(output).xml == xml.replace(old.encode(), new.encode(), 1)


def test_utf16_remains_readable_but_does_not_gain_order_editing():
    editor = CafExecutionOrder(pack(CafArchive(make_graph()).xml.decode().encode("utf-16")))
    assert editor.graph.diagram(REF)["execution_order"] == [0, 1, 2, 3]
    with pytest.raises(ValueError, match="UTF-8/ASCII"):
        editor.inspect(REF)


@pytest.mark.parametrize("kind", ["activity", "sequence"])
@pytest.mark.parametrize("proposed", list(itertools.permutations(range(4))))
def test_all_four_member_permutations_preserve_literal_bytes_or_refuse(kind, proposed):
    raw = make_graph()
    if kind == "activity":
        raw = pack(CafArchive(raw).xml.replace(b'classid="575"', b'classid="536"', 1))
    original = CafArchive(raw)
    editor = CafExecutionOrder(original)
    request = order_request(editor, list(proposed))
    # Independent edge oracle: the original sources0/1 precede destinations2/3.
    permitted = proposed.index(0) < proposed.index(2) and proposed.index(1) < proposed.index(3)
    if not permitted:
        with pytest.raises(ValueError, match="execution relationship"):
            editor.compile(**request)
        return
    output, result = editor.compile(**request)
    old = prop("3117", "<array>" + "".join(shorts(0, 1, 2, 3)) + "</array>").encode()
    new = prop("3117", "<array>" + "".join(shorts(*proposed)) + "</array>").encode()
    expected = original.xml.replace(old, new, 1)
    assert CafArchive(output).xml == expected
    assert CafGraph(output).diagram(REF)["execution_order"] == list(proposed)
    assert result["output_sha256"] == sha(output)
    assert result["output_xml_sha256"] == sha(expected)
    assert result["changed_positions"] == sum(x != y for x, y in enumerate(proposed))
    assert result["order_sha256"] == seal({k: v for k, v in result.items() if k != "order_sha256"})
    assert result["preserved"]["original_object_count"] == 5
    assert all(result["preserved"].values())
    assert {k: result[k] for k in FLAGS} == FLAGS
    assert original.original == raw
    if proposed == (0, 1, 2, 3):
        assert output == raw


@pytest.mark.parametrize(
    "wires", [[(2, 663, 0, 513)], [(2, 663, 0, 513), (0, 663, 2, 513)], [(0, 663, 0, 513)]]
)
def test_original_backward_feedback_and_self_relationships_remain_exact(wires):
    editor = CafExecutionOrder(make_graph(wires=wires))
    source = editor.inspect(REF)
    output, _ = editor.compile(**order_request(editor, [0, 2, 1, 3]))
    assert CafGraph(output).diagram(REF)["connections"] == editor.graph.diagram(REF)["connections"]
    assert source["edge_relationships"][0]["relationship"] == (
        "same" if wires[0][0] == 0 else "after"
    )
    if wires[0][0] != 0:
        with pytest.raises(ValueError, match="execution relationship"):
            editor.compile(**order_request(editor, [2, 0, 1, 3]))


def test_numeric_spelling_and_surrounding_whitespace_only_changed_for_moved_slots():
    original = CafArchive(make_graph())
    xml = original.xml.replace(
        b"<array>" + "".join(shorts(0, 1, 2, 3)).encode() + b"</array>",
        b"<array>\n<unsignedShort> 000 \t</unsignedShort>\n<unsignedShort>01</unsignedShort>\r\n<unsignedShort>002</unsignedShort><unsignedShort> 3 </unsignedShort></array>",
        1,
    )
    editor = CafExecutionOrder(pack(xml))
    output, _ = editor.compile(**order_request(editor))
    expected = xml.replace(b"> 000 \t<", b"> 1 \t<", 1).replace(b">01<", b">0<", 1)
    assert CafArchive(output).xml == expected
    assert b">002<" in expected
    assert editor.compile(**order_request(editor, [0, 1, 2, 3]))[0] == editor.archive.original


@pytest.mark.parametrize(
    "old,new",
    [
        (b'<property id="3117">', b'<property id="3117" opaque="yes">'),
        (b'<property id="3117"><data>', b'<property id="3117"><data opaque="yes">'),
        (b'<property id="3117"><data><array>', b'<property id="3117"><data><array opaque="yes">'),
        (b'<property id="3117"><data><array>', b'<property id="3117"><data><array>unknown'),
        (b"<unsignedShort>0</unsignedShort>", b"<unsignedShort><![CDATA[0]]></unsignedShort>"),
        (b'classVersion="1.0"', b'classVersion="9.0"'),
    ],
)
def test_unknown_order_schema_or_lexical_forms_refuse_without_rewriting(old, new):
    raw = pack(CafArchive(make_graph()).xml.replace(old, new, 1))
    editor = CafExecutionOrder(raw)
    with pytest.raises(ValueError):
        editor.inspect(REF)
    assert editor.archive.original == raw


@pytest.mark.parametrize(
    "update",
    [
        {"proposed_order": [0, 1, 2]},
        {"proposed_order": [0, 1, 2, 2]},
        {"proposed_order": [0, 1, 2, 4]},
        {"proposed_order": [True, 0, 2, 3]},
        {"proposed_order": [1.0, 0, 2, 3]},
        {"proposed_order": ["1", 0, 2, 3]},
        {"proposed_order": [512, 0, 2, 3]},
        {"proposed_order": []},
        {"original_order": [1, 0, 2, 3]},
        {"selection_sha256": "0" * 64},
        {"diagram_sha256": "0" * 64},
        {"order_property_sha256": "0" * 64},
        {"source_sha256": "0" * 64},
        {"extra": True},
    ],
)
def test_strict_request_and_every_original_guard_refuse(update):
    editor = CafExecutionOrder(make_graph())
    with pytest.raises(ValueError):
        editor.compile(**{**order_request(editor), **update})


@pytest.mark.parametrize("modified", ["0", "false"])
def test_unmodified_parent_flag_is_not_invented(modified):
    raw = pack(
        CafArchive(make_graph()).xml.replace(
            b'<property id="2390">',
            prop("3373", f"<boolean>{modified}</boolean>").encode() + b'<property id="2390">',
            1,
        )
    )
    with pytest.raises(ValueError, match="user-modified"):
        CafExecutionOrder(raw).inspect(REF)


def test_readback_detects_wrong_output_and_changed_zip_metadata(monkeypatch):
    editor = CafExecutionOrder(make_graph())
    original = editor.archive._copy_xml
    request = order_request(editor)
    monkeypatch.setattr(editor.archive, "_copy_xml", lambda xml: editor.archive.original)
    with pytest.raises(ValueError, match="preservation"):
        editor.compile(**request)
    monkeypatch.setattr(
        editor.archive, "_copy_xml", lambda xml: repack(original(xml), origin=0, attributes=0)
    )
    with pytest.raises(ValueError, match="preservation"):
        editor.compile(**request)


def test_selected_reports_are_detached_from_compiler_state():
    editor = CafExecutionOrder(make_graph())
    request = order_request(editor)
    source = editor.inspect(REF)
    source["original_order"].reverse()
    source["members"][0]["ref"] = "mutated"
    source["edge_relationships"][0]["relationship"] = "after"
    assert order_request(editor) == request
    assert editor.compile(**request)[1]["changed_positions"] == 2


def test_http_exact_original_and_export_proofs_without_field_or_intent_work(tmp_path, monkeypatch):
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Execution-order copy attempted field or intent work")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    raw = make_graph()
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post("/api/caf", headers=headers, files={"file": ("authored.caf", raw)})
        source_hash = opened.json()["sha256"]
        base = f"/api/caf/{source_hash}/execution-order"
        body = dict(source_sha256=source_hash, diagram_ref=REF)
        assert client.post(base + "/source", json=body).status_code == 403
        source = client.post(base + "/source", headers=headers, json=body).json()
        request = {
            **{k: source[k] for k in OrderPreview.model_fields if k != "proposed_order"},
            "proposed_order": [1, 0, 2, 3],
        }
        response = client.post(base + "/preview", headers=headers, json=request)
        assert response.status_code == 200
        review = response.json()
        assert review["review_sha256"] == seal(
            {k: v for k, v in review.items() if k != "review_sha256"}
        )
        export_body = {**request, "review_sha256": review["review_sha256"]}
        assert client.post(base + "/export", json=export_body).status_code == 403
        export = client.post(base + "/export", headers=headers, json=export_body)
        assert export.status_code == 200
        assert (
            sha(export.content)
            == export.headers["X-Studio-Artifact-Sha256"]
            == review["result"]["output_sha256"]
        )
        assert export.headers["X-Studio-Source-Sha256"] == source_hash
        assert export.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert export.headers["X-Studio-Order-Sha256"] == review["result"]["order_sha256"]
        assert export.headers["X-Studio-Request-Sha256"] == seal(request)
        assert CafGraph(export.content).diagram(REF)["execution_order"] == [1, 0, 2, 3]
        assert (
            client.post(
                base + "/export", headers=headers, json={**export_body, "review_sha256": "0" * 64}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/source", headers=headers, json={**body, "source_sha256": "0" * 64}
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False
