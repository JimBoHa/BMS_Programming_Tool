"""Native record HTTP reads stay local and enforce the capture's route/configuration."""

import hashlib

import pytest
from bms_tool.app import create_app
from fastapi.testclient import TestClient

from .test_moi_identity import source

BASE = "/api/bacnet/controller/application"


@pytest.fixture
def records_client(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    data = source(modules=3, compressed=True)
    config = {"local_address": "127.0.0.1:49140", "router": "127.0.0.1:49141", "dnet": 3001}
    target = {
        "address": "3001:8",
        "device": "device,5136",
        "router": config["router"],
        "dnet": 3001,
    }
    receipt = {
        "id": "a" * 32,
        "target": {"address": target["address"], "device": target["device"]},
        "connector_config": config,
        "sha256": hashlib.sha256(data).hexdigest(),
        "received_at": "2026-01-05T12:00:00Z",
    }
    app.state.bacnet.config = dict(config)
    monkeypatch.setattr(
        app.state.controller_application.files, "capture_data", lambda _: (receipt, data)
    )
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        yield client, headers, {**target, "capture_id": receipt["id"]}, app


def test_token_required_and_record_property_pages_retain_source_without_connecting(records_client):
    client, headers, body, _ = records_client
    assert client.post(BASE + "/records", json=body).status_code == 403
    response = client.post(BASE + "/records", headers=headers, json={**body, "limit": 2})
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["recognized_record_count"] == 5 and len(page["records"]) == 2
    assert page["profile"] == "controller-native-records/1"
    assert page["target"]["router"] == body["router"] and page["target"]["dnet"] == 3001
    assert page["read_only"] and not page["identity_verified"] and not page["field_actions"]
    detail_body = {**body, "record_id": page["records"][0]["id"], "limit": 2}
    detail = client.post(BASE + "/record", headers=headers, json=detail_body).json()
    assert detail["capture_id"] == page["capture_id"] and detail["sha256"] == page["sha256"]
    assert len(detail["properties"]) == 2 and detail["next_offset"] == 2
    assert client.get("/api/session").json()["field_network_open"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"offset": True},
        {"offset": -1},
        {"limit": 129},
        {"limit": 0},
        {"query": "x" * 257},
    ],
)
def test_record_queries_are_strict_and_bounded(records_client, changes):
    client, headers, body, _ = records_client
    assert (
        client.post(BASE + "/records", headers=headers, json={**body, **changes}).status_code == 422
    )


@pytest.mark.parametrize("record_id", ["another:1", "record:-1", "record:999999999", "record:0"])
def test_unknown_or_malformed_record_selection_is_rejected(records_client, record_id):
    client, headers, body, _ = records_client
    response = client.post(BASE + "/record", headers=headers, json={**body, "record_id": record_id})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "changes", [{"router": "127.0.0.1:49142"}, {"address": "3001:9"}, {"device": "device,5137"}]
)
def test_another_controller_route_cannot_read_the_capture(records_client, changes):
    client, headers, body, _ = records_client
    assert (
        client.post(BASE + "/records", headers=headers, json={**body, **changes}).status_code == 422
    )


def test_reopening_another_interface_retires_local_record_access(records_client):
    client, headers, body, app = records_client
    app.state.bacnet.config = {**app.state.bacnet.config, "local_address": "127.0.0.1:49143"}
    response = client.post(BASE + "/records", headers=headers, json=body)
    assert response.status_code == 422 and "different controller" in response.text
