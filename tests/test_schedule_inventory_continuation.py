"""An explicit cursor resumes discovery, not unseen object fields or old requests."""

import asyncio

import pytest
from bms_tool.connections import Bacnet
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_schedule_inventory import make_peer, options, retired, verify_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("index", [1, 4])
@pytest.mark.parametrize("interruption", ["deadline", "cancel"])
async def test_explicit_continuation_preserves_zero_or_partial_progress_and_source(
    tmp_path, routed, index, interruption
):
    peer = await make_peer(routed=routed)
    client = Bacnet(Store(tmp_path))
    service = ScheduleInventory(
        client,
        client.store,
        timeout=0.5,
        operation_timeout=3,
        request_gap=0,
    )
    service.operation_timeout = 0.15 if interruption == "deadline" else 3
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        peer.hold_reference = ("device,42", "object-list", index)
        task = asyncio.create_task(service.read(**options(peer, object_ids=None)))
        await asyncio.wait_for(peer.entered.wait(), 1)
        if interruption == "cancel":
            service.cancel("schedule_test_operation")
        report = await task
        assert report["status"] == ("timeout" if interruption == "deadline" else "cancelled")
        assert report["identity_verified"] and not report["complete"]
        assert report["inventory"]["next_offset"] == index - 1
        assert [row["array_index"] for row in report["inventory"]["entries"]] == list(
            range(1, index)
        )
        assert not report["inventory"]["complete"] and report["objects"] == []
        assert report["target"] == {
            key: options(peer)[key] for key in ("address", "device", "router", "dnet")
        }
        verify_hash(report)
        retired(client)
        before = list(peer.requests)
        await asyncio.sleep(0.02)
        assert peer.requests == before
        peer.hold_reference = None
        peer.release.set()
        service.operation_timeout = 3
        resumed = await service.read(
            **options(
                peer,
                operation_id="explicit_continuation_read",
                object_ids=None,
                object_list_offset=report["inventory"]["next_offset"],
            )
        )
        assert resumed["inventory"]["entries"][0]["array_index"] == index
        assert resumed["target"] == report["target"]
        assert resumed["inventory"]["next_offset"] is None
        assert resumed["complete"] is (index == 1)
        assert {obj["object"] for obj in resumed["objects"]} == (
            {"calendar,1", "schedule,1", "calendar,2"}
            if index == 1
            else {"schedule,1", "calendar,2"}
        )
        verify_hash(resumed)
        retired(client)
        if index == 4:
            # The earlier page identified calendar,1 without inspecting its fields.
            # A separate explicit selection reads it; continuation never claims it did.
            remaining = await service.read(
                **options(peer, operation_id="explicit_unread_object", object_ids=["calendar,1"])
            )
            assert remaining["complete"] and [obj["object"] for obj in remaining["objects"]] == [
                "calendar,1"
            ]
            verify_hash(remaining)
            retired(client)
        assert not peer.errors
    finally:
        await service.close()
        client.close()
        peer.close()
