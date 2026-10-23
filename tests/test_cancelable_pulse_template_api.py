"""Original local HTTP sources, guarded merge and deliberate existing editor workflows."""

import copy
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.cancelable_pulse_template import PROFILE_SHA, canonical
from bms_tool.connections import Bacnet
from bms_tool.formats import import_program
from bms_tool.models import Edge, Node, Program
from bms_tool.models import canonical as program_canonical
from fastapi.testclient import TestClient

from tests.test_cancelable_pulse_template import parent

BASE = "/api/macros/templates/cancelable-pulse"


class OriginalHTTP:
    def __init__(self, client, case):
        self.client, self.records = client, []
        location = os.environ.get("BMS_PULSE_API_EVIDENCE")
        self.folder = Path(location) / case if location else None
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=False)

    def request(self, method, path, body=None, headers=None):
        raw = (
            None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        )
        response = self.client.request(
            method,
            path,
            content=raw,
            headers=(headers or {})
            | ({"Content-Type": "application/json"} if raw is not None else {}),
        )
        index = len(self.records) + 1
        record = {
            "method": method,
            "path": path,
            "status": response.status_code,
            "request_sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "response_headers": dict(response.headers),
        }
        self.records.append(record)
        if self.folder:
            prefix = self.folder / f"{index:03}"
            if raw is not None:
                prefix.with_suffix(".request.json").write_bytes(raw)
            prefix.with_suffix(".response").write_bytes(response.content)
            (self.folder / "ORIGINAL_HTTP.json").write_text(
                json.dumps(self.records, indent=2) + "\n"
            )
        return response


def source(response):
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert hashlib.sha256(envelope["source_json"].encode()).hexdigest() == envelope["source_sha256"]
    value = json.loads(envelope["source_json"])
    for item in envelope["programs"]:
        graph = value
        for field in item["path"]:
            graph = graph[field]
        assert Program.model_validate(graph).digest() == item["canonical_sha256"]
    return value


def guarded(program, report):
    return {
        "program": program.model_dump(),
        "choices": report["choices"],
        "profile_sha256": report["profile_sha256"],
        "reviewed_parent_sha256": report["parent_reference"]["program_sha256"],
    }


