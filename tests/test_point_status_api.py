import asyncio
import json

import pytest
from bms_tool.app import create_app
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_point_status import make_point_peer, options
from .test_schedule_inventory import verify_hash


def test_local_profile_and_session_guards_leave_interfaces_closed(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        state = client.get("/api/bacnet/point-status/profile").json()
        assert state["read_only"] and not state["auto_poll"] and not state["reports"]
        assert not client.get("/api/session").json()["field_network_open"]
        assert (
            client.post(
                "/api/bacnet/point-status/cancel", json={"operation_id": "blocked_operation"}
            ).status_code
            == 403
        )
        assert (
            client.post("/api/bacnet/point-status/export", json={"id": "a" * 32}).status_code == 403
        )
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/point-status/read",
                headers=headers,
                json={
                    "address": "127.0.0.1",
                    "device": "device,42",
                    "operation_id": "no_interface_read",
                    "object_ids": ["analog-input,1"],
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/bacnet/point-status/read",
                headers=headers,
                json={
                    "address": "127.0.0.1",
                    "device": "device,42",
                    "operation_id": "bad_object_read",
                    "object_ids": ["schedule,1"],
                },
            ).status_code
            == 422
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
async def test_api_reads_native_quality_and_byte_exact_priority_json(tmp_path, routed):
    app = create_app(tmp_path)
    peer = await make_point_peer(routed=routed)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            response = await client.post(
                "/api/bacnet/point-status/read",
                headers=headers,
                json=options(peer, include_commandable=True),
            )
            assert response.status_code == 200, response.text
            report = response.json()
            assert report["complete"]
            verify_hash(report)
            count = len(peer.requests)
            exported = await client.post(
                "/api/bacnet/point-status/export", headers=headers, json={"id": report["id"]}
            )
            assert (
                exported.status_code == 200
                and b'"value":-0.0' in exported.content
                and b'"value":2.0' in exported.content
            )
            assert (
                exported.content
                == json.dumps(
                    report, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            assert (
                await client.get("/api/bacnet/point-status/reports/" + report["id"])
            ).json() == report
            assert len(peer.requests) == count
            # Restart creates no job/report; no hidden durable interpretation.
            fresh = create_app(tmp_path)
            assert fresh.state.point_status.status()["reports"] == []
            await fresh.state.point_status.close()
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)
