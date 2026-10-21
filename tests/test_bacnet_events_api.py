import asyncio

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_bacnet_events import assert_retired, continuation, events_device, options
from .test_connections import free_udp


def test_event_profile_has_no_field_side_effects_and_mutations_require_session_token(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        profile = client.get("/api/bacnet/events/profile").json()
        assert profile["read_only"] and not profile["auto_poll"] and not profile["connected"]
        request = options("127.0.0.1:47808")
        assert client.post("/api/bacnet/events/read", json=request).status_code == 403
        assert (
            client.post(
                "/api/bacnet/events/cancel", json={"operation_id": request["operation_id"]}
            ).status_code
            == 403
        )
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post("/api/bacnet/events/read", json=request, headers=headers).status_code == 422
        )
        invalid = request | {"device": "device,4194303"}
        assert (
            client.post("/api/bacnet/events/read", json=invalid, headers=headers).status_code == 422
        )
        cancelled = client.post(
            "/api/bacnet/events/cancel",
            json={"operation_id": request["operation_id"]},
            headers=headers,
        )
        assert cancelled.status_code == 200 and not cancelled.json()["cancel_requested"]
        assert client.get("/api/session").json()["field_network_open"] is False


@pytest.mark.asyncio
async def test_api_reads_real_native_event_pages_and_disconnect_cancels_owned_exchange(tmp_path):
    application = create_app(tmp_path)
    port = free_udp()
    peer = events_device(port)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            opened = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            assert opened.status_code == 200, opened.text
            address = f"127.0.0.1:{port}"
            first = await client.post(
                "/api/bacnet/events/read", json=options(address), headers=headers
            )
            assert first.status_code == 200, first.text
            assert first.json()["source_kind"] == "bacnet-get-event-information"
            second = await client.post(
                "/api/bacnet/events/read",
                json=options(address, **continuation(first.json())),
                headers=headers,
            )
            assert second.status_code == 200 and second.json()["complete"]
            assert len(second.json()["events"]) == 2
            replay = await client.post(
                "/api/bacnet/events/read",
                json=options(address, **continuation(first.json())),
                headers=headers,
            )
            assert replay.status_code == 422
            peer.behavior = "hold"
            peer.entered.clear()
            pending = asyncio.create_task(
                client.post("/api/bacnet/events/read", json=options(address), headers=headers)
            )
            await asyncio.wait_for(peer.entered.wait(), 2)
            old_app = application.state.bacnet.app
            disconnected = await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            assert disconnected.status_code == 200
            report = (await pending).json()
            assert report["outcome"] == "interface_changed" and report["status"] == "interrupted"
            assert_retired(application.state.bacnet, old_app)
    finally:
        await application.state.event_inventory.close()
        application.state.bacnet.close()
        peer.release.set()
        close_application(peer)
        await asyncio.sleep(0.02)
