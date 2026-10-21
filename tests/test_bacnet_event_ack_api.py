import asyncio

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_bacnet_event_ack import apply_request, configure_ack_peer, preview_request
from .test_bacnet_events import assert_retired, event, events_device, options
from .test_connections import free_udp


def test_ack_profile_and_receipts_are_local_and_mutations_require_token(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        profile = client.get("/api/bacnet/events/ack/profile").json()
        assert not profile["connected"] and not profile["automatic_retries"]
        assert profile["receipts"] == []
        for operation in ("preview", "apply", "cancel"):
            assert client.post("/api/bacnet/events/ack/" + operation, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post("/api/bacnet/events/ack/preview", json={}, headers=headers).status_code
            == 422
        )
        assert client.get("/api/bacnet/events/ack/receipts/" + "a" * 32).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False


@pytest.mark.asyncio
async def test_actual_udp_api_review_apply_receipt_replay_and_disconnect(tmp_path):
    application = create_app(tmp_path)
    port = free_udp()
    peer = events_device(port, pages={None: ([event()], False)})
    await configure_ack_peer(peer)
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
            assert opened.status_code == 200
            report = (
                await client.post(
                    "/api/bacnet/events/read", json=options(f"127.0.0.1:{port}"), headers=headers
                )
            ).json()
            preview = await client.post(
                "/api/bacnet/events/ack/preview", json=preview_request(report), headers=headers
            )
            assert preview.status_code == 200 and preview.json()["can_apply"], preview.text
            assert not peer.ack_packets
            request = apply_request(preview.json())
            response = await client.post(
                "/api/bacnet/events/ack/apply", json=request, headers=headers
            )
            assert response.status_code == 200 and response.json()["status"] == "accepted", (
                response.text
            )
            receipt = response.json()
            assert len(peer.ack_packets) == 1
            loaded = await client.get("/api/bacnet/events/ack/receipts/" + receipt["id"])
            assert loaded.json() == receipt
            assert (await client.get("/api/bacnet/events/ack/profile")).json()["receipts"][0][
                "id"
            ] == receipt["id"]
            assert (
                await client.post("/api/bacnet/events/ack/apply", json=request, headers=headers)
            ).status_code == 422
            assert len(peer.ack_packets) == 1
            # New exact event, then disconnect after actual write dispatch. No repeat on teardown.
            peer.pages[None][0][0].acknowledgedTransitions = [0, 1, 1]
            report = (
                await client.post(
                    "/api/bacnet/events/read", json=options(f"127.0.0.1:{port}"), headers=headers
                )
            ).json()
            plan = (
                await client.post(
                    "/api/bacnet/events/ack/preview", json=preview_request(report), headers=headers
                )
            ).json()
            peer.ack_mode = "hold"
            peer.ack_entered.clear()
            pending = asyncio.create_task(
                client.post(
                    "/api/bacnet/events/ack/apply", json=apply_request(plan), headers=headers
                )
            )
            await asyncio.wait_for(peer.ack_entered.wait(), 2)
            old_app = application.state.bacnet.app
            disconnected = await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            assert disconnected.status_code == 200
            outcome = (await pending).json()
            assert outcome["status"] == "unknown" and outcome["may_have_applied"]
            assert len(peer.ack_packets) == 2
            assert_retired(application.state.bacnet, old_app)
            assert (
                await client.get("/api/bacnet/events/ack/receipts/" + outcome["id"])
            ).json() == outcome
    finally:
        await application.state.event_ack.close()
        await application.state.event_inventory.close()
        application.state.bacnet.close()
        peer.ack_release.set()
        close_application(peer)
        await asyncio.sleep(0.02)
