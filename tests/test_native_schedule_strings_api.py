"""Native String profile authority and original HTTP exports over real loopback UDP."""

import asyncio
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.native_schedule_library import STRING_DRAFT_PROFILE, encoded
from bms_tool.native_schedule_write import STRING_PROFILE
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from tests.test_connections import free_udp
from tests.test_native_schedule_strings import string_request, stringtag
from tests.test_native_schedule_strings import string_source as string_source_fixture
from tests.test_native_schedule_write import WeeklyPeer
from tests.test_schedule_inventory import options

api_string_source = string_source_fixture

LIBRARY = "/api/bacnet/schedules/library"
WRITES = "/api/bacnet/schedules/writes"


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_actual_string_http_wire_apply_exact_exports_restart_and_readonly_reconcile(
    tmp_path, routed
):
    peer = WeeklyPeer(routed=routed)
    peer.exception_count = 0
    peer.days = [bytes.fromhex("0eb408000000") + stringtag("old") + b"\x0f"] * 7
    peer.overrides.update(
        {("schedule,1", p, None): stringtag("old") for p in ("schedule-default", "present-value")}
    )
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    application = create_app(tmp_path)
    service = application.state.schedule_writes
    service.timeout, service.operation_timeout, service.request_gap = 0.1, 5, 0
    restarted = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            response = await client.post(
                "/api/bacnet/schedules/read",
                headers=headers,
                json=options(peer, object_ids=["schedule,1"]),
            )
            assert response.status_code == 200 and response.json()["complete"], response.text
            capture = (
                await client.post(
                    LIBRARY + "/save", headers=headers, json={"id": response.json()["id"]}
                )
            ).json()
            args = string_request(
                capture,
                [
                    {
                        "time": [8, 0, 0, 0],
                        "native_type": "CharacterString",
                        "value_text": '\x00\r\né"\\',
                    }
                ],
            )
            assert (await client.post(LIBRARY + "/drafts/review", json=args)).status_code == 403
            reviewed = await client.post(LIBRARY + "/drafts/review", headers=headers, json=args)
            assert reviewed.status_code == 200, reviewed.text
            draft = reviewed.json()
            assert draft["profile"] == STRING_DRAFT_PROFILE
            exported = await client.post(
                LIBRARY + "/drafts/export", headers=headers, json={"id": draft["id"]}
            )
            assert exported.content == encoded(draft)
            plan_response = await client.post(
                WRITES + "/preview",
                headers=headers,
                json={
                    "operation_id": "api_string_preview",
                    "draft_id": draft["id"],
                    "operator_name": "Declared operator",
                    "rationale": "Local String test",
                },
            )
            assert plan_response.status_code == 200 and plan_response.json()["can_apply"], (
                plan_response.text
            )
            plan = plan_response.json()
            assert plan["profile"] == STRING_PROFILE
            apply = {
                "operation_id": "api_string_apply",
                "token": plan["token"],
                "review_sha256": plan["review_sha256"],
            }
            assert (await client.post(WRITES + "/apply", json=apply)).status_code == 403
            applied = await client.post(WRITES + "/apply", headers=headers, json=apply)
            assert applied.status_code == 200, applied.text
            receipt = applied.json()
            assert receipt["protocol_accepted"] and receipt["readback"]["status"] == "match"
            assert (
                receipt["evidence_sha256"]
                == hashlib.sha256(
                    encoded({k: v for k, v in receipt.items() if k != "evidence_sha256"})
                ).hexdigest()
            )
            assert (
                await client.get(WRITES + "/receipts/" + receipt["id"])
            ).content == applied.content
            assert len(peer.writes) == 1
            assert (
                await client.post(WRITES + "/apply", headers=headers, json=apply)
            ).status_code == 422
            await client.post("/api/bacnet/disconnect", headers=headers, json={})
        restarted = create_app(tmp_path)
        restarted.state.schedule_writes.timeout = 0.1
        restarted.state.schedule_writes.request_gap = 0
        count = len(peer.requests)
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.get(WRITES + "/receipts/" + receipt["id"])
            ).content == applied.content
            assert (
                len(peer.requests) == count
                and not (await client.get("/api/session")).json()["field_network_open"]
            )
            await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            reconciled = await client.post(
                WRITES + "/reconcile",
                headers=headers,
                json={"operation_id": "api_string_reconcile", "receipt_id": receipt["id"]},
            )
            assert reconciled.status_code == 200, reconciled.text
            assert reconciled.json()["profile"] == STRING_PROFILE and reconciled.json()["read_only"]
            assert (
                reconciled.json()["readback"]["status"] == "match"
                and len(peer.writes) == 1
                and not peer.errors
            )
            await client.post("/api/bacnet/disconnect", headers=headers, json={})
    finally:
        for app in (application, restarted):
            if app is not None:
                await app.state.schedule_writes.close()
                await app.state.schedule_inventory.close()
                app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("value", ["\ud800", "🌡" * 65])
def test_http_bad_string_is_422_without_queries_or_writes(tmp_path, api_string_source, value):
    application = create_app(tmp_path)
    capture = application.state.schedule_library._store(api_string_source, "imported")
    with TestClient(application, raise_server_exceptions=False) as client:
        headers = {
            "X-Studio-Token": client.get("/api/session").json()["token"],
            "Content-Type": "application/json",
        }
        args = string_request(
            capture, [{"time": [0, 0, 0, 0], "native_type": "CharacterString", "value_text": value}]
        )
        response = client.post(
            LIBRARY + "/drafts/review",
            headers=headers,
            content=json.dumps(args, ensure_ascii=True).encode(),
        )
        assert response.status_code == 422, response.text
        assert not client.get("/api/session").json()["field_network_open"]
        assert not client.get(WRITES + "/profile").json()["journal"]["records"]
