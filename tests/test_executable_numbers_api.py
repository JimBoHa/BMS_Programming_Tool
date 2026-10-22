"""Real HTTP execution boundaries refuse lossy integers without migrating source."""

import copy
import json
from pathlib import Path

from bms_tool.app import create_app
from bms_tool.models import Program
from fastapi.testclient import TestClient

from .test_executable_numbers import UNREPRESENTABLE, addition, memory, passthrough


def test_actual_step_scenario_runtime_and_conversion_refuse_but_archive_reopens(tmp_path):
    p = addition(UNREPRESENTABLE, 0.0)
    source = p.model_dump(mode="json")
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for path, body in (
            ("/api/simulation/step", {"program": source}),
            ("/api/simulation/scenario", {"program": source, "events": [], "duration": 1.0}),
            ("/api/runtime/plan", {"program": source}),
            ("/api/export", {"program": source, "format": "st"}),
        ):
            response = client.post(path, json=body, headers=headers)
            assert response.status_code == 422 and "binary64" in response.json()["detail"]
        saved = client.post(
            "/api/projects", json={"program": source, "expected_revision": 0}, headers=headers
        )
        assert saved.status_code == 200
        original = Program.model_validate(saved.json())
        reopened = client.get("/api/projects/" + p.id)
        assert Program.model_validate(reopened.json()).digest() == original.digest()
        assert reopened.json()["nodes"][0]["params"]["default"] == UNREPRESENTABLE
        exported = client.post(
            "/api/export",
            json={"program": original.model_dump(), "format": "json"},
            headers=headers,
        )
        assert exported.status_code == 200 and str(UNREPRESENTABLE).encode() in exported.content
        assert not client.get("/api/session").json()["field_network_open"]


def test_actual_live_refusal_keeps_session_state_and_accepts_exact_large_integer(tmp_path):
    p = memory().model_dump(mode="json")
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        first = client.post(
            "/api/simulation/step", json={"program": p, "inputs": {"source": 3}}, headers=headers
        ).json()
        before = copy.deepcopy(first["snapshot"])
        for extra in (
            {"inputs": {"source": UNREPRESENTABLE}},
            {"forces": {"source": UNREPRESENTABLE}},
        ):
            refused = client.post(
                "/api/simulation/step",
                json={"program": p, "session": first["session"], **extra},
                headers=headers,
            )
            assert refused.status_code == 422 and "binary64" in refused.json()["detail"]
        resumed = client.post(
            "/api/simulation/step",
            json={"program": p, "session": first["session"], "inputs": {"source": 4}},
            headers=headers,
        ).json()
        assert resumed["last"]["outputs"]["out"] == 3
        assert resumed["snapshot"]["time"] == before["time"] + 1
        exact = client.post(
            "/api/simulation/step",
            json={"program": passthrough().model_dump(), "inputs": {"source": 2**60}},
            headers=headers,
        )
        assert exact.status_code == 200 and exact.json()["last"]["outputs"]["out"] == 2**60


def test_legacy_archive_import_http_preserves_original_integer_without_execution(tmp_path):
    fixtures = Path(__file__).parent / "fixtures/legacy-numeric"
    provenance = json.loads((fixtures / "provenance.json").read_text())
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/import",
            headers=headers,
            files={"file": ("legacy.st", (fixtures / "legacy.st").read_bytes(), "text/plain")},
        )
        assert response.status_code == 200, response.text
        assert b"9007199254740993" in response.content
        p = Program.model_validate(response.json())
        assert p.digest() == provenance["program_sha256"]
        refused = client.post(
            "/api/simulation/step", headers=headers, json={"program": p.model_dump()}
        )
        assert refused.status_code == 422 and "binary64" in refused.json()["detail"]
        assert not client.get("/api/session").json()["field_network_open"]
