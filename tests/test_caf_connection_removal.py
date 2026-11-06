"""Authored CAF removal checks; no manufacturer applications or field operations."""

import zipfile

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_connection_removal import (
    FLAGS,
    PROFILE,
    SCOPE,
    ZIP_METADATA,
    CafConnectionRemoval,
    RemovalPreview,
)
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from .test_caf_graph import REF, connection, make_graph, pack, prop, record, shorts
from .test_caf_zip_attributes import repack


def removal_caf(*, wires=None, boolean="1", version="1.0"):
    return make_graph(wires=wires, boolean=boolean, version=version)


def removal_request(editor, wire_index=0, diagram_ref=REF):
    selected = editor.inspect(diagram_ref, wire_index)
    return {key: selected[key] for key in RemovalPreview.model_fields}


def authored_rows(wires, boolean="true"):
    raw = removal_caf(wires=wires, boolean=boolean)
    a = CafArchive(raw)
    old = record(f"<boolean>{boolean}</boolean>", "<string>Opaque &amp; retained</string>").encode()
    rows = [
        record(
            f"<boolean>{boolean}</boolean>", f"<string>row {i} &amp; preserved</string>"
        ).encode()
        for i in range(len(wires))
    ]
    xml = a.xml
    for row in rows:
        xml = xml.replace(old, row, 1)
    return pack(xml), rows


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("boolean", ["0", "1", "false", "true"])
def test_removes_one_literal_pair_and_preserves_every_other_byte(index, boolean):
    wires = [(0, 663, 2, 513), (1, 663, 3, 513), (0, 85, 3, 7000)]
    source, continuations = authored_rows(wires, boolean)
    editor = CafConnectionRemoval(source)
    original = editor.archive
    selection = editor.inspect(REF, index)
    assert selection["profile"] == PROFILE and selection["scope"] == SCOPE
    assert selection["old"] == list(wires[index])
    assert selection["continuation"] == {
        "flag": boolean in ("1", "true"),
        "text": f"row {index} & preserved",
    }
    assert selection["selection_sha256"] == seal(
        {k: v for k, v in selection.items() if k != "selection_sha256"}
    )
    assert {key: selection[key] for key in FLAGS} == FLAGS
    assert selection["target_remaining_writer_count"] == 0
    output, result = editor.compile(**removal_request(editor, index))
    expected = original.xml.replace(record(*shorts(*wires[index])).encode(), b"", 1).replace(
        continuations[index], b"", 1
    )
    readback = CafArchive(output)
    assert readback.xml == expected
    assert list(readback.objects) == list(original.objects)
    before, after = CafGraph(original).diagram(REF), CafGraph(readback).diagram(REF)
    assert (
        after["blocks"] == before["blocks"]
        and after["execution_order"] == before["execution_order"]
    )
    assert [r["raw"] for r in after["connections"]] == [
        list(w) for i, w in enumerate(wires) if i != index
    ]
    assert [r["index"] for r in after["connections"]] == [0, 1]
    assert result["selection"] == selection and result["remaining_connection_count"] == 2
    assert result["output_sha256"] == sha(output) and result["output_xml_sha256"] == sha(expected)
    assert result["removal_sha256"] == seal(
        {k: v for k, v in result.items() if k != "removal_sha256"}
    )
    assert {key: result[key] for key in FLAGS} == FLAGS
    assert all(result["preserved"].values())
    assert original.original == source and original.xml != expected
    assert (original.info.CRC, original.info.file_size) == (
        CafArchive(source).info.CRC,
        CafArchive(source).info.file_size,
    )


def test_last_wire_retains_explicit_empty_collections_and_all_objects():
    editor = CafConnectionRemoval(removal_caf(wires=[(0, 663, 2, 513)]))
    output, result = editor.compile(**removal_request(editor))
    readback = CafArchive(output)
    assert prop("3118", "<array></array>").encode() in readback.xml
    assert prop("3384", "<listof></listof>").encode() in readback.xml
    assert result["remaining_connection_count"] == 0
    assert CafGraph(readback).diagram(REF)["connections"] == []
    assert list(readback.objects) == list(editor.archive.objects)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("origin,attributes", [(0, 0), (3, 0o600 << 16)])
def test_original_zip_metadata_including_zero_permissions_is_preserved(
    compression, origin, attributes
):
    editor = CafConnectionRemoval(repack(removal_caf(), attributes, origin, compression))
    output, _ = editor.compile(**removal_request(editor))
    actual = CafArchive(output)
    assert actual.comment == editor.archive.comment
    assert all(
        getattr(actual.info, field) == getattr(editor.archive.info, field) for field in ZIP_METADATA
    )
    assert editor.archive.original == repack(removal_caf(), attributes, origin, compression)


