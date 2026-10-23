"""Actual local authenticated target authoring, source export and revisions."""

import hashlib
import itertools
import json

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.models import Program
from bms_tool.zone_setpoints import PROFILE, PROFILE_SHA, canonical
from fastapi.testclient import TestClient

from tests.test_zone_setpoints import choices

PREFIX = "/api/zone-setpoint-wizard"


@pytest.mark.parametrize("population,window", list(itertools.product((False, True), repeat=2)))
@pytest.mark.parametrize("source_transport", [False, True])
def test_actual_branch_preview_source_original_export_simulate_revision_and_restart(
    tmp_path, monkeypatch, population, window, source_transport
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Setpoint authoring attempted controller access")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    body = {"choices": choices(population=population, window=window).model_dump()}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        catalog = client.get(PREFIX + "/catalog").json()
        assert catalog["profile"] == PROFILE and catalog["profile_sha256"] == PROFILE_SHA
        for action in ("preview", "export", "units"):
            assert client.post(PREFIX + "/" + action, json=body).status_code == 403
        response = client.post(
            PREFIX + "/preview",
            json=body,
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
        program = Program.model_validate(report["program"])
        assert report["can_create"] and program.digest() == report["program_sha256"]
        assert (
            report["profile_sha256"] == PROFILE_SHA
            and not report["native_compile"]
            and not report["controller_writes"]
        )
        exported = client.post(PREFIX + "/export", json=body, headers=headers)
        assert exported.content == canonical(report)
        assert hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        simulated = client.post(
            "/api/simulation/step",
            json={
                "program": report["program"],
                "inputs": {
                    "scheduled_occupied": True,
                    **({"populated": False} if population else {}),
                    **({"window_open": True} if window else {}),
                },
                "steps": 3,
            },
            headers=headers,
        )
        assert simulated.status_code == 200, simulated.text
        out = simulated.json()["last"]["outputs"]
        assert out["setpoint_profile"] == (3 if window else 2 if population else 1)
        assert out["effective_heating_setpoint"] == (40 if window else 69 if population else 70)
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
        assert client.get("/api/projects/zone-targets").json() == original
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize("offset", [1, 1e-6])
def test_actual_coupled_units_bind_source_convert_all_pairs_and_population_delta(tmp_path, offset):
    value = choices().model_dump()
    value["population_control"]["offset"] = offset
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            PREFIX + "/units", json={"choices": value, "temperature_unit": "degC"}, headers=headers
        )
        assert response.status_code == 200, response.text
        d = response.json()
        assert d["profile_sha256"] == PROFILE_SHA
        for key in ("source_choices", "choices"):
            assert hashlib.sha256(canonical(d[key])).hexdigest() == d[key + "_sha256"]
        assert d["choices"]["occupied_heating_setpoint"] == pytest.approx((70 - 32) * 5 / 9)
        assert d["choices"]["window_control"]["cooling_setpoint"] == pytest.approx(
            (120 - 32) * 5 / 9
        )
        assert d["choices"]["population_control"]["offset"] == pytest.approx(offset * 5 / 9)
        assert d["choices"]["population_control"]["entry_seconds"] == 3


@pytest.mark.parametrize(
    "patch",
    [
        {"population": "off"},
        {"window": "off"},
        {"population_control": None},
        {"window_control": None},
        {"occupied_heating_setpoint": 74},
        {"window_control": {"heating_setpoint": 120}},
        {"population_control": {"offset": 0}},
        {"scheduled_occupied_default": 1},
        {"native_write": True},
        {"demand_limit": 1},
        {"scan_seconds": 7},
    ],
)
def test_unsupported_or_malformed_choice_does_not_save_or_query_network(tmp_path, patch):
    body = {"choices": choices().model_dump() | patch}
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for action in ("preview", "export"):
            response = client.post(PREFIX + "/" + action, json=body, headers=headers)
            assert response.status_code == 422, response.text
        assert (
            client.get("/api/projects").json() == []
            and not client.get("/api/session").json()["field_network_open"]
        )
