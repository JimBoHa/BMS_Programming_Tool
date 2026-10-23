"""Actual local authenticated AHU author/simulate/export/save/restart workflow."""

import hashlib
import itertools
import json

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.masd_ahu import PROFILE, PROFILE_SHA, canonical
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_masd_ahu import choices

PREFIX = "/api/masd-ahu-wizard"


@pytest.mark.parametrize(
    "fan,economizer",
    list(
        itertools.product(
            ("constant-speed", "variable-speed"), ("off", "fixed-drybulb", "differential-drybulb")
        )
    ),
)
@pytest.mark.parametrize("source_transport", [False, True])
def test_actual_six_branch_source_preview_simulation_revision_restart_and_original_export(
    tmp_path, monkeypatch, fan, economizer, source_transport
):
    async def forbidden(*args, **kwargs):
        pytest.fail("MASD wizard attempted field access")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    source = {"choices": choices(fan=fan, economizer=economizer).model_dump()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get(PREFIX + "/catalog").json()
        assert catalog["profile"] == PROFILE and catalog["profile_sha256"] == PROFILE_SHA
        for action in ("preview", "export", "units"):
            assert client.post(PREFIX + "/" + action, json=source).status_code == 403
        response = client.post(
            PREFIX + "/preview",
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
        assert report["can_create"] and report["profile_sha256"] == PROFILE_SHA
        assert report["format"] == "bms.masd-ahu-wizard-preview" and report["version"] == 1
        program = Program.model_validate(report["program"])
        assert program.digest() == report["program_sha256"]
        assert (
            len(program.nodes) >= 160
            and not report["native_compile"]
            and not report["controller_writes"]
        )
        exported = client.post(PREFIX + "/export", json=source, headers=headers)
        assert (
            exported.content == canonical(report)
            and hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        )
        simulated = client.post(
            "/api/simulation/step",
            json={"program": report["program"], "inputs": {"sat": 58}, "steps": 4},
            headers=headers,
        )
        assert simulated.status_code == 200, simulated.text
        assert simulated.json()["last"]["outputs"]["fan_ready"]
        saved = client.post(
            "/api/projects",
            json={"program": report["program"], "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        original = saved.json()
        assert original["metadata"] == report["program"]["metadata"]
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects/authored-ahu").json() == original
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize("gain", [4, 1e6])
def test_actual_units_bind_source_and_convert_absolute_delta_inverse_gains_without_pressure_conversion(
    tmp_path, gain
):
    source = choices(
        fan="variable-speed", economizer="differential-drybulb", heating_kp=gain
    ).model_dump()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(
            PREFIX + "/units", json={"choices": source, "temperature_unit": "degC"}, headers=headers
        )
        assert result.status_code == 200, result.text
        data = result.json()
        assert (
            data["source_choices_sha256"]
            == hashlib.sha256(canonical(data["source_choices"])).hexdigest()
        )
        assert data["choices_sha256"] == hashlib.sha256(canonical(data["choices"])).hexdigest()
        assert data["choices"]["heating_kp"] == pytest.approx(gain * 9 / 5)
        assert data["choices"]["temperature_band"] == pytest.approx(
            source["temperature_band"] * 5 / 9
        )
        assert data["choices"]["sat_setpoint"] == pytest.approx(
            (source["sat_setpoint"] - 32) * 5 / 9
        )
        assert data["choices"]["variable_fan"] == source["variable_fan"]
        assert data["choices"]["proof_seconds"] == source["proof_seconds"]


@pytest.mark.parametrize(
    "patch",
    [
        {"choices": None},
        {"choices": {"fan": "dual"}},
        {"choices": {"variable_fan": {}}},
        {"choices": {"economizer_control": {}}},
        {"choices": {"occupied_default": 1}},
        {"choices": {"scan_seconds": True}},
        {"choices": {"startup_timeout_seconds": 4}},
        {"native_write": True},
    ],
)
def test_malformed_unsupported_requests_do_not_save_or_open_field_network(tmp_path, patch):
    source = {"choices": choices().model_dump()}
    if isinstance(patch.get("choices"), dict):
        source["choices"].update(patch["choices"])
    else:
        source.update(patch)
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for action in ("preview", "export"):
            response = client.post(PREFIX + "/" + action, json=source, headers=headers)
            assert response.status_code == 422, response.text
        assert (
            client.get("/api/projects").json() == []
            and not client.get("/api/session").json()["field_network_open"]
        )
