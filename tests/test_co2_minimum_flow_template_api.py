"""Authenticated original-source template, edit, revision and interchange APIs."""

import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path

import pytest
from bms_tool.app import create_app
from bms_tool.co2_minimum_flow_template import PROFILE_SHA, Choices, canonical, convert_units
from bms_tool.connections import Bacnet
from bms_tool.formats import import_program
from bms_tool.models import Edge, Node, Program
from fastapi.testclient import TestClient

from tests.test_co2_minimum_flow_template import PORTS, parent

BASE = "/api/activities/templates/co2-minimum-flow"


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
    root = os.environ.get("BMS_CO2_MIN_FLOW_API_EVIDENCE")
    if root:
        folder = Path(root)
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
    if isinstance(value, dict) and value.get("format") in (
        "bms.program-source-response/1",
        "bms.program-source/1",
    ):
        assert hashlib.sha256(value["source_json"].encode()).hexdigest() == value["source_sha256"]
        return json.loads(value["source_json"])
    return value


def retain(name, rows, files):
    root = os.environ.get("BMS_CO2_MIN_FLOW_API_EVIDENCE")
    if root:
        folder = Path(root) / name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "records.original.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        )
        for name, raw in files.items():
            (folder / name).write_bytes(raw)


@pytest.mark.parametrize("unit,scan", [("cfm", 0.5), ("L/s", 3.0)])
def test_original_review_archive_import_edit_live_ports_revision_and_four_format_interchange(
    tmp_path, monkeypatch, unit, scan
):
    async def forbidden(*args, **kwargs):
        pytest.fail("CO2 flow template opened field networking")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    choices = convert_units(Choices(co2_default=-0.0), unit)
    p = parent(scan, choices)
    rows, files = [], {"authored-parent.original.json": p.model_dump_json().encode()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        power = client.get("/api/operation-power").json()
        catalog = call(client, headers, rows, BASE + "/catalog")
        assert (
            catalog["profile_sha256"] == PROFILE_SHA
            and catalog["defaults"]["flow_low_default"] == 425.0
        )
        report = call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": p.model_dump(), "choices": choices.model_dump()},
        )
        envelope = json.loads(rows[-1]["response"])
        assert [row["path"] for row in envelope["programs"]] == [
            ["program"],
            ["bundle", "library", "definitions", 0, "program"],
        ]
        assert all(
            row["canonical_sha256"] == report["program_sha256"] for row in envelope["programs"]
        )
        assert math.copysign(1, report["choices"]["co2_default"]) < 0
        assert (
            report["parent_reference"]["scan_seconds"] == scan
            and report["program"]["scan_seconds"] == 1.0
        )
        for format in ("review", "bundle"):
            call(
                client,
                headers,
                rows,
                BASE + "/export",
                {"program": p.model_dump(), "choices": choices.model_dump(), "format": format},
                source=False,
            )
            raw = rows[-1]["response"].encode()
            assert raw == canonical(report if format == "review" else report["bundle"])
            assert hashlib.sha256(raw).hexdigest() == rows[-1]["headers"]["x-file-sha256"]
            files["original-" + format + ".json"] = raw
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
            for k in ("definition_id", "definition_sha256", "program_sha256", "bundle_sha256")
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
        inspected["description"] += " Operator-reviewed diagram annotation."
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
                Node(id="flow", kind="Output", unit=unit),
                Node(id="valid", kind="Output", value_type="boolean"),
            ]
        )
        p.edges.extend(
            [Edge(id=name, source=name, target=instance, target_port=name) for name in PORTS]
        )
        p.edges.extend(
            [
                Edge(id="flow", source=instance, source_port="minimum_airflow", target="flow"),
                Edge(
                    id="valid",
                    source=instance,
                    source_port="reset_configuration_valid",
                    target="valid",
                ),
            ]
        )
        simulated = call(
            client,
            headers,
            rows,
            "/api/simulation/step",
            {"program": p.model_dump(), "inputs": {"co2": 900}},
        )
        expected = choices.flow_low_default + 0.5 * (
            choices.flow_high_default - choices.flow_low_default
        )
        assert simulated["last"]["outputs"] == {"flow": expected, "valid": True}
        call(
            client,
            headers,
            rows,
            "/api/simulation/retire",
            {
                "session": simulated["session"],
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
    assert math.copysign(1, stored.metadata["original_source"]["signed"]) < 0
    note = stored.metadata["macros"]["definitions"][0]["program"]["metadata"]["operator_note"]
    assert (
        type(note["integer"]) is int
        and type(note["floating"]) is float
        and math.copysign(1, note["signed"]) < 0
    )
    retain(unit.replace("/", ""), rows, files)


def test_auth_strict_defaults_profile_source_and_version_no_mutations(tmp_path):
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
            {"co2_default": True},
            {"flow_low_default": -1},
            {"co2_reset_b_default": 800},
            {"flow_unit": "%"},
        ):
            call(
                client,
                headers,
                rows,
                BASE + "/preview",
                {"program": p.model_dump(), "choices": choices | changed},
                status=422,
            )
        call(
            client,
            headers,
            rows,
            BASE + "/preview",
            {"program": Program().model_dump(), "choices": choices},
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


def test_units_original_sign_coupling_and_real_conversion_refusals(tmp_path):
    rows = []
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        source = Choices(
            co2_default=-0.0, flow_low_default=-0.0, flow_high_default=1e-6
        ).model_dump()
        result = call(
            client,
            headers,
            rows,
            BASE + "/units",
            {"choices": source, "flow_unit": "L/s", "profile_sha256": PROFILE_SHA},
        )
        assert (
            result["source_choices"] == source
            and result["source_choices_sha256"] == hashlib.sha256(canonical(source)).hexdigest()
        )
        assert (
            math.copysign(1, result["choices"]["flow_low_default"]) < 0
            and math.copysign(1, result["choices"]["co2_default"]) < 0
        )
        assert (
            result["choices"] == convert_units(Choices.model_validate(source), "L/s").model_dump()
        )
        for low, high in ((5e-324, 5e-324), (1.063, 1.0630000000000002)):
            call(
                client,
                headers,
                rows,
                BASE + "/units",
                {
                    "choices": Choices(flow_low_default=low, flow_high_default=high).model_dump(),
                    "flow_unit": "L/s",
                    "profile_sha256": PROFILE_SHA,
                },
                status=422,
            )
        call(
            client,
            headers,
            rows,
            BASE + "/units",
            {"choices": source, "flow_unit": "L/s", "profile_sha256": "0" * 64},
            status=422,
        )
        assert client.get("/api/projects").json() == []
    retain("units", rows, {})


def test_conflicting_source_definition_refuses_preview_and_import_without_replacement(tmp_path):
    from bms_tool.co2_minimum_flow_template import definition

    p, rows = parent(), []
    p.metadata["macros"]["definitions"] = [definition(Choices()).model_dump()]
    p.metadata["macros"]["definitions"][0]["program"]["metadata"]["edited"] = -0.0
    before = p.model_dump_json()
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
    assert p.model_dump_json() == before
    retain("conflict", rows, {})
