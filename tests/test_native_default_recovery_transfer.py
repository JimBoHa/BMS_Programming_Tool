"""A previous-value draft requires an independent new guarded native transfer."""

import asyncio
import copy
import struct
import types

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications
from bms_tool.native_default_transfer import DefaultTransferPreview
from bms_tool.native_signal_compiler import SignalCompilerService

from .test_native_applications import NativePeer
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import (
    NativeRouter,
    apply_request,
    controller_storage,
    default_review,
    mutations,
    real_slot,
)
from .test_native_signal_compiler import FIRST


async def recovery_review(link, *, target=None):
    peer, _, _, service, original_target = link
    target = target or original_target
    _, _, _, first_plan = await default_review(link, target=target)
    parent = await service.apply_default(**apply_request(first_plan))
    assert parent["result"]["status"] == "verified", parent
    capture = await service.capture(**target, operation_id="capture-recovery-source")
    prepared = service.default_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    proposal = {
        **prepared["proposal"],
        "recovery_origin_sha256": prepared["origin_sha256"],
    }
    plan = await service.preview_default(
        **target, operation_id="review-recovery-default", **proposal
    )
    # Author the subsequent controller storage outcome independently. The
    # original transfer's storage simulation must not choose the recovery value.
    peer.do_ReinitializeDeviceRequest = types.MethodType(
        NativePeer.do_ReinitializeDeviceRequest, peer
    )
    controller_storage(peer, bits=struct.pack(">f", 42).hex())
    return parent, capture, prepared, proposal, plan


@pytest.mark.parametrize("routed", [False, True])
async def test_previous_effective_value_is_a_new_direct_or_routed_verified_transfer(
    native_link, routed
):
    peer, _, _, service, target = native_link
    transport = proxy = None
    if routed:
        host, port = target["address"].split(":")
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        parent, _, prepared, _, plan = await recovery_review(native_link, target=target)
        assert prepared["previous_effective_value"] == 42.0  # Archive originally had 23.5.
        assert plan["recovery_origin"] == prepared["origin"]
        assert plan["recovery_origin_sha256"] == prepared["origin_sha256"]
        assert plan["compilation"]["selected_edit"]["before_bits"] == "3dcccccd"
        assert plan["compilation"]["selected_edit"]["after_bits"] == "42280000"
        real_slot(peer.files, -5, struct.pack(">f", 17.5))
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        before = copy.deepcopy(peer.files)
        start = len(mutations(peer))
        result = await service.apply_default(**apply_request(plan))
        assert result["result"]["status"] == "verified", result
        assert not result["pending"]
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
        assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
        assert service.storage.load(result["intent"]["backup_id"])[1] == before
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        fields = SignalCompilerService(service.storage).source(
            result["result"]["verification_capture_id"]
        )
        assert next(row for row in fields["fields"] if row["ref"] == FIRST)["effective_value"] == 42
        assert any(row["effective_value"] == 17.5 for row in fields["fields"])
        assert (
            MoiIdentity(peer.files[3]).reader.scalar(MoiIdentity(peer.files[3]).root, 900) == 9.25
        )
        changes = mutations(peer)[start:]
        assert changes.count(("state", "start-restore")) == 1
        assert changes.count(("state", "end-restore")) == 1
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await service.apply_default(**apply_request(plan))
        assert mutations(peer)[start:] == changes
        if proxy:
            assert not proxy.errors and not proxy.clients
            assert len(proxy.requests) == len(proxy.responses)
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("change", ["value", "origin", "parent", "missing-origin"])
async def test_recovery_review_refuses_changed_local_proposal_without_dispatch(native_link, change):
    peer, _, _, service, target = native_link
    _, _, _, proposal, _ = await recovery_review(native_link)
    changed = dict(proposal)
    if change == "value":
        changed["value_text"] = "41"
    elif change == "origin":
        changed["recovery_origin_sha256"] = "0" * 64
    elif change == "parent":
        changed["recovery_parent_receipt"] = "0" * 32
    else:
        del changed["recovery_origin_sha256"]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await service.preview_default(**target, operation_id="reject-recovery-draft", **changed)
    assert peer.events == before


@pytest.mark.parametrize("change", ["selected", "directory", "parent-pending", "parent-backup"])
async def test_recovery_apply_rechecks_fresh_source_and_original_evidence(native_link, change):
    peer, _, store, service, _ = native_link
    parent, _, _, _, plan = await recovery_review(native_link)
    if change == "selected":
        real_slot(peer.files, -10, struct.pack(">f", 19))
    elif change == "directory":
        peer.files[11] += b"changed"
    elif change == "parent-pending":
        with store.connect() as db:
            db.execute(
                "UPDATE application_transfers SET pending=1 WHERE id=?", (parent["intent"]["id"],)
            )
    else:
        folder = service.storage.directory / parent["intent"]["backup_id"]
        files = list(folder.glob("*.bin"))
        assert files
        files[0].write_bytes(b"tampered original")
    before = list(mutations(peer))
    result = await service.apply_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent", result
    assert not result["result"]["may_have_applied"]
    assert mutations(peer) == before
    assert len(service.storage.receipts()) == 1


async def test_uncertain_recovery_is_reconciled_after_restart_without_replay(native_link):
    peer, bacnet, store, service, _ = native_link
    parent, _, prepared, _, plan = await recovery_review(native_link)
    peer.mode = "drop-end"
    outcome = await service.apply_default(**apply_request(plan))
    assert outcome["pending"] and outcome["result"]["status"] == "unknown"
    assert outcome["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
    changes = list(mutations(peer))
    peer.mode = "normal"
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        observed = await restarted.reconcile(
            operation_id="reconcile-recovery-default", receipt_id=outcome["intent"]["id"]
        )
        assert not observed["pending"] and observed["latest_readback"]["status"] == "verified"
        assert observed["result"] == outcome["result"]
        assert observed["intent"]["recovery_origin"] == prepared["origin"]
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        assert mutations(peer) == changes
    finally:
        await restarted.close()


def test_optional_recovery_fields_must_be_paired():
    normal = {
        "operation_id": "strict-recovery-model",
        "address": "127.0.0.1:47808",
        "device": "device,5136",
        "capture_id": "a" * 32,
        "snapshot_sha256": "b" * 64,
        "record_ref": FIRST,
        "encoded_sha256": "c" * 64,
        "value_text": "42",
    }
    assert DefaultTransferPreview(**normal).recovery_parent_receipt is None
    for changed in [
        {"recovery_parent_receipt": "d" * 32},
        {"recovery_origin_sha256": "e" * 64},
        {"recovery_parent_receipt": "bad", "recovery_origin_sha256": "e" * 64},
    ]:
        with pytest.raises(ValueError):
            DefaultTransferPreview(**(normal | changed))
