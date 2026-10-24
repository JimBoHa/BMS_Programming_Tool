"""Local authenticated API and interface lifecycle for commissioning."""

import asyncio

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_bacnet_events import assert_retired
from .test_connections import free_udp
from .test_device_instance import NEW, apply_request, instance_peer, options

BASE = "/api/bacnet/device-instance"


def test_mutations_require_local_session_and_requests_are_strict(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        status = client.get(BASE + "/status").json()
        assert not status["automatic_retries"] and status["receipts"] == []
        for operation in ("preview", "apply", "readback", "cancel"):
            assert client.post(BASE + "/" + operation, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/preview", json={}, headers=headers).status_code == 422
        assert client.get(BASE + "/receipts/" + "a" * 32).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.asyncio
async def test_actual_api_review_apply_receipt_replay_and_disconnect(tmp_path):
    application = create_app(tmp_path)
    port = free_udp()
    peer = instance_peer(port)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                    headers=headers,
                )
            ).status_code == 200
            plan_response = await client.post(
                BASE + "/preview", json=options(f"127.0.0.1:{port}"), headers=headers
            )
            assert plan_response.status_code == 200, plan_response.text
            assert not peer.wire_writes
            plan = plan_response.json()
            response = await client.post(BASE + "/apply", json=apply_request(plan), headers=headers)
            assert response.status_code == 200 and response.json()["status"] == "verified", (
                response.text
            )
            receipt = response.json()
            assert peer.instance == NEW and len(peer.wire_writes) == 1
            assert (await client.get(BASE + "/receipts/" + receipt["id"])).json()[
                "attempt"
            ] == receipt
            assert (
                await client.post(BASE + "/apply", json=apply_request(plan), headers=headers)
            ).status_code == 422
            observed = await client.post(
                BASE + "/readback",
                json={"operation_id": "api-readback", "receipt_id": receipt["id"]},
                headers=headers,
            )
            assert (
                observed.json()["read_only"]
                and observed.json()["readback"]["status"] == "verified_new"
            )
            # Begin a second attempt against the peer reset for this test only.
            peer.instance, peer.mode = 5136, "hold"
            peer.entered.clear()
            plan = (
                await client.post(
                    BASE + "/preview", json=options(f"127.0.0.1:{port}"), headers=headers
                )
            ).json()
            pending = asyncio.create_task(
                client.post(BASE + "/apply", json=apply_request(plan), headers=headers)
            )
            await asyncio.wait_for(peer.entered.wait(), 4)
            old_app = application.state.bacnet.app
            assert (
                await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            ).status_code == 200
            outcome = (await pending).json()
            assert outcome["status"] == "unknown" and outcome["may_have_applied"]
            assert len(peer.wire_writes) == 2
            assert_retired(application.state.bacnet, old_app)
            assert (await client.get(BASE + "/receipts/" + outcome["id"])).json()[
                "attempt"
            ] == outcome
    finally:
        await application.state.device_instances.close()
        application.state.bacnet.close()
        peer.release.set()
        close_application(peer)
