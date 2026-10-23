"""Actual local template->existing macro import/edit/save/interchange workflow."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.formats import import_program
from bms_tool.models import Edge, Node, Program
from bms_tool.sum8_macro_template import PROFILE_SHA, UNITS, canonical
from fastapi.testclient import TestClient

BASE = "/api/macros/templates/sum8"


@pytest.mark.parametrize("unit", list(UNITS))
def test_actual_original_bundles_existing_macro_flow_edit_revision_and_all_interchange(
    tmp_path, monkeypatch, unit
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Sum template opened field networking")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    retained = {}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        before = client.get("/api/operation-power").json()
        catalog = client.get(BASE + "/catalog")
        assert catalog.json()["profile_sha256"] == PROFILE_SHA
        assert client.post(BASE + "/preview", json={"unit": unit}).status_code == 403
        response = client.post(
            BASE + "/preview",
            json={"unit": unit},
            headers=headers | {"X-Studio-Program-Source": "true"},
        )
        assert response.status_code == 200, response.text
        envelope = response.json()
        assert (
            hashlib.sha256(envelope["source_json"].encode()).hexdigest()
            == envelope["source_sha256"]
        )
        assert [x["path"] for x in envelope["programs"]] == [
            ["program"],
            ["bundle", "library", "definitions", 0, "program"],
        ]
        report = json.loads(envelope["source_json"])
        assert all(x["canonical_sha256"] == report["program_sha256"] for x in envelope["programs"])
        retained.update(catalog=catalog.content, preview=response.content)
        for format in ("review", "bundle"):
            result = client.post(
                BASE + "/export", json={"unit": unit, "format": format}, headers=headers
            )
            assert result.content == canonical(report if format == "review" else report["bundle"])
            assert hashlib.sha256(result.content).hexdigest() == result.headers["X-File-SHA256"]
            retained[format] = result.content
        root = Program(
            id="sum8-http",
            nodes=[
                Node(id=f"v{i}", kind="Input", unit=unit, params={"default": float(i)})
                for i in range(1, 9)
            ],
        )

        def old(path, payload):
            result = client.post("/api/macros/" + path, json=payload, headers=headers)
            assert result.status_code == 200, result.text
            return result.json()

        imported = old("import", {"program": root.model_dump(), "bundle": report["bundle"]})
        added = old(
            "instantiate",
            {"program": imported, "definition": report["definition_id"], "x": 360, "y": 160},
        )
        root = Program.model_validate(added)
        instance = root.nodes[-1].id
        root.nodes.append(Node(id="total", kind="Output", unit=unit))
        root.edges.extend(
            Edge(id=f"wire{i}", source=f"v{i}", target=instance, target_port=f"i{i}")
            for i in range(1, 9)
        )
        root.edges.append(Edge(id="publish", source=instance, target="total"))
        simulated = client.post(
            "/api/simulation/step", json={"program": root.model_dump()}, headers=headers
        )
        assert simulated.json()["last"]["outputs"] == {"total": 36}
        inspected = old(
            "definition", {"program": root.model_dump(), "definition": report["definition_id"]}
        )
        next(n for n in inspected["nodes"] if n["id"] == "sum_2")["kind"] = "Subtract"
        next(n for n in inspected["nodes"] if n["id"] == "i1")["params"]["default"] = -0.0
        next(n for n in inspected["nodes"] if n["id"] == "i2")["params"]["default"] = 1e-6
        edited = old(
            "update",
            {
                "program": root.model_dump(),
                "definition": report["definition_id"],
                "replacement": inspected,
            },
        )
        changed = Program.model_validate(edited)
        item = changed.metadata["macros"]["definitions"][0]
        assert item["program"]["metadata"]["sum8_macro_template"]["profile_sha256"] == PROFILE_SHA
        assert Program.model_validate(item["program"]).digest() != report["program_sha256"]
        check = client.post("/api/simulation/step", json={"program": edited}, headers=headers)
        assert check.json()["last"]["outputs"] == {"total": 32}
        saved = client.post(
            "/api/projects", json={"program": edited, "expected_revision": 0}, headers=headers
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 1
        retained.update(
            simulation=simulated.content, edited_simulation=check.content, saved=saved.content
        )
        assert b"-0.0" in saved.content and b"1e-06" in saved.content
        for format, suffix in (
            ("json", "json"),
            ("st", "st"),
            ("plcopen", "xml"),
            ("graphml", "graphml"),
        ):
            exported = client.post(
                "/api/export", json={"program": edited, "format": format}, headers=headers
            )
            assert exported.status_code == 200, exported.text
            restored = import_program(exported.content, "original." + suffix)
            assert restored.digest() == changed.digest()
            retained["interchange-" + format] = exported.content
        after = client.get("/api/operation-power").json()
        assert (
            before["active"] == after["active"] == [] and before["recent"] == after["recent"] == []
        )
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        restored = client.get("/api/projects/sum8-http")
        assert restored.content == saved.content
    # Exact saved text is observed independently of the project HTTP response.
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        table = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='revisions'"
        ).fetchone()
        assert table is not None
        columns = [x[1] for x in db.execute("PRAGMA table_info(revisions)")]
        assert "content" in columns
        row = db.execute(
            "SELECT content FROM revisions WHERE id='sum8-http' AND revision=1"
        ).fetchone()
        stored = row[0].encode() if isinstance(row[0], str) else row[0]
        assert json.loads(stored) == saved.json()
        retained["sqlite-project-content"] = stored
    evidence = os.environ.get("BMS_SUM8_API_EVIDENCE")
    if evidence:
        folder = Path(evidence) / (unit.replace("/", "-") or "dimensionless")
        folder.mkdir(parents=True, exist_ok=False)
        for name, raw in retained.items():
            (folder / name).write_bytes(raw)


def test_invalid_unit_and_export_format_do_not_change_existing_definitions(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for path, body in [
            ("preview", {}),
            ("preview", {"unit": "degC"}),
            ("preview", {"unit": "", "capacity": 8}),
            ("export", {"unit": "", "format": "caf"}),
        ]:
            assert client.post(BASE + "/" + path, json=body, headers=headers).status_code == 422
        assert client.get("/api/projects").json() == []
