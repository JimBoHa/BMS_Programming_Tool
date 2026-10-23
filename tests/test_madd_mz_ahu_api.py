"""Actual authenticated two-deck AHU author/simulate/export/restart flows."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.madd_mz_ahu import PROFILE, PROFILE_SHA, canonical
from bms_tool.models import Program
from fastapi.testclient import TestClient

from tests.test_madd_mz_ahu import choices

PREFIX = "/api/madd-mz-ahu-wizard"


@pytest.mark.parametrize("economizer", ["off", "fixed-drybulb", "differential-drybulb"])
@pytest.mark.parametrize("source_transport", [False, True])
def test_actual_branch_source_preview_simulate_save_revision_restart_original_export(
    tmp_path, monkeypatch, economizer, source_transport
):
    async def forbidden(*args, **kwargs):
        pytest.fail("MADD-MZ authoring attempted field access")

    for name in ("connect", "connect_mstp", "discover", "read", "apply_write", "release"):
        monkeypatch.setattr(Bacnet, name, forbidden)
    body = {"choices": choices(economizer=economizer).model_dump()}
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
        assert report["can_create"] and report["profile_sha256"] == PROFILE_SHA
        assert report["format"] == "bms.madd-mz-ahu-wizard-preview" and report["version"] == 1
        program = Program.model_validate(report["program"])
        assert program.digest() == report["program_sha256"] and len(program.nodes) >= 170
        assert not report["native_compile"] and not report["controller_writes"]
        exported = client.post(PREFIX + "/export", json=body, headers=headers)
        assert exported.content == canonical(report)
        assert hashlib.sha256(exported.content).hexdigest() == exported.headers["X-File-SHA256"]
        simulated = client.post(
            "/api/simulation/step",
            json={
                "program": report["program"],
                "inputs": {"hot_deck_temperature": 83, "cold_deck_temperature": 57},
                "steps": 4,
            },
            headers=headers,
        )
        assert simulated.status_code == 200, simulated.text
        out = simulated.json()["last"]["outputs"]
        assert out["fan_ready"] and out["hot_heating_valve"] > 0
        assert (
            out["cold_cooling_valve"] > 0 if economizer == "off" else out["cold_economizer_active"]
        )
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
        assert client.get("/api/projects/authored-decks").json() == original
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize("gain", [4, 1e6])
def test_actual_units_bind_source_convert_both_deck_absolutes_deltas_and_inverse_gains(
    tmp_path, gain
):
    source = choices(economizer="differential-drybulb", hot_kp=gain, cold_kp=gain).model_dump()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(
            PREFIX + "/units", json={"choices": source, "temperature_unit": "degC"}, headers=headers
        )
        assert result.status_code == 200, result.text
        report = result.json()
        assert report["profile_sha256"] == PROFILE_SHA
        for key in ("source_choices", "choices"):
            assert report[key + "_sha256"] == hashlib.sha256(canonical(report[key])).hexdigest()
        for field in (
            "hot_deck_default",
            "cold_deck_default",
            "hot_deck_setpoint",
            "cold_deck_setpoint",
        ):
            assert report["choices"][field] == pytest.approx((source[field] - 32) * 5 / 9)
        for field in (
            "hot_entry_delta",
            "hot_release_delta",
            "cold_entry_delta",
            "cold_release_delta",
        ):
            assert report["choices"][field] == pytest.approx(source[field] * 5 / 9)
        assert (
            report["choices"]["hot_kp"]
            == report["choices"]["cold_kp"]
            == pytest.approx(gain * 9 / 5)
        )
        assert report["choices"]["proof_seconds"] == source["proof_seconds"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"configuration": "ahu-and-zones"},
        {"fan": "variable-speed"},
        {"return_fan": True},
        {"zone_requests": []},
        {"economizer_control": {}},
        {"hot_kp": 0, "hot_ki": 0},
        {"cold_kp": 0, "cold_ki": 0},
        {"occupied_default": 1},
        {"scan_seconds": True},
        {"startup_timeout_seconds": 4},
    ],
)
def test_unsupported_or_malformed_choices_never_save_or_open_network(tmp_path, mutation):
    body = {"choices": choices().model_dump() | mutation}
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for action in ("preview", "export"):
            result = client.post(PREFIX + "/" + action, json=body, headers=headers)
            assert result.status_code == 422, result.text
        assert client.get("/api/projects").json() == []
        assert not client.get("/api/session").json()["field_network_open"]


def test_actual_good_runtime_sp_inhibition_and_bad_quality_transaction_retention_are_distinct(
    tmp_path,
):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        generated = client.post(
            PREFIX + "/preview", json={"choices": choices().model_dump()}, headers=headers
        ).json()
        program = generated["program"]
        run = client.post(
            "/api/simulation/step",
            json={
                "program": program,
                "inputs": {"hot_deck_temperature": 83, "cold_deck_temperature": 57},
                "steps": 4,
            },
            headers=headers,
        )
        assert run.status_code == 200, run.text
        assert run.json()["last"]["outputs"]["hot_heating_valve"] > 0
        inhibited = client.post(
            "/api/simulation/step",
            json={"program": program, "inputs": {"hot_deck_setpoint": 500}, "steps": 1},
            headers=headers,
        )
        assert inhibited.status_code == 200, inhibited.text
        out = inhibited.json()["last"]["outputs"]
        assert (
            not out["setpoints_valid"]
            and out["hot_heating_valve"] == out["cold_cooling_valve"] == 0
        )
        bad = client.post(
            "/api/simulation/step",
            json={
                "program": program,
                "inputs": {"unit_enable": False, "hot_deck_temperature": {"quality": "unreliable"}},
                "steps": 1,
            },
            headers=headers,
        )
        assert bad.status_code == 422, bad.text
        assert not client.get("/api/session").json()["field_network_open"]
