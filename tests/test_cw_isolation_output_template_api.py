"""Actual authenticated template/activities/revision/source API workflows."""

import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.cw_isolation_output_template import PROFILE_SHA, canonical
from bms_tool.formats import import_program
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_cw_isolation_output_template import parent

BASE = "/api/activities/templates/cw-iso-output"


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
    evidence = os.environ.get("BMS_CW_OUTPUT_API_EVIDENCE")
    if evidence:
        folder = Path(evidence)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "original-http-stream.jsonl").open("a") as stream:
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
    if value.get("format") in ("bms.program-source-response/1", "bms.program-source/1"):
        assert hashlib.sha256(value["source_json"].encode()).hexdigest() == value["source_sha256"]
        return json.loads(value["source_json"])
    return value


def retain(name, rows, files):
    root = os.environ.get("BMS_CW_OUTPUT_API_EVIDENCE")
    if root:
        folder = Path(root) / name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "records.original.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        )
        for name, raw in files.items():
            (folder / name).write_bytes(raw)


@pytest.mark.parametrize("minimum,stroke,scan", [(20.0, 4, 1), (-0.0, 60, 1), (12.5, 6, 3)])
def test_http_original_review_archive_activity_import_and_revision_interchange(
    tmp_path, monkeypatch, minimum, stroke, scan
):
    async def forbidden(*args, **kwargs):
        pytest.fail("CW output template opened field networking")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    p = parent(scan)
    original = p.model_dump_json().encode()
    rows, files = [], {"authored-parent.original.json": original}
    choices = {"minimum_command": minimum, "stroke_seconds": stroke, "scan_seconds": scan}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        power = client.get("/api/operation-power").json()
        catalog = call(client, headers, rows, BASE + "/catalog")
        assert catalog["profile_sha256"] == PROFILE_SHA
        report = call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": p.model_dump(), "choices": choices},
        )
        envelope = json.loads(rows[-1]["response"])
        assert [r["path"] for r in envelope["programs"]] == [
            ["program"],
            ["bundle", "library", "definitions", 0, "program"],
        ]
        assert all(r["canonical_sha256"] == report["program_sha256"] for r in envelope["programs"])
        assert math.copysign(1, report["choices"]["minimum_command"]) == math.copysign(1, minimum)
        for format in ("review", "bundle"):
            call(
                client,
                headers,
                rows,
                BASE + "/export",
                {"program": p.model_dump(), "choices": choices, "format": format},
                source=False,
            )
            expected = canonical(report if format == "review" else report["bundle"])
            assert rows[-1]["response"].encode() == expected
            assert hashlib.sha256(expected).hexdigest() == rows[-1]["headers"]["x-file-sha256"]
            files["original-" + format + ".json"] = expected
        imported = call(
            client,
            headers,
            rows,
            BASE + "/import",
            {
                "program": p.model_dump(),
                "choices": choices,
                "profile_sha256": PROFILE_SHA,
                "reviewed_parent_sha256": report["parent_reference"]["program_sha256"],
            },
        )
        repeated = call(
            client, headers, rows, BASE + "/preview", {"program": imported, "choices": choices}
        )
        assert (
            repeated["program_sha256"] == report["program_sha256"]
            and repeated["bundle_sha256"] == report["bundle_sha256"]
        )
        added = call(
            client,
            headers,
            rows,
            "/api/activities/instantiate",
            {"program": imported, "definition": report["definition_id"]},
        )
        from bms_tool.models import Edge, Node

        p = Program.model_validate(added)
        instance = p.nodes[-1].id
        p.nodes.extend(
            [
                Node(id="on", kind="Output", value_type="boolean"),
                Node(id="percent", kind="Output", unit="%"),
            ]
        )
        p.edges.extend(
            [
                Edge(id="enable", source="enable", target=instance, target_port="device_enable"),
                Edge(id="request", source="requested", target=instance, target_port="command"),
                Edge(id="on", source=instance, source_port="device_on_off", target="on"),
                Edge(
                    id="percent", source=instance, source_port="effective_command", target="percent"
                ),
            ]
        )
        simulated = call(
            client,
            headers,
            rows,
            "/api/simulation/step",
            {"program": p.model_dump(), "inputs": {"enable": True, "requested": 100}},
        )
        assert simulated["last"]["outputs"]["on"] is True
        assert simulated["last"]["outputs"]["percent"] == 100 * scan / stroke
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
        restored = client.get("/api/projects/" + p.id)
        files["saved-http.original.json"] = restored.content
        assert (
            Program.model_validate(restored.json()).digest()
            == Program.model_validate(saved).digest()
        )
        if minimum == 0:
            assert math.copysign(
                1,
                restored.json()["metadata"]["macros"]["definitions"][0]["program"]["metadata"][
                    "cw_isolation_output_template"
                ]["choices"]["minimum_command"],
            ) == math.copysign(1, minimum)
        after = client.get("/api/operation-power").json()
        assert power["active"] == after["active"] == [] and power["recent"] == after["recent"] == []
        assert not client.get("/api/session").json()["field_network_open"]
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        raw = db.execute(
            "SELECT content FROM revisions WHERE id=? AND revision=1", (p.id,)
        ).fetchone()[0]
        files["saved-sqlite.original.json"] = raw.encode() if isinstance(raw, str) else raw
        assert (
            Program.model_validate_json(files["saved-sqlite.original.json"]).digest()
            == Program.model_validate(saved).digest()
        )
    retain("negative-zero" if minimum == 0 else f"m{minimum}-t{stroke}-h{scan}", rows, files)


def test_actual_auth_bounds_clock_source_profile_and_v1_boundary_no_project_mutations(tmp_path):
    p = parent()
    choices = {"minimum_command": 0.0, "stroke_seconds": 60, "scan_seconds": 1}
    rows = []
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
            {"minimum_command": True},
            {"stroke_seconds": True},
            {"scan_seconds": 1.0},
            {"minimum_command": 101},
            {"stroke_seconds": 5, "scan_seconds": 2},
        ):
            call(
                client,
                headers,
                rows,
                BASE + "/preview",
                {"program": p.model_dump(), "choices": choices | changed},
                status=422,
            )
        for program in (Program().model_dump(), parent(2).model_dump()):
            call(
                client,
                headers,
                rows,
                BASE + "/preview",
                {"program": program, "choices": choices},
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


def test_same_choices_reuse_definition_but_conflicting_existing_source_refuses(tmp_path):
    from bms_tool.cw_isolation_output_template import Choices, definition

    item = definition(Choices())
    p = parent()
    p.metadata["macros"]["definitions"] = [item.model_dump()]
    p.metadata["macros"]["definitions"][0]["program"]["metadata"]["edited"] = -0.0
    rows = []
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": p.model_dump(), "choices": Choices().model_dump()},
            status=422,
        )
        call(
            client,
            headers,
            rows,
            BASE + "/import",
            {
                "program": p.model_dump(),
                "choices": Choices().model_dump(),
                "profile_sha256": PROFILE_SHA,
                "reviewed_parent_sha256": p.digest(),
            },
            status=422,
        )
        assert client.get("/api/projects").json() == []
    retain("conflict", rows, {})
