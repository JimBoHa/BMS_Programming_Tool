"""Bounded object-list pages retain actual UDP results after a later failure."""

import asyncio

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_connections import application, free_udp, point


@pytest.mark.asyncio
async def test_object_pages_use_real_indices_without_silent_500_entry_limit(tmp_path):
    port = free_udp()
    server = application(port, 4190074)
    server.add_object(point())
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        first = await client.objects(target, "device,4190074", limit=2)
        second = await client.objects(target, "device,4190074", offset=2, limit=2)
        assert first["complete"] and first["truncated"] and first["next_offset"] == 2
        assert second["complete"] and not second["truncated"]
        assert second["next_offset"] is None and first["total"] == second["total"] == 3
        assert [row["index"] for row in first["objects"] + second["objects"]] == [1, 2, 3]
        assert len({row["object"] for row in first["objects"] + second["objects"]}) == 3
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_object_page_deadline_retains_prior_entries_and_retires_wire_transaction(tmp_path):
    port = free_udp()
    server = application(port, 4190075)
    server.add_object(point())
    original, release = server.do_ReadPropertyRequest, asyncio.Event()

    async def slow(request):
        if str(request.propertyIdentifier) == "object-list" and request.propertyArrayIndex == 2:
            await release.wait()
        await original(request)

    server.do_ReadPropertyRequest = slow
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{port}"
        await client.discover(target)
        report = await client.objects(target, "device,4190075", limit=3, timeout_seconds=1.0)
        assert len(report["objects"]) == 1 and report["objects"][0]["index"] == 1
        assert not report["complete"] and report["next_offset"] == 1
        assert "timed out" in report["error"]
        assert not client.app.asap.clientTransactions and not client.app._requests
    finally:
        release.set()
        client.close()
        await asyncio.sleep(0.05)
        server.close()


@pytest.mark.asyncio
async def test_changed_live_list_is_explicitly_incomplete_instead_of_a_complete_snapshot(tmp_path):
    port = free_udp()
    server = application(port, 4190076)
    server.add_object(point())
    original = server.do_ReadPropertyRequest

    async def changed(request):
        await original(request)
        if str(request.propertyIdentifier) == "object-list" and request.propertyArrayIndex == 1:
            extra = point()
            extra.objectIdentifier = ("analog-value", 2)
            extra.objectName = "Added during inventory"
            server.add_object(extra)

    server.do_ReadPropertyRequest = changed
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        report = await client.objects(f"127.0.0.1:{port}", "device,4190076", limit=2)
        assert len(report["objects"]) == 2 and not report["complete"]
        assert "length changed" in report["error"]
    finally:
        client.close()
        server.close()
        await asyncio.sleep(0.05)


def test_object_page_http_bounds_and_real_udp_indices(tmp_path):
    port = free_udp()
    with TestClient(create_app(tmp_path)) as client:
        server = client.portal.call(application, port, 4190077)
        try:
            headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
            assert (
                client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                ).status_code
                == 200
            )
            payload = {"address": f"127.0.0.1:{port}", "object_id": "device,4190077", "limit": 1}
            page = client.post("/api/bacnet/objects", headers=headers, json=payload)
            assert page.status_code == 200
            assert page.json()["objects"][0]["index"] == 1 and page.json()["next_offset"] == 1
            for key, value in [
                ("limit", 201),
                ("offset", -1),
                ("offset", True),
                ("timeout_seconds", 31),
            ]:
                assert (
                    client.post(
                        "/api/bacnet/objects", headers=headers, json={**payload, key: value}
                    ).status_code
                    == 422
                )
            assert client.post("/api/bacnet/objects", json=payload).status_code == 403
        finally:
            client.portal.call(server.close)
