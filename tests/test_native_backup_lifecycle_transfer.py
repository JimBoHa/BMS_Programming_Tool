"""Archived sources still qualify a new actual UDP transfer and uncertain readback."""

import asyncio
from functools import partial

import pytest
from bms_tool.device_instance import DeviceInstances
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_lifecycle import NativeBackupLifecycle

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_backup_lifecycle import original_bytes, transition
from .test_native_default_transfer import mutations
from .test_native_instance_recovery_transfer import InstanceRouter, apply_request, recovery_review


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("lost_commit", [False, True])
async def test_archived_parent_preview_and_pending_sources_remain_usable_without_replay(
    native_link, routed, lost_commit
):
    peer, bacnet, store, service, target = native_link
    service.instances._collision = partial(DeviceInstances._collision, service.instances)
    transport = proxy = restarted = None
    if routed:
        host, port = target["address"].split(":")
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: InstanceRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        parent, capture, prepared, _, plan, _ = await recovery_review(native_link, target=target)
        original = original_bytes(service.storage)
        library = NativeBackupLifecycle(service.storage)
        before_events = list(peer.events)
        for snapshot in service.storage.captures():
            transition(library, snapshot)
        assert peer.events == before_events and not service.storage.captures()
        assert original_bytes(service.storage) == original
        assert (
            service.instance_recovery.prepare(
                {
                    "receipt_id": parent["intent"]["id"],
                    "capture_id": capture["id"],
                    "snapshot_sha256": capture["snapshot_evidence_sha256"],
                }
            )
            == prepared
        )
        peer.mode = "drop-end" if lost_commit else "normal"
        start = len(mutations(peer))
        result = await service.apply(**apply_request(plan))
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        changes = mutations(peer)[start:]
        assert (
            changes.count(("state", "start-restore"))
            == changes.count(("state", "end-restore"))
            == 1
        )
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        assert result["pending"] is lost_commit
        if lost_commit:
            assert result["result"]["may_have_applied"]
        else:
            assert result["result"]["status"] == "verified", result
        before_archive = list(peer.events)
        for snapshot in service.storage.captures():
            transition(library, snapshot)
        assert peer.events == before_archive
        await service.close()
        restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
        assert restarted.storage.receipt(parent["intent"]["id"]) == parent
        if lost_commit:
            readback = await restarted.reconcile(
                receipt_id=result["intent"]["id"], operation_id="archived-pending-readback"
            )
            assert (
                not readback["pending"] and readback["latest_readback"]["status"] == "verified"
            ), readback
        else:
            assert restarted.storage.receipt(result["intent"]["id"]) == result
        assert [
            row
            for row in mutations(peer)[start:]
            if row[0] == "write" or row[1] in ("start-restore", "end-restore")
        ] == changes
        for relative, value in original.items():
            assert (restarted.storage.directory / relative).read_bytes() == value[0]
        if proxy:
            assert not proxy.errors
            assert [row["candidate"] for row in proxy.discovery_requests] == [
                5336,
                5336,
                5136,
                5136,
            ]
    finally:
        if restarted:
            await restarted.close()
        if transport:
            transport.close()
            await asyncio.sleep(0.02)
