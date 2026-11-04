"""Reference metadata never substitutes for the source graph or its raw meanings."""

import json

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_reference_labels import (
    CATALOG_FILE,
    CATALOG_SHA256,
    PROFILE,
    CafReferenceLabels,
    _catalog,
)
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import (
    PROTOTYPE as FPROTO,
)
from tests.test_caf_constant_copy import (
    REF as FREF,
)
from tests.test_caf_constant_copy import (
    example as constant,
)
from tests.test_caf_constant_copy import (
    packed,
)
from tests.test_caf_math_copy import REF
from tests.test_caf_math_copy import example as math


def test_complete_reference_sets_have_recorded_provenance_and_attribution():
    raw = CATALOG_FILE.read_bytes()
    assert sha(raw) == CATALOG_SHA256
    data = json.loads(raw)
    assert {k: len(v["members"]) for k, v in data["enum_sets"].items()} == {
        "287": 6,
        "288": 23,
        "432": 11152,
    }
    assert data["source"]["database"] == "FDB_Control_10_8___Firmware_12_0"
    assert data["source"]["commit"] == "c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2"
    assert (
        data["source"]["sha256"]
        == "ce867309de563177133975dcf02661696b11a7839a81a554f24c2cfedef8986e"
    )
    assert data["enum_sets"]["432"]["members"]["796"] == "Supply Damper Stroke Time"
    assert "Apache License" in CATALOG_FILE.with_name("cafReferenceLabels-LICENSE.txt").read_text()
    assert (
        "thecontrolscompany/oct"
        in CATALOG_FILE.with_name("cafReferenceLabels-NOTICE.txt").read_text()
    )


@pytest.mark.parametrize(
    "setup,standard,operator,name",
    [
        (12, 42, "/", "Divide"),
        (13, 43, "-", "Subtract"),
        (14, 41, "+", "Add"),
        (15, 40, "*", "Multiply"),
        (17, 58, "MAX", "MAX"),
        (18, 59, "MIN", "MIN"),
    ],
)
def test_math_reference_names_bind_actual_native_fields_without_changing_graph(
    setup, standard, operator, name
):
    original = math(setup=setup, standard=standard, zero=True)
    a = CafArchive(original)
    before = CafGraph(a).diagram(REF)
    report = CafReferenceLabels(a).diagram(REF)
    row = report["rows"][0]
    assert row["standard_name"] == {
        "property_id": 3670,
        "observed": {"type": "enum", "text": str(standard), "attributes": {"set": "432"}},
        "enum_set": 432,
        "code": standard,
        "reference_name": name,
        "status": "reference_label",
    }
    assert (
        row["setup"]["observed"]
        == {"type": "enum", "text": str(setup), "attributes": {"set": "288"}}
        and row["setup"]["reference_name"] == operator
    )
    assert (
        report["profile"] == PROFILE
        and report["source_sha256"] == sha(original)
        and report["diagram_ref"] == REF
    )
    assert (
        report["catalog"]["archive_compatibility_verified"] is False
        and report["runtime_meaning_verified"] is False
    )
    assert report["controller_write"] is False and report["field_requests"] == 0
    assert report["annotation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "annotation_sha256"}
    )
    assert a.original == original and CafGraph(a).diagram(REF) == before


@pytest.mark.parametrize(
    "setup,standard,operator,name",
    [
        (1, 28, ">", "Greater Than"),
        (2, 31, "<=", "Less Than or Equal"),
        (3, 32, ">=", "Greater Than or Equal"),
    ],
)
def test_comparison_reference_labels_do_not_infer_execution(setup, standard, operator, name):
    from tests.test_caf_comparison_copy import example

    report = CafReferenceLabels(example(setup=setup, standard=standard)).diagram(REF)
    assert (
        report["rows"][0]["setup"]["reference_name"] == operator
        and report["rows"][0]["standard_name"]["reference_name"] == name
    )
    assert report["runtime_meaning_verified"] is False


