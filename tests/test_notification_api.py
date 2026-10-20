"""Actual local HTTP receipts from recorded simulations through the production API."""

import hashlib
import json
import shutil
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from bms_tool.app import create_app
from bms_tool.observability import ObservabilityStore
from fastapi.testclient import TestClient

from tests.test_observation_api import alarm_program, headers, step


@pytest.fixture
def receiver():
    messages = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            messages.append({"raw": raw, "headers": dict(self.headers)})
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/alarms", messages
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Local delivery did not reach the expected durable state.")
        time.sleep(0.01)


def test_actual_alarm_delivery_preserves_event_clock_and_does_not_acknowledge_or_resume_on_restart(
    tmp_path, receiver, monkeypatch
):
    url, received = receiver
    monkeypatch.setenv("BMS_TEST_WEBHOOK_TOKEN", "local-receiver-only")
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        route = client.post(
            "/api/notifications/routes",
            headers=token,
            json={
                "name": "Local receiver",
                "url": url,
                "bearer_env": "BMS_TEST_WEBHOOK_TOKEN",
            },
        )
        assert route.status_code == 200, route.text
        route_id = route.json()["id"]
        assert route.json()["enabled"] is False
        first = step(client, token, clock="2026-01-05T00:00:00Z")
        source, session = first["recording_source"], first["session"]
        assert client.post("/api/notifications/cycle", headers=token, json={}).status_code == 200
        assert received == []
        enabled = client.post(
            "/api/notifications/routes/enable",
            headers=token,
            json={"route_id": route_id, "enabled": True},
        )
        assert enabled.status_code == 200
        result = client.post("/api/notifications/cycle", headers=token, json={"limit": 20})
        assert result.status_code == 200, result.text
        wait_for(lambda: len(received) == 1)
        payload = json.loads(received[0]["raw"])
        assert payload["source_kind"] == "simulation"
        event = client.get("/api/observations/events", params={"source": source}).json()[0]
        assert payload["event"] == event
        assert payload["event"]["clock"] != payload["event"]["recorded_at"]
        assert received[0]["headers"]["Authorization"] == "Bearer local-receiver-only"
        assert (
            received[0]["headers"]["X-BMS-Payload-SHA256"]
            == hashlib.sha256(received[0]["raw"]).hexdigest()
        )
        alarm = client.get("/api/observations/alarms").json()[0]
        assert alarm["active"] and not alarm["acknowledged"]
        page = client.get("/api/notifications/deliveries").json()
        delivery = client.get(f"/api/notifications/deliveries/{page['rows'][0]['id']}").json()
        assert delivery["state"] == "delivered" and delivery["payload"] == payload
        assert delivery["payload_integrity"]
        assert received[0]["headers"]["Idempotency-Key"] == delivery["idempotency_key"]
        assert "local-receiver-only" not in json.dumps(
            {"page": page, "route": route.json(), "delivery": delivery}
        )
        # The real background worker delivers later alarm events, without a manual pass.
        step(client, token, session=session, temperature=70)
        wait_for(lambda: len(received) == 2)
        assert json.loads(received[1]["raw"])["event"]["event"] == "returned"
        wait_for(lambda: client.get("/api/notifications/status").json()["counts"]["delivered"] == 2)
        assert not client.get("/api/session").json()["field_network_open"]
    with TestClient(create_app(tmp_path)) as restarted:
        token = headers(restarted)
        assert restarted.get("/api/notifications/status").json()["active_routes"] == 0
        assert not restarted.get("/api/notifications/routes").json()[0]["enabled"]
        before = len(received)
        step(restarted, token)
        restarted.post("/api/notifications/cycle", headers=token, json={})
        assert len(received) == before
        rows = restarted.get("/api/notifications/deliveries").json()["rows"]
        assert all(row["state"] == "delivered" for row in rows)
        removed = restarted.post(
            "/api/notifications/prune",
            headers=token,
            json={"through_id": rows[-1]["id"], "limit": 1000},
        )
        assert removed.status_code == 200 and removed.json()["removed"] == 2
        assert restarted.get("/api/observations/alarms").json()[0]["acknowledged"] is False


def test_new_route_defaults_to_future_events_and_http_guards_cannot_send(tmp_path, receiver):
    url, received = receiver
    with TestClient(create_app(tmp_path)) as client:
        token = headers(client)
        first = step(client, token, clock="2026-01-05T00:00:00Z")
        assert (
            client.post("/api/notifications/routes", json={"name": "bad", "url": url}).status_code
            == 403
        )
        assert (
            client.post(
                "/api/notifications/routes",
                headers={**token, "Origin": "https://other.example"},
                json={"name": "bad", "url": url},
            ).status_code
            == 403
        )
        for body in (
            {"url": "http://user:password@example.test"},
            {"url": "file:///tmp/not-http"},
            {"url": url, "start_after": True},
            {"url": url, "events": ["fabricated"]},
        ):
            response = client.post(
                "/api/notifications/routes", headers=token, json={"name": "invalid", **body}
            )
            assert response.status_code == 422, response.text
        route = client.post(
            "/api/notifications/routes", headers=token, json={"name": "Future only", "url": url}
        ).json()
        assert route["cursor"] == 1
        client.post(
            "/api/notifications/routes/enable",
            headers=token,
            json={"route_id": route["id"], "enabled": True},
        )
        client.post("/api/notifications/cycle", headers=token, json={})
        assert not received
        assert (
            client.post(
                "/api/notifications/routes/enable",
                headers=token,
                json={"route_id": route["id"], "enabled": 1},
            ).status_code
            == 422
        )
        assert (
            client.post("/api/notifications/cycle", headers=token, json={"limit": True}).status_code
            == 422
        )
        step(client, token, session=first["session"], temperature=70)
        client.post("/api/notifications/cycle", headers=token, json={})
        wait_for(lambda: len(received) == 1)
        assert json.loads(received[0]["raw"])["event"]["event"] == "returned"
        assert not client.get("/api/session").json()["field_network_open"]


def test_outbox_source_mismatch_does_not_block_other_programming_features_or_erase_routes(tmp_path):
    directory = tmp_path / "workspace"
    with TestClient(create_app(directory)) as client:
        response = client.post(
            "/api/notifications/routes",
            headers=headers(client),
            json={"name": "Retain original evidence", "url": "http://127.0.0.1:1/unused"},
        )
        assert response.status_code == 200
    replacement = ObservabilityStore(tmp_path / "different-stream")
    shutil.copyfile(replacement.db, directory / "observability.sqlite3")
    with TestClient(create_app(directory)) as client:
        token = headers(client)
        status = client.get("/api/notifications/status").json()
        assert not status["available"] and not status["active_routes"]
        assert "unavailable" in status["worker_error"]
        assert client.get("/api/notifications/routes").json() == []
        assert client.get("/api/notifications/deliveries").json()["rows"] == []
        refused = client.post(
            "/api/notifications/routes",
            headers=token,
            json={"name": "Do not replace evidence", "url": "http://127.0.0.1:1/unused"},
        )
        assert refused.status_code == 422
        assert client.post("/api/validate", headers=token, json=alarm_program()).status_code == 200
        assert not client.get("/api/session").json()["field_network_open"]
    with sqlite3.connect(directory / "notifications" / "notification_outbox.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM notification_routes").fetchone()[0] == 1
