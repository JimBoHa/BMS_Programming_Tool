"""Retire only owned volatile calculations without modifying saved observations."""

from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from tests.test_observation_api import alarm_program
from tests.test_simulation_clock_api import timer_program


def ownership(receipt):
    return {
        "session": receipt["session"],
        "retirement_token": receipt["retirement_token"],
        "creation_operation_id": receipt["session_creation_operation_id"],
    }


def start(client, headers, operation="a" * 32, **changes):
    response = client.post(
        "/api/simulation/step",
        json={"program": timer_program(), "operation_id": operation, **changes},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_owned_retirement_is_idempotent_and_another_session_keeps_its_retained_state(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        first = start(client, headers)
        second = start(client, headers, "b" * 32, session=first["session"])
        assert ownership(first) == ownership(second)
        assert second["operation_id"] == "b" * 32
        another = start(client, headers, "c" * 32)
        assert client.get("/api/simulation/sessions/status").json()["cached_sessions"] == 2
        for changes in [
            {"retirement_token": "z" * 32},
            {"creation_operation_id": "d" * 32},
            {"retirement_token": another["retirement_token"]},
        ]:
            rejected = client.post(
                "/api/simulation/retire", json=ownership(first) | changes, headers=headers
            )
            assert rejected.status_code == 422, rejected.text
            assert client.get("/api/simulation/sessions/status").json()["cached_sessions"] == 2
        assert client.post("/api/simulation/retire", json=ownership(first)).status_code == 403
        retired = client.post("/api/simulation/retire", json=ownership(first), headers=headers)
        assert retired.status_code == 200, retired.text
        assert retired.json()["retired"] and retired.json()["recorded_evidence_unchanged"]
        again = client.post("/api/simulation/retire", json=ownership(first), headers=headers)
        assert again.status_code == 200 and not again.json()["retired"]
        expired = client.post(
            "/api/simulation/step",
            json={"program": timer_program(), "session": first["session"]},
            headers=headers,
        )
        assert expired.status_code == 422 and "expired" in expired.json()["detail"]
        continued = start(client, headers, "e" * 32, session=another["session"])
        assert continued["last"]["time"] == 0.5
        assert client.get("/api/simulation/sessions/status").json() == {
            "cached_sessions": 1,
            "limit": 25,
            "idle_expiry_seconds": 3600,
        }
        assert not client.get("/api/session").json()["field_network_open"]


def test_more_than_forty_create_retire_cycles_leave_no_cached_calculation(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for index in range(45):
            value = start(client, headers, f"{index:032x}")
            assert value["last"]["time"] == 0.25
            retired = client.post("/api/simulation/retire", json=ownership(value), headers=headers)
            assert retired.status_code == 200 and retired.json()["retired"]
            assert client.get("/api/simulation/sessions/status").json()["cached_sessions"] == 0
        assert client.get("/api/observations/sources").json() == []


def test_retirement_preserves_exact_trends_active_alarms_events_and_source_lifecycle(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        receipt = start(
            client,
            headers,
            program=alarm_program(),
            inputs={"temperature": 90},
            record=True,
        )
        source = receipt["recording_source"]
        paths = [
            "/api/observations/status",
            "/api/observations/sources",
            "/api/observations/alarms",
            "/api/observations/events",
            "/api/observations/trends?source=" + source,
        ]
        before = {path: client.get(path).json() for path in paths}
        assert before["/api/observations/alarms"][0]["active"]
        retired = client.post("/api/simulation/retire", json=ownership(receipt), headers=headers)
        assert retired.status_code == 200 and retired.json()["retired"]
        assert {path: client.get(path).json() for path in paths} == before
    with TestClient(create_app(tmp_path)) as client:
        assert {path: client.get(path).json() for path in paths} == before


def test_legacy_callers_receive_retirement_ownership_and_invalid_requests_keep_capacity(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        legacy = client.post(
            "/api/simulation/step", json={"program": timer_program()}, headers=headers
        ).json()
        assert legacy["operation_id"] is None
        assert legacy["session_creation_operation_id"] is None
        body = ownership(legacy)
        for changes in [
            {"session": "../invalid"},
            {"retirement_token": "short"},
            {"creation_operation_id": "Z" * 32},
            {"retirement_token": True},
            {"unexpected": True},
        ]:
            rejected = client.post(
                "/api/simulation/retire", json=deepcopy(body) | changes, headers=headers
            )
            assert rejected.status_code == 422
        assert client.get("/api/simulation/sessions/status").json()["cached_sessions"] == 1
        retired = client.post("/api/simulation/retire", json=body, headers=headers)
        assert retired.status_code == 200 and retired.json()["retired"]


def test_status_expires_only_idle_sessions_without_changing_the_host_event_loop_clock(
    tmp_path, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(
        import_module("bms_tool.app"), "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        old = start(client, headers)
        clock[0] = 200.0
        newer = start(client, headers, "b" * 32)
        clock[0] = 3701.0
        assert client.get("/api/simulation/sessions/status").json()["cached_sessions"] == 1
        missing = client.post("/api/simulation/retire", json=ownership(old), headers=headers)
        assert missing.status_code == 200 and not missing.json()["retired"]
        continued = start(client, headers, "c" * 32, session=newer["session"])
        assert continued["last"]["time"] == 0.5
        assert ownership(continued) == ownership(newer)
