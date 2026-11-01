"""A previous Boolean value requires its own confirmed native restore and full readback."""

import asyncio
import struct
import types

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications
from bms_tool.native_boolean_transfer import BooleanTransferPreview

from .test_native_applications import NativePeer
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_boolean_copies import FIRST, SECOND
from .test_native_boolean_transfer import boolean_review, boolean_slot, storage_outcome
from .test_native_default_transfer import NativeRouter, apply_request, mutations, real_slot


def apply_recovery(plan):
    return apply_request(plan) | {"operation_id": "apply-boolean-recovery"}


async def recovery_review(link, *, ref=FIRST, target=None):
    peer, _, _, service, original_target = link
    target = target or original_target
    after = ref == SECOND
    _, _, _, original_review = await boolean_review(link, ref=ref, value=after, target=target)
    parent = await service.apply_boolean_default(**apply_request(original_review))
    assert parent["result"]["status"] == "verified", parent
    capture = await service.capture(**target, operation_id="capture-boolean-recovery")
    prepared = service.boolean_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    proposal = {**prepared["proposal"], "recovery_origin_sha256": prepared["origin_sha256"]}
    review = await service.preview_boolean_default(
        **target, **proposal, operation_id="review-boolean-recovery"
    )
    peer.do_ReinitializeDeviceRequest = types.MethodType(
        NativePeer.do_ReinitializeDeviceRequest, peer
    )
    storage_outcome(peer, ref=ref, value=not after)
    return parent, capture, prepared, proposal, review


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("ref", [FIRST, SECOND])
async def test_previous_boolean_is_a_new_direct_or_routed_verified_transfer(
    native_link, routed, ref
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
        parent, _, prepared, _, review = await recovery_review(native_link, ref=ref, target=target)
        assert review["recovery_origin"] == prepared["origin"]
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        other = SECOND if ref == FIRST else FIRST
        boolean_slot(peer.files, other, ref == FIRST)
        start = len(mutations(peer))
        result = await service.apply_boolean_default(**apply_recovery(review))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["operation_id"] != parent["intent"]["operation_id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
        assert result["intent"]["payload_sha256"] != review["payload_sha256"]
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        image = MoiIdentity(peer.files[3])
        assert image.instance == 5136 and image.reader.scalar(image.root, 900) == 9.25
        assert image.reader.scalar(image.reader.records[ref], 3113) is (ref == FIRST)
        assert image.reader.scalar(image.reader.records[other], 3113) is (ref == FIRST)
        assert result["result"]["preservation"]["selected_default"]["effective_value"] is (
            ref == FIRST
        )
        changes = mutations(peer)[start:]
        assert changes.count(("state", "start-restore")) == 1
        assert changes.count(("state", "end-restore")) == 1
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await service.apply_boolean_default(**apply_recovery(review))
        assert mutations(peer)[start:] == changes
        if proxy:
            assert not proxy.errors and not proxy.clients
            assert len(proxy.requests) == len(proxy.responses)
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("change", ["value", "numeric", "origin", "missing-origin"])
async def test_boolean_recovery_preview_refuses_other_value_or_unbound_purpose(native_link, change):
    peer, _, _, service, target = native_link
    _, _, _, proposal, _ = await recovery_review(native_link)
    if change == "value":
        proposal["value"] = False
    elif change == "numeric":
        proposal["value"] = 1
    elif change == "origin":
        proposal["recovery_origin_sha256"] = "0" * 64
    else:
        del proposal["recovery_origin_sha256"]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await service.preview_boolean_default(
            **target, **proposal, operation_id="reject-boolean-recovery"
        )
    assert peer.events == before


@pytest.mark.parametrize(
    "change", ["selected", "application", "directory", "parent-pending", "parent-backup"]
)
async def test_boolean_recovery_apply_rechecks_original_and_fresh_source_without_dispatch(
    native_link, change
):
    peer, _, store, service, _ = native_link
    parent, _, _, _, review = await recovery_review(native_link)
    if change == "selected":
        boolean_slot(peer.files, FIRST, True)
    elif change == "application":
        import gzip

        peer.files[3] = gzip.compress(
            MoiIdentity(peer.files[3]).data.replace(b"opaque footer", b"unsafe footer"), mtime=0
        )
    elif change == "directory":
        peer.files[11] += b"changed"
    elif change == "parent-pending":
        with store.connect() as db:
            db.execute(
                "UPDATE application_transfers SET pending=1 WHERE id=?", (parent["intent"]["id"],)
            )
    else:
        (service.storage.directory / parent["intent"]["backup_id"] / "file-12.bin").write_bytes(
            b"tampered"
        )
    before = list(mutations(peer))
    result = await service.apply_boolean_default(**apply_recovery(review))
    assert result["result"]["status"] == "not_sent" and not result["result"]["may_have_applied"], (
        result
    )
    assert mutations(peer) == before and len(service.storage.receipts()) == 1


async def test_uncertain_boolean_recovery_reconciles_after_restart_without_replay(native_link):
    peer, bacnet, store, service, _ = native_link
    parent, _, prepared, _, review = await recovery_review(native_link)
    peer.mode = "drop-end"
    result = await service.apply_boolean_default(**apply_recovery(review))
    assert result["pending"] and result["result"]["status"] == "unknown"
    assert result["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
    before = list(mutations(peer))
    peer.mode = "normal"
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        observed = await restarted.reconcile(
            operation_id="readback-boolean-recovery", receipt_id=result["intent"]["id"]
        )
        assert not observed["pending"] and observed["latest_readback"]["status"] == "verified"
        assert observed["result"] == result["result"]
        assert observed["intent"]["recovery_origin"] == prepared["origin"]
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        assert mutations(peer) == before
    finally:
        await restarted.close()


def test_optional_boolean_recovery_fields_remain_a_strict_pair():
    normal = {
        "operation_id": "strict-boolean-recovery",
        "address": "127.0.0.1:47808",
        "device": "device,5136",
        "capture_id": "a" * 32,
        "snapshot_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "record_ref": FIRST,
        "encoded_sha256": "d" * 64,
        "value": True,
    }
    assert BooleanTransferPreview(**normal).recovery_parent_receipt is None
    for change in [
        {"recovery_parent_receipt": "e" * 32},
        {"recovery_origin_sha256": "f" * 64},
        {"value": 1, "recovery_parent_receipt": "e" * 32, "recovery_origin_sha256": "f" * 64},
    ]:
        with pytest.raises(ValueError):
            BooleanTransferPreview(**(normal | change))
