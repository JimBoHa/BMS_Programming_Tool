"""Authenticated original-source fan purge authoring, simulation and revision evidence."""

import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.formats import import_program
from bms_tool.models import Edge, Node, Program
from bms_tool.parallel_fan_purge_template import PROFILE_SHA, Choices, canonical, definition
from fastapi.testclient import TestClient

from tests.test_parallel_fan_purge_template import PORTS, parent

BASE = "/api/activities/templates/parallel-fan-purge"


def call(client, headers, rows, path, body=None, status=200, source=True):
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
    rows.append(
        {
            "path": path,
            "request": raw.decode() if raw else None,
            "status": response.status_code,
            "response": response.text,
            "headers": dict(response.headers),
        }
    )
    root = os.environ.get("BMS_PARALLEL_FAN_PURGE_API_EVIDENCE")
    if root:
        folder = Path(root)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "original-http-stream.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"test": os.environ.get("PYTEST_CURRENT_TEST"), **rows[-1]}, ensure_ascii=False
                )
                + "\n"
            )
    assert response.status_code == status, response.text
    if status != 200:
        return response
    value = response.json()
    if isinstance(value, dict) and value.get("format") in (
        "bms.program-source-response/1",
        "bms.program-source/1",
    ):
        assert hashlib.sha256(value["source_json"].encode()).hexdigest() == value["source_sha256"]
        return json.loads(value["source_json"])
    return value


def retain(name, rows, files):
    root = os.environ.get("BMS_PARALLEL_FAN_PURGE_API_EVIDENCE")
    if root:
        folder = Path(root) / name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "records.original.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for name, raw in files.items():
            (folder / name).write_bytes(raw)


@pytest.mark.parametrize("h", [1, 2])
def test_original_source_import_raw_purge_quality_edit_revision_and_interchange(
    tmp_path, monkeypatch, h
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Parallel fan purge template opened field networking")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    choices = Choices(
        scan_seconds=h, heating_percent_command_default=-0.0, heating_purge_duration_default=2 * h
    )
    p = parent(choices)
    rows, files = [], {"authored-parent.original.json": p.model_dump_json().encode()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        power = client.get("/api/operation-power").json()
        catalog = call(client, headers, rows, BASE + "/catalog")
        assert (
            catalog["profile_sha256"] == PROFILE_SHA
            and catalog["defaults"]["heating_purge_duration_default"] == 120
        )
        report = call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": p.model_dump(), "choices": choices.model_dump()},
        )
        envelope = json.loads(rows[-1]["response"])
        assert [r["path"] for r in envelope["programs"]] == [
            ["program"],
            ["bundle", "library", "definitions", 0, "program"],
        ]
        assert all(r["canonical_sha256"] == report["program_sha256"] for r in envelope["programs"])
        assert math.copysign(1, report["choices"]["heating_percent_command_default"]) < 0
        for format in ("review", "bundle"):
            call(
                client,
                headers,
                rows,
                BASE + "/export",
                {"program": p.model_dump(), "choices": choices.model_dump(), "format": format},
            )
            response = rows[-1]["response"].encode()
            assert hashlib.sha256(response).hexdigest() == rows[-1]["headers"]["x-file-sha256"]
            assert response == canonical(report if format == "review" else report["bundle"])
            files["original-" + format + ".json"] = response
        adopted = call(
            client,
            headers,
            rows,
            BASE + "/import",
            {
                "program": p.model_dump(),
                "choices": choices.model_dump(),
                "profile_sha256": PROFILE_SHA,
                "reviewed_parent_sha256": p.digest(),
            },
        )
        repeated = call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": adopted, "choices": choices.model_dump()},
        )
        assert all(
            repeated[k] == report[k]
            for k in ("program_sha256", "definition_sha256", "bundle_sha256")
        )
        inspected = call(
            client,
            headers,
            rows,
            "/api/activities/definition",
            {"program": adopted, "definition": report["definition_id"]},
        )
        files["definition-inspected.original.json"] = json.loads(rows[-1]["response"])[
            "source_json"
        ].encode()
        inspected["description"] += " Operator-reviewed purge logic."
        inspected["metadata"]["operator_note"] = {
            "signed": -0.0,
            "integer": 0,
            "floating": 0.0,
            "small": 1e-6,
        }
        edited = call(
            client,
            headers,
            rows,
            "/api/activities/update",
            {"program": adopted, "definition": report["definition_id"], "replacement": inspected},
        )
        files["definition-edited.original.json"] = json.loads(rows[-1]["response"])[
            "source_json"
        ].encode()
        added = call(
            client,
            headers,
            rows,
            "/api/activities/instantiate",
            {"program": edited, "definition": report["definition_id"]},
        )
        p = Program.model_validate(added)
        instance = p.nodes[-1].id
        p.nodes.extend(
            [
                Node(id="request", kind="Output", value_type="boolean"),
                Node(id="valid", kind="Output", value_type="boolean"),
            ]
        )
        p.edges.extend(
            Edge(id=name, source=name, target=instance, target_port=name) for name in PORTS
        )
        p.edges.extend(
            [
                Edge(id="request", source=instance, source_port="fan_request", target="request"),
                Edge(
                    id="valid",
                    source=instance,
                    source_port="request_configuration_valid",
                    target="valid",
                ),
            ]
        )
        simulated = call(
            client,
            headers,
            rows,
            "/api/simulation/step",
            {"program": p.model_dump(), "inputs": {"heating_percent_command": 6}},
        )
        assert simulated["last"]["outputs"] == {"request": True, "valid": True}
        session = simulated["session"]
        second = call(
            client,
            headers,
            rows,
            "/api/simulation/step",
            {"program": p.model_dump(), "session": session, "inputs": {}},
        )
        assert second["last"]["outputs"]["request"] is True
        call(
            client,
            headers,
            rows,
            "/api/simulation/step",
            {
                "program": p.model_dump(),
                "session": session,
                "inputs": {"heating_percent_command": {"quality": "open-circuit"}},
            },
            status=422,
        )
        released = call(
            client,
            headers,
            rows,
            "/api/simulation/step",
            {"program": p.model_dump(), "session": session, "inputs": {}},
        )
        assert (
            released["last"]["outputs"] == {"request": False, "valid": True}
            and released["last"]["time"] == 3 * h
        )
        call(
            client,
            headers,
            rows,
            "/api/simulation/retire",
            {
                "session": session,
                "retirement_token": simulated["retirement_token"],
                "creation_operation_id": simulated["session_creation_operation_id"],
            },
        )
        assert client.get("/api/projects").json() == []
        saved = call(
            client,
            headers,
            rows,
            "/api/projects",
            {"program": p.model_dump(), "expected_revision": 0},
        )
        assert saved["revision"] == 1
        for format, suffix in (
            ("json", "json"),
            ("st", "st"),
            ("plcopen", "xml"),
            ("graphml", "graphml"),
        ):
            response = client.post(
                "/api/export", json={"program": p.model_dump(), "format": format}, headers=headers
            )
            assert response.status_code == 200, response.text
            assert import_program(response.content, "original." + suffix).digest() == p.digest()
            files["interchange-" + format] = response.content
        files["saved-http.original.json"] = client.get("/api/projects/" + p.id).content
        assert (
            Program.model_validate_json(files["saved-http.original.json"]).digest()
            == Program.model_validate(saved).digest()
        )
        after = client.get("/api/operation-power").json()
        assert power["active"] == after["active"] == [] and power["recent"] == after["recent"] == []
        assert not client.get("/api/session").json()["field_network_open"]
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        text = db.execute(
            "SELECT content FROM revisions WHERE id=? AND revision=1", (p.id,)
        ).fetchone()[0]
    files["saved-sqlite.original.json"] = text.encode()
    stored = Program.model_validate_json(text)
    assert stored.digest() == Program.model_validate(saved).digest()
    note = stored.metadata["macros"]["definitions"][0]["program"]["metadata"]["operator_note"]
    assert (
        type(note["integer"]) is int
        and type(note["floating"]) is float
        and math.copysign(1, note["signed"]) < 0
    )
    retain(f"h{h}", rows, files)


