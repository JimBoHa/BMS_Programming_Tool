"""Actual native dispatch evidence must distinguish handoff from missing replies."""

import asyncio
from datetime import datetime

import pytest
from bms_tool.connections import Bacnet
from bms_tool.native_schedule_library import NativeScheduleLibrary, encoded
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_schedule_inventory import make_peer, options


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize("missing", [False, True], ids=["complete", "missing-exception"])
async def test_actual_read_handoff_and_missing_exception_remain_independent(
    tmp_path, routed, missing
):
    peer = await make_peer(routed=routed)
    reference = ("schedule,1", "exception-schedule", 1)
    if missing:
        peer.drop_reference = reference
    client = Bacnet(Store(tmp_path / "peer"))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.2, operation_timeout=5, request_gap=0
    )
    try:
        report = await inventory.read(**options(peer))
        assert not peer.errors
        assert peer.requests.count(reference) == 1  # no retry after a dropped reply
        row = report["objects"][1]["properties"]["exception-schedule"]["elements"][0]
        timing = row["request_diagnostics"]
        assert timing["request_timeout_seconds"] == 0.2
        assert "preparation" in timing["timeout_basis"]
        assert "not socket transmit" in timing["basis"]
        assert datetime.fromisoformat(timing["dispatch_handoff_at"]).tzinfo is not None
        assert datetime.fromisoformat(timing["finished_at"]).tzinfo is not None
        assert 0 <= timing["dispatch_handoff_elapsed_ms"] <= timing["elapsed_ms"]
        assert timing["matching_transport_candidate"] is (not missing)
        assert timing["source_filter_rejections"] == 0
        assert row["status"] == ("timeout" if missing else "ok")
        assert bool(row.get("transport_evidence")) is (not missing)
        assert report["complete"] is (not missing)
        source = encoded(report)
        library = NativeScheduleLibrary(tmp_path / "library")
        detail = library._store(source, "imported")
        assert library.source(detail["id"]) == source
        assert detail["objects"][0]["eligible"] is (not missing)
        if missing:
            assert detail["objects"][0]["issues"]
            with pytest.raises(ValueError):
                library.review(
                    capture_id=detail["id"], object_id="schedule,1", day=1, transitions=[]
                )
            assert not library.reviews
        assert not client.app.asap.clientTransactions
    finally:
        await inventory.close()
        client.close()
        peer.close()
        await asyncio.sleep(0.01)


async def test_preparation_failure_has_no_claimed_dispatch_or_receive(tmp_path, monkeypatch):
    peer = await make_peer()
    client = Bacnet(Store(tmp_path / "peer"))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.2, operation_timeout=5, request_gap=0
    )

    async def unavailable(*args, **kwargs):
        raise RuntimeError("Deliberately unavailable native device cache.")

    monkeypatch.setattr(client.app.asap.device_info_cache, "get_device_info", unavailable)
    try:
        report = await inventory.read(**options(peer))
        row = report["device_identity"]
        assert row["status"] == "protocol_error"
        assert "unavailable native device cache" in row["error"]
        timing = row["request_diagnostics"]
        assert timing["dispatch_handoff_at"] is None
        assert timing["dispatch_handoff_elapsed_ms"] is None
        assert timing["matching_transport_candidate"] is False
        assert timing["elapsed_ms"] >= 0
        assert not report["identity_verified"] and not report["complete"]
        assert not peer.requests and not peer.errors
        assert not client.app.asap.clientTransactions
    finally:
        await inventory.close()
        client.close()
        peer.close()
        await asyncio.sleep(0.01)
