"""Actual direct/routed Calendar HTTP transfer and strict closed-interface admission."""

import asyncio

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.native_calendar_write import PROFILE

from .test_connections import free_udp
from .test_native_calendar_write import DATE, NEW, CalendarPeer
from .test_schedule_inventory import options

BASE = "/api/bacnet/calendars/writes"


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_full_http_preview_single_apply_exact_receipt_and_read_only_reconcile(
    tmp_path, routed
):
    peer = CalendarPeer(routed=routed)
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    app = create_app(tmp_path)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            response = await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                "/api/bacnet/schedules/read",
                headers=headers,
                json=options(peer, object_ids=["calendar,1"]),
            )
            assert response.status_code == 200 and response.json()["complete"], response.text
            response = await client.post(
                "/api/bacnet/schedules/library/save",
                headers=headers,
                json={"id": response.json()["id"]},
            )
            assert response.status_code == 200, response.text
            draft = {
                "capture_id": response.json()["id"],
                "object_id": "calendar,1",
                "entries": [DATE],
            }
            local = await client.post(
                "/api/bacnet/schedules/library/calendar/review", headers=headers, json=draft
            )
            assert local.status_code == 200, local.text
            body = {
                "operation_id": "http_preview_calendar",
                "draft": draft,
                "expected_review_id": local.json()["id"],
                "operator_name": "Authored HTTP Operator",
                "rationale": "Authored Calendar HTTP test",
            }
            count = len(peer.requests)
            assert (await client.post(BASE + "/preview", json=body)).status_code == 403
            assert (
                await client.post(
                    BASE + "/preview",
                    headers=headers,
                    json={**body, "target": {"address": "192.0.2.99"}},
                )
            ).status_code == 422
            assert len(peer.requests) == count and not peer.writes
            preview = await client.post(BASE + "/preview", headers=headers, json=body)
            assert preview.status_code == 200 and preview.json()["can_apply"], preview.text
            preview = preview.json()
            apply = {
                "operation_id": "http_apply_calendar",
                "token": preview["token"],
                "review_sha256": preview["review_sha256"],
            }
            assert (await client.post(BASE + "/apply", json=apply)).status_code == 403
            actual = await client.post(BASE + "/apply", headers=headers, json=apply)
            assert actual.status_code == 200, actual.text
            receipt = actual.json()
            assert receipt["protocol_accepted"] and receipt["readback"]["status"] == "match"
            exported = await client.get(BASE + "/receipts/" + receipt["id"])
            assert exported.status_code == 200 and exported.content == actual.content
            assert (
                await client.post(BASE + "/apply", headers=headers, json=apply)
            ).status_code == 422
            reconciled = await client.post(
                BASE + "/reconcile",
                headers=headers,
                json={"operation_id": "http_reconcile_calendar", "receipt_id": receipt["id"]},
            )
            assert reconciled.status_code == 200, reconciled.text
            assert (
                reconciled.json()["writes_sent"] == 0
                and reconciled.json()["readback"]["status"] == "match"
            )
            assert (
                peer.writes == [NEW]
                and (await client.get(BASE + "/receipts/" + receipt["id"])).content
                == actual.content
            )
            profile = (await client.get(BASE + "/profile")).json()
            assert profile["profile"] == PROFILE and profile["automatic_retries"] is False
            assert profile["journal"]["records"][0]["id"] == receipt["id"]
            assert (
                await client.post("/api/bacnet/disconnect", headers=headers, json={})
            ).status_code == 200
            assert (
                await client.post(BASE + "/preview", headers=headers, json=body)
            ).status_code == 422
            assert not (await client.get("/api/session")).json()["field_network_open"]
    finally:
        await app.state.calendar_writes.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.01)
        assert not peer.errors


async def test_strict_closed_interface_routes_and_passive_missing_receipts(tmp_path):
    app = create_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
        assert (
            await client.post(
                BASE + "/apply",
                headers=headers,
                json={"operation_id": 123, "token": "x" * 32, "review_sha256": "0" * 64},
            )
        ).status_code == 422
        assert (
            await client.post(
                BASE + "/cancel",
                headers=headers,
                json={"operation_id": "closed_calendar", "apply": True},
            )
        ).status_code == 422
        cancelled = await client.post(
            BASE + "/cancel", headers=headers, json={"operation_id": "closed_calendar"}
        )
        assert cancelled.status_code == 200 and cancelled.json()["cancel_requested"] is False
        assert (await client.get(BASE + "/receipts/" + "0" * 32)).status_code == 422
        assert not (await client.get("/api/session")).json()["field_network_open"]
        assert app.state.calendar_writes.journal.status()["records"] == []


async def test_http_cancel_retires_an_owned_held_preview_on_its_event_loop(tmp_path):
    peer = CalendarPeer()
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    app = create_app(tmp_path)
    pending = entered = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            response = await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                "/api/bacnet/schedules/read",
                headers=headers,
                json=options(peer, object_ids=["calendar,1"]),
            )
            assert response.status_code == 200 and response.json()["complete"], response.text
            response = await client.post(
                "/api/bacnet/schedules/library/save",
                headers=headers,
                json={"id": response.json()["id"]},
            )
            assert response.status_code == 200, response.text
            draft = {
                "capture_id": response.json()["id"],
                "object_id": "calendar,1",
                "entries": [DATE],
            }
            response = await client.post(
                "/api/bacnet/schedules/library/calendar/review", headers=headers, json=draft
            )
            assert response.status_code == 200, response.text
            body = {
                "operation_id": "http_cancel_preview",
                "draft": draft,
                "expected_review_id": response.json()["id"],
                "operator_name": "Authored HTTP Operator",
                "rationale": "Owned cancellation qualification",
            }
            peer.hold_property = "date-list"
            peer.entered.clear()
            pending = asyncio.create_task(
                client.post(BASE + "/preview", headers=headers, json=body)
            )
            entered = asyncio.create_task(peer.entered.wait())
            done, _ = await asyncio.wait(
                {pending, entered}, timeout=2, return_when=asyncio.FIRST_COMPLETED
            )
            assert entered in done and peer.entered.is_set(), (
                pending.result().text
                if pending.done()
                else "Held Calendar request did not reach peer"
            )
            cancelled = await client.post(
                BASE + "/cancel", headers=headers, json={"operation_id": body["operation_id"]}
            )
            assert cancelled.status_code == 200 and cancelled.json()["cancel_requested"] is True
            retired = await pending
            assert retired.status_code == 200 and retired.json()["status"] == "cancelled"
            assert not retired.json()["can_apply"] and not peer.writes
            assert retired.json()["fresh"]["pending_read"]["property"] == "date-list"
            assert (
                await client.post("/api/bacnet/disconnect", headers=headers, json={})
            ).status_code == 200
    finally:
        for task in (pending, entered):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await app.state.calendar_writes.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.01)
        assert not peer.errors