def test_auth_domain_version_clock_profile_source_and_no_project_side_effects(tmp_path):
    p, choices, rows = parent(), Choices().model_dump(), []
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        call(
            client,
            {},
            rows,
            BASE + "/preview",
            {"program": p.model_dump(), "choices": choices},
            status=403,
        )
        for changed in (
            {"fan_off_threshold_default": 0},
            {"fan_on_threshold_default": 100},
            {"scan_seconds": True},
            {"heating_purge_duration_default": -1},
        ):
            call(
                client,
                headers,
                rows,
                BASE + "/preview",
                {"program": p.model_dump(), "choices": choices | changed},
                status=422,
            )
        for bad_parent in (Program(), parent(scan=2)):
            call(
                client,
                headers,
                rows,
                BASE + "/preview",
                {"program": bad_parent.model_dump(), "choices": choices},
                status=422,
            )
        for changed in ({"profile_sha256": "0" * 64}, {"reviewed_parent_sha256": "0" * 64}):
            call(
                client,
                headers,
                rows,
                BASE + "/import",
                {
                    "program": p.model_dump(),
                    "choices": choices,
                    "profile_sha256": PROFILE_SHA,
                    "reviewed_parent_sha256": p.digest(),
                }
                | changed,
                status=422,
            )
        assert client.get("/api/projects").json() == []
    retain("refusals", rows, {})


def test_same_id_source_conflict_cannot_replace_edited_definition(tmp_path):
    p, choices, rows = parent(), Choices(), []
    p.metadata["macros"]["definitions"] = [definition(choices).model_dump()]
    p.metadata["macros"]["definitions"][0]["program"]["metadata"]["edited"] = -0.0
    before = p.model_dump_json()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": p.model_dump(), "choices": choices.model_dump()},
            status=422,
        )
        call(
            client,
            headers,
            rows,
            BASE + "/import",
            {
                "program": p.model_dump(),
                "choices": choices.model_dump(),
                "profile_sha256": PROFILE_SHA,
                "reviewed_parent_sha256": p.digest(),
            },
            status=422,
        )
        assert client.get("/api/projects").json() == []
    assert p.model_dump_json() == before
    retain("conflict", rows, {})
