"""Actual HTTP source/evidence/download and durable revision boundaries."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.models import Program
from bms_tool.schedule_coordination import PROFILE_SHA, canonical
from fastapi.testclient import TestClient

from tests.test_schedule_coordination import choices, group


@pytest.mark.parametrize("transport", [False, True])
def test_actual_preview_export_simulation_revision_and_restart_keep_exact_sources_and_network_closed(
    tmp_path, transport
):
    source = {
        "choices": choices(
            group(start="01:00", end="23:00", days=[0]), group(id="other", mode="all-day")
        ).model_dump(),
        "clocks": ["2026-01-04T22:00:00Z", "2026-01-05T12:00:00Z"],
    }
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/schedule-coordination/catalog").json()
        assert catalog["profile_sha256"] == PROFILE_SHA
        assert (
            catalog["defaults"]["groups"][0]["mode"]
            == catalog["defaults"]["groups"][0]["timezone"]
            == ""
        )
        for action in ("preview", "export"):
            assert (
                client.post("/api/schedule-coordination/" + action, json=source).status_code == 403
            )
        result = client.post(
            "/api/schedule-coordination/preview",
            json=source,
            headers=headers | ({"X-Studio-Program-Source": "true"} if transport else {}),
        )
        assert result.status_code == 200, result.text
        report = result.json()
        if transport:
            assert report["format"] == "bms.program-source-response/1"
            assert (
                hashlib.sha256(report["source_json"].encode()).hexdigest()
                == report["source_sha256"]
            )
            assert report["programs"][0]["path"] == ["program"]
            report = json.loads(report["source_json"])
        assert report["can_create"] and report["profile_sha256"] == PROFILE_SHA
        assert report["profile"] == catalog["profile"]
        program = Program.model_validate(report["program"])
        assert program.digest() == report["program_sha256"]
        assert report["evaluation"][0]["outputs"]["zg1_pre_only"]
        assert not report["evaluation"][0]["outputs"]["ahu_occupied"]
        assert report["evaluation"][1]["outputs"]["ahu_occupied"]
        exported = client.post("/api/schedule-coordination/export", json=source, headers=headers)
        assert exported.status_code == 200, exported.text
        assert hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        assert exported.content == canonical(report)
        assert not report["native_compile"] and not report["controller_writes"]
        step = client.post(
            "/api/simulation/step",
            json={"program": report["program"], "inputs": {}, "steps": 1},
            headers=headers,
        )
        assert step.status_code == 200, step.text
        assert step.json()["last"]["outputs"]["ahu_occupied"]  # all-day other group Monday.
        saved = client.post(
            "/api/projects",
            json={"program": report["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        assert saved["metadata"] == report["program"]["metadata"]
        exported = client.post(
            "/api/export", json={"program": saved, "format": "json"}, headers=headers
        )
        assert exported.status_code == 200 and Program.model_validate_json(
            exported.content
        ) == Program.model_validate(saved)
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/authored-schedules").json() == saved
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "patch",
    [
        {"choices": None},
        {"choices": []},
        {"choices": {"groups": []}},
        {"clocks": ["2026-01-05T00:00:00"]},
        {"clocks": ["2026-01-05T00:00:00-00:00"]},
        {"clocks": ["2026-01-05T00:00:00Z"] * 129},
        {"native_write": True},
    ],
    ids=["null", "list", "missing", "naive-clock", "unknown-offset", "clock-limit", "native-write"],
)
def test_malformed_or_unsupported_request_is_422_with_no_save_or_field_effect(tmp_path, patch):
    source = {"choices": choices().model_dump()} | patch
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for action in ("preview", "export"):
            response = client.post(
                "/api/schedule-coordination/" + action, json=source, headers=headers
            )
            assert response.status_code == 422, response.text
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
