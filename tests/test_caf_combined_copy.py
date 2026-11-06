"""Authored local CAF composition; literal XML oracles and no field operations."""

import copy
import io
import zipfile

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_combined_copy import FLAGS, CafCombinedCopy, CombinedSource
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha
from fastapi.testclient import TestClient

from .test_caf_graph import REF, change, connection, make_graph, pack, prop, record, shorts


def combined_fixture(kind="rewire", *, enum=False):
    raw = make_graph() if kind != "connect" else make_graph(wires=[(0, 663, 2, 513)])
    if enum:
        xml = CafArchive(raw).xml
        for instance in (10, 11):
            xml = xml.replace(
                f'classid="526" classVersion="1.0" ref="{REF}.2_{instance}"'.encode(),
                f'classid="528" classVersion="1.0" ref="{REF}.2_{instance}"'.encode(),
            ).replace(
                f"<float>{instance}.000</float>".encode(),
                f'<enum set="510">{instance}</enum>'.encode(),
            )
        raw = pack(xml)
    archive = CafArchive(raw)
    rows = [
        {
            "ref": REF + ".2_10",
            "property": "3113",
            "old": "10" if enum else "10.000",
            "value": "0002" if enum else "12.5000",
        },
        {"ref": REF, "property": "2390", "old": "Authored example", "value": "Combined & café"},
        {"ref": REF + ".2_13", "property": "2390", "old": "Block 13", "value": "New destination"},
    ]
    wiring = {"kind": kind, **(connection() if kind == "connect" else change())}
    return raw, {"source_sha256": archive.hash, "changes": rows, "wiring": wiring}


def compile_copy(raw, request):
    editor = CafCombinedCopy(raw)
    source = editor.inspect(**request)
    return editor.compile(**request, selection_sha256=source["selection_sha256"])


@pytest.mark.parametrize("kind", ["rewire", "connect"])
@pytest.mark.parametrize("enum", [False, True])
def test_exact_literal_union_both_orders_raw_text_metadata_and_names(kind, enum):
    raw, request = combined_fixture(kind, enum=enum)
    a = CafArchive(raw)
    output, result = compile_copy(raw, request)
    expected = (
        a.xml.replace(
            b'<enum set="510">10</enum>' if enum else b"<float>10.000</float>",
            b'<enum set="510">2</enum>' if enum else b"<float>12.5</float>",
            1,
        )
        .replace(b"Authored example", "Combined &amp; café".encode(), 1)
        .replace(b"Block 13", b"New destination", 1)
    )
    if kind == "rewire":
        expected = expected.replace(
            record(*shorts(0, 663, 2, 513)).encode(), record(*shorts(1, 663, 2, 513)).encode(), 1
        )
    else:
        old_rows = record(*shorts(0, 663, 2, 513))
        expected = expected.replace(
            prop("3118", "<array>" + old_rows + "</array>").encode(),
            prop(
                "3118", "<array>" + old_rows + record(*shorts(1, 663, 3, 513)) + "</array>"
            ).encode(),
            1,
        )
        tail = b"<struct><structElement><boolean>0</boolean></structElement><structElement><string /></structElement></struct>"
        start = expected.index(b'<property id="3384">')
        end = expected.index(b"</listof>", start)
        expected = expected[:end] + tail + expected[end:]
    verified = CafArchive(output)
    assert verified.xml == expected
    assert verified.comment == a.comment and verified.info.external_attr == a.info.external_attr
    assert list(verified.objects) == list(a.objects)
    assert result["actual_scalar_change_count"] == 3
    assert result["actual_wiring_change_count"] == 1
    assert result["selection"]["request"] == request
    assert result["scalar_changes"][0]["value"] == request["changes"][0]["value"]
    assert result["scalar_changes"][0]["exported_value"] == ("2" if enum else "12.5")
    assert result["combined_sha256"] == seal(
        {k: v for k, v in result.items() if k != "combined_sha256"}
    )
    assert all(result[k] is False for k in FLAGS)
    assert a.original == raw and a.xml != expected
    graph = CafGraph(verified).diagram(REF)
    assert graph["name"] == "Combined & café" and graph["blocks"][3]["name"] == "New destination"


