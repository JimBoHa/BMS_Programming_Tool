"""Local authenticated API and interface lifecycle for commissioning."""

import asyncio
import threading

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_read import close_application
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_bacnet_events import assert_retired
from .test_connections import free_udp
from .test_device_instance import NEW, apply_request, clear_collision, instance_peer, options

BASE = "/api/bacnet/device-instance"


@pytest.mark.asyncio
async def test_http_cancel_executes_on_the_owned_task_event_loop(tmp_path):
    application = create_app(tmp_path)
    loop = asyncio.get_running_loop()
    original_debug, owner = loop.get_debug(), threading.get_ident()
    called = []

    class OwnedTask:
        def cancel(self):
            # Check before mutating a Future, so a wrong-thread regression does
            # not strand a real task after asyncio rejects its wake-up callback.
            assert threading.get_ident() == owner, "Cancellation crossed the task's loop thread"
            called.append(True)

    service = application.state.device_instances
    service._active = {"operation_id": "http-thread-cancel", "task": OwnedTask()}
    loop.set_debug(True)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            response = await client.post(
                BASE + "/cancel", json={"operation_id": "http-thread-cancel"}, headers=headers
            )
            assert response.status_code == 200 and response.json()["cancel_requested"]
            assert called == [True]
    finally:
        service._active = None
        loop.set_debug(original_debug)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_dispatch", "after_dispatch"])
async def test_actual_http_cancel_with_loop_debug_preserves_dispatch_evidence(
    tmp_path, monkeypatch, phase
):
    application = create_app(tmp_path)
    loop = asyncio.get_running_loop()
    original_debug = loop.get_debug()
    peer = instance_peer(free_udp(), "hold")
    # Keep the actual UDP transport's address instead of allocating another port.
    endpoint = str(peer.nsap.local_adapter.adapterAddr)
    service = application.state.device_instances
    monkeypatch.setattr(service, "_collision", clear_collision)
    entered, release = asyncio.Event(), asyncio.Event()
    pending = None
    loop.set_debug(True)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            connected = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            assert connected.status_code == 200
            plan_response = await client.post(
                BASE + "/preview", json=options(endpoint), headers=headers
            )
            assert plan_response.status_code == 200, plan_response.text
            if phase == "before_dispatch":
                app = application.state.bacnet.app
                original_lookup = app.device_info_cache.get_device_info

                async def held_lookup(target):
                    if any(
                        packet.apduService == 15
                        for requests in app._requests.values()
                        for packet, _ in requests
                    ):
                        entered.set()
                        await release.wait()
                    return await original_lookup(target)

                monkeypatch.setattr(app.device_info_cache, "get_device_info", held_lookup)
            request = apply_request(plan_response.json())
            pending = asyncio.create_task(
                client.post(BASE + "/apply", json=request, headers=headers)
            )
            await asyncio.wait_for(
                (entered if phase == "before_dispatch" else peer.entered).wait(), 3
            )
            cancelled = await client.post(
                BASE + "/cancel", json={"operation_id": request["operation_id"]}, headers=headers
            )
            assert cancelled.status_code == 200 and cancelled.json()["cancel_requested"]
            outcome_response = await asyncio.wait_for(pending, 3)
            assert outcome_response.status_code == 200, outcome_response.text
            outcome = outcome_response.json()
            expected_dispatch = phase == "after_dispatch"
            assert outcome["dispatch_started"] is expected_dispatch
            assert outcome["may_have_applied"] is expected_dispatch
            assert outcome["status"] == ("unknown" if expected_dispatch else "not_sent")
            assert len(peer.wire_writes) == int(expected_dispatch)
            loaded = (await client.get(BASE + "/receipts/" + outcome["id"])).json()
            assert loaded["attempt"] == outcome
            assert (loaded["intent"] is not None) is expected_dispatch
            assert service.status()["receipts"][0]["pending"] is expected_dispatch
            release.set()
            await asyncio.sleep(0)
            assert len(peer.wire_writes) == int(expected_dispatch)
            assert_retired(application.state.bacnet)
    finally:
        release.set()
        await service.close()
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        application.state.bacnet.close()
        peer.release.set()
        close_application(peer)
        loop.set_debug(original_debug)


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
