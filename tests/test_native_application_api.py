"""Local API admission and credential confidentiality for connected native work."""

from bms_tool.app import create_app
from fastapi.testclient import TestClient

BASE = "/api/bacnet/controller/native-application"


def test_session_token_required_and_credentials_are_never_returned(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"X-Studio-Token": token}
        body = {"backup": "test-backup-private", "restore": "test-restore-private"}
        assert client.post(BASE + "/credentials", json=body).status_code == 403
        saved = client.post(BASE + "/credentials", headers=headers, json=body)
        assert saved.status_code == 200 and saved.json() == {"configured": True}
        status = client.get(BASE + "/status")
        assert status.json()["credentials_configured"]
        assert all(secret not in status.text + saved.text for secret in body.values())
        bad = "private-credential-too-long" * 10
        rejected = client.post(
            BASE + "/credentials", headers=headers, json={**body, "restore": bad}
        )
        assert rejected.status_code == 422 and bad not in rejected.text
        assert (
            client.post(
                BASE + "/capture",
                headers=headers,
                json={
                    "operation_id": "read-only-capture",
                    "address": "127.0.0.1:47808",
                    "device": "device,5136",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                BASE + "/apply",
                headers=headers,
                json={
                    "operation_id": "native-apply",
                    "token": "A" * 32,
                    "review_sha256": "a" * 64,
                    "allocation_confirmed": True,
                    "application_transfer_confirmed": True,
                },
            ).status_code
            == 422
        )
        assert not app.state.native_applications.storage.receipts()


def test_connected_instance_service_blocks_on_unresolved_native_intent(tmp_path):
    app = create_app(tmp_path)
    native = app.state.native_applications
    intent = {
        "id": "a" * 32,
        "target": {"address": "127.0.0.1:47808", "router": None, "dnet": None},
        "old_instance": 5136,
        "new_instance": 5336,
        "identity": {},
        "connector_config": {},
    }
    native.storage.intent(intent)
    import pytest

    with pytest.raises(ValueError, match="retained native"):
        app.state.device_instances._available(intent["target"])