@pytest.mark.parametrize(
    "spelling,value,count", [("10.000", "10.000", 0), ("12.5", "12.5000", 0), ("10.000", "10.0", 1)]
)
def test_noops_count_literal_changes_separately_from_legacy_float_reports(spelling, value, count):
    raw, request = combined_fixture()
    raw = pack(
        CafArchive(raw).xml.replace(
            b"<float>10.000</float>", f"<float>{spelling}</float>".encode(), 1
        )
    )
    request["source_sha256"] = sha(raw)
    request["changes"] = [
        {"ref": REF + ".2_10", "property": "3113", "old": spelling, "value": value}
    ]
    request["wiring"]["source_ref"] = REF + ".2_10"
    output, report = compile_copy(raw, request)
    assert report["actual_scalar_change_count"] == count
    assert report["actual_wiring_change_count"] == 0
    assert report["unchanged"] is (count == 0)
    if count == 0:
        assert output == raw and report["output_sha256"] == sha(raw)
    if spelling == "12.5":
        assert (
            len(report["legacy_scalar_report"]) == 1
            and report["scalar_changes"][0]["changed"] is False
        )


@pytest.mark.parametrize("value", ["-", "1e", "NaN", "Infinity", "1e99", "1e-100"])
def test_incomplete_scalar_inspects_but_rejects_whole_output(value):
    raw, request = combined_fixture()
    request["changes"][0]["value"] = value
    editor = CafCombinedCopy(raw)
    selected = editor.inspect(**request)
    with pytest.raises(ValueError):
        editor.compile(**request, selection_sha256=selected["selection_sha256"])
    assert editor.archive.original == raw


def test_original_configuration_mismatch_cannot_be_rescued_by_scalar_names_or_defaults():
    raw, request = combined_fixture()
    xml = CafArchive(raw).xml
    at = xml.index(f'ref="{REF}.2_11"'.encode())
    raw = pack(
        xml[:at]
        + xml[at:].replace(
            b"<unsignedShort>44</unsignedShort>", b"<unsignedShort>45</unsignedShort>", 1
        )
    )
    request["source_sha256"] = sha(raw)
    with pytest.raises(ValueError, match="different native configuration"):
        CafCombinedCopy(raw).inspect(**request)


@pytest.mark.parametrize("fault", ["scalar", "wiring"])
def test_shared_unrelated_encoder_mutation_rejected_even_if_both_orders_agree(monkeypatch, fault):
    raw, request = combined_fixture()
    if fault == "scalar":
        original = CafArchive.patch

        def broken(self, changes):
            output, report = original(self, changes)
            after = CafArchive(output)
            return after._copy_xml(after.xml.replace(b"Preserve job", b"Altered job")), report

        monkeypatch.setattr(CafArchive, "patch", broken)
    else:
        original = CafGraph._export_edits

        def broken(self, *args):
            output, report = original(self, *args)
            after = CafArchive(output)
            output = after._copy_xml(after.xml.replace(b"Preserve job", b"Altered job"))
            for row in report:
                row["result_sha256"] = sha(output)
            return output, report

        monkeypatch.setattr(CafGraph, "_export_edits", broken)
    with pytest.raises(ValueError, match="permitted parsed byte deltas"):
        compile_copy(raw, request)


def test_zip_metadata_mutation_refused(monkeypatch):
    raw, request = combined_fixture()
    original = CafArchive.patch

    def broken(self, changes):
        output, report = original(self, changes)
        after = CafArchive(output)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.comment = b"unexpected comment"
            archive.writestr(after.info, after.xml)
        return buf.getvalue(), report

    monkeypatch.setattr(CafArchive, "patch", broken)
    with pytest.raises(ValueError, match="ZIP metadata"):
        compile_copy(raw, request)


def test_duplicate_wire_occurrences_keep_the_unselected_occurrence_and_continuation():
    _, request = combined_fixture()
    raw = make_graph(wires=[(0, 663, 2, 513), (0, 663, 2, 513), (1, 663, 3, 513)])
    request["source_sha256"] = sha(raw)
    request["wiring"]["wire_index"] = 1
    original = CafArchive(raw)
    output, _ = compile_copy(raw, request)
    diagram = CafGraph(output).diagram(REF)
    assert [w["raw"] for w in diagram["connections"]] == [
        [0, 663, 2, 513],
        [1, 663, 2, 513],
        [1, 663, 3, 513],
    ]
    assert [w["continuation"] for w in diagram["connections"]] == [
        w["continuation"] for w in CafGraph(original).diagram(REF)["connections"]
    ]


