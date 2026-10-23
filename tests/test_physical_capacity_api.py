"""Authenticated offline API, original report hashes and exact survey-host binding."""

import copy

from bms_tool.app import create_app
from bms_tool.hardware_survey import analyze_archive, enrich_report
from bms_tool.hardware_workbench import canonical as survey_bytes
from bms_tool.physical_capacity import canonical, digest
from fastapi.testclient import TestClient

from tests.test_hardware_survey import authored_archive
from tests.test_hardware_workbench_api import offline_report
from tests.test_physical_capacity import request


def headers(client):
    return {"X-Studio-Token": client.get("/api/session").json()["token"]}


def test_api_auth_exact_original_response_and_zero_connection_activity(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        token = headers(client)
        assert client.get("/api/hardware-capacity/catalog").status_code == 200
        body = request("FX-PCX3721-0", ("input-voltage", 1))
        assert client.post("/api/hardware-capacity/review", json=body).status_code == 403
        response = client.post("/api/hardware-capacity/review", json=body, headers=token)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "count-mode-shortfall"
        assert response.content == canonical(result)
        assert (
            digest({k: v for k, v in result.items() if k != "content_sha256"})
            == result["content_sha256"]
        )
        assert result["field_queries"] is False and result["controller_writes"] is False
        assert client.get("/api/bacnet/status").json()["connected"] is False
        body["write"] = True
        assert (
            client.post("/api/hardware-capacity/review", json=body, headers=token).status_code
            == 422
        )


def test_original_stored_survey_binding_explicit_host_stale_deleted_and_import_limits(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        uploaded = client.post(
            "/api/bacnet/hardware/import-report",
            files={
                "file": (
                    "authored.json",
                    survey_bytes(
                        enrich_report(offline_report(), analyze_archive(authored_archive()))
                    ),
                )
            },
            headers=token,
        )
        assert uploaded.status_code == 200, uploaded.text
        report = uploaded.json()
        before = client.get(f"/api/bacnet/hardware/reports/{report['id']}")
        body = request(report["identity"]["model"], ("input-voltage", 1))
        body["survey_reference"] = {
            "id": report["id"],
            "content_sha256": report["content_sha256"],
            "host": "base",
        }
        response = client.post("/api/hardware-capacity/review", json=body, headers=token)
        assert response.status_code == 200, response.text
        binding = response.json()["survey_binding"]
        assert binding["reference"] == body["survey_reference"] | {"sa_mac": None}
        assert (
            binding["imported"]
            and not binding["physical_identity_verified"]
            and not binding["occupancy_applied"]
        )
        module = next(row for row in report["modules"] if row["host"] == "sa")
        body["model"] = module["configured_model"]
        body["survey_reference"].update(host="sa", sa_mac=module["sa_mac"])
        response = client.post("/api/hardware-capacity/review", json=body, headers=token)
        assert response.status_code == 200, response.text
        assert "configured" in response.json()["survey_binding"]["basis"]
        assert client.get(f"/api/bacnet/hardware/reports/{report['id']}").content == before.content
        wrong = copy.deepcopy(body)
        wrong["survey_reference"]["content_sha256"] = "0" * 64
        assert (
            client.post("/api/hardware-capacity/review", json=wrong, headers=token).status_code
            == 422
        )
        wrong = copy.deepcopy(body)
        wrong["model"] = (
            "FX-PCX3721-0" if module["configured_model"] != "FX-PCX3721-0" else "FX-PCX3711-0"
        )
        assert (
            client.post("/api/hardware-capacity/review", json=wrong, headers=token).status_code
            == 422
        )
        wrong = copy.deepcopy(body)
        wrong["survey_reference"]["sa_mac"] = 254
        assert (
            client.post("/api/hardware-capacity/review", json=wrong, headers=token).status_code
            == 422
        )
        assert (
            client.delete(f"/api/bacnet/hardware/reports/{report['id']}", headers=token).status_code
            == 200
        )
        assert (
            client.post("/api/hardware-capacity/review", json=body, headers=token).status_code
            == 422
        )
        body.pop("survey_reference")
        assert (
            client.post("/api/hardware-capacity/review", json=body, headers=token).status_code
            == 200
        )
