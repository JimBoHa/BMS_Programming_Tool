"""A previous Enum code is a new one-use transfer, never replay or automatic restore."""

import asyncio
import copy
import struct
import types

import pytest
from bms_tool.moi_effective_enum import EffectiveEnumCompiler
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_enum_compiler import EffectiveEnumService
from bms_tool.native_enum_transfer import EnumTransferPreview

from .test_moi_effective_enum import enum_files
from .test_moi_enum_defaults import REF
from .test_native_applications import NativePeer
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, apply_request, mutations, real_slot
from .test_native_enum_compiler import proposal
from .test_native_enum_transfer import (
    add_enum_states_slot,
    enum_slot,
    enum_states_slot,
    enum_storage,
)


async def recovery_review(link, *, target=None, cid=528, previous=513, after=65535):
    peer, _, _, service, original_target = link
    target = target or original_target
    peer.files = enum_files(cid=cid, saved=previous)
    add_enum_states_slot(peer.files, cid=cid)
    enum_storage(peer, value=after)
    capture = await service.capture(**target, operation_id="enum-original-source")
    source = EffectiveEnumService(NativeBackupRecords(service.storage)).source(
        {"capture_id": capture["id"], "snapshot_sha256": capture["snapshot_evidence_sha256"]}
    )
    first = await service.preview_enum_default(
        **target, operation_id="enum-original-review", **proposal(source, after)
    )
    parent = await service.apply_enum_default(**apply_request(first))
    assert parent["result"]["status"] == "verified", parent
    capture = await service.capture(**target, operation_id="enum-recovery-source")
    prepared = service.enum_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    body = {**prepared["proposal"], "recovery_origin_sha256": prepared["origin_sha256"]}
    plan = await service.preview_enum_default(**target, operation_id="enum-recovery-review", **body)
    peer.do_ReinitializeDeviceRequest = types.MethodType(
        NativePeer.do_ReinitializeDeviceRequest, peer
    )
    enum_storage(peer, value=previous)
    return parent, capture, prepared, body, plan


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("cid", [528, 529])
@pytest.mark.parametrize("previous,after", [(0, 65535), (513, 0)])
async def test_enum_recovery_new_direct_or_routed_transfer_preserves_fresh_values(
    native_link, routed, cid, previous, after
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
        parent, _, prepared, _, plan = await recovery_review(
            native_link, target=target, cid=cid, previous=previous, after=after
        )
        assert plan["recovery_origin"] == prepared["origin"]
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        before, start = copy.deepcopy(peer.files), len(mutations(peer))
        result = await service.apply_enum_default(**apply_request(plan))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert result["intent"]["review_snapshot_sha256"] == plan["snapshot_sha256"]
        assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
        assert service.storage.load(result["intent"]["backup_id"])[1] == before
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        field = EffectiveEnumCompiler(peer.files).fields()[0]
        assert field["effective_value"] == previous and field["class_id"] == cid
        image = MoiIdentity(peer.files[3])
        assert image.reader.scalar(image.root, 900) == 9.25
        assert image.reader.scalar(image.reader.records[REF], 931) == 291
        changes = mutations(peer)[start:]
        assert changes.count(("state", "start-restore")) == 1
        assert changes.count(("state", "end-restore")) == 1
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await service.apply_enum_default(**apply_request(plan))
        assert mutations(peer)[start:] == changes
        if proxy:
            assert not proxy.errors and not proxy.clients
            assert len(proxy.requests) == len(proxy.responses)
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("change", ["value", "origin", "parent", "missing-origin"])
async def test_enum_recovery_altered_proposal_refuses_before_controller_queries(
    native_link, change
):
    peer, _, _, service, target = native_link
    _, _, _, body, _ = await recovery_review(native_link)
    changed = dict(body)
    if change == "value":
        changed["value"] = 42
    elif change == "origin":
        changed["recovery_origin_sha256"] = "0" * 64
    elif change == "parent":
        changed["recovery_parent_receipt"] = "0" * 32
    else:
        del changed["recovery_origin_sha256"]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await service.preview_enum_default(**target, operation_id="enum-recovery-reject", **changed)
    assert peer.events == before


@pytest.mark.parametrize(
    "change", ["code", "states", "directory", "application", "parent-pending", "parent-backup"]
)
async def test_enum_recovery_preintent_rechecks_fresh_field_context_and_parent(native_link, change):
    peer, _, store, service, _ = native_link
    parent, _, _, _, plan = await recovery_review(native_link)
    if change == "code":
        enum_slot(peer.files, 42)
    elif change == "states":
        enum_states_slot(peer.files, 292)
    elif change == "directory":
        peer.files[11] += b"changed"
    elif change == "application":
        peer.files[3] += b"changed"
    elif change == "parent-pending":
        with store.connect() as db:
            db.execute(
                "UPDATE application_transfers SET pending=1 WHERE id=?", (parent["intent"]["id"],)
            )
    else:
        folder = service.storage.directory / parent["intent"]["backup_id"]
        next(folder.glob("*.bin")).write_bytes(b"altered parent original")
    before = list(mutations(peer))
    result = await service.apply_enum_default(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not result["result"]["may_have_applied"] and mutations(peer) == before
    assert len(service.storage.receipts()) == 1


async def test_uncertain_enum_recovery_reconciles_after_restart_without_replay(native_link):
    peer, bacnet, store, service, _ = native_link
    parent, _, prepared, _, plan = await recovery_review(native_link)
    peer.mode = "drop-end"
    outcome = await service.apply_enum_default(**apply_request(plan))
    assert outcome["pending"] and outcome["result"]["status"] == "unknown", outcome
    assert outcome["intent"]["recovery_origin_sha256"] == prepared["origin_sha256"]
    changes = list(mutations(peer))
    peer.mode = "normal"
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        observed = await restarted.reconcile(
            operation_id="enum-recovery-readback", receipt_id=outcome["intent"]["id"]
        )
        assert not observed["pending"] and observed["latest_readback"]["status"] == "verified", (
            observed
        )
        assert observed["result"] == outcome["result"]
        assert observed["intent"]["recovery_origin"] == prepared["origin"]
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        assert mutations(peer) == changes
    finally:
        await restarted.close()


def test_enum_recovery_optional_fields_require_both_strict_hashes():
    body = {
        "operation_id": "enum-recovery-contract",
        "address": "127.0.0.1:47808",
        "device": "device,5136",
        "capture_id": "a" * 32,
        "snapshot_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "record_ref": REF,
        "encoded_sha256": "d" * 64,
        "value": 513,
    }
    assert EnumTransferPreview(**body).recovery_parent_receipt is None
    for change in (
        {"recovery_parent_receipt": "e" * 32},
        {"recovery_origin_sha256": "f" * 64},
        {"recovery_parent_receipt": "bad", "recovery_origin_sha256": "f" * 64},
    ):
        with pytest.raises(ValueError):
            EnumTransferPreview(**(body | change))