def test_control_activity_is_admitted_without_changing_other_identity_namespaces():
    original = CafArchive(removal_caf())
    raw = pack(original.xml.replace(b'classid="575"', b'classid="536"', 1))
    editor = CafConnectionRemoval(raw)
    assert editor.inspect(REF, 0)["diagram_class_id"] == "536"
    output, _ = editor.compile(**removal_request(editor))
    assert CafGraph(output).diagram(REF)["class_id"] == "536"


def test_addition_inverse_recovers_exact_original_xml_and_graph():
    original = removal_caf(wires=[(0, 663, 2, 513)])
    added, _ = CafGraph(original).add_connections([connection()])
    editor = CafConnectionRemoval(added)
    output, report = editor.compile(**removal_request(editor, 1))
    assert CafArchive(output).xml == CafArchive(original).xml
    assert CafGraph(output).diagram(REF) == CafGraph(original).diagram(REF)
    assert report["selection"]["continuation"] == {"flag": False, "text": ""}
    assert report["remaining_connection_count"] == 1


@pytest.mark.parametrize(
    "key",
    [
        "source_sha256",
        "selection_sha256",
        "diagram_sha256",
        "connection_property_sha256",
        "continuation_property_sha256",
        "connection_record_sha256",
        "continuation_record_sha256",
    ],
)
def test_every_source_and_occurrence_hash_is_recomputed(key):
    editor = CafConnectionRemoval(removal_caf())
    request = removal_request(editor)
    request[key] = "0" * 64
    with pytest.raises(ValueError, match="changed"):
        editor.compile(**request)
    assert editor.archive.original == removal_caf()


@pytest.mark.parametrize(
    "change",
    [
        {"wire_index": 1},
        {"connection_count": 1},
        {"old": [1, 663, 2, 513]},
        {"continuation": {"flag": False, "text": "Opaque & retained"}},
        {"continuation": {"flag": True, "text": "changed"}},
    ],
)
def test_original_tuple_count_index_and_continuation_are_required(change):
    editor = CafConnectionRemoval(removal_caf())
    request = removal_request(editor)
    request.update(change)
    with pytest.raises(ValueError, match="changed"):
        editor.compile(**request)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda xml: xml.replace(b'classVersion="1.0"', b'classVersion="2.0"', 1),
        lambda xml: xml.replace(b'<property id="3118">', b'<property id="3118" unknown="x">', 1),
        lambda xml: xml.replace(b'<property id="3384">', b'<property id="3384" unknown="x">', 1),
        lambda xml: xml.replace(
            b'<property id="3118"><data>', b'<property id="3118"><data unknown="x">', 1
        ),
        lambda xml: xml.replace(
            b'<property id="3118"><data><array>',
            b'<property id="3118"><data><array unknown="x">',
            1,
        ),
        lambda xml: xml.replace(
            b'<property id="3118"><data><array><struct>',
            b'<property id="3118"><data><array><struct unknown="x">',
            1,
        ),
        lambda xml: xml.replace(
            b'<property id="3384"><data><listof><struct>',
            b'<property id="3384"><data><listof><struct unknown="x">',
            1,
        ),
        lambda xml: xml.replace(
            b'<property id="3118"><data><array>', b'<property id="3118"><data><array>unmodeled', 1
        ),
        lambda xml: xml.replace(
            b'<property id="3118"><data><array><struct>',
            b'<property id="3118"><data><array><struct>unmodeled',
            1,
        ),
    ],
)
def test_unsupported_version_selected_rows_and_wrapper_metadata_refuse(mutate):
    source = pack(mutate(CafArchive(removal_caf()).xml))
    editor = CafConnectionRemoval(source)
    with pytest.raises(ValueError):
        editor.inspect(REF, 0)
    assert editor.archive.original == source


@pytest.mark.parametrize("wire_index", [-1, 65535, True, 0.0, "0", 2])
def test_source_selection_requires_actual_typed_bounded_occurrence(wire_index):
    with pytest.raises(ValueError):
        CafConnectionRemoval(removal_caf()).inspect(REF, wire_index)


def test_no_connections_do_not_create_a_removal_or_choose_a_default_occurrence():
    with pytest.raises(ValueError, match="actual existing"):
        CafConnectionRemoval(removal_caf(wires=[])).inspect(REF, 0)


