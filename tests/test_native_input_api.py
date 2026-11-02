"""Local native-input copies cannot acquire field transfer authority."""

import copy

from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity
from fastapi.testclient import TestClient

from .test_native_inputs import allocation, source

BASE = "/api/bacnet/controller/native-application"


def test_retained_native_input_source_and_export_work_without_an_interface(tmp_path):
    app = create_app(tmp_path)
    service = app.state.native_applications
    files = source()
    capture = service.storage.save(
        {
            "target": {"address": "127.0.0.1:47999", "router": None, "dnet": None},
            "device": "device,5136",
            "identity": {"device": "device,5136", "object-name": "Authored controller"},
            "source_identity_matches": True,
            "connector_config": {},
        },
        files,
    )
    options = {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/input/source", json=options).status_code == 403
        listed = client.get(BASE + "/input/sources").json()
        assert listed["controller_queries"] is listed["controller_writes"] is False
        assert listed["sources"][0]["capture_id"] == capture["id"]
        read = client.post(BASE + "/input/source", headers=headers, json=options)
        assert read.status_code == 200 and read.json()["available_slots"] == [1, 2, 3]
        request = {**options, "edit": allocation()}
        review = client.post(BASE + "/input/copy/preview", headers=headers, json=request)
        assert review.status_code == 200, review.text
        r = review.json()
        assert "token" not in r and r["controller_writes"] is False
        assert (
            client.post(BASE + "/input/copy/export", headers=headers, json=request).status_code
            == 422
        )
        output = client.post(
            BASE + "/input/copy/export",
            headers=headers,
            json={**request, "expected_review_sha256": r["review_sha256"]},
        )
        assert output.status_code == 200
        assert len(MoiIdentity(output.content).records) == len(MoiIdentity(files[3]).records) + 1
        changed = copy.deepcopy(request)
        changed["edit"]["slot"] = 2
        assert (
            client.post(
                BASE + "/input/copy/export",
                headers=headers,
                json={**changed, "expected_review_sha256": r["review_sha256"]},
            ).status_code
            == 422
        )
        assert (
            client.post(
                BASE + "/input/source",
                headers=headers,
                json={**options, "snapshot_sha256": "0" * 64},
            ).status_code
            == 422
        )
        assert service.storage.load(capture["id"])[1] == files
        assert not service.plans and not service.storage.receipts()
        assert client.get("/api/session").json()["field_network_open"] is False


def test_native_input_apply_requires_exact_typed_confirmations(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            BASE + "/input/apply",
            headers=headers,
            json={
                "operation_id": "authored-input-apply",
                "token": "A" * 32,
                "review_sha256": "a" * 64,
                "physical_wiring_confirmed": "true",
                "input_change_confirmed": True,
                "application_transfer_confirmed": True,
            },
        )
        assert response.status_code == 422
        assert not app.state.native_applications.storage.receipts()
