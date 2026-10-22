"""Actual loopback read/write API admission, sealed bytes and offline restart."""

import asyncio
import hashlib

import pytest
from bms_tool.app import create_app
from bms_tool.native_schedule_library import encoded
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_native_schedule_write import WeeklyPeer
from .test_schedule_inventory import options

PREFIX = "/api/bacnet/schedules/writes"
LIBRARY = "/api/bacnet/schedules/library"


@pytest.mark.parametrize("routed", [False, True])
async def test_authenticated_actual_udp_preview_apply_original_receipt_and_restart_reconcile(
    tmp_path, routed
):
    peer = WeeklyPeer(routed=routed)
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    application = create_app(tmp_path)
    service = application.state.schedule_writes
    service.timeout, service.operation_timeout, service.request_gap = 0.1, 5, 0
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            token = (await client.get("/api/session")).json()["token"]
            headers = {"X-Studio-Token": token}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            report = await client.post(
                "/api/bacnet/schedules/read",
                headers=headers,
                json=options(peer, object_ids=["schedule,1"]),
            )
            assert report.status_code == 200 and report.json()["complete"]
            capture = await client.post(
                LIBRARY + "/save", headers=headers, json={"id": report.json()["id"]}
            )
            assert capture.status_code == 200
            reviewed = await client.post(
                LIBRARY + "/drafts/review",
                headers=headers,
                json={
                    "capture_id": capture.json()["id"],
                    "object_id": "schedule,1",
                    "day": 3,
                    "transitions": [
                        {"time": [8, 0, 0, 0], "native_type": "Real", "value_text": "-0.0"},
                        {"time": [17, 30, 0, 0], "native_type": "Null", "value_text": "null"},
                    ],
                },
            )
            assert reviewed.status_code == 200, reviewed.text
            prepared = await client.post(
                PREFIX + "/preview",
                headers=headers,
                json={
                    "operation_id": "api_preview_1",
                    "draft_id": reviewed.json()["id"],
                    "operator_name": "Declared operator",
                    "rationale": "Authored two-transition day",
                },
            )
            assert prepared.status_code == 200 and prepared.json()["can_apply"], prepared.text
            plan = prepared.json()
            assert b'"value":-0.0' in prepared.content and not peer.writes
            request = {
                "operation_id": "api_apply_1",
                "token": plan["token"],
                "review_sha256": plan["review_sha256"],
            }
            assert (await client.post(PREFIX + "/apply", json=request)).status_code == 403
            applied = await client.post(PREFIX + "/apply", headers=headers, json=request)
            assert applied.status_code == 200, applied.text
            result = applied.json()
            assert result["protocol_accepted"] and result["readback"]["status"] == "match", result
            assert len(peer.writes) == 1 and peer.writes[0][0] == 3
            assert b'"value":-0.0' in applied.content
            assert (
                result["evidence_sha256"]
                == hashlib.sha256(
                    encoded({k: v for k, v in result.items() if k != "evidence_sha256"})
                ).hexdigest()
            )
            exported = await client.get(PREFIX + "/receipts/" + result["id"])
            assert (
                exported.content == applied.content
                and "attachment;" in exported.headers["content-disposition"]
            )
            assert (
                await client.post(PREFIX + "/apply", headers=headers, json=request)
            ).status_code == 422
            assert len(peer.writes) == 1
            assert (
                await client.post("/api/bacnet/disconnect", headers=headers, json={})
            ).status_code == 200
        restarted = create_app(tmp_path)
        restarted.state.schedule_writes.timeout = 0.1
        restarted.state.schedule_writes.request_gap = 0
        before = len(peer.requests), len(peer.writes)
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.get(PREFIX + "/receipts/" + result["id"])
            ).content == applied.content
            assert (await client.get(PREFIX + "/profile")).json()["journal"]["records"][0][
                "id"
            ] == result["id"]
            assert before == (len(peer.requests), len(peer.writes))
            assert not (await client.get("/api/session")).json()["field_network_open"]
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            reconciled = await client.post(
                PREFIX + "/reconcile",
                headers=headers,
                json={"operation_id": "api_reconcile_1", "receipt_id": result["id"]},
            )
            assert reconciled.status_code == 200, reconciled.text
            assert (
                reconciled.json()["read_only"]
                and reconciled.json()["readback"]["status"] == "match"
            )
            assert len(peer.writes) == 1 and not peer.errors
            await client.post("/api/bacnet/disconnect", headers=headers, json={})
    finally:
        await service.close()
        await application.state.schedule_inventory.close()
        application.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.02)


def test_no_auto_traffic_authentication_strict_inputs_and_unavailable_receipts(tmp_path):
    application = create_app(tmp_path)
    with TestClient(application) as client:
        assert not client.get("/api/session").json()["field_network_open"]
        assert client.get(PREFIX + "/profile").json()["journal"]["records"] == []
        for route in ("preview", "apply", "cancel", "reconcile"):
            assert client.post(PREFIX + "/" + route, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for route in ("preview", "apply", "cancel", "reconcile"):
            assert client.post(PREFIX + "/" + route, headers=headers, json={}).status_code == 422
        for id in ("bad", "a" * 32):
            assert client.get(PREFIX + "/receipts/" + id).status_code == 422
        for extra in ({"address": "127.0.0.1"}, {"priority": 8}, {"day": 0}, {"retry": True}):
            body = {
                "operation_id": "typed_apply",
                "token": "a" * 32,
                "review_sha256": "b" * 64,
                **extra,
            }
            assert client.post(PREFIX + "/apply", headers=headers, json=body).status_code == 422
        assert not application.state.schedule_writes.plans
        assert not client.get("/api/session").json()["field_network_open"]