@pytest.mark.parametrize("duration,scan", [(1, 1), (6, 2)])
def test_original_review_import_instances_simulation_retention_save_and_interchange(
    tmp_path, monkeypatch, duration, scan
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Pulse template attempted field I/O")

    for method in ("connect", "connect_mstp", "discover", "read", "apply_write"):
        monkeypatch.setattr(Bacnet, method, forbidden)
    root = parent(float(scan))
    original = program_canonical(root)
    with TestClient(create_app(tmp_path)) as client:
        wire = OriginalHTTP(client, f"d{duration}-h{scan}")
        session = wire.request("GET", "/api/session").json()
        headers = {"X-Studio-Token": session["token"]}
        exact = headers | {"X-Studio-Program-Source": "true"}
        power = wire.request("GET", "/api/operation-power").json()
        catalog = wire.request("GET", BASE + "/catalog").json()
        assert catalog["profile_sha256"] == PROFILE_SHA
        body = {
            "program": root.model_dump(),
            "choices": {"duration_seconds": duration, "scan_seconds": scan},
        }
        for path in ("preview", "export", "import"):
            assert wire.request("POST", BASE + "/" + path, body).status_code == 403
        reviewed = wire.request("POST", BASE + "/preview", body, exact)
        report = source(reviewed)
        assert [p["path"] for p in reviewed.json()["programs"]] == [
            ["program"],
            ["bundle", "library", "definitions", 0, "program"],
        ]
        assert report["parent_reference"]["program_sha256"] == root.digest()
        assert report["parent_reference"]["scan_seconds"] == float(scan)
        for kind in ("review", "bundle"):
            exported = wire.request("POST", BASE + "/export", body | {"format": kind}, headers)
            assert exported.status_code == 200
            assert exported.content == canonical(report if kind == "review" else report["bundle"])
            assert exported.headers["x-file-sha256"] == hashlib.sha256(exported.content).hexdigest()
        imported = source(wire.request("POST", BASE + "/import", guarded(root, report), exact))
        assert program_canonical(root) == original
        assert imported["metadata"]["original_source"] == root.metadata["original_source"]
        for name in ("first", "second"):
            imported = source(
                wire.request(
                    "POST",
                    "/api/macros/instantiate",
                    {
                        "program": imported,
                        "definition": report["definition_id"],
                        "x": 320,
                        "y": 180,
                    },
                    exact,
                )
            )
            instance = imported["nodes"][-1]["id"]
            imported["nodes"].append(
                Node(id=name, kind="Output", value_type="boolean").model_dump()
            )
            imported["edges"].extend(
                [
                    Edge(
                        id=name + "_request",
                        source=name + "_request",
                        target=instance,
                        target_port="request",
                    ).model_dump(),
                    Edge(id=name + "_result", source=instance, target=name).model_dump(),
                ]
            )
        program = Program.model_validate(imported)
        response = wire.request(
            "POST",
            "/api/simulation/step",
            {"program": imported, "inputs": {"first_request": True, "second_request": True}},
            headers,
        )
        assert response.status_code == 200, response.text
        live = response.json()
        assert live["last"]["outputs"] == {"first": True, "second": True}
        previous = copy.deepcopy(live["last"])
        rejected = wire.request(
            "POST",
            "/api/simulation/step",
            {
                "program": imported,
                "session": live["session"],
                "inputs": {"first_request": {"value": False, "quality": "stale"}},
            },
            headers,
        )
        assert rejected.status_code == 422 and "stale" in rejected.text
        cancelled = wire.request(
            "POST",
            "/api/simulation/step",
            {
                "program": imported,
                "session": live["session"],
                "inputs": {"first_request": False, "second_request": True},
            },
            headers,
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["history"][0] == previous
        assert cancelled.json()["last"]["outputs"] == {"first": False, "second": duration > scan}
        assert cancelled.json()["last"]["time"] == scan * 2
        reset = wire.request(
            "POST",
            "/api/simulation/step",
            {"program": imported, "inputs": {"first_request": True}},
            headers,
        )
        assert reset.status_code == 200 and reset.json()["last"]["outputs"] == {
            "first": True,
            "second": False,
        }
        saved = wire.request(
            "POST", "/api/projects", {"program": imported, "expected_revision": 0}, exact
        )
        restored = Program.model_validate(source(saved))
        assert restored.revision == 1
        assert b"-0.0" in saved.content and b"1e-06" in saved.content
        for kind, suffix in (
            ("json", "json"),
            ("st", "st"),
            ("plcopen", "xml"),
            ("graphml", "graphml"),
        ):
            exported = wire.request(
                "POST", "/api/export", {"program": imported, "format": kind}, headers
            )
            assert exported.status_code == 200, exported.text
            assert import_program(exported.content, "pulse." + suffix).digest() == program.digest()
        assert wire.request("GET", "/api/session").json()["field_network_open"] is False
        after = wire.request("GET", "/api/operation-power").json()
        assert after["active"] == power["active"] == [] and after["recent"] == power["recent"] == []
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        row = db.execute(
            "SELECT content,sha256,hash_format FROM revisions WHERE id=? AND revision=1", (root.id,)
        ).fetchone()
    assert row and row[1] == restored.digest() and row[2] == "canonical-json/1"
    assert program_canonical(Program.model_validate_json(row[0])) == program_canonical(restored)
    assert b"-0.0" in row[0].encode()
    if wire.folder:
        (wire.folder / "original-SQLite-content.json").write_text(row[0])
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/projects/" + root.id)
        assert response.status_code == 200
        assert program_canonical(Program.model_validate(response.json())) == program_canonical(
            restored
        )
        if wire.folder:
            (wire.folder / "original-restarted-project-HTTP.json").write_bytes(response.content)


def test_parent_source_clock_profile_staleness_schema_and_collision_are_actual_422(tmp_path):
    root = parent()
    with TestClient(create_app(tmp_path)) as client:
        wire = OriginalHTTP(client, "admission-refusals")
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        exact = headers | {"X-Studio-Program-Source": "true"}
        body = {"program": root.model_dump(), "choices": {"duration_seconds": 5, "scan_seconds": 1}}
        report = source(wire.request("POST", BASE + "/preview", body, exact))
        invalid = [
            body | {"choices": {"duration_seconds": True, "scan_seconds": 1}},
            body | {"choices": {"duration_seconds": 5, "scan_seconds": True}},
            body | {"choices": {"duration_seconds": 0, "scan_seconds": 1}},
            body | {"choices": {"duration_seconds": 86401, "scan_seconds": 1}},
            body | {"choices": {"duration_seconds": 5, "scan_seconds": 61}},
            body | {"choices": {"duration_seconds": 5, "scan_seconds": 2}},
            body | {"choices": {"duration_seconds": 1, "scan_seconds": 2}},
            body | {"choices": {"duration_seconds": 1.0, "scan_seconds": 1}},
            body | {"choices": {"duration_seconds": 5, "scan_seconds": 1, "reset": True}},
            body | {"program": parent(0.5).model_dump()},
            body | {"program": parent(2).model_dump()},
        ]
        for value in invalid:
            assert wire.request("POST", BASE + "/preview", value, headers).status_code == 422
        for changes in (
            {"profile_sha256": "0" * 64},
            {"reviewed_parent_sha256": "0" * 64},
            {"program": root.model_dump() | {"name": "Source edited"}},
        ):
            assert (
                wire.request(
                    "POST", BASE + "/import", guarded(root, report) | changes, headers
                ).status_code
                == 422
            )
        changed = root.model_copy(deep=True)
        changed.metadata["original_source"]["negative_zero"] = 0.0
        assert (
            wire.request(
                "POST",
                BASE + "/import",
                guarded(root, report) | {"program": changed.model_dump()},
                headers,
            ).status_code
            == 422
        )
        assert (
            wire.request("POST", BASE + "/export", body | {"format": "caf"}, headers).status_code
            == 422
        )
        assert (
            wire.request(
                "POST", BASE + "/export", body | {"program": parent(2).model_dump()}, headers
            ).status_code
            == 422
        )
        imported = Program.model_validate(
            source(wire.request("POST", BASE + "/import", guarded(root, report), exact))
        )
        imported.metadata["macros"]["definitions"][0]["program"]["nodes"][1]["params"][
            "seconds"
        ] = 5.0
        original = program_canonical(imported)
        conflict = wire.request(
            "POST",
            BASE + "/import",
            guarded(imported, report) | {"reviewed_parent_sha256": imported.digest()},
            headers,
        )
        assert conflict.status_code == 422 and "identifier conflict" in conflict.text
        assert program_canonical(imported) == original
        assert client.get("/api/projects").json() == []


def test_incomplete_editor_graph_can_import_without_engine_validation_or_silent_clock_enforcement(
    tmp_path,
):
    root = parent(1.0)
    root.nodes.append(Node(id="unfinished", kind="And", value_type="boolean"))
    with TestClient(create_app(tmp_path)) as client:
        wire = OriginalHTTP(client, "incomplete-editor")
        headers = {
            "X-Studio-Token": client.get("/api/session").json()["token"],
            "X-Studio-Program-Source": "true",
        }
        body = {"program": root.model_dump(), "choices": {}}
        report = source(wire.request("POST", BASE + "/preview", body, headers))
        result = source(wire.request("POST", BASE + "/import", guarded(root, report), headers))
        assert result["nodes"] == root.model_dump()["nodes"]
        assert len(result["metadata"]["macros"]["definitions"]) == 1
        # Stateless review does not persist a server-side editor, save or execute its incomplete graph.
        assert client.get("/api/projects").json() == []
        foreign = parent(0.5)
        generic = source(
            wire.request(
                "POST",
                "/api/macros/import",
                {"program": foreign.model_dump(), "bundle": report["bundle"]},
                headers,
            )
        )
        assert generic["scan_seconds"] == 0.5


def test_repreview_after_import_binds_new_parent_but_reuses_identical_definition(tmp_path):
    root = parent()
    with TestClient(create_app(tmp_path)) as client:
        wire = OriginalHTTP(client, "idempotent-new-parent-review")
        headers = {
            "X-Studio-Token": client.get("/api/session").json()["token"],
            "X-Studio-Program-Source": "true",
        }
        first = source(
            wire.request(
                "POST", BASE + "/preview", {"program": root.model_dump(), "choices": {}}, headers
            )
        )
        once = Program.model_validate(
            source(wire.request("POST", BASE + "/import", guarded(root, first), headers))
        )
        second = source(
            wire.request(
                "POST", BASE + "/preview", {"program": once.model_dump(), "choices": {}}, headers
            )
        )
        assert (
            first["parent_reference"]["program_sha256"]
            != second["parent_reference"]["program_sha256"]
        )
        assert second["parent_reference"]["program_sha256"] == once.digest()
        assert first["definition_sha256"] == second["definition_sha256"]
        assert first["program_sha256"] == second["program_sha256"]
        assert first["bundle_sha256"] == second["bundle_sha256"]
        assert canonical(first["program"]) == canonical(second["program"])
        twice = Program.model_validate(
            source(wire.request("POST", BASE + "/import", guarded(once, second), headers))
        )
        assert program_canonical(twice) == program_canonical(once)
        assert len(twice.metadata["macros"]["definitions"]) == 1
