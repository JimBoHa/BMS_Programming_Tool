"""A missing current pin requires qualified original proof and a new owned-UDP restore."""

import asyncio
import struct

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications

from .test_moi_wire_sources import REF, A, B
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, mutations, real_slot
from .test_native_wire_recovery import FANOUT
from .test_native_wire_recovery_transfer import recovery_review
from .test_native_wire_transfer import applying


@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("index", [0, 1])
async def test_verified_original_pin_supports_only_one_new_restore_and_preserves_fresh_values(
    native_link, diagram_class, routed, index
):
    peer, _, _, native, target = native_link
    transport = proxy = None
    if routed:
        host, port = target["address"].rsplit(":", 1)
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        parent, prepared, _, plan = await recovery_review(
            native_link, index=index, target=target, diagram_class=diagram_class, wires=FANOUT[:2]
        )
        assert prepared["profile"] == "native-historical-pin-wire-recovery-draft/1"
        assert (
            plan["compilation"]["historical_pin_evidence_sha256"]
            == prepared["origin"]["historical_pin_sha256"]
        )
        real_slot(peer.files, 0, struct.pack(">f", 45))
        start = len(mutations(peer))
        child = await native.apply_wire(**applying(plan))
        assert child["result"]["status"] == "verified" and not child["pending"], child
        assert child["intent"]["id"] != parent["intent"]["id"]
        assert child["intent"]["recovery_origin"] == prepared["origin"]
        assert native.storage.receipt(parent["intent"]["id"]) == parent
        image = MoiIdentity(peer.files[3])
        assert image.instance == 5136
        assert image.reader.diagram(REF)["connections"][index]["source_ref"] == (
            A if index == 0 else B
        )
        assert image.reader.scalar(image.reader.records[A], 3113) == 45
        assert image.reader.scalar(image.reader.records[B], 3113) == 17
        changed = mutations(peer)[start:]
        assert (
            changed.count(("state", "start-restore"))
            == changed.count(("state", "end-restore"))
            == 1
        )
        assert all(row[1] == 3 for row in changed if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await native.apply_wire(**applying(plan))
        assert mutations(peer)[start:] == changed
        if proxy:
            assert not proxy.errors
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


async def test_recorded_pin_can_reconcile_child_after_restart_without_grandparent_files_or_replay(
    native_link,
):
    peer, bacnet, store, native, _ = native_link
    parent, _, _, plan = await recovery_review(native_link, wires=FANOUT[:2])
    peer.mode = "drop-end"
    child = await native.apply_wire(**applying(plan))
    assert child["pending"] and child["result"]["status"] == "unknown"
    (native.storage.directory / parent["intent"]["backup_id"] / "file-12.bin").unlink()
    before = list(mutations(peer))
    peer.mode = "normal"
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        observed = await restarted.reconcile(
            operation_id="historical-pin-readback", receipt_id=child["intent"]["id"]
        )
        assert not observed["pending"] and observed["latest_readback"]["status"] == "verified", (
            observed
        )
        assert observed["result"] == child["result"]
        assert observed["latest_readback"]["preservation"]["selected_wire"]["source_ref"] == A
        assert mutations(peer) == before
    finally:
        await restarted.close()


async def test_recovering_a_verified_historical_pin_child_reconstructs_its_own_original_payload(
    native_link,
):
    _, _, _, native, target = native_link
    _, _, _, plan = await recovery_review(native_link, wires=FANOUT[:2])
    child = await native.apply_wire(**applying(plan))
    assert child["result"]["status"] == "verified", child
    capture = await native.capture(**target, operation_id="capture-pin-child-recovery")
    report = native.wire_recovery.prepare(
        {
            "receipt_id": child["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    assert report["profile"] == "native-wire-source-recovery-draft/1"
    assert report["proposal"]["source_ref"] == B
    assert report["origin"]["parent_receipt_id"] == child["intent"]["id"]