def test_opaque_lookalike_before_the_real_graph_is_never_silently_rewritten():
    raw, request = combined_fixture()
    original = CafArchive(raw)
    # The old graph encoder uses lexical searches. The new independent parser
    # oracle must refuse an ambiguous serialization rather than broaden it.
    decoy = (
        b'<!-- <object ref="'
        + REF.encode()
        + b'">'
        + prop("3118", "<array>" + record(*shorts(0, 663, 2, 513)) + "</array>").encode()
        + b"</object> -->"
    )
    raw = pack(original.xml.replace(b'<object classid="575"', decoy + b'<object classid="575"', 1))
    request["source_sha256"] = sha(raw)
    with pytest.raises(ValueError, match="serialization"):
        compile_copy(raw, request)


def test_noop_enum_and_name_rows_remain_in_original_order_without_false_edits():
    raw, request = combined_fixture(enum=True)
    request["changes"] = [request["changes"][1], request["changes"][0]]
    request["changes"][0]["value"] = request["changes"][0]["old"]
    request["changes"][1]["value"] = "00010"
    output, report = compile_copy(raw, request)
    assert report["actual_scalar_change_count"] == 0 and report["actual_wiring_change_count"] == 1
    assert report["selection"]["request"]["changes"] == request["changes"]
    assert report["legacy_scalar_report"] == []
    assert CafArchive(output).xml != CafArchive(raw).xml


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "boolean_index",
        "string_index",
        "duplicate_scalar",
        "empty_scalars",
        "unknown_kind",
        "raw_nonstring",
    ],
)
def test_strict_request_refuses_coercion_unknown_fields_and_duplicates(mutation):
    _, request = combined_fixture()
    if mutation == "unknown":
        request["can_apply"] = True
    if mutation == "boolean_index":
        request["wiring"]["wire_index"] = False
    if mutation == "string_index":
        request["wiring"]["wire_index"] = "0"
    if mutation == "duplicate_scalar":
        request["changes"].append(request["changes"][0])
    if mutation == "empty_scalars":
        request["changes"] = []
    if mutation == "unknown_kind":
        request["wiring"]["kind"] = "remove"
    if mutation == "raw_nonstring":
        request["changes"][0]["value"] = 12.5
    with pytest.raises(ValueError):
        CombinedSource.model_validate(request)


def test_http_roundtrip_seals_headers_stale_review_and_original_registry(tmp_path):
    raw, request = combined_fixture()
    with TestClient(create_app(tmp_path)) as client:
        client.headers["X-Studio-Token"] = client.get("/api/session").json()["token"]
        opened = client.post("/api/caf", files={"file": ("authored.caf", raw)})
        assert opened.status_code == 200
        base = "/api/caf/" + request["source_sha256"] + "/combined-copy"
        source = client.post(base + "/source", json=request)
        assert source.status_code == 200
        selected = source.json()
        body = {**request, "selection_sha256": selected["selection_sha256"]}
        reviewed = client.post(base + "/preview", json=body)
        assert reviewed.status_code == 200
        review = reviewed.json()
        exported = client.post(
            base + "/export", json={**body, "review_sha256": review["review_sha256"]}
        )
        assert exported.status_code == 200
        assert (
            exported.headers["X-CAF-Output-SHA256"]
            == sha(exported.content)
            == review["result"]["output_sha256"]
        )
        assert exported.headers["X-CAF-Combined-SHA256"] == review["result"]["combined_sha256"]
        assert exported.headers["X-CAF-Request-SHA256"] == selected["request_sha256"]
        changed = copy.deepcopy(body)
        changed["changes"].reverse()
        assert client.post(base + "/preview", json=changed).status_code == 422
        assert (
            client.post(base + "/export", json={**body, "review_sha256": "0" * 64}).status_code
            == 422
        )
        changed = copy.deepcopy(body)
        changed["source_sha256"] = "0" * 64
        assert client.post(base + "/preview", json=changed).status_code == 422
        result = client.post(
            "/api/caf/" + request["source_sha256"] + "/export", json={"changes": []}
        )
        assert result.content == raw
