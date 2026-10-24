"""Actual local v2 authoring, migration, alias forces and source transport."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from bms_tool import activities as a
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.engine import Engine
from bms_tool.formats import import_program
from bms_tool.models import Edge, Node, Program, canonical
from fastapi.testclient import TestClient

from tests.test_activities import caller


def observe(client, headers, retained, path, body=None, *, source=True, status=200):
    raw = (
        json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if body is not None else None
    )
    response = client.request(
        "GET" if raw is None else "POST",
        path,
        content=raw,
        headers=headers
        | ({"Content-Type": "application/json"} if raw else {})
        | ({"X-Studio-Program-Source": "true"} if source else {}),
    )
    retained.append(
        {
            "path": path,
            "request": raw.decode() if raw else None,
            "response": response.content.decode(),
            "status": response.status_code,
            "headers": dict(response.headers),
        }
    )
    evidence = os.environ.get("BMS_ACTIVITY_API_EVIDENCE")
    if evidence:
        folder = Path(evidence)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "original-http-stream.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {"test": os.environ.get("PYTEST_CURRENT_TEST"), **retained[-1]},
                    ensure_ascii=False,
                )
                + "\n"
            )
    assert response.status_code == status, response.text
    if status != 200:
        return response
    value = (
        response.json()
        if response.headers.get("Content-Type", "").startswith("application/json")
        else None
    )
    if isinstance(value, dict) and value.get("format") == "bms.program-source-response/1":
        assert hashlib.sha256(value["source_json"].encode()).hexdigest() == value["source_sha256"]
        return json.loads(value["source_json"])
    return value if value is not None else response


def retain(case, rows, **artifacts):
    root = os.environ.get("BMS_ACTIVITY_API_EVIDENCE")
    if not root:
        return
    folder = Path(root) / case
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "actual-http-records.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    )
    for name, raw in artifacts.items():
        (folder / name).write_bytes(raw)


@pytest.mark.parametrize("nested", [False, True])
def test_http_v2_library_resolve_force_edit_save_reopen_and_exact_interchange(
    tmp_path, monkeypatch, nested
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Activity authoring opened field networking")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    program = caller(nested=nested)
    records, artifacts = [], {}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        before = client.get("/api/operation-power").json()
        profile = observe(client, headers, records, "/api/activities/profile")
        assert profile["profile_sha256"] == a.PROFILE_SHA
        catalog = observe(
            client, headers, records, "/api/activities/catalog", {"program": program.model_dump()}
        )
        bindings = observe(
            client, headers, records, "/api/activities/resolve", {"program": program.model_dump()}
        )
        assert catalog["bindings"] == bindings == a.resolve(program)
        root = "outer" if nested else "controller"
        archive = client.post(
            "/api/activities/export",
            json={"program": program.model_dump(), "definition": root},
            headers=headers,
        )
        assert archive.status_code == 200, archive.text
        records.append(
            {
                "path": "/api/activities/export",
                "request": {"program": program.model_dump(), "definition": root},
                "response": archive.text,
                "status": 200,
                "headers": dict(archive.headers),
            }
        )
        descriptor = next(row for row in catalog["definitions"] if row["id"] == root)
        assert (
            hashlib.sha256(archive.content).hexdigest()
            == descriptor["archive_sha256"]
            == archive.headers["X-File-SHA256"]
        )
        imported = observe(
            client,
            headers,
            records,
            "/api/activities/import",
            {"program": program.model_dump(), "bundle": archive.json()},
        )
        assert Program.model_validate(imported).digest() == program.digest()
        alias = next(
            row["alias_node_id"]
            for row in bindings["outputs"]
            if row["instance_path"] == ["use0"]
            and row["output_id"] == ("power" if nested else "first")
        )
        simulated = observe(
            client,
            headers,
            records,
            "/api/simulation/step",
            {"program": imported, "forces": {alias: 71}},
        )
        assert simulated["last"]["outputs"] == {"value0": 71, "active0": True}
        assert simulated["last"]["computed"][alias] == 2
        editing = observe(
            client,
            headers,
            records,
            "/api/activities/definition",
            {"program": imported, "definition": "controller"},
        )
        next(n for n in editing["nodes"] if n["id"] == "ramp")["params"]["rate"] = 3
        editing["metadata"]["authored"] = {
            "signed": -0.0,
            "integer": 0,
            "float": 0.0,
            "scientific": 1e-6,
        }
        edited = observe(
            client,
            headers,
            records,
            "/api/activities/update",
            {"program": imported, "definition": "controller", "replacement": editing},
        )
        changed = Program.model_validate(edited)
        assert Engine(changed).step()["outputs"] == {"value0": 3, "active0": True}
        saved = observe(
            client, headers, records, "/api/projects", {"program": edited, "expected_revision": 0}
        )
        assert saved["revision"] == 1
        assert b'"signed": -0.0' in canonical(Program.model_validate(saved))
        for format, suffix in (
            ("json", "json"),
            ("st", "st"),
            ("plcopen", "xml"),
            ("graphml", "graphml"),
        ):
            response = client.post(
                "/api/export", json={"program": edited, "format": format}, headers=headers
            )
            assert response.status_code == 200, response.text
            assert import_program(response.content, "source." + suffix).digest() == changed.digest()
            artifacts["original-" + format] = response.content
        response = client.get("/api/projects/" + program.id)
        stored_program = Program.model_validate(response.json())
        assert stored_program.digest() == Program.model_validate(saved).digest()
        artifacts["saved-http.json"] = response.content
        assert not client.get("/api/session").json()["field_network_open"]
        after = client.get("/api/operation-power").json()
        assert before["active"] == after["active"] == []
        assert before["recent"] == after["recent"] == []
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        raw = db.execute(
            "SELECT content FROM revisions WHERE id=? AND revision=1", (program.id,)
        ).fetchone()[0]
        artifacts["saved-sqlite.json"] = raw.encode() if isinstance(raw, str) else raw
        assert (
            Program.model_validate_json(artifacts["saved-sqlite.json"]).digest()
            == stored_program.digest()
        )
    with TestClient(create_app(tmp_path)) as client:
        assert (
            Program.model_validate(client.get("/api/projects/" + program.id).json()).digest()
            == stored_program.digest()
        )
    retain("nested" if nested else "mixed", records, **artifacts)


def test_http_selection_initialization_dependency_archive_import_instantiate_edit_delete(tmp_path):
    program = Program(
        id="selection-http",
        nodes=[
            Node(id="x", kind="Input", params={"default": 4}),
            Node(id="double", kind="Add"),
            Node(id="flag", kind="Greater"),
            Node(id="zero", kind="Constant"),
            Node(id="out", kind="Output"),
            Node(id="bool", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="a", source="x", target="double", target_port="a"),
            Edge(id="b", source="x", target="double", target_port="b"),
            Edge(id="c", source="double", target="out"),
            Edge(id="d", source="double", target="flag", target_port="a"),
            Edge(id="e", source="zero", target="flag", target_port="b"),
            Edge(id="f", source="flag", target="bool"),
        ],
    )
    records = []
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        reviewed = observe(
            client,
            headers,
            records,
            "/api/activities/migration/preview",
            {"program": program.model_dump()},
        )
        initialized = observe(
            client,
            headers,
            records,
            "/api/activities/migration/apply",
            {
                "program": program.model_dump(),
                "profile_sha256": a.PROFILE_SHA,
                "review_sha256": reviewed["review_sha256"],
            },
        )
        created = observe(
            client,
            headers,
            records,
            "/api/activities/create",
            {
                "program": initialized,
                "selected_ids": ["double", "flag", "zero"],
                "name": "Two published values",
            },
        )
        identifier = created["metadata"]["macros"]["definitions"][0]["id"]
        assert Engine(Program.model_validate(created)).step()["outputs"] == {"out": 8, "bool": True}
        bundle = observe(
            client,
            headers,
            records,
            "/api/activities/export",
            {"program": created, "definition": identifier},
        )
        imported = observe(
            client,
            headers,
            records,
            "/api/activities/import",
            {"program": Program().model_dump(), "bundle": bundle},
        )
        placed = observe(
            client,
            headers,
            records,
            "/api/activities/instantiate",
            {"program": imported, "definition": identifier, "x": -0.0, "y": 25},
        )
        assert placed["nodes"][-1]["kind"] == "Activity" and placed["nodes"][-1]["unit"] == ""
        unresolved = observe(
            client, headers, records, "/api/activities/catalog", {"program": placed}
        )
        assert unresolved["bindings"] is None and len(unresolved["definitions"][0]["outputs"]) == 2
        observe(
            client, headers, records, "/api/activities/resolve", {"program": placed}, status=422
        )
        observe(
            client,
            headers,
            records,
            "/api/activities/delete",
            {"program": placed, "definition": identifier},
            status=422,
        )
        deleted = observe(
            client,
            headers,
            records,
            "/api/activities/delete",
            {"program": imported, "definition": identifier},
        )
        assert deleted["metadata"]["macros"]["definitions"] == []
    retain("selection", records)


@pytest.mark.parametrize("kind", ["program", "bundle"])
def test_actual_http_migration_source_transport_and_stale_provenance_refusal(tmp_path, kind):
    from bms_tool.macros import export_macro_library

    from tests.test_macro_integration import nested_rate_program

    source, records = nested_rate_program(), []
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        if kind == "program":
            request, preview, apply = (
                {"program": source.model_dump()},
                "/migration/preview",
                "/migration/apply",
            )
        else:
            request, preview, apply = (
                {"bundle": export_macro_library(source, "outer")},
                "/migration/bundle-preview",
                "/migration/bundle-export",
            )
        report = observe(client, headers, records, "/api/activities" + preview, request)
        actual = observe(
            client,
            headers,
            records,
            "/api/activities" + apply,
            request | {"profile_sha256": a.PROFILE_SHA, "review_sha256": report["review_sha256"]},
        )
        if kind == "program":
            assert Program.model_validate(actual).digest() == report["program_sha256"]
        else:
            assert a.digest(actual) == report["bundle_sha256"]
        observe(
            client,
            headers,
            records,
            "/api/activities" + apply,
            request | {"profile_sha256": a.PROFILE_SHA, "review_sha256": "0" * 64},
            status=422,
        )
        changed = json.loads(json.dumps(request))
        if kind == "program":
            changed["program"]["metadata"]["new_source"] = -0.0
        else:
            changed["bundle"]["library"]["definitions"][0]["program"]["metadata"][
                "new_source"
            ] = -0.0
        observe(
            client,
            headers,
            records,
            "/api/activities" + apply,
            changed | {"profile_sha256": a.PROFILE_SHA, "review_sha256": report["review_sha256"]},
            status=422,
        )
        assert client.get("/api/projects").json() == []
    retain("migration-" + kind, records)


def test_auth_invalid_fields_and_mutated_model_bounds_refuse_without_writes(tmp_path):
    program, records = caller(), []
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        observe(
            client,
            {},
            records,
            "/api/activities/resolve",
            {"program": program.model_dump()},
            status=403,
        )
        for body in (
            {"program": program.model_dump(), "definition": "controller", "x": True},
            {"program": program.model_dump(), "definition": "controller", "extra": 1},
        ):
            observe(client, headers, records, "/api/activities/instantiate", body, status=422)
        for value in (2.0, True, "2", 3):
            body = program.model_dump()
            body["metadata"]["macros"]["version"] = value
            observe(
                client, headers, records, "/api/activities/resolve", {"program": body}, status=422
            )
        assert client.get("/api/projects").json() == []
    retain("refusals", records)
