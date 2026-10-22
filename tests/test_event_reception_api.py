"""HTTP/session guards and explicit snapshots against real raw UDP events."""

import asyncio

import httpx
import pytest
from bms_tool.app import create_app

from .test_connections import free_udp
from .test_event_reception import RawEvents, notification
from .test_foreign_bacnet import wait_until


@pytest.mark.parametrize("routed", [False, True])
async def test_api_explicit_identity_listener_ack_stop_save_restart_and_export(tmp_path, routed):
    transport, peer = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: RawEvents(routed), local_addr=("127.0.0.1", 0)
    )
    app = create_app(tmp_path)
    identifier = None
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                status = (await client.get("/api/bacnet/event-reception/status")).json()
                assert status["sessions"] == [] and not peer.frames
                token = (await client.get("/api/session")).json()["token"]
                headers = {"X-Studio-Token": token}
                endpoint = f"127.0.0.1:{peer.endpoint[1]}"
                body = dict(
                    address="2001:4" if routed else endpoint,
                    device="device,4190010",
                    process_identifier=7,
                    mode="both",
                    duration_seconds=30,
                )
                if routed:
                    body.update(router=endpoint, dnet=2001)
                assert (
                    await client.post("/api/bacnet/event-reception/start", json=body)
                ).status_code == 403
                assert not peer.frames
                await client.post(
                    "/api/bacnet/connect",
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                    headers=headers,
                )
                response = await client.post(
                    "/api/bacnet/event-reception/start", json=body, headers=headers
                )
                assert response.status_code == 200, response.text
                identifier = response.json()["id"]
                peer.send()
                await wait_until(lambda: len(peer.acks) == 1)
                received = (
                    await client.get(f"/api/bacnet/event-reception/sessions/{identifier}")
                ).json()
                assert (
                    received["received"] == 1
                    and received["events"][0]["operator_acknowledged"] is None
                )
                assert received["events"][0]["apdu_hex"] == notification().hex()
                assert (
                    await client.post(
                        "/api/bacnet/event-reception/save", json={"id": identifier}, headers=headers
                    )
                ).status_code == 422
                await client.post(
                    "/api/bacnet/event-reception/stop", json={"id": identifier}, headers=headers
                )
                saved = await client.post(
                    "/api/bacnet/event-reception/save", json={"id": identifier}, headers=headers
                )
                assert saved.status_code == 200 and saved.json()["saved_sha256"]
                assert not saved.json()["auto_resume"]
                assert (await client.get("/api/bacnet/event-reception/snapshots")).json()[0][
                    "id"
                ] == identifier
                assert not app.state.bacnet.commands and not app.state.event_reception.hooks
        count = len(peer.frames)
        reopened = create_app(tmp_path)
        async with reopened.router.lifespan_context(reopened):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=reopened), base_url="http://testserver"
            ) as client:
                assert (await client.get("/api/bacnet/event-reception/status")).json()[
                    "sessions"
                ] == []
                assert not reopened.state.bacnet.status()["connected"] and len(peer.frames) == count
                saved = (
                    await client.get(f"/api/bacnet/event-reception/snapshots/{identifier}")
                ).json()
                assert saved["received"] == 1 and not saved["active"]
                assert saved["config"]["router"] == (endpoint if routed else None)
                assert (
                    await client.get(f"/api/bacnet/event-reception/sessions/{identifier}")
                ).status_code == 422
    finally:
        transport.close()
        await asyncio.sleep(0.02)
    assert not peer.errors
