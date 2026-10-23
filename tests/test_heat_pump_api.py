"""Actual guarded HTTP authoring, original review bytes, save and restart."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.heat_pump import PROFILE_SHA, canonical
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_heat_pump import choices


@pytest.mark.parametrize("source_transport", [False, True])
def test_http_preview_export_simulation_revision_and_restart_are_source_bound(
    tmp_path, monkeypatch, source_transport
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Heat-pump authoring attempted field access")

    for method in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, method, forbidden)
    source = {"choices": choices(condensate="disable-cooling", setpoints="inputs").model_dump()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/heat-pump-wizard/catalog").json()
        assert catalog["profile_sha256"] == PROFILE_SHA
        for field in ("reversing_polarity", "initial_mode", "fan_policy", "condensate"):
            assert catalog["defaults"][field] == ""
        assert catalog["defaults"]["airflow_proven_default"] is False
        for action in ("preview", "export", "units"):
            assert client.post("/api/heat-pump-wizard/" + action, json=source).status_code == 403
        response = client.post(
            "/api/heat-pump-wizard/preview",
            json=source,
            headers=headers | ({"X-Studio-Program-Source": "true"} if source_transport else {}),
        )
        assert response.status_code == 200, response.text
        report = response.json()
        if source_transport:
            assert report["format"] == "bms.program-source-response/1"
            assert (
                hashlib.sha256(report["source_json"].encode()).hexdigest()
                == report["source_sha256"]
            )
            assert report["programs"][0]["path"] == ["program"]
            report = json.loads(report["source_json"])
        assert report["can_create"] and report["profile"] == catalog["profile"]
        assert report["format"] == "bms.heat-pump-wizard-preview" and report["version"] == 1
        program = Program.model_validate(report["program"])
        assert program.digest() == report["program_sha256"]
        assert not report["native_compile"] and not report["controller_writes"]
        exported = client.post("/api/heat-pump-wizard/export", json=source, headers=headers)
        assert exported.status_code == 200 and exported.content == canonical(report)
        assert hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        scan = client.post(
            "/api/simulation/step",
            json={"program": report["program"], "inputs": {}, "steps": 2},
            headers=headers,
        )
        assert scan.status_code == 200, scan.text
        assert scan.json()["last"]["outputs"]["compressor"]
        saved = client.post(
            "/api/projects",
            json={"program": report["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        assert saved["metadata"] == report["program"]["metadata"]
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/authored-heat-pump").json() == saved
        assert not client.get("/api/session").json()["field_network_open"]


def test_http_units_bind_exact_source_and_convert_differences_separately(tmp_path):
    source = choices(zone_default=32, demand_on_delta=18, demand_off_delta=9).model_dump()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/heat-pump-wizard/units",
            json={"choices": source, "temperature_unit": "degC"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["profile_sha256"] == PROFILE_SHA
        assert (
            data["source_choices_sha256"]
            == hashlib.sha256(canonical(data["source_choices"])).hexdigest()
        )
        assert data["choices_sha256"] == hashlib.sha256(canonical(data["choices"])).hexdigest()
        assert data["source_choices"]["temperature_unit"] == "degF"
        assert data["choices"]["zone_default"] == 0
        assert data["choices"]["demand_on_delta"] == 10 and data["choices"]["demand_off_delta"] == 5
        assert data["choices"]["minimum_on_seconds"] == source["minimum_on_seconds"]
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "patch",
    [
        {"choices": None},
        {"choices": []},
        {"choices": {"native_compile": True}},
        {"choices": {"scan_seconds": True}},
        {"choices": {"scan_seconds": 0.5}},
        {"choices": {"reversing_polarity": ""}},
        {"choices": {"initial_mode": ""}},
        {"choices": {"airflow_proven_default": 1}},
        {"choices": {"minimum_on_seconds": 0}},
        {"choices": {"demand_on_delta": 0}},
        {"choices": {"demand_off_delta": 2}},
        {"native_write": True},
    ],
)
def test_malformed_or_unsupported_request_has_no_save_or_field_effect(tmp_path, patch):
    source = {"choices": choices().model_dump()}
    if isinstance(patch.get("choices"), dict):
        source["choices"].update(patch["choices"])
    else:
        source.update(patch)
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for action in ("preview", "export"):
            response = client.post("/api/heat-pump-wizard/" + action, json=source, headers=headers)
            assert response.status_code == 422, response.text
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]
