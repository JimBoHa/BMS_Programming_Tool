import asyncio

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_bacnet_history_multiple import device, options, retired
from .test_connections import free_udp


def test_multiple_history_local_profile_token_checks_and_empty_inventory(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        profile = client.get("/api/bacnet/history-multiple/status").json()
        assert profile["read_only"] and not profile["auto_poll"] and not profile["connected"]
        assert profile["captures"] == []
        for path in ("read", "cancel", "save"):
            assert client.post("/api/bacnet/history-multiple/" + path, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/history-multiple/read", json=options("127.0.0.1"), headers=headers
            ).json()["status"]
            == "failed"
        )
        assert (
            client.post(
                "/api/bacnet/history-multiple/read",
                json=options("127.0.0.1", object_id="trend-log,1"),
                headers=headers,
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False


@pytest.mark.asyncio
async def test_actual_multiple_api_save_restart_and_disconnect_partial_capture(tmp_path):
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
            result = await client.post(
                "/api/bacnet/history-multiple/read",
                json=options(f"127.0.0.1:{port}"),
                headers=headers,
            )
            assert result.status_code == 200 and result.json()["complete"], result.text
            report = result.json()
            saved = await client.post(
                "/api/bacnet/history-multiple/save", json={"id": report["id"]}, headers=headers
            )
            assert saved.status_code == 200 and saved.json()["records"] == 5
            assert (
                await client.get("/api/bacnet/history-multiple/captures/" + report["id"])
            ).json() == report
            restarted = create_app(tmp_path)
            async with AsyncClient(
                transport=ASGITransport(app=restarted), base_url="http://127.0.0.1"
            ) as reader:
                assert (
                    await reader.get("/api/bacnet/history-multiple/captures/" + report["id"])
                ).json() == report
                assert not (await reader.get("/api/session")).json()["field_network_open"]
            server.behavior = "hold-second"
            server.requests.clear()
            pending = asyncio.create_task(
                client.post(
                    "/api/bacnet/history-multiple/read",
                    json=options(f"127.0.0.1:{port}"),
                    headers=headers,
                )
            )
            while len(server.requests) < 2:
                await asyncio.sleep(0.005)
            old_app = app.state.bacnet.app
            disconnected = await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            assert disconnected.status_code == 200
            interrupted = (await pending).json()
            assert interrupted["status"] == "interface_changed" and len(interrupted["records"]) == 2
            retired(app.state.bacnet, old_app)
    finally:
        await app.state.multiple_history.close()
        app.state.bacnet.close()
        server.release.set()
        close_application(server)
        await asyncio.sleep(0.02)