def test_enum_comparison_only_annotates_parent_not_default_encoding_domains():
    from tests.test_caf_enum_comparison_copy import example

    original = example()
    report = CafReferenceLabels(original).diagram(REF)
    assert (
        report["rows"][0]["standard_name"]["reference_name"] == "Equal (Enum)"
        and report["rows"][0]["setup"]["reference_name"] == "="
    )
    assert len(report["rows"]) == 3 and all("default" not in k for r in report["rows"] for k in r)
    assert b'<enum set="647">5</enum>' in CafArchive(original).xml
    assert report["runtime_meaning_verified"] is False


def test_absent_setup_stays_absent_and_raw_names_are_not_replaced():
    a = CafArchive(constant())
    report = CafReferenceLabels(a).diagram(FREF)
    assert report["rows"][0]["standard_name"]["reference_name"] == "Constant (Float)"
    assert report["rows"][0]["setup"] == {
        "property_id": 518,
        "observed": None,
        "enum_set": None,
        "code": None,
        "reference_name": None,
        "status": "absent",
    }
    assert report["rows"][1]["standard_name"]["status"] == "absent"
    assert CafGraph(a).diagram(FREF)["blocks"][0]["name"] == ""


@pytest.mark.parametrize(
    "old,new,status",
    [
        ('<enum set="432">11</enum>', '<enum set="432">4294967295</enum>', "unmapped"),
        ('<enum set="432">11</enum>', '<enum set="433">11</enum>', "unsupported_encoding"),
        ('<enum set="432">11</enum>', '<enum set="432">011</enum>', "unsupported_encoding"),
        ('<enum set="432">11</enum>', "<string>11</string>", "unsupported_encoding"),
    ],
)
def test_unmapped_or_unknown_encoding_remains_raw_and_does_not_gain_a_label(old, new, status):
    original = packed(CafArchive(constant()).xml.decode().replace(old, new, 1))
    a = CafArchive(original)
    value = CafReferenceLabels(a).diagram(FREF)["rows"][0]["standard_name"]
    assert value["status"] == status and value["reference_name"] is None
    assert (
        value["observed"] == next(p["scalar"] for p in a.properties(FPROTO) if p["id"] == "3670")
        and a.original == original
    )


def test_report_mutation_cannot_poison_source_or_shared_catalog():
    a = CafArchive(constant())
    c = CafReferenceLabels(a)
    first = c.diagram(FREF)
    expected = json.loads(json.dumps(first))
    first["rows"][0]["standard_name"]["observed"]["attributes"]["set"] = "wrong"
    first["catalog"]["source"]["database"] = "wrong"
    assert c.diagram(FREF) == expected and a.original == constant()


def test_corrupt_catalog_refuses_annotation_without_touching_source(tmp_path, monkeypatch):
    bad = tmp_path / "catalog.json"
    bad.write_bytes(CATALOG_FILE.read_bytes() + b" ")
    _catalog.cache_clear()
    monkeypatch.setattr("bms_tool.caf_reference_labels.CATALOG_FILE", bad)
    a = CafArchive(constant())
    try:
        with pytest.raises(ValueError, match="digest"):
            CafReferenceLabels(a).diagram(FREF)
        assert a.original == constant()
    finally:
        _catalog.cache_clear()


def test_metadata_endpoint_never_opens_a_field_interface_or_changes_original(tmp_path, monkeypatch):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    def field(*args, **kwargs):
        raise AssertionError("Reference labels attempted field access")

    original = math(zero=True)
    identity = sha(original)
    with TestClient(create_app(tmp_path)) as client:
        h = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/caf", headers=h, files={"file": ("reference.caf", original)}
            ).status_code
            == 200
        )
        before = client.get(f"/api/caf/{identity}/graph", params={"ref": REF}).json()
        monkeypatch.setattr("socket.create_connection", field)
        response = client.get(f"/api/caf/{identity}/reference-labels", params={"ref": REF})
        assert response.status_code == 200 and response.json() == CafReferenceLabels(
            original
        ).diagram(REF)
        assert client.get(f"/api/caf/{identity}/graph", params={"ref": REF}).json() == before
        assert (
            client.post(f"/api/caf/{identity}/export", headers=h, json={"changes": []}).content
            == original
        )
        assert client.post(
            f"/api/caf/{identity}/reference-labels/apply", headers=h, json={}
        ).status_code in {404, 405}
        assert not client.get("/api/session").json()["field_network_open"]
