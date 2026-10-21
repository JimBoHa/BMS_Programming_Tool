"""Real encoders and re-importers expose losses without native/field execution."""

import copy
import hashlib
import json
import subprocess

import pytest
from bms_tool.app import create_app
from bms_tool.conversion_preview import conversion_preview
from bms_tool.formats import export_program
from bms_tool.models import Edge, Node, Program
from fastapi.testclient import TestClient


def primitive():
    return Program(
        id="conversion-fixture",
        name="OA signal",
        nodes=[
            Node(id="sensor", kind="Input", params={"default": 12.5}, unit="degC"),
            Node(id="out", kind="Output", unit="degC"),
        ],
        edges=[Edge(id="wire", source="sensor", target="out")],
    )


def targets(report):
    return {row["format"]: row for row in report["targets"]}


def test_real_source_encoders_round_trip_and_keep_source_unchanged(monkeypatch):
    p = primitive()
    before = copy.deepcopy(p.model_dump())

    def forbidden(*args, **kwargs):
        raise AssertionError("Conversion preview must not execute native tools")

    monkeypatch.setattr(subprocess, "run", forbidden)
    r = conversion_preview(p)
    assert p.model_dump() == before
    assert r["program"]["sha256"] == p.digest()
    assert r["source"]["inputs"] == ["sensor"]
    assert r["source"]["outputs"] == ["out"]
    rows = targets(r)
    for f in ["json", "st", "plcopen", "graphml", "bog"]:
        assert rows[f]["status"] == "source-generated", rows[f]
        assert rows[f]["editable_round_trip"]["exact"] is True
        assert rows[f]["native_compilation"] == "not-run"
        assert rows[f]["controller_acceptance"] == "unverified"
    content, _, _ = export_program(p, "st")
    assert rows["st"]["artifact"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert rows["sedona"]["status"] == "source-lowering-checked"
    assert rows["sedona"]["artifact"] is None
    assert rows["temco-bas"]["status"] == "source-generated-review-required"
    assert {"id", "name", "nodes", "edges", "target", "metadata"} <= set(
        rows["temco-bas"]["editable_round_trip"]["changed_fields"]
    )
    assert rows["temco-bas"]["error"] is None


def test_native_only_manufacturers_never_acquire_a_fabricated_artifact():
    rows = targets(conversion_preview(primitive()))
    for f in ["jci-caf", "alc", "honeywell-spyder"]:
        assert rows[f]["status"] == "no-verified-encoder"
        assert rows[f]["artifact"] is None
        assert rows[f]["editable_round_trip"] is None


def test_sedona_preview_checks_actual_declared_scan_period():
    p = primitive()
    p.scan_seconds = 0.0105
    rows = targets(conversion_preview(p))
    assert rows["sedona"]["status"] == "blocked"
    assert "whole milliseconds" in rows["sedona"]["error"]
    assert rows["st"]["status"] == "source-generated"


def test_precision_blocker_is_target_specific_and_other_evidence_survives():
    p = primitive()
    p.nodes[0] = Node(id="sensor", kind="Constant", params={"value": 0.0001}, unit="degC")
    rows = targets(conversion_preview(p))
    assert rows["temco-bas"]["status"] == "blocked"
    assert "0.001" in rows["temco-bas"]["error"]
    assert rows["json"]["status"] == "source-generated"
    assert rows["st"]["status"] == "source-generated"
    assert any(n["code"] == "float32" for n in rows["st"]["notes"])


def test_invalid_graph_can_be_preserved_as_authoring_data_but_not_exported_as_logic():
    p = primitive()
    p.edges.clear()
    r = conversion_preview(p)
    assert any(d["level"] == "error" for d in r["diagnostics"])
    rows = targets(r)
    assert rows["json"]["status"] == "source-generated"
    for f in ["st", "plcopen", "graphml", "bog", "temco-bas", "sedona"]:
        assert rows[f]["status"] == "blocked", rows[f]
        assert rows[f]["artifact"] is None


def test_calendar_provisioning_reports_exact_affected_schedule():
    p = primitive()
    p.nodes[0] = Node(
        id="sensor",
        kind="Schedule",
        value_type="boolean",
        params={"timezone": "America/Los_Angeles"},
    )
    p.nodes[1] = Node(id="out", kind="Output", value_type="boolean")
    r = conversion_preview(p)
    assert r["source"]["host_calendar_nodes"] == ["sensor"]
    for f in ["st", "plcopen", "temco-bas", "sedona"]:
        note = next(n for n in targets(r)[f]["notes"] if n["code"] == "host-calendar")
        assert note["nodes"] == ["sensor"]


def test_artifact_bound_blocks_only_oversized_formats(monkeypatch):
    monkeypatch.setattr("bms_tool.conversion_preview.MAX_ARTIFACT_BYTES", 1)
    rows = targets(conversion_preview(primitive()))
    for f in ["json", "st", "plcopen", "graphml", "bog", "temco-bas", "sedona"]:
        assert rows[f]["status"] == "blocked"
        assert "bound" in rows[f]["error"]
    assert rows["jci-caf"]["status"] == "no-verified-encoder"


def test_report_is_finite_json_and_uses_current_source_identity():
    p = primitive()
    first = conversion_preview(p)
    p.nodes[0].params["default"] = 22
    second = conversion_preview(p)
    assert first["program"]["sha256"] != second["program"]["sha256"]
    json.dumps(second, allow_nan=False)
    assert "source assessment" in second["scope"].lower()


def test_http_preview_requires_session_and_never_opens_field_interface(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        payload = {"program": primitive().model_dump()}
        assert client.post("/api/conversion/preview", json=payload).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/conversion/preview", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.json()["targets"]) == 10
        assert client.get("/api/session").json()["field_network_open"] is False
        assert (
            client.post(
                "/api/conversion/preview", json={**payload, "deploy": True}, headers=headers
            ).status_code
            == 422
        )


@pytest.mark.parametrize("bad", [None, {}, {"program": "not-a-graph"}])
def test_http_rejects_invalid_preview_envelope(tmp_path, bad):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post("/api/conversion/preview", json=bad, headers=headers).status_code == 422
