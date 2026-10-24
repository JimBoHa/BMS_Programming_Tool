"""Production local API persistence, source binding and no-field boundaries."""

import copy

from bms_tool.app import create_app
from bms_tool.hardware_workbench import canonical
from fastapi.testclient import TestClient

from tests.test_hardware_workbench_api import offline_report
from tests.test_sensor_supply import plan


def headers(client):
    return {"X-Studio-Token": client.get("/api/session").json()["token"]}


def test_supply_api_save_import_calculate_restart_and_optimistic_guard(tmp_path):
    source = plan()
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        catalog = client.get("/api/sensor-supply/catalog")
        assert catalog.status_code == 200
        assert catalog.json()["catalog"]["sha256"] == source["catalog_sha256"]
        assert client.post("/api/sensor-supply/evaluate", json={"plan": source}).status_code == 403
        validated = client.post("/api/sensor-supply/validate", json={"plan": source}, headers=token)
        assert validated.status_code == 200, validated.text
        source = validated.json()["plan"]
        calculated = client.post(
            "/api/sensor-supply/evaluate", json={"plan": source}, headers=token
        )
        assert calculated.status_code == 200, calculated.text
        assert calculated.json()["status"] == "within-declared-limits"
        saved = client.post(
            "/api/sensor-supply/save", json={"plan": source, "expected_revision": 0}, headers=token
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        assert saved["plan"] == source and saved["revision"] == 1
        assert not client.get("/api/bacnet/status").json()["connected"]
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        assert client.get("/api/sensor-supply/plans").json()[0]["id"] == saved["id"]
        assert client.get("/api/sensor-supply/plans/" + saved["id"]).json() == saved
        conflict = client.post(
            "/api/sensor-supply/save",
            json={"plan": source, "id": saved["id"], "expected_revision": 0},
            headers=token,
        )
        assert conflict.status_code == 409
        assert (
            client.post(
                "/api/sensor-supply/save",
                json={"plan": source, "expected_revision": True},
                headers=token,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/sensor-supply/evaluate", json={"plan": source, "write": True}, headers=token
            ).status_code
            == 422
        )
        assert (
            client.request(
                "DELETE",
                "/api/sensor-supply/plans/" + saved["id"],
                json={"expected_revision": 1},
                headers=token,
            ).status_code
            == 200
        )
        assert client.get("/api/sensor-supply/plans").json() == []
        assert not client.get("/api/bacnet/status").json()["connected"]


def test_source_survey_binding_rejects_stale_hash_and_deleted_report_without_blocking_other_plans(
    tmp_path,
):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        report = client.post(
            "/api/bacnet/hardware/import-report",
            files={"file": ("authored.json", canonical(offline_report()))},
            headers=token,
        )
        assert report.status_code == 200, report.text
        report = report.json()
        bound = plan() | {
            "source_report": {"id": report["id"], "content_sha256": report["content_sha256"]}
        }
        saved = client.post(
            "/api/sensor-supply/save", json={"plan": bound, "expected_revision": 0}, headers=token
        )
        assert saved.status_code == 200, saved.text
        saved = saved.json()
        wrong = copy.deepcopy(bound)
        wrong["source_report"]["content_sha256"] = "0" * 64
        assert (
            client.post(
                "/api/sensor-supply/validate", json={"plan": wrong}, headers=token
            ).status_code
            == 422
        )
        assert (
            client.delete("/api/bacnet/hardware/reports/" + report["id"], headers=token).status_code
            == 200
        )
        assert client.get("/api/sensor-supply/plans/" + saved["id"]).status_code == 422
        listed = client.get("/api/sensor-supply/plans")
        assert listed.status_code == 200 and listed.json()[0]["available"] is False
        assert (
            client.post(
                "/api/sensor-supply/save",
                json={"plan": plan(), "expected_revision": 0},
                headers=token,
            ).status_code
            == 200
        )
        assert (
            client.request(
                "DELETE",
                "/api/sensor-supply/plans/" + saved["id"],
                json={"expected_revision": 1},
                headers=token,
            ).status_code
            == 200
        )
        assert not client.get("/api/bacnet/status").json()["connected"]


def test_import_rejects_forged_catalog_and_profile_before_saved_data_changes(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        wrong = plan()
        wrong["catalog_sha256"] = "0" * 64
        for endpoint in ("validate", "evaluate", "save"):
            payload = {"plan": wrong}
            if endpoint == "save":
                payload["expected_revision"] = 0
            assert (
                client.post(
                    "/api/sensor-supply/" + endpoint, json=payload, headers=token
                ).status_code
                == 422
            )
        assert client.get("/api/sensor-supply/plans").json() == []