def test_utf16_is_readable_but_not_removed():
    xml = CafArchive(removal_caf()).xml.decode()
    raw = pack(('<?xml version="1.0" encoding="utf-16"?>' + xml).encode("utf-16"))
    editor = CafConnectionRemoval(raw)
    assert len(editor.graph.diagram(REF)["connections"]) == 2
    with pytest.raises(ValueError, match="UTF-8/ASCII"):
        editor.inspect(REF, 0)


def test_selection_is_detached_and_compile_checks_actual_output(monkeypatch):
    editor = CafConnectionRemoval(removal_caf())
    request = removal_request(editor)
    selected = editor.inspect(REF, 0)
    selected["old"][0] = 999
    selected["continuation"]["text"] = "mutated response"
    assert removal_request(editor) == request
    monkeypatch.setattr(editor.archive, "_copy_xml", lambda xml: editor.archive.original)
    with pytest.raises(ValueError, match="preservation"):
        editor.compile(**request)


def test_export_refuses_changed_zip_metadata(monkeypatch):
    editor = CafConnectionRemoval(removal_caf())
    original_copy = editor.archive._copy_xml

    def changed(xml):
        raw = original_copy(xml)
        return repack(raw, origin=0, attributes=0)

    monkeypatch.setattr(editor.archive, "_copy_xml", changed)
    with pytest.raises(ValueError, match="preservation"):
        editor.compile(**removal_request(editor))


def test_http_source_review_and_export_have_exact_proofs_and_no_field_operations(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("CAF removal attempted field or native intent work")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    raw = removal_caf()
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        opened = client.post("/api/caf", headers=headers, files={"file": ("authored.caf", raw)})
        assert opened.status_code == 200
        source_hash = opened.json()["sha256"]
        base = f"/api/caf/{source_hash}/connection-removal"
        source_body = {"source_sha256": source_hash, "diagram_ref": REF, "wire_index": 0}
        assert client.post(base + "/source", json=source_body).status_code == 403
        response = client.post(base + "/source", headers=headers, json=source_body)
        assert response.status_code == 200
        selected = response.json()
        request = {key: selected[key] for key in RemovalPreview.model_fields}
        review_response = client.post(base + "/preview", headers=headers, json=request)
        assert review_response.status_code == 200
        review = review_response.json()
        assert review["request"] == request and review["removal"]["selection"] == selected
        assert review["review_sha256"] == seal(
            {k: v for k, v in review.items() if k != "review_sha256"}
        )
        export = client.post(
            base + "/export",
            headers=headers,
            json={**request, "review_sha256": review["review_sha256"]},
        )
        assert export.status_code == 200
        assert (
            export.headers["x-studio-artifact-sha256"]
            == sha(export.content)
            == review["removal"]["output_sha256"]
        )
        assert export.headers["x-studio-review-sha256"] == review["review_sha256"]
        assert export.headers["x-studio-source-sha256"] == source_hash
        assert export.headers["x-studio-removal-sha256"] == review["removal"]["removal_sha256"]
        assert export.headers["x-studio-request-sha256"] == seal(request)
        assert len(CafGraph(export.content).diagram(REF)["connections"]) == 1
        assert (
            client.post(
                base + "/export", headers=headers, json={**request, "review_sha256": "0" * 64}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base.replace(source_hash, "0" * 64) + "/source", headers=headers, json=source_body
            ).status_code
            == 422
        )
        assert client.post(base + "/source", headers=headers, json=source_body).json() == selected
        assert client.get("/api/session").json()["field_network_open"] is False


@pytest.mark.parametrize(
    "update",
    [
        {"wire_index": True},
        {"wire_index": "0"},
        {"wire_index": 0.0},
        {"connection_count": True},
        {"old": [True, 663, 2, 513]},
        {"old": [0, 663, 2]},
        {"old": [0, 663, 2, 65536]},
        {"continuation": {"flag": 1, "text": "x"}},
        {"continuation": {"flag": True, "text": "x", "unknown": True}},
        {"continuation": {"flag": True, "text": "x" * 8193}},
        {"controller_write": True},
        {"prototype_ref": "x"},
        {"review_sha256": "0" * 64},
    ],
)
def test_http_strict_preview_does_not_coerce_or_accept_other_operation_authority(tmp_path, update):
    raw = removal_caf()
    editor = CafConnectionRemoval(raw)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        client.post("/api/caf", headers=headers, files={"file": ("authored.caf", raw)})
        body = {**removal_request(editor), **update}
        response = client.post(
            f"/api/caf/{editor.archive.hash}/connection-removal/preview", headers=headers, json=body
        )
        assert response.status_code == 422
