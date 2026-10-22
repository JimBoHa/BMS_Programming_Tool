"""Session guards, actual UDP reads and byte-exact native evidence exports."""

import asyncio
import json

import pytest
from bms_tool.app import create_app
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_schedule_inventory import make_peer, options, verify_hash


def test_profile_restart_and_session_guards(tmp_path):
    for _ in range(2):
        with TestClient(create_app(tmp_path)) as client:
            profile = client.get("/api/bacnet/schedules/profile").json()
            assert profile["read_only"] and not profile["auto_query"] and not profile["reports"]
            assert not client.get("/api/session").json()["field_network_open"]
            assert (
                client.post(
                    "/api/bacnet/schedules/cancel", json={"operation_id": "pending_operation"}
                ).status_code
                == 403
            )
            assert (
                client.post("/api/bacnet/schedules/export", json={"id": "a" * 32}).status_code
                == 403
            )
            headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
            assert (
                client.post(
                    "/api/bacnet/schedules/read",
                    json={
                        "operation_id": "read_no_interface",
                        "address": "127.0.0.1",
                        "device": "device,42",
                    },
                    headers=headers,
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/bacnet/schedules/read",
                    json={
                        "operation_id": "invalid_selection",
                        "address": "127.0.0.1",
                        "device": "device,42",
                        "object_ids": ["analog-input,1"],
                    },
                    headers=headers,
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/bacnet/schedules/export", json={"id": "a" * 32}, headers=headers
                ).status_code
                == 422
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
async def test_actual_native_api_export_is_exact_body_hash_and_reopen_has_no_queries(
    tmp_path, routed
):
    application = create_app(tmp_path)
    peer = await make_peer(routed=routed)
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
            response = await client.post(
                "/api/bacnet/schedules/read", json=options(peer), headers=headers
            )
            assert response.status_code == 200, response.text
            report = response.json()
            assert report["complete"]
            verify_hash(report)
            count = len(peer.requests)
            copied = await client.get("/api/bacnet/schedules/reports/" + report["id"])
            assert copied.json() == report
            exported = await client.post(
                "/api/bacnet/schedules/export", json={"id": report["id"]}, headers=headers
            )
            assert (
                exported.status_code == 200
                and "attachment;" in exported.headers["content-disposition"]
            )
            assert b'"value":-0.0' in exported.content and b'"value":2.0' in exported.content
            verify_hash(json.loads(exported.content))
            assert (
                exported.content
                == json.dumps(
                    report, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            assert len(peer.requests) == count
    finally:
        await application.state.schedule_inventory.close()
        application.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


@pytest.mark.asyncio
async def test_api_owned_cancel_and_shutdown_stop_pending_exchange(tmp_path):
    application = create_app(tmp_path)
    peer = await make_peer(routed=True, behavior="hold")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            pending = asyncio.create_task(
                client.post("/api/bacnet/schedules/read", json=options(peer), headers=headers)
            )
            await asyncio.wait_for(peer.entered.wait(), 1)
            response = await client.post(
                "/api/bacnet/schedules/cancel",
                json={"operation_id": "schedule_test_operation"},
                headers=headers,
            )
            assert response.json()["cancel_requested"]
            report = (await pending).json()
            assert report["status"] == "cancelled"
            assert (
                not application.state.bacnet.app._requests
                and not application.state.bacnet.app.asap.clientTransactions
            )
            verify_hash(report)
    finally:
        await application.state.schedule_inventory.close()
        application.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)
