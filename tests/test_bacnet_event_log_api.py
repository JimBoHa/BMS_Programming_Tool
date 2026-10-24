import asyncio

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_bacnet_event_log import device, options, retired
from .test_connections import free_udp


def test_event_log_profile_is_local_and_field_reads_and_captures_require_session_token(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        profile = client.get("/api/bacnet/event-log/status").json()
        assert profile["read_only"] and not profile["auto_poll"] and not profile["connected"]
        assert not profile["unsolicited_subscriptions"] and not profile["operator_acknowledgement"]
        assert profile["captures"] == []
        for path in ("read", "cancel", "save"):
            assert client.post("/api/bacnet/event-log/" + path, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/event-log/read",
                json=options("127.0.0.1", object_id="trend-log-multiple,1"),
                headers=headers,
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False


@pytest.mark.asyncio
async def test_event_log_api_reads_native_history_saves_restart_capture_and_disconnects_owned_request(
    tmp_path,
):
    app = create_app(tmp_path)
    port = free_udp()
    server = device(port)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                    headers=headers,
                )
            ).status_code == 200
            response = await client.post(
                "/api/bacnet/event-log/read", json=options(f"127.0.0.1:{port}"), headers=headers
            )
            assert response.status_code == 200 and response.json()["complete"], response.text
            report = response.json()
            assert report["source_kind"] == "device-history-event-log"
            saved = await client.post(
                "/api/bacnet/event-log/save", json={"id": report["id"]}, headers=headers
            )
            assert saved.status_code == 200 and saved.json()["records"] == 5
            restarted = create_app(tmp_path)
            async with AsyncClient(
                transport=ASGITransport(app=restarted), base_url="http://127.0.0.1"
            ) as reader:
                assert (
                    await reader.get("/api/bacnet/event-log/captures/" + report["id"])
                ).json() == report
                assert not (await reader.get("/api/session")).json()["field_network_open"]
            server.behavior = "hold-second"
            server.requests.clear()
            task = asyncio.create_task(
                client.post(
                    "/api/bacnet/event-log/read", json=options(f"127.0.0.1:{port}"), headers=headers
                )
            )
            while len(server.requests) < 2:
                await asyncio.sleep(0.005)
            previous = app.state.bacnet.app
            assert (
                await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            ).status_code == 200
            partial = (await task).json()
            assert partial["status"] == "interface_changed" and len(partial["records"]) == 2
            retired(app.state.bacnet, previous)
    finally:
        await app.state.event_log.close()
        await app.state.multiple_history.close()
        app.state.bacnet.close()
        server.release.set()
        close_application(server)
        await asyncio.sleep(0.02)
